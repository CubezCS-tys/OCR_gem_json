"""
Gemini unified structural extractor.

Single Gemini call per page-batch that classifies and extracts ALL content:
  - **text** lines  → text + bbox   (for fuzzy merge with Azure bboxes)
  - **tables**      → HTML <table>  + bbox   (rendered as positioned tables)
  - **equations**   → LaTeX         + bbox   (rendered as MathJax)

This replaces the separate text-only and equation-only extractors with a
unified approach that is:
  - Cheaper (1 Gemini call instead of 2–3)
  - Better at tables (produces real <table> markup instead of text overlays)
  - Better at equations (no fragile heuristic candidate detection)

The text lines are fuzzy-merged with Azure ``prebuilt-read`` bounding boxes
by ``fuzzy_text_merger.py`` (Azure geometry + Gemini text quality).

Tables and equations use Gemini's own bounding boxes — these regions are
large enough that pixel-level precision isn't needed.
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

_STRUCTURAL_PROMPT = """\
You are analysing a scanned document page by page.

Your job is to extract TWO types of content:
  "text"     — every visible text line (paragraphs, headings, captions,
                footnotes, page numbers, table captions, cell text inside tables)
  "equation" — standalone mathematical equations or formulas

NOTE: Tables are reconstructed from bounding-box geometry by a separate system.
Do NOT return a "tables" key.  DO include the text content of table cells as
ordinary "lines" entries so they can be fuzzy-merged with Azure bounding boxes.

──────────────────────────────────────────────────────────
SCHEMA
──────────────────────────────────────────────────────────

{
  "pages": [
    {
      "page": 1,
      "lines": [
        {"text": "...", "bbox_pct": [x0, y0, x1, y1]}
      ],
      "equations": [
        {
          "bbox_pct": [x0, y0, x1, y1],
          "latex": "LaTeX here"
        }
      ]
    }
  ]
}

──────────────────────────────────────────────────────────
RULES FOR TEXT LINES
──────────────────────────────────────────────────────────

- Include EVERY visible text line including table cell content.
- One entry per visual line — do NOT merge multiple lines.
- Arabic text in natural RTL reading order.
- bbox_pct = tight bounding box as [x0, y0, x1, y1] percentages of page
  (0 = top/left, 100 = bottom/right).

──────────────────────────────────────────────────────────
RULES FOR EQUATIONS
──────────────────────────────────────────────────────────

- Extract ONLY standalone mathematical expressions/formulas.
- Do NOT treat ordinary text or table content as equations.
- bbox_pct should tightly wrap the equation only.
- Convert to valid LaTeX (no labels, numbering, or surrounding prose).
- Inline math that is part of a sentence should stay as a text line, NOT
  be extracted as a separate equation.

──────────────────────────────────────────────────────────
GENERAL
──────────────────────────────────────────────────────────

- All bbox_pct values MUST be numbers 0–100.
- If a page is blank, return empty arrays for lines and equations.
- Do NOT hallucinate content that isn't visible.
- Do NOT add commentary, translations, or explanations.
- Return ONLY valid JSON (no markdown fences, no extra text).
"""

# Text-only variant — used when equations are disabled (--no-tables mode).
# Simpler schema and prompt = faster, cheaper, less likely to hallucinate.
_TEXT_ONLY_PROMPT = """\
You are analysing a scanned document page by page.

Your job is to extract every visible text line.

NOTE: Tables are reconstructed separately. Include table cell text as
ordinary lines. Do NOT return tables or equations keys.

──────────────────────────────────────────────────────────
SCHEMA
──────────────────────────────────────────────────────────

{"pages": [{"page": 1, "lines": [{"text": "...", "bbox_pct": [x0, y0, x1, y1]}]}]}

──────────────────────────────────────────────────────────
RULES
──────────────────────────────────────────────────────────

- Include EVERY visible text line including table cell content.
- One entry per visual line — do NOT merge multiple lines.
- Arabic text in natural RTL reading order.
- bbox_pct = tight bounding box as [x0, y0, x1, y1] percentages of page
  (0 = top/left, 100 = bottom/right).
- All bbox_pct values MUST be numbers 0–100.
- If a page is blank return {"pages": [{"page": N, "lines": []}]}.
- Do NOT hallucinate. Do NOT add commentary or translations.
- Return ONLY valid JSON (no markdown fences, no extra text).
"""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_fences(s: str) -> str:
    """Remove markdown code fences from Gemini output."""
    s = s.strip()
    s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _fix_json_backslashes(s: str) -> str:
    r"""
    Fix backslash escapes in Gemini JSON that contain raw LaTeX.

    Gemini often returns LaTeX like ``\frac``, ``\alpha`` inside JSON string
    values without proper escaping.  ``json.loads()`` chokes on invalid
    escapes (``\a``) and silently misinterprets others (``\f`` → form-feed
    instead of ``\frac``).

    Strategy – inside JSON string literals double **every** backslash that
    is not a *structural* JSON escape:

    * ``\"``  ``\\``  ``\/``  → keep (required by JSON grammar)
    * ``\uXXXX``              → keep (unicode escape)
    * Everything else         → double the backslash so ``json.loads``
      treats it as a literal backslash character.

    This is safe because each content value in our schema is a single text
    line, an HTML table fragment, or a LaTeX expression — none of which
    require literal control characters (tab, newline, etc.) inside the
    JSON string.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
        else:
            if ch == '\\':
                if i + 1 < n:
                    nxt = s[i + 1]
                    if nxt in ('"', '\\', '/'):
                        # Structural JSON escapes — always keep
                        out.append(ch)
                        out.append(nxt)
                        i += 2
                    elif nxt == 'u' and i + 5 < n and all(
                        c in '0123456789abcdefABCDEF' for c in s[i + 2 : i + 6]
                    ):
                        # Unicode escape \uXXXX — keep
                        out.append(s[i : i + 6])
                        i += 6
                    else:
                        # Everything else (including \b \f \n \r \t and
                        # invalid escapes like \a \g \l) → double so it
                        # becomes a literal backslash after parsing.
                        out.append('\\\\')
                        i += 1          # leave nxt for next iteration
                else:
                    # Trailing backslash
                    out.append('\\\\')
                    i += 1
            elif ch == '"':
                out.append(ch)
                in_string = False
                i += 1
            else:
                out.append(ch)
                i += 1
    return "".join(out)


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


def _normalise_bbox(raw: Any) -> list[float] | None:
    """Validate and normalise [x0, y0, x1, y1] percentages (0–100)."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        vals = [max(0.0, min(100.0, float(v))) for v in raw]
    except (TypeError, ValueError):
        return None
    x0, y0, x1, y1 = vals
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if (x1 - x0) < 0.1 or (y1 - y0) < 0.1:
        return None
    return [x0, y0, x1, y1]


def _normalise_text_line(raw: Any) -> dict | None:
    """Validate one text line entry."""
    if not isinstance(raw, dict):
        return None
    text = (raw.get("text") or "").strip()
    if not text:
        return None
    bbox = _normalise_bbox(raw.get("bbox_pct"))
    if not bbox:
        return None
    return {"text": text, "bbox_pct": bbox}


def _normalise_table(raw: Any) -> dict | None:
    """Validate one table entry."""
    if not isinstance(raw, dict):
        return None
    html = (raw.get("html") or "").strip()
    if not html:
        return None
    # Basic sanity: must contain <table and </table>
    if "<table" not in html.lower() or "</table>" not in html.lower():
        return None
    bbox = _normalise_bbox(raw.get("bbox_pct"))
    if not bbox:
        return None
    return {"html": html, "bbox_pct": bbox}


def _normalise_equation(raw: Any) -> dict | None:
    """Validate one equation entry."""
    if not isinstance(raw, dict):
        return None
    latex = (raw.get("latex") or "").strip()
    if not latex:
        return None
    # Strip math delimiters if Gemini wraps them
    for start, end in [("\\[", "\\]"), ("\\(", "\\)"), ("$$", "$$"), ("$", "$")]:
        if latex.startswith(start) and latex.endswith(end):
            latex = latex[len(start):-len(end)].strip()
            break
    if not latex:
        return None
    bbox = _normalise_bbox(raw.get("bbox_pct"))
    if not bbox:
        return None
    return {"latex": latex, "bbox_pct": bbox}


# ── Per-page result container ─────────────────────────────────────────────────

def _empty_page() -> dict:
    return {"lines": [], "tables": [], "equations": []}


def _parse_page(raw_page: dict) -> dict:
    """Parse and validate one page of Gemini structural output."""
    result = _empty_page()

    for raw_line in (raw_page.get("lines") or []):
        line = _normalise_text_line(raw_line)
        if line:
            result["lines"].append(line)

    for raw_table in (raw_page.get("tables") or []):
        table = _normalise_table(raw_table)
        if table:
            result["tables"].append(table)

    for raw_eq in (raw_page.get("equations") or []):
        eq = _normalise_equation(raw_eq)
        if eq:
            result["equations"].append(eq)

    return result


# ── Core Gemini call ──────────────────────────────────────────────────────────


def _call_gemini_structural(
    client: Any,
    model: str,
    file_uri: str,
    page_start: int,
    page_end: int,
    max_retries: int,
    prompt_base: str = _STRUCTURAL_PROMPT,
) -> list[dict]:
    """
    Call Gemini to extract structured content from pages [page_start, page_end]
    (1-based inclusive).

    Returns a list of per-page result dicts, each with keys:
      "lines", "tables", "equations"
    """
    from google.genai import types

    count = page_end - page_start + 1
    prompt_text = prompt_base + (
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

            cleaned = _fix_json_backslashes(_strip_fences(raw))
            data = json.loads(cleaned)
            if not isinstance(data, dict) or "pages" not in data:
                raise ValueError(f"Unexpected JSON structure: {list(data.keys())}")

            pages_raw = sorted(data["pages"], key=lambda p: p.get("page", 0))
            result: list[dict] = []
            for p in pages_raw:
                result.append(_parse_page(p))

            # Pad/trim to exactly `count` entries
            while len(result) < count:
                result.append(_empty_page())
            result = result[:count]

            n_lines = sum(len(pg["lines"]) for pg in result)
            n_tables = sum(len(pg["tables"]) for pg in result)
            n_eqs = sum(len(pg["equations"]) for pg in result)
            logger.info(
                "Gemini structural p%d–p%d: %d lines, %d tables, %d equations",
                page_start, page_end, n_lines, n_tables, n_eqs,
            )
            return result

        except Exception as exc:
            last_err = exc
            logger.warning(
                "Gemini structural p%d–p%d attempt %d/%d failed: %s",
                page_start, page_end, attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                if attempt == 0:
                    contents.append(
                        types.Part.from_text(
                            text=(
                                "Your previous response could not be parsed. "
                                "Return ONLY valid JSON matching the schema. "
                                'Each page must have "lines", "tables", "equations" arrays. '
                                "No markdown fences, no extra text."
                            )
                        )
                    )
                _backoff(attempt)

    logger.error(
        "Gemini structural p%d–p%d failed after %d attempts: %s",
        page_start, page_end, max_retries, last_err,
    )
    return [_empty_page() for _ in range(count)]


# ── Public API ────────────────────────────────────────────────────────────────


def extract_structural_from_pdf(
    pdf_path: Path,
    client: Any,
    model: str,
    *,
    expected_pages: Optional[int] = None,
    max_retries: int = 3,
    page_batch_size: int = 4,
    max_workers: int = 1,
    include_equations: bool = True,
) -> list[dict]:
    """
    Extract structured content from a scanned PDF via Gemini.

    Uploads the PDF once, then splits into batches of ``page_batch_size``
    pages per Gemini call.  Batches run in parallel when ``max_workers > 1``.

    Parameters
    ----------
    pdf_path :
        Path to the scanned PDF file.
    client :
        An initialised ``google.genai.Client`` instance.
    model :
        Gemini model identifier, e.g. ``"gemini-2.0-flash"``.
    expected_pages :
        Number of pages in the document.
    max_retries :
        Retry count per batch.
    page_batch_size :
        Max pages per Gemini call.  Smaller = more reliable for dense
        pages with many tables/equations.  Default 4 (lower than text-only
        because structural output is larger).
    max_workers :
        Number of parallel Gemini calls.  Set to page count / batch size
        for maximum parallelism.  Default 1 (sequential).

    Returns
    -------
    list[dict]
        One dict per page (0-indexed), each with::

            {
                "lines": [{"text": str, "bbox_pct": [x0,y0,x1,y1]}],
                "tables": [{"html": str, "bbox_pct": [x0,y0,x1,y1]}],
                "equations": [{"latex": str, "bbox_pct": [x0,y0,x1,y1]}]
            }

        Returns ``[]`` on complete failure.
    """
    from google.genai import types

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    prompt = _STRUCTURAL_PROMPT if include_equations else _TEXT_ONLY_PROMPT
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
        prompt_text = prompt
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

                cleaned = _fix_json_backslashes(_strip_fences(raw))
                data = json.loads(cleaned)
                if not isinstance(data, dict) or "pages" not in data:
                    raise ValueError(
                        f"Unexpected JSON structure: {list(data.keys())}"
                    )

                pages_raw = sorted(data["pages"], key=lambda p: p.get("page", 0))
                result: list[dict] = [_parse_page(p) for p in pages_raw]

                n_lines = sum(len(pg["lines"]) for pg in result)
                n_tables = sum(len(pg["tables"]) for pg in result)
                n_eqs = sum(len(pg["equations"]) for pg in result)
                logger.info(
                    "Gemini structural: %d pages, %d lines, %d tables, %d equations",
                    len(result), n_lines, n_tables, n_eqs,
                )
                return result

            except Exception as exc:
                last_err = exc
                logger.warning(
                    "Gemini structural attempt %d/%d failed: %s",
                    attempt + 1, max_retries, exc,
                )
                if attempt < max_retries - 1:
                    if attempt == 0:
                        contents.append(types.Part.from_text(
                            text=(
                                "Your previous response could not be parsed. "
                                "Return ONLY valid JSON matching the schema. "
                                'Each page must have "lines", "tables", '
                                '"equations" arrays. '
                                "No markdown fences, no extra text."
                            )
                        ))
                    _backoff(attempt)

        logger.error(
            "Gemini structural failed after %d attempts: %s",
            max_retries, last_err,
        )
        return []

    # ── Multi-batch path (large document) ────────────────────────────────────
    # Build batch specs: [(page_start, page_end), ...]
    batches: list[tuple[int, int]] = []
    page = 1
    while page <= total_pages:
        batch_end = min(page + page_batch_size - 1, total_pages)
        batches.append((page, batch_end))
        page = batch_end + 1

    effective_workers = min(max_workers, len(batches))
    logger.info(
        "Document has %d pages — %d batches of ≤%d pages, %d parallel workers",
        total_pages, len(batches), page_batch_size, effective_workers,
    )

    if effective_workers <= 1:
        # Sequential path
        all_pages: list[dict] = []
        for ps, pe in batches:
            logger.info("  Extracting pages %d–%d …", ps, pe)
            batch_result = _call_gemini_structural(
                client, model, uploaded.uri, ps, pe, max_retries, prompt,
            )
            all_pages.extend(batch_result)
    else:
        # Parallel path
        import concurrent.futures

        batch_results: dict[int, list[dict]] = {}

        def _worker(idx_ps_pe: tuple[int, int, int]) -> tuple[int, list[dict]]:
            idx, ps, pe = idx_ps_pe
            logger.info("  [worker] Extracting pages %d–%d …", ps, pe)
            return idx, _call_gemini_structural(
                client, model, uploaded.uri, ps, pe, max_retries, prompt,
            )

        work_items = [(i, ps, pe) for i, (ps, pe) in enumerate(batches)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as pool:
            for idx, result in pool.map(_worker, work_items):
                batch_results[idx] = result

        # Reassemble in page order
        all_pages = []
        for i in range(len(batches)):
            all_pages.extend(batch_results.get(i, []))

    n_lines = sum(len(pg["lines"]) for pg in all_pages)
    n_tables = sum(len(pg["tables"]) for pg in all_pages)
    n_eqs = sum(len(pg["equations"]) for pg in all_pages)
    logger.info(
        "Gemini structural complete: %d pages, %d lines, %d tables, "
        "%d equations (batched, %d workers)",
        len(all_pages), n_lines, n_tables, n_eqs, effective_workers,
    )
    return all_pages
