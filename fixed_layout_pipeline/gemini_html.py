"""
Gemini Fidelity HTML Generator (hybrid approach).

Positions are computed EXACTLY from OCR JSON polygon data (no LLM math).
Gemini is used ONLY for semantic classification (heading, quran, footnote, etc.).

Usage (standalone):
    python -m fixed_layout_pipeline gemini-html \\
        --pdf  doc_searchable.pdf \\
        --json doc_ocr.json

    python -m fixed_layout_pipeline gemini-html \\
        --pdf doc.pdf --json doc.json --no-gemini   # skip Gemini

Usage (library):
    from fixed_layout_pipeline.gemini_html import render
    render(pdf_path, json_path, output_path, model="gemini-2.0-flash")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

DPI = 150


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_rtl(text: str) -> bool:
    """True if text is predominantly Arabic / RTL."""
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF' or '\uFE70' <= c <= '\uFEFF')
    return arabic > len(text) * 0.2


def _auto_classify(text: str) -> str | None:
    """Rule-based classification for obvious cases."""
    if '﴿' in text or '﴾' in text:
        return 'quran'
    if re.fullmatch(r'[\d٠-٩]+', text.strip()):
        return 'page_number'
    return None


# ── Step 1: Exact positions from JSON polygons ──────────────────────────────

def extract_pages(ocr_data: dict, page_num: int | None = None) -> list[dict]:
    """Parse OCR JSON and compute pixel positions at *DPI*."""
    pages = ocr_data.get("pages", [])
    if page_num is not None:
        pages = [p for p in pages if p["pageNumber"] == page_num]

    result = []
    for page in pages:
        w_in, h_in = page["width"], page["height"]
        w_px, h_px = round(w_in * DPI), round(h_in * DPI)

        lines = []
        for line in page.get("lines", []):
            poly = line["polygon"]
            xs = [poly[i] for i in range(0, 8, 2)]
            ys = [poly[i] for i in range(1, 8, 2)]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            h = (y_max - y_min) * DPI
            top = y_min * DPI

            rtl = _is_rtl(line["content"])
            if rtl:
                pos_css = f"right: {(w_in - x_max) * DPI:.1f}px"
            else:
                pos_css = f"left: {x_min * DPI:.1f}px"

            lines.append({
                "content": line["content"],
                "top_px": round(top, 1),
                "height_px": round(h, 1),
                "font_size_px": round(h * 0.72, 1),
                "pos_css": pos_css,
                "rtl": rtl,
                "auto_type": _auto_classify(line["content"]),
            })

        result.append({
            "pageNumber": page["pageNumber"],
            "width_px": w_px, "height_px": h_px,
            "lines": lines,
        })
    return result


# ── Step 2: Gemini semantic classification ──────────────────────────────────

def classify_with_gemini(
    pages: list[dict], pdf_path: Path, model: str,
) -> tuple[dict, object, float]:
    """Send line text + PDF visual to Gemini for semantic classification."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)

    line_list = [
        {"p": pg["pageNumber"], "i": i, "t": ln["content"][:120]}
        for pg in pages for i, ln in enumerate(pg["lines"])
    ]

    prompt = f"""Look at the attached Arabic PDF and classify each text line below.

Categories:
  heading     – main titles / section headings (visually larger or bolder)
  subheading  – subtitles, author bylines
  body        – normal paragraph text
  quran       – Quranic verses (usually between ﴿ ﴾ or heavily diacritized)
  footnote    – smaller text, footnote references
  page_number – page numbers
  decorative  – repeated header/footer banners, decorative labels

Return a JSON array: [{{"p":<page>,"i":<index>,"c":"<category>"}},...].
Return ONLY the JSON, no explanation.

Lines:
{json.dumps(line_list, ensure_ascii=False)}"""

    t0 = time.time()
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=pdf_path.read_bytes(), mime_type="application/pdf"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type="application/json",
        ),
    )
    elapsed = time.time() - t0

    text = response.text.strip()
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Gemini returned invalid JSON — falling back to auto-classify")
        items = []

    lookup = {(it["p"], it["i"]): it.get("c", "body") for it in items}
    return lookup, response.usage_metadata, elapsed


# ── Step 3: Build HTML ──────────────────────────────────────────────────────

_TYPE_CSS = {
    "heading":     ("font-weight: bold;", 1.10),
    "subheading":  ("font-weight: bold;", 1.00),
    "body":        ("", 1.00),
    "quran":       ("font-weight: bold; color: #1a1a1a;", 1.00),
    "footnote":    ("color: #555;", 0.92),
    "page_number": ("color: #888;", 0.85),
    "decorative":  ("color: #666;", 0.90),
}


def build_html(pages: list[dict], classifications: dict) -> str:
    """Assemble the final HTML string."""
    pages_html = []

    for page in pages:
        line_divs = []
        for i, ln in enumerate(page["lines"]):
            lt = ln["auto_type"] or classifications.get((page["pageNumber"], i), "body")
            extra_css, fs_scale = _TYPE_CSS.get(lt, ("", 1.0))
            fs = ln["font_size_px"] * fs_scale
            d = ' dir="rtl"' if ln["rtl"] else ' dir="ltr"'
            align = "text-align:right;" if ln["rtl"] else "text-align:left;"
            style = (
                f"top:{ln['top_px']}px;{ln['pos_css']};"
                f"font-size:{fs:.1f}px;line-height:{ln['height_px']}px;"
                f"{align}{extra_css}"
            )
            cls = f"line {lt}" if lt != "body" else "line"
            line_divs.append(f'    <div class="{cls}" style="{style}"{d}>{ln["content"]}</div>')

        pages_html.append(
            f'  <div class="page" style="width:{page["width_px"]}px;'
            f'height:{page["height_px"]}px;">\n'
            + "\n".join(line_divs)
            + "\n  </div>"
        )

    return f"""<!DOCTYPE html>
<html lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>OCR Document</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400;1,700&display=swap" rel="stylesheet">
<style>
body{{background:#525659;margin:0;padding:20px;display:flex;flex-direction:column;align-items:center;gap:20px;font-family:'Amiri',serif;}}
.page{{background:#fff;position:relative;box-shadow:0 0 15px rgba(0,0,0,.3);overflow:hidden;}}
.line{{position:absolute;white-space:nowrap;color:#000;}}
.heading{{font-weight:bold;}}
.subheading{{font-weight:bold;}}
.quran{{font-weight:bold;color:#1a1a1a;}}
.footnote{{color:#555;}}
.page_number{{color:#888;}}
.decorative{{color:#666;}}
</style>
</head>
<body>
{chr(10).join(pages_html)}
</body>
</html>"""


# ── Public API ──────────────────────────────────────────────────────────────

def render(
    pdf_path: Path,
    json_path: Path,
    output_path: Path,
    model: str = "gemini-2.0-flash",
    page_num: int | None = None,
    use_gemini: bool = True,
) -> Path:
    """
    Generate fidelity HTML from a searchable PDF + OCR JSON.

    Returns *output_path*.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        ocr_data = json.load(f)

    # Step 1 — exact positions
    logger.info("Step 1: Computing positions from JSON polygons…")
    pages = extract_pages(ocr_data, page_num)
    total_lines = sum(len(p["lines"]) for p in pages)
    logger.info("  %d lines across %d page(s)", total_lines, len(pages))

    # Step 2 — semantic classification
    classifications: dict = {}
    cost = 0.0
    if use_gemini:
        logger.info("Step 2: Classifying via %s…", model)
        classifications, usage, elapsed = classify_with_gemini(pages, pdf_path, model)
        inp = usage.prompt_token_count if usage else 0
        out = usage.candidates_token_count if usage else 0
        cost = (inp / 1e6) * 0.50 + (out / 1e6) * 3.00
        logger.info("  %.1fs | %d in / %d out | $%.4f", elapsed, inp, out, cost)
        for t, c in Counter(classifications.values()).most_common():
            logger.info("    %s: %d", t, c)
    else:
        logger.info("Step 2: Skipped (auto-classify only)")

    # Step 3 — assemble HTML
    logger.info("Step 3: Generating HTML…")
    html = build_html(pages, classifications)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    logger.info("✅ %s  (%d pages, %d lines, $%.4f)", output_path, len(pages), total_lines, cost)
    return output_path
