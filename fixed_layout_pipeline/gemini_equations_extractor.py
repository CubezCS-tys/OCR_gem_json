"""
Gemini equations-only extractor.

Asks Gemini to find ONLY mathematical equations on a scanned page and
return their bounding boxes + LaTeX.  Does NOT extract tables — Azure
handles text (including tabular text) accurately enough.

Schema returned:
{
  "equations": [
    {"bbox_pct": [x0, y0, x1, y1], "latex": "..."}
  ]
}
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

_EMPTY_RESULT: dict = {"equations": []}

_TASK_PROMPT = """\
You are analysing a SCANNED document page image.

TASK: Find every **mathematical equation** on this page and return it as LaTeX.

For each equation:
- Provide its TIGHT bounding box as percentages of page dimensions:
  [x0_pct, y0_pct, x1_pct, y1_pct]
  (0,0) = top-left, (100,100) = bottom-right.
- The bbox should tightly wrap ONLY the equation itself, not surrounding text.
- Convert the equation to VALID LaTeX.

IMPORTANT RULES:
- Extract ONLY standalone mathematical expressions/formulas/equations.
- Do NOT extract ordinary text, even if it appears next to an equation.
- Do NOT treat aligned examples or two-column layouts as tables.
- Do NOT include labels, numbering, or Arabic text that accompanies the equation
  inside the LaTeX — only the mathematical expression itself.
- bbox_pct values MUST be numbers between 0 and 100.
- If no equations are found, return "equations": [].
- Do NOT hallucinate. Only extract clearly visible equations.

Output ONLY valid JSON (no markdown fences, no commentary):
{
  "equations": [
    {"bbox_pct": [x0, y0, x1, y1], "latex": "LaTeX here"}
  ]
}
"""

_REGION_TASK_PROMPT = """\
You are analysing a SCANNED document page image plus OCR candidate regions.

TASK:
- You are given candidate regions (id + bbox_pct), produced by OCR geometry.
- For EACH candidate region, decide if it contains a standalone mathematical
  equation/formula/expression.
- If yes, return LaTeX for that region's expression.
- If no, skip that id.

IMPORTANT RULES:
- Use ONLY the provided candidate IDs.
- Do NOT invent new IDs.
- Do NOT return any bbox values.
- Do NOT include labels/Arabic prose/paragraph text in LaTeX.
- Return only clearly visible math.

Output ONLY valid JSON:
{
  "equations": [
    {"id": 3, "latex": "LaTeX here"}
  ]
}
"""


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _normalise_latex(raw: Any) -> str | None:
    """Return cleaned LaTeX string or None if unusable."""
    if not isinstance(raw, str):
        return None
    latex = raw.strip()
    if not latex:
        return None

    # Strip common math fences if Gemini includes them.
    if latex.startswith("\\[") and latex.endswith("\\]"):
        latex = latex[2:-2].strip()
    elif latex.startswith("\\(") and latex.endswith("\\)"):
        latex = latex[2:-2].strip()
    elif latex.startswith("$$") and latex.endswith("$$"):
        latex = latex[2:-2].strip()
    elif latex.startswith("$") and latex.endswith("$"):
        latex = latex[1:-1].strip()

    return latex or None


def _normalise_bbox_pct(raw: Any) -> list[float] | None:
    """
    Validate and normalise [x0, y0, x1, y1] percentages.

    Returns sorted/clamped floats on success, else None.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None

    vals: list[float] = []
    for v in raw:
        # Exclude booleans; Python bool is a subclass of int.
        if isinstance(v, bool):
            return None
        if not isinstance(v, (int, float)):
            return None
        fv = float(v)
        if not math.isfinite(fv):
            return None
        vals.append(max(0.0, min(100.0, fv)))

    x0, y0, x1, y1 = vals
    x_lo, x_hi = sorted((x0, x1))
    y_lo, y_hi = sorted((y0, y1))

    w = x_hi - x_lo
    h = y_hi - y_lo
    if w < 0.2 or h < 0.2:
        return None

    # Reject grossly oversized "equations" that are usually false positives.
    if (w * h) > 85.0 * 85.0:
        return None

    return [x_lo, y_lo, x_hi, y_hi]


def _extract_response_text(resp: Any) -> str:
    """Best-effort text extraction from Gemini response object."""
    text = (getattr(resp, "text", None) or "").strip()
    if text:
        return text
    # Fallback for SDK variants where .text may be empty but parts contain text.
    candidates = getattr(resp, "candidates", None) or []
    chunks: list[str] = []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            ptxt = getattr(part, "text", None)
            if ptxt:
                chunks.append(str(ptxt))
    return "".join(chunks).strip()


def _backoff(attempt: int) -> None:
    time.sleep(min(8.0, 0.8 * (2 ** attempt)))


def _normalise_candidate_regions(candidates: list[dict]) -> tuple[list[dict], dict[int, list[float]]]:
    """Validate and canonicalise candidate regions for region-anchored extraction."""
    cleaned: list[dict] = []
    id_to_bbox: dict[int, list[float]] = {}
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        raw_id = cand.get("id")
        if isinstance(raw_id, bool):
            continue
        try:
            cid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if cid < 0:
            continue
        bbox = _normalise_bbox_pct(cand.get("bbox_pct"))
        if not bbox:
            continue
        # Keep first occurrence per id.
        if cid in id_to_bbox:
            continue
        id_to_bbox[cid] = bbox
        cleaned.append({"id": cid, "bbox_pct": bbox})
    cleaned.sort(key=lambda x: x["id"])
    return cleaned, id_to_bbox


def extract_equations_in_regions(
    client: Any,
    model: str,
    page_png_bytes: bytes,
    candidates: list[dict],
    max_retries: int = 3,
) -> dict:
    """
    Ask Gemini for LaTeX using OCR-provided candidate regions.

    Parameters
    ----------
    candidates : list of {"id": int, "bbox_pct": [x0,y0,x1,y1]}

    Returns
    -------
    {"equations": [{"bbox_pct": [...], "latex": "..."}]}
    Geometry is always from provided candidate regions, never from Gemini.
    """
    from google.genai import types

    regions, id_to_bbox = _normalise_candidate_regions(candidates)
    if not regions:
        return dict(_EMPTY_RESULT)

    regions_json = json.dumps({"candidates": regions}, ensure_ascii=False)
    contents = [
        types.Part.from_text(text=_REGION_TASK_PROMPT),
        types.Part.from_text(text=f"Candidate regions JSON:\n{regions_json}"),
        types.Part.from_bytes(data=page_png_bytes, mime_type="image/png"),
        types.Part.from_text(text="Output JSON only."),
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            text = _extract_response_text(resp)
            if not text:
                raise ValueError("Empty response from Gemini")

            obj = json.loads(_strip_fences(text))
            if not isinstance(obj, dict):
                raise ValueError(f"Response is not a JSON object: {type(obj)}")

            equations = obj.get("equations") or []
            valid: list[dict] = []
            used_ids: set[int] = set()

            for eq in equations:
                if not isinstance(eq, dict):
                    continue
                raw_id = eq.get("id")
                if isinstance(raw_id, bool):
                    continue
                try:
                    cid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if cid in used_ids or cid not in id_to_bbox:
                    continue
                latex = _normalise_latex(eq.get("latex"))
                if not latex:
                    continue
                valid.append({"bbox_pct": id_to_bbox[cid], "latex": latex})
                used_ids.add(cid)

            logger.debug(
                "Gemini region extraction: %d/%d candidate equations",
                len(valid), len(regions),
            )
            return {"equations": valid}

        except Exception as e:
            last_err = e
            if attempt < max_retries:
                logger.debug(
                    "Gemini region equations attempt %d failed: %s — retrying …",
                    attempt + 1, e,
                )
                _backoff(attempt)
                contents.append(
                    types.Part.from_text(
                        text=(
                            "Your previous output was invalid. "
                            "Return ONLY valid JSON: "
                            "{\"equations\":[{\"id\":<int>,\"latex\":\"...\"}]}. "
                            "Use only provided IDs."
                        )
                    )
                )
                continue
            break

    logger.warning(
        "Gemini region equation extraction failed after %d retries: %s",
        max_retries, last_err,
    )
    return dict(_EMPTY_RESULT)


def extract_equations(
    client: Any,
    model: str,
    page_png_bytes: bytes,
    max_retries: int = 3,
) -> dict:
    """
    Ask Gemini to extract ONLY equations from a page image.

    Returns dict with key "equations" (list).
    Falls back to {"equations": []} on failure.
    """
    from google.genai import types

    contents = [
        types.Part.from_text(text=_TASK_PROMPT),
        types.Part.from_bytes(data=page_png_bytes, mime_type="image/png"),
        types.Part.from_text(text="Output JSON only."),
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            text = _extract_response_text(resp)
            if not text:
                raise ValueError("Empty response from Gemini")

            obj = json.loads(_strip_fences(text))
            if not isinstance(obj, dict):
                raise ValueError(f"Response is not a JSON object: {type(obj)}")

            equations = obj.get("equations") or []

            # Validate each equation has bbox_pct and latex
            valid = []
            for eq in equations:
                if not isinstance(eq, dict):
                    continue
                bbox = _normalise_bbox_pct(eq.get("bbox_pct"))
                latex = _normalise_latex(eq.get("latex"))
                if bbox and latex:
                    valid.append({"bbox_pct": bbox, "latex": latex})

            result = {"equations": valid}
            logger.debug("Gemini extracted %d equations", len(valid))
            return result

        except Exception as e:
            last_err = e
            if attempt < max_retries:
                logger.debug(
                    "Gemini equations attempt %d failed: %s — retrying …",
                    attempt + 1, e,
                )
                _backoff(attempt)
                contents.append(
                    types.Part.from_text(
                        text=(
                            "Your previous output was invalid. "
                            "Return ONLY valid JSON with an 'equations' array. "
                            "No markdown fences, no commentary."
                        )
                    )
                )
                continue
            break

    logger.warning(
        "Gemini equation extraction failed after %d retries: %s",
        max_retries, last_err,
    )
    return dict(_EMPTY_RESULT)
