"""
Gemini PDF text extractor.

Uploads a scanned PDF to Gemini via the Files API and extracts per-page,
per-line structured text with bounding boxes.

Returns: list[list[dict]]  — outer list is pages (0-indexed), inner list is
lines, each dict = {"text": str, "bbox_pct": [x0, y0, x1, y1]}.
Bounding boxes are percentages of page dimensions (0-100).

This is the first stage of the hybrid pipeline:
  Azure  → bounding boxes / geometry  (authoritative positions)
  Gemini → text content + fallback geometry for Azure-missed regions

The two outputs are reconciled by fuzzy_text_merger.py:
  • Azure line matched  → keep Azure bbox, replace text with Gemini's
  • Gemini line missed by Azure → inject as synthetic line using Gemini bbox
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_TEXT_PROMPT = """\
Extract ALL text from this scanned PDF document, page by page, line by line,
in reading order.

For EACH visual text line on each page return:
  "text"     — the exact text of that line (Arabic in natural RTL reading order)
  "bbox_pct" — tight bounding box as [x0, y0, x1, y1] where each value is a
               PERCENTAGE of the page dimensions (0 = top/left, 100 = bottom/right)

Rules:
- Include EVERY visible line: headings, body text, captions, footnotes, page numbers.
- Do NOT skip any text.
- Do NOT merge multiple visual lines into one entry.
- Do NOT add commentary, translations, or explanations.
- Do NOT use markdown inside "text" values.
- bbox_pct values MUST be numbers 0-100.
- If a page is blank, return an empty "lines" array for it.

Return ONLY valid JSON (no markdown fences, no extra text outside the braces):
{
  "pages": [
    {
      "page": 1,
      "lines": [
        {"text": "line text here", "bbox_pct": [x0, y0, x1, y1]},
        {"text": "next line",     "bbox_pct": [x0, y0, x1, y1]}
      ]
    }
  ]
}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _extract_response_text(resp: Any) -> str:
    """Best-effort text extraction from a Gemini response object."""
    text = (getattr(resp, "text", None) or "").strip()
    if text:
        return text
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
    time.sleep(min(16.0, 0.8 * (2 ** attempt)))


def _normalise_line(raw: Any) -> dict | None:
    """
    Validate and normalise one Gemini line entry.

    Expects ``{"text": str, "bbox_pct": [x0, y0, x1, y1]}``.
    Returns the cleaned dict or None if invalid.
    """
    if not isinstance(raw, dict):
        return None
    text = (raw.get("text") or "").strip()
    if not text:
        return None
    bbox_raw = raw.get("bbox_pct")
    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
        return None
    try:
        vals = [max(0.0, min(100.0, float(v))) for v in bbox_raw]
    except (TypeError, ValueError):
        return None
    x0, y0, x1, y1 = vals
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if (x1 - x0) < 0.1 or (y1 - y0) < 0.1:
        return None
    return {"text": text, "bbox_pct": [x0, y0, x1, y1]}


def _call_gemini_for_pages(
    client: Any,
    model: str,
    file_uri: str,
    page_start: int,
    page_end: int,
    max_retries: int,
) -> list[list[dict]]:
    """
    Call Gemini to extract lines from pages [page_start, page_end] (1-based inclusive).
    Returns a list of per-page line lists in page order.
    """
    from google.genai import types

    count = page_end - page_start + 1
    prompt_text = _TEXT_PROMPT + (
        f"\n\nIMPORTANT: Extract ONLY pages {page_start} through {page_end} "
        f"({count} page(s)). Return exactly {count} entries in \"pages\", "
        f"numbered {page_start} to {page_end}."
    )

    contents = [
        types.Part.from_uri(file_uri=file_uri, mime_type="application/pdf"),
        types.Part.from_text(text=prompt_text),
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            raw = _extract_response_text(resp)
            if not raw:
                raise ValueError("Empty response from Gemini")

            data = json.loads(_strip_fences(raw))
            if not isinstance(data, dict) or "pages" not in data:
                raise ValueError(f"Unexpected JSON structure: {list(data.keys())}")

            pages_raw = sorted(data["pages"], key=lambda p: p.get("page", 0))
            result: list[list[dict]] = []
            for p in pages_raw:
                raw_lines = p.get("lines") or []
                valid_lines = [ln for ln in (_normalise_line(l) for l in raw_lines) if ln]
                result.append(valid_lines)

            # Pad/trim to exactly `count` entries
            while len(result) < count:
                result.append([])
            return result[:count]

        except Exception as exc:
            last_err = exc
            logger.warning(
                "Gemini batch p%d–p%d attempt %d/%d failed: %s",
                page_start, page_end, attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                if attempt == 0:
                    contents.append(
                        types.Part.from_text(
                            text=(
                                "Your previous response could not be parsed. "
                                "Return ONLY valid JSON with the per-line schema. "
                                'Every line entry MUST have "text" and "bbox_pct". '
                                "No markdown fences, no extra text."
                            )
                        )
                    )
                _backoff(attempt)

    logger.error(
        "Gemini batch p%d–p%d failed after %d attempts: %s",
        page_start, page_end, max_retries, last_err,
    )
    # Return empty lists for all pages in this batch so the pipeline can continue
    return [[] for _ in range(count)]


def extract_text_from_pdf(
    pdf_path: Path,
    client: Any,
    model: str,
    *,
    expected_pages: Optional[int] = None,
    max_retries: int = 3,
    page_batch_size: int = 6,
) -> list[list[dict]]:
    """
    Extract per-page, per-line structured text from a scanned PDF via Gemini.

    The PDF is uploaded once.  If ``expected_pages`` exceeds ``page_batch_size``
    the extraction is split into multiple Gemini calls (each covering a small
    page range) to avoid hitting the model's output-token limit.  Results are
    then stitched back in order.

    Parameters
    ----------
    pdf_path :
        Path to the scanned PDF file.
    client :
        An initialised ``google.genai.Client`` instance.
    model :
        Gemini model identifier, e.g. ``"gemini-2.0-flash"``.
    expected_pages :
        Number of pages in the document (used to size batches).
    max_retries :
        How many times to retry each batch on transient errors.
    page_batch_size :
        Maximum pages per Gemini call.  Reduce for very dense / equation-heavy
        documents to stay within output-token limits.

    Returns
    -------
    list[list[dict]]
        Outer list is 0-indexed pages.  Each inner list contains dicts::

            {"text": "line text", "bbox_pct": [x0, y0, x1, y1]}

        Returns ``[]`` on complete failure.
    """
    from google.genai import types

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ── Upload to Files API (once) ───────────────────────────────────────────
    logger.info("Uploading '%s' to Gemini Files API …", pdf_path.name)
    uploaded = client.files.upload(
        file=str(pdf_path),
        config=types.UploadFileConfig(
            mime_type="application/pdf",
            display_name=pdf_path.name,
        ),
    )
    logger.info("Upload complete → %s", uploaded.name)

    total_pages = expected_pages or 0

    # ── Single-batch fast path (small document) ──────────────────────────────
    if total_pages <= page_batch_size:
        prompt_text = _TEXT_PROMPT
        if total_pages:
            prompt_text += (
                f"\n\nNote: this PDF has exactly {total_pages} page(s). "
                f"Return exactly {total_pages} entries in \"pages\"."
            )
        contents = [
            types.Part.from_uri(file_uri=uploaded.uri, mime_type="application/pdf"),
            types.Part.from_text(text=prompt_text),
        ]
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(temperature=0.0),
                )
                raw = _extract_response_text(resp)
                if not raw:
                    raise ValueError("Empty response from Gemini")
                data = json.loads(_strip_fences(raw))
                if not isinstance(data, dict) or "pages" not in data:
                    raise ValueError(f"Unexpected JSON structure: {list(data.keys())}")
                pages_raw = sorted(data["pages"], key=lambda p: p.get("page", 0))
                result: list[list[dict]] = []
                for p in pages_raw:
                    raw_lines = p.get("lines") or []
                    valid_lines = [ln for ln in (_normalise_line(l) for l in raw_lines) if ln]
                    result.append(valid_lines)
                total_lines = sum(len(pg) for pg in result)
                logger.info(
                    "Gemini extraction complete: %d pages, %d lines",
                    len(result), total_lines,
                )
                return result
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "Gemini extraction attempt %d/%d failed: %s",
                    attempt + 1, max_retries, exc,
                )
                if attempt < max_retries - 1:
                    if attempt == 0:
                        contents.append(types.Part.from_text(
                            text=(
                                "Your previous response could not be parsed. "
                                "Return ONLY valid JSON with the per-line schema. "
                                'Every line entry MUST have "text" and "bbox_pct". '
                                "No markdown fences, no extra text."
                            )
                        ))
                    _backoff(attempt)
        logger.error("Gemini extraction failed after %d attempts: %s", max_retries, last_err)
        return []

    # ── Multi-batch path (large document) ────────────────────────────────────
    logger.info(
        "Document has %d pages — splitting into batches of %d",
        total_pages, page_batch_size,
    )
    all_pages: list[list[dict]] = []
    page = 1
    while page <= total_pages:
        batch_end = min(page + page_batch_size - 1, total_pages)
        logger.info("  Extracting pages %d–%d …", page, batch_end)
        batch_result = _call_gemini_for_pages(
            client, model, uploaded.uri, page, batch_end, max_retries,
        )
        all_pages.extend(batch_result)
        page = batch_end + 1

    total_lines = sum(len(pg) for pg in all_pages)
    logger.info(
        "Gemini extraction complete: %d pages, %d lines (batched)",
        len(all_pages), total_lines,
    )
    return all_pages
