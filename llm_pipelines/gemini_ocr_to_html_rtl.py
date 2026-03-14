#!/usr/bin/env python3
"""
Scanned PDF -> Gemini 3 Flash -> JSON blocks (flow/document understanding) -> HTML with RTL/LTR + boilerplate de-dup.

Adds a post-pass that:
- Finds repeated header/footer/page_number blocks across pages
- Marks them role="boilerplate"
- By default, hides boilerplate meta blocks in HTML

Outputs:
  out_dir/pages/page_0001.png
  out_dir/pages/page_0001.json
  out_dir/merged.json
  out_dir/document.html
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

from google import genai
from google.genai import types


# -------------------------
# Prompts / Schema
# -------------------------

SCHEMA_DESCRIPTION = r"""
Return ONLY valid JSON (no markdown, no commentary).

Top-level:
{
  "page": <int>,
  "page_size": {"width_px": <int>, "height_px": <int>},
  "direction": "rtl" | "ltr" | "mixed",
  "language": "ar" | "en" | "mixed" | "unknown",
  "blocks": [
    {
      "type": "title" | "heading" | "paragraph" | "list" | "table" | "equation" | "figure" | "footnote" | "header" | "footer" | "page_number",
      "role": "main" | "boilerplate",

      "direction": "rtl" | "ltr" | "mixed",
      "language": "ar" | "en" | "mixed" | "unknown",

      "text": <string|null>,
      "latex": <string|null>,

      "table": {
        "caption": <string|null>,
        "rows": [
          [
            {"text": <string>, "rowspan": <int>, "colspan": <int>}
          ]
        ]
      } | null,

      "figure": {
        "caption": <string|null>,
        "ref": <string|null>
      } | null
    }
  ]
}

Rules:
- Blocks MUST be in correct READING ORDER for the page.
- Extract everything visible, including headers, footers, page numbers.
- Mark repeated headers/footers/page numbers as role="boilerplate" when appropriate.
- Tables MUST be structured in table.rows (no prose table).
- Equations MUST be LaTeX in "latex". Keep "text" null for pure equations.
- Detect direction:
  - If Arabic script dominates: direction="rtl"
  - If Latin dominates: direction="ltr"
  - If strongly mixed: direction="mixed"
- Detect language similarly (ar/en/mixed/unknown).
- Do NOT hallucinate content. If unreadable, keep best guess with "[unclear]".
"""

TASK_INSTRUCTIONS = r"""
You are doing OCR + document understanding on a SCANNED page image.

Goal: accurate transcription + structure + FLOW (reading order), not pixel-perfect layout.

Extract:
- Titles/headings/paragraphs/lists
- Tables as structured cells
- Equations as LaTeX
- Figures with captions (if present)
- Footnotes
- Headers/footers/page numbers as separate blocks

Return JSON matching the schema exactly.
"""


# -------------------------
# Helpers
# -------------------------

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def strip_code_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def safe_json_load(s: str) -> Any:
    return json.loads(strip_code_fences(s))


def backoff_sleep(attempt: int) -> None:
    time.sleep(min(8.0, 0.8 * (2 ** attempt)))


# -------------------------
# RTL/LTR heuristic fallback
# -------------------------

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def detect_lang_dir(text: str) -> Tuple[str, str]:
    if not text or not text.strip():
        return "unknown", "mixed"

    ar = len(_ARABIC_RE.findall(text))
    la = len(_LATIN_RE.findall(text))

    if ar == 0 and la == 0:
        return "unknown", "mixed"

    if ar > 0 and la == 0:
        return "ar", "rtl"
    if la > 0 and ar == 0:
        return "en", "ltr"

    if ar >= la:
        return "mixed", "rtl"
    return "mixed", "ltr"


def normalise_dir(value: Any) -> str:
    v = str(value).lower().strip() if value is not None else ""
    if v in {"rtl", "ltr", "mixed"}:
        return v
    return "mixed"


def normalise_lang(value: Any) -> str:
    v = str(value).lower().strip() if value is not None else ""
    if v in {"ar", "en", "mixed", "unknown"}:
        return v
    return "unknown"


# -------------------------
# PDF rendering
# -------------------------

def render_pdf_pages(pdf_path: Path, out_pages_dir: Path, dpi: int) -> List[Tuple[int, Path, Tuple[int, int]]]:
    doc = fitz.open(str(pdf_path))
    results: List[Tuple[int, Path, Tuple[int, int]]] = []

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for i in range(doc.page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_path = out_pages_dir / f"page_{i+1:04d}.png"
        pix.save(str(png_path))
        results.append((i + 1, png_path, (pix.width, pix.height)))

    doc.close()
    return results


def load_image_bytes(path: Path) -> bytes:
    with Image.open(path) as im:
        if im.mode != "RGB":
            im = im.convert("RGB")
        import io
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


# -------------------------
# Minimal validation
# -------------------------

_ALLOWED_TYPES = {
    "title", "heading", "paragraph", "list", "table", "equation", "figure",
    "footnote", "header", "footer", "page_number"
}


def minimal_validate(page_obj: Dict[str, Any]) -> None:
    if not isinstance(page_obj, dict):
        raise ValueError("Top-level is not an object")
    for key in ["page", "page_size", "blocks"]:
        if key not in page_obj:
            raise ValueError(f"Missing key: {key}")

    if not isinstance(page_obj["page"], int):
        raise ValueError("page must be int")

    ps = page_obj["page_size"]
    if not isinstance(ps, dict) or "width_px" not in ps or "height_px" not in ps:
        raise ValueError("page_size must include width_px/height_px")

    if not isinstance(page_obj["blocks"], list):
        raise ValueError("blocks must be list")

    for b in page_obj["blocks"]:
        if not isinstance(b, dict):
            raise ValueError("block not object")
        if b.get("type") not in _ALLOWED_TYPES:
            raise ValueError(f"invalid block.type: {b.get('type')}")
        if b.get("role") not in {"main", "boilerplate"}:
            raise ValueError(f"invalid block.role: {b.get('role')}")

        if b["type"] == "equation" and not b.get("latex"):
            raise ValueError("equation block must include latex")

        if b["type"] == "table" and b.get("table") is None:
            raise ValueError("table block must include table")


def postprocess_page_obj(obj: Dict[str, Any], page_num: int, w: int, h: int) -> Dict[str, Any]:
    obj["page"] = page_num
    obj.setdefault("page_size", {"width_px": w, "height_px": h})
    if isinstance(obj.get("page_size"), dict):
        obj["page_size"]["width_px"] = w
        obj["page_size"]["height_px"] = h

    obj["direction"] = normalise_dir(obj.get("direction"))
    obj["language"] = normalise_lang(obj.get("language"))

    if obj["language"] == "unknown" or obj["direction"] == "mixed":
        combined = []
        for b in obj.get("blocks", []):
            if isinstance(b, dict) and b.get("text"):
                combined.append(str(b["text"]))
        if combined:
            lang, d = detect_lang_dir("\n".join(combined))
            if obj["language"] == "unknown":
                obj["language"] = lang
            if obj["direction"] == "mixed":
                obj["direction"] = d if d in {"rtl", "ltr"} else "mixed"

    for b in obj.get("blocks", []):
        if not isinstance(b, dict):
            continue
        b["direction"] = normalise_dir(b.get("direction"))
        b["language"] = normalise_lang(b.get("language"))

        txt = b.get("text") or ""
        if (b["language"] == "unknown" or b["direction"] == "mixed") and txt:
            lang, d = detect_lang_dir(str(txt))
            if b["language"] == "unknown":
                b["language"] = lang
            if b["direction"] == "mixed":
                b["direction"] = d

        if b.get("type") == "equation":
            b["direction"] = "ltr"
            if b["language"] == "unknown":
                b["language"] = "mixed"

    return obj


# -------------------------
# Boilerplate de-dup across pages
# -------------------------

_DIGITS_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _normalise_boilerplate_text(t: str, kind: str) -> str:
    """
    Normalise header/footer/page_number text so repeated strings match across pages.
    - Lowercase (for Latin; Arabic unaffected)
    - Collapse whitespace
    - Replace digits with a placeholder (so "Page 1" ~= "Page 2")
    """
    t = t or ""
    t = t.strip()
    t = _WS_RE.sub(" ", t)
    t = t.lower()

    # For page_number and many running headers/footers, digits vary by page.
    # Replace digits to allow matching.
    if kind in {"page_number", "header", "footer"}:
        t = _DIGITS_RE.sub("#", t)

    # Remove common purely decorative separators
    t = t.replace("–", "-").replace("—", "-")
    t = _WS_RE.sub(" ", t).strip()
    return t


def dedup_boilerplate_across_pages(
    pages: List[Dict[str, Any]],
    min_pages: int = 2,
    min_ratio: float = 0.6,
) -> Dict[str, int]:
    """
    Marks repeated header/footer/page_number blocks as role="boilerplate".

    Strategy:
    - Build a frequency table of normalised text for header/footer/page_number blocks.
    - Anything appearing on >= min_pages and >= min_ratio of total pages becomes boilerplate.

    Returns stats dict: {"marked": int, "total_candidates": int}
    """
    total_pages = len(pages)
    if total_pages == 0:
        return {"marked": 0, "total_candidates": 0}

    # Count occurrences by kind+normalised_text, but only once per page for each key
    per_key_pages = defaultdict(set)  # (kind, norm_text) -> set(page_index)
    candidates = 0

    for pi, p in enumerate(pages):
        seen_this_page = set()
        for b in p.get("blocks", []):
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind not in {"header", "footer", "page_number"}:
                continue
            txt = b.get("text") or ""
            norm = _normalise_boilerplate_text(str(txt), kind)
            if not norm:
                continue
            key = (kind, norm)
            if key in seen_this_page:
                continue
            seen_this_page.add(key)
            per_key_pages[key].add(pi)
            candidates += 1

    # Decide which keys are boilerplate
    boiler_keys = set()
    for key, page_set in per_key_pages.items():
        count = len(page_set)
        if count >= min_pages and (count / total_pages) >= min_ratio:
            boiler_keys.add(key)

    # Mark blocks
    marked = 0
    for pi, p in enumerate(pages):
        for b in p.get("blocks", []):
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind not in {"header", "footer", "page_number"}:
                continue
            txt = b.get("text") or ""
            norm = _normalise_boilerplate_text(str(txt), kind)
            if (kind, norm) in boiler_keys:
                if b.get("role") != "boilerplate":
                    b["role"] = "boilerplate"
                    marked += 1

    return {"marked": marked, "total_candidates": candidates}


# -------------------------
# Gemini call
# -------------------------

def gemini_ocr_page(
    client: genai.Client,
    model: str,
    page_num: int,
    image_bytes: bytes,
    width_px: int,
    height_px: int,
    temperature: float = 0.0,
    max_retries: int = 4,
) -> Dict[str, Any]:
    contents = [
        types.Part.from_text(TASK_INSTRUCTIONS),
        types.Part.from_text(SCHEMA_DESCRIPTION),
        types.Part.from_text(f"Page number: {page_num}. Page size: {width_px}x{height_px} pixels."),
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        types.Part.from_text("Now output the JSON only."),
    ]

    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                ),
            )
            text = (resp.text or "").strip()
            if not text:
                raise ValueError("Empty response text")

            obj = safe_json_load(text)
            if not isinstance(obj, dict):
                raise ValueError("Response is not a JSON object")

            obj = postprocess_page_obj(obj, page_num, width_px, height_px)
            minimal_validate(obj)
            return obj

        except Exception as e:
            last_err = e
            if attempt < max_retries:
                backoff_sleep(attempt)
                contents.append(
                    types.Part.from_text(
                        "Your previous output was invalid JSON or did not match the schema."
                        "Fix it. Return ONLY valid JSON matching the schema. Do not add commentary."
                    )
                )
                continue
            break

    raise RuntimeError(f"Failed page {page_num} after retries. Last error: {last_err}")


# -------------------------
# HTML rendering
# -------------------------

def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#039;")
    )


def block_to_html(block: Dict[str, Any], show_boilerplate: bool) -> str:
    t = block.get("type")
    role = block.get("role", "main")
    direction = block.get("direction", "mixed")
    text = block.get("text") or ""
    latex = block.get("latex") or ""

    role_cls = "boilerplate" if role == "boilerplate" else "main"
    dir_attr = "rtl" if direction == "rtl" else ("ltr" if direction == "ltr" else "auto")

    # Hide boilerplate meta by default
    if (not show_boilerplate) and role == "boilerplate" and t in ("header", "footer", "page_number"):
        return ""

    if t in ("header", "footer", "page_number"):
        return f'<div dir="{dir_attr}" class="meta {role_cls} {t}">{escape_html(text)}</div>'

    if t == "title":
        return f'<h1 dir="{dir_attr}" class="{role_cls}">{escape_html(text)}</h1>'

    if t == "heading":
        return f'<h2 dir="{dir_attr}" class="{role_cls}">{escape_html(text)}</h2>'

    if t == "paragraph":
        return f'<p dir="{dir_attr}" class="{role_cls}">{escape_html(text)}</p>'

    if t == "list":
        items = [x.strip() for x in str(text).splitlines() if x.strip()]
        lis = "\n".join(f'<li dir="{dir_attr}">{escape_html(i)}</li>' for i in items)
        return f'<ul class="{role_cls}">\n{lis}\n</ul>'

    if t == "equation":
        return f'<div dir="ltr" class="{role_cls} equation">\\[{escape_html(latex)}\\]</div>'

    if t == "table":
        table = block.get("table") or {}
        caption = table.get("caption")
        rows = table.get("rows") or []

        html_rows = []
        for r in rows:
            cells_html = []
            for c in r:
                ctext = escape_html(str(c.get("text", "")))
                rowspan = int(c.get("rowspan", 1) or 1)
                colspan = int(c.get("colspan", 1) or 1)
                attrs = ""
                if rowspan > 1:
                    attrs += f' rowspan="{rowspan}"'
                if colspan > 1:
                    attrs += f' colspan="{colspan}"'
                cells_html.append(f"<td{attrs}>{ctext}</td>")
            html_rows.append("<tr>" + "".join(cells_html) + "</tr>")

        cap_html = f"<caption>{escape_html(caption)}</caption>" if caption else ""
        return f'<table dir="{dir_attr}" class="{role_cls}">\n{cap_html}\n' + "\n".join(html_rows) + "\n</table>'

    if t == "figure":
        fig = block.get("figure") or {}
        cap = fig.get("caption") or ""
        ref = fig.get("ref") or ""
        return (
            f'<div dir="{dir_attr}" class="{role_cls} figure">'
            f'<div class="figref">{escape_html(ref)}</div>'
            f'<div class="figcap">{escape_html(cap)}</div>'
            f'</div>'
        )

    if t == "footnote":
        return f'<div dir="{dir_attr}" class="{role_cls} footnote">{escape_html(text)}</div>'

    return f'<div dir="{dir_attr}" class="{role_cls}">{escape_html(text)}</div>'


def render_document_html(pages: List[Dict[str, Any]], show_boilerplate: bool) -> str:
    head = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>OCR Document</title>

<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"></script>

<style>
  body {
    font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    margin: 24px;
    line-height: 1.55;
  }

  [dir="rtl"] { direction: rtl; text-align: right; }
  [dir="ltr"] { direction: ltr; text-align: left; }

  p, div, li, h1, h2, td, caption { unicode-bidi: plaintext; }

  .page { border-top: 1px solid #ddd; padding-top: 16px; margin-top: 24px; }
  .meta { font-size: 12px; opacity: 0.70; }
  .boilerplate { opacity: 0.80; }

  table { border-collapse: collapse; margin: 12px 0; width: 100%; }
  td { border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; }
  caption { text-align: start; font-weight: 600; margin-bottom: 6px; }

  .equation { margin: 12px 0; }
  .footnote { font-size: 12px; opacity: 0.92; margin-top: 10px; }
  .figure { border: 1px dashed #bbb; padding: 10px; margin: 12px 0; }
  .figref { font-weight: 600; margin-bottom: 4px; }
</style>
</head>
<body>
<script>
document.addEventListener("DOMContentLoaded", function() {
  renderMathInElement(document.body, {
    delimiters: [
      {left: "$$", right: "$$", display: true},
      {left: "\\\\[", right: "\\\\]", display: true},
      {left: "\\\\(", right: "\\\\)", display: false},
      {left: "$", right: "$", display: false}
    ]
  });
});
</script>
"""
    body_parts: List[str] = []
    for p in pages:
        pn = p.get("page")
        page_dir = p.get("direction", "mixed")
        page_dir_attr = "rtl" if page_dir == "rtl" else ("ltr" if page_dir == "ltr" else "auto")

        body_parts.append(f'<div class="page" id="page-{pn}" dir="{page_dir_attr}">')
        body_parts.append(f'<div class="meta">Page {pn}</div>')

        for b in p.get("blocks", []):
            html = block_to_html(b, show_boilerplate=show_boilerplate)
            if html:
                body_parts.append(html)

        body_parts.append("</div>")

    tail = "\n</body>\n</html>\n"
    return head + "\n".join(body_parts) + tail


# -------------------------
# Main
# -------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=str, help="Input scanned PDF path")
    ap.add_argument("--out", type=str, default="out_ocr", help="Output directory")
    ap.add_argument("--dpi", type=int, default=350, help="Render DPI (300-400 recommended for scans)")
    ap.add_argument("--model", type=str, default="gemini-3-flash-preview", help="Gemini model id")
    ap.add_argument("--max-pages", type=int, default=0, help="Limit pages (0=all)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--show-boilerplate", action="store_true", help="Show boilerplate headers/footers in HTML")
    ap.add_argument("--boilerplate-min-ratio", type=float, default=0.6, help="Min fraction of pages for boilerplate")
    ap.add_argument("--boilerplate-min-pages", type=int, default=2, help="Min pages for boilerplate")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    pages_dir = out_dir / "pages"
    ensure_dir(out_dir)
    ensure_dir(pages_dir)

    client = genai.Client()

    renders = render_pdf_pages(pdf_path, pages_dir, dpi=args.dpi)
    if args.max_pages and args.max_pages > 0:
        renders = renders[: args.max_pages]

    extracted_pages: List[Dict[str, Any]] = []

    for page_num, png_path, (w, h) in renders:
        json_path = pages_dir / f"page_{page_num:04d}.json"

        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                obj = postprocess_page_obj(obj, page_num, w, h)
                minimal_validate(obj)
                extracted_pages.append(obj)
                print(f"[OK] page {page_num} (cached)")
                continue
            except Exception:
                print(f"[WARN] page {page_num} cache invalid, redoing...")

        img_bytes = load_image_bytes(png_path)

        print(f"[RUN] page {page_num} -> Gemini")
        obj = gemini_ocr_page(
            client=client,
            model=args.model,
            page_num=page_num,
            image_bytes=img_bytes,
            width_px=w,
            height_px=h,
            temperature=args.temperature,
        )

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

        extracted_pages.append(obj)
        print(f"[OK] page {page_num}")

    # Boilerplate de-dup pass (across ALL pages)
    stats = dedup_boilerplate_across_pages(
        extracted_pages,
        min_pages=args.boilerplate_min_pages,
        min_ratio=args.boilerplate_min_ratio,
    )
    print(f"[INFO] boilerplate marked: {stats['marked']} (candidates seen: {stats['total_candidates']})")

    merged = {
        "source_pdf": str(pdf_path),
        "model": args.model,
        "dpi": args.dpi,
        "boilerplate_dedup": {
            "min_pages": args.boilerplate_min_pages,
            "min_ratio": args.boilerplate_min_ratio,
            "marked": stats["marked"],
        },
        "pages": extracted_pages,
    }
    merged_path = out_dir / "merged.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    html = render_document_html(extracted_pages, show_boilerplate=args.show_boilerplate)
    html_path = out_dir / "document.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone.\n- {merged_path}\n- {html_path}\n")


if __name__ == "__main__":
    main()