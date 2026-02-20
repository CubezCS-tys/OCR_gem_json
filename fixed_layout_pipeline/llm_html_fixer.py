"""
LLM HTML Correction Pass — uses Gemini to fix OCR errors in rendered HTML.

After the initial OCR + HTML render, this module sends each page's text
content along with the page image to an LLM for correction:
  - Fix Arabic OCR misreads (diacritics, letter confusions)
  - Repair broken mathematical equations and formulas
  - Fill in missing or truncated text
  - Fix word order / reading direction issues

Usage (standalone):
    python -m fixed_layout_pipeline.llm_html_fixer \
        --html  doc_replace_text.html \
        --pdf   doc_searchable.pdf \
        --json  doc_ocr.json

Usage (library):
    from fixed_layout_pipeline.llm_html_fixer import fix_html
    fixed = fix_html(html_path, pdf_path, json_path)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "gemini-2.0-flash"
MAX_LINES_PER_CHUNK = 80  # send lines in chunks to avoid context overflow


# ── Extract text divs from HTML ──────────────────────────────────────────────

_TW_RE = re.compile(
    r'<div\s+class="tw"\s+dir="([^"]*)"\s+data-lang="([^"]*)"\s+'
    r'style="([^"]*)">'
    r'(.*?)</div>',
    re.DOTALL,
)


def _extract_page_lines(html: str) -> list[list[dict]]:
    """
    Parse the rendered HTML and extract text divs grouped by page.
    Returns list of pages, each page is a list of line dicts.
    """
    pages: list[list[dict]] = []
    current_page_lines: list[dict] = []

    # Split by page divs
    page_splits = re.split(r'<div class="page"[^>]*>', html)

    for page_chunk in page_splits[1:]:  # skip before first page
        lines = []
        for m in _TW_RE.finditer(page_chunk):
            lines.append({
                "dir": m.group(1),
                "lang": m.group(2),
                "style": m.group(3),
                "text": m.group(4),
                "full_match": m.group(0),
            })
        pages.append(lines)

    return pages


# ── Rasterise a single page for context ──────────────────────────────────────

def _rasterise_page(pdf_path: Path, page_idx: int, dpi: int = 150) -> bytes:
    """Rasterise one page of the PDF as a JPEG for sending to the LLM."""
    import fitz

    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    # Convert to JPEG via PIL for smaller size
    try:
        from PIL import Image as PILImage
        img = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=75)
        result = buf.getvalue()
    except ImportError:
        result = pix.tobytes("png")

    doc.close()
    return result


# ── Build correction prompt ──────────────────────────────────────────────────

def _build_correction_prompt(lines: list[dict], page_num: int) -> str:
    """Build the prompt for the LLM to correct OCR text."""
    line_data = []
    for i, ln in enumerate(lines):
        line_data.append({
            "i": i,
            "text": ln["text"],
            "lang": ln["lang"],
        })

    return f"""You are correcting OCR output for page {page_num} of an Arabic academic document.

Look at the attached page image and compare it with the OCR text below.
Fix any errors you find:

1. **Arabic text errors**: Fix misread letters, missing/wrong diacritics,
   split words that should be joined, wrong letter forms (e.g. ه vs ة, ی vs ي).

2. **Mathematical equations**: Fix equation formatting. Use proper Arabic
   mathematical notation. Ensure fraction bars, subscripts, superscripts,
   and operators are correct. Keep equations as plain text (no LaTeX).

3. **Missing text**: If text visible in the image is missing from the OCR,
   add it to the nearest line.

4. **Page numbers, headers, footers**: Keep these as-is.

5. **DO NOT** change the line structure — keep the same number of lines.
   Each corrected line must correspond to the same line index.

Return ONLY a JSON array of corrections. Each item:
  {{"i": <line_index>, "fixed": "<corrected text>"}}

Only include lines that need correction. If a line is correct, omit it.
If no lines need correction, return an empty array: []

OCR lines:
{json.dumps(line_data, ensure_ascii=False, indent=2)}"""


# ── Call Gemini for corrections ──────────────────────────────────────────────

def _call_gemini(
    prompt: str,
    page_image: bytes,
    model: str,
) -> tuple[list[dict], float, int, int]:
    """
    Send prompt + page image to Gemini and parse corrections.
    Returns (corrections, elapsed, input_tokens, output_tokens).
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)

    t0 = time.time()
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=page_image, mime_type="image/jpeg"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type="application/json",
        ),
    )
    elapsed = time.time() - t0

    inp = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
    out = response.usage_metadata.candidates_token_count if response.usage_metadata else 0

    text = response.text.strip()
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)

    try:
        corrections = json.loads(text)
        if not isinstance(corrections, list):
            corrections = []
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON — skipping corrections")
        corrections = []

    return corrections, elapsed, inp, out


# ── Apply corrections to HTML ────────────────────────────────────────────────

def _apply_corrections(html: str, pages_lines: list[list[dict]],
                       all_corrections: list[list[dict]]) -> str:
    """
    Apply the LLM corrections back into the HTML string.
    Replaces text content of .tw divs while keeping all positioning intact.
    """
    import html as html_mod

    result = html
    total_fixes = 0

    for page_idx, (lines, corrections) in enumerate(zip(pages_lines, all_corrections)):
        if not corrections:
            continue

        # Build lookup from line index to corrected text
        fix_map = {}
        for corr in corrections:
            idx = corr.get("i")
            fixed = corr.get("fixed", "")
            if idx is not None and fixed and 0 <= idx < len(lines):
                fix_map[idx] = fixed

        # Replace each line's text in the HTML
        for idx, fixed_text in fix_map.items():
            line = lines[idx]
            old_match = line["full_match"]
            old_text = line["text"]

            # Escape the new text for HTML
            safe_text = html_mod.escape(fixed_text)
            new_match = old_match.replace(f">{old_text}</div>", f">{safe_text}</div>")

            if old_match in result:
                result = result.replace(old_match, new_match, 1)
                total_fixes += 1
                logger.debug(
                    "Page %d, line %d: '%s' → '%s'",
                    page_idx + 1, idx, old_text[:40], fixed_text[:40],
                )

    logger.info("Applied %d text corrections", total_fixes)
    return result


# ── Public API ───────────────────────────────────────────────────────────────

def fix_html(
    html_path: Path,
    pdf_path: Path,
    ocr_json_path: Path | None = None,
    output_path: Path | None = None,
    model: str | None = None,
    dpi: int = 150,
) -> Path:
    """
    Run LLM correction pass on a rendered HTML file.

    Parameters
    ----------
    html_path : path to the rendered HTML
    pdf_path : path to the searchable PDF (for page images)
    ocr_json_path : optional, not currently used
    output_path : where to write the corrected HTML (default: overwrite)
    model : Gemini model name (default from env or gemini-2.0-flash)
    dpi : DPI for page images sent to LLM

    Returns the output path.
    """
    from dotenv import load_dotenv
    load_dotenv()

    if model is None:
        model = os.environ.get("MODEL_NAME", DEFAULT_MODEL)

    if output_path is None:
        # Overwrite in place — the corrected version replaces the original
        output_path = html_path

    logger.info("LLM correction pass: %s", html_path.name)
    logger.info("  Model: %s | PDF: %s", model, pdf_path.name)

    html = html_path.read_text(encoding="utf-8")
    pages_lines = _extract_page_lines(html)
    n_pages = len(pages_lines)
    total_lines = sum(len(p) for p in pages_lines)

    logger.info("  %d pages, %d lines to check", n_pages, total_lines)

    if total_lines == 0:
        logger.warning("No text lines found in HTML — skipping")
        return output_path

    # Process each page
    all_corrections: list[list[dict]] = []
    total_cost = 0.0
    total_elapsed = 0.0
    total_fixes = 0

    import fitz
    doc = fitz.open(str(pdf_path))
    n_pdf_pages = len(doc)
    doc.close()

    for page_idx, lines in enumerate(pages_lines):
        if not lines:
            all_corrections.append([])
            continue

        if page_idx >= n_pdf_pages:
            logger.warning("Page %d beyond PDF page count — skipping", page_idx + 1)
            all_corrections.append([])
            continue

        # Rasterise page for visual context
        page_image = _rasterise_page(pdf_path, page_idx, dpi)

        # Build prompt and call LLM
        prompt = _build_correction_prompt(lines, page_idx + 1)

        try:
            corrections, elapsed, inp, out = _call_gemini(prompt, page_image, model)
        except Exception as e:
            logger.error("Page %d LLM call failed: %s", page_idx + 1, e)
            all_corrections.append([])
            continue

        cost = (inp / 1e6) * 0.10 + (out / 1e6) * 0.40  # Flash pricing
        total_cost += cost
        total_elapsed += elapsed
        n_fixes = len(corrections)
        total_fixes += n_fixes

        logger.info(
            "  Page %d/%d: %d fixes (%.1fs, %d→%d tokens, $%.4f)",
            page_idx + 1, n_pages, n_fixes, elapsed, inp, out, cost,
        )
        all_corrections.append(corrections)

    # Apply all corrections
    if total_fixes > 0:
        fixed_html = _apply_corrections(html, pages_lines, all_corrections)
    else:
        fixed_html = html
        logger.info("No corrections needed")

    output_path.write_text(fixed_html, encoding="utf-8")

    logger.info(
        "✅ LLM correction done: %d fixes across %d pages (%.1fs, $%.4f)",
        total_fixes, n_pages, total_elapsed, total_cost,
    )
    return output_path


# ── Batch fix ────────────────────────────────────────────────────────────────

def fix_directory(
    input_dir: Path,
    model: str | None = None,
    dpi: int = 150,
) -> list[dict]:
    """
    Run LLM correction pass on all documents in a directory.
    Expects structure: input_dir/<doc_id>/<doc_id>_replace_text.html + <doc_id>_searchable.pdf
    """
    results = []

    for subdir in sorted(input_dir.iterdir()):
        if not subdir.is_dir():
            continue

        stem = subdir.name
        html_files = list(subdir.glob("*_replace_text.html"))
        pdf_files = list(subdir.glob("*_searchable.pdf"))

        if not html_files or not pdf_files:
            logger.warning("Skipping %s — missing HTML or PDF", stem)
            continue

        html_path = html_files[0]
        pdf_path = pdf_files[0]

        # Create _llm_fixed.html output
        out_name = html_path.stem.replace("_replace_text", "_llm_fixed") + ".html"
        out_path = subdir / out_name

        try:
            fix_html(html_path, pdf_path, output_path=out_path, model=model, dpi=dpi)
            results.append({"file": stem, "status": "success", "output": str(out_path)})
        except Exception as e:
            logger.error("Failed %s: %s", stem, e)
            results.append({"file": stem, "status": "error", "error": str(e)})

    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="LLM correction pass for OCR HTML",
    )
    parser.add_argument("--html", type=Path, help="Single HTML file to fix")
    parser.add_argument("--pdf", type=Path, help="Searchable PDF (for page images)")
    parser.add_argument("--json", type=Path, help="OCR JSON (optional)")
    parser.add_argument("-o", "--output", type=Path, help="Output HTML path")
    parser.add_argument("-i", "--input-dir", type=Path, help="Directory of doc subdirectories")
    parser.add_argument("--model", type=str, help="Gemini model name")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for page images (default: 150)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from dotenv import load_dotenv
    load_dotenv()

    if args.input_dir:
        results = fix_directory(args.input_dir, model=args.model, dpi=args.dpi)
        ok = sum(1 for r in results if r["status"] == "success")
        print(f"\nFixed {ok}/{len(results)} documents")
    elif args.html and args.pdf:
        result = fix_html(
            args.html, args.pdf, args.json, args.output,
            model=args.model, dpi=args.dpi,
        )
        print(f"Output: {result}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
