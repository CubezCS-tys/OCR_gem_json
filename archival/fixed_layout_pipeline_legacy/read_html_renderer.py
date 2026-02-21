"""
Word-Level Fidelity HTML Renderer from ``prebuilt-read`` OCR JSON.

Each word is absolutely positioned at its bounding-box coordinates.
No fixed widths, no overflow clipping — font rendering differences
never accumulate.

Usage (standalone):
    python -m fixed_layout_pipeline render-read --input output_read_test

Usage (library):
    from fixed_layout_pipeline.read_html_renderer import render_document
    html = render_document(ocr_data, dpi=150)
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_STACK_RTL = (
    "'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
    "'Simplified Arabic', 'Tahoma', serif"
)
FONT_STACK_LTR = (
    "'Noto Serif', 'Times New Roman', 'Georgia', "
    "'Amiri', 'Noto Naskh Arabic', serif"
)

_STRONG_BIDI = frozenset({'L', 'R', 'AL'})


# ── Helpers ──────────────────────────────────────────────────────────────────

def polygon_to_bbox(polygon: list[float]) -> tuple[float, float, float, float]:
    """[x0,y0,…x3,y3] → (x, y, w, h) inches."""
    xs, ys = polygon[0::2], polygon[1::2]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return x0, y0, x1 - x0, y1 - y0


def detect_direction(text: str) -> str:
    """First strong BiDi character → 'rtl' or 'ltr'."""
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ('R', 'AL'):
            return 'rtl'
        if bidi == 'L':
            return 'ltr'
    return 'rtl'


# ── Per-page / per-document renderers ────────────────────────────────────────

def render_page(page: dict, dpi: float, scale: float = 1.0) -> str:
    """Render one page with each word as an absolutely-positioned span."""
    w_px = int(page["width"] * dpi * scale)
    h_px = int(page["height"] * dpi * scale)
    num = page["pageNumber"]

    spans = []
    for word in page.get("words", []):
        text = word["content"]
        x_in, y_in, _, h_in = polygon_to_bbox(word["polygon"])
        x, y, h = x_in * dpi * scale, y_in * dpi * scale, h_in * dpi * scale
        d = detect_direction(text)
        fs = max(8, h * 0.75) if d == 'rtl' else max(8, h * 0.80)
        conf = word.get("confidence", 0.95)
        t = html_mod.escape(text)
        spans.append(
            f'    <span class="w" dir="{d}" data-conf="{conf:.2f}" '
            f'style="left:{x:.1f}px;top:{y:.1f}px;'
            f'font-size:{fs:.1f}px;line-height:{h:.1f}px;">{t}</span>'
        )

    return (
        f'  <div class="page" id="page-{num}" lang="ar" '
        f'style="width:{w_px}px;height:{h_px}px;">\n'
        + "\n".join(spans)
        + f'\n    <div class="page-num">{num}</div>\n  </div>'
    )


def render_document(data: dict, dpi: float = 150, scale: float = 1.0) -> str:
    """Render the full multi-page fidelity HTML."""
    pages = data.get("pages", [])
    if not pages:
        return "<html><body><p>No pages found</p></body></html>"

    pages_html = [render_page(p, dpi, scale) for p in pages]
    total_words = sum(len(p.get("words", [])) for p in pages)
    doc_dir = detect_direction(data.get("content", ""))

    return f"""<!DOCTYPE html>
<html lang="ar" dir="{doc_dir}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Document — Word-Level Fidelity</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Amiri&family=Noto+Naskh+Arabic&family=Noto+Serif&display=swap" rel="stylesheet">
<style>
:root{{--arabic:{FONT_STACK_RTL};--latin:{FONT_STACK_LTR};--ink:#111;}}
*,*::before,*::after{{box-sizing:border-box;}}
body{{margin:0;padding:20px;background:#525659;display:flex;flex-direction:column;align-items:center;font-family:var(--arabic);}}
.page{{position:relative;background:#fff;margin:20px auto;box-shadow:0 2px 10px rgba(0,0,0,.35);}}
.w{{position:absolute;white-space:nowrap;cursor:text;color:var(--ink);font-variant-ligatures:contextual;text-rendering:geometricPrecision;-webkit-font-smoothing:antialiased;line-height:1;}}
.w[dir="rtl"]{{font-family:var(--arabic);transform-origin:top right;}}
.w[dir="ltr"]{{font-family:var(--latin);transform-origin:top left;}}
.w::selection{{background:rgba(0,120,215,.35);}}
.w:hover{{background:rgba(255,255,0,.15);border-radius:2px;}}
.page-num{{position:absolute;bottom:4px;left:50%;transform:translateX(-50%);font-size:11px;color:#aaa;pointer-events:none;user-select:none;z-index:5;}}
.toolbar{{position:fixed;top:10px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,.88);color:#fff;padding:8px 18px;border-radius:8px;z-index:1000;display:flex;gap:14px;align-items:center;font-family:sans-serif;font-size:13px;box-shadow:0 2px 12px rgba(0,0,0,.4);}}
.toolbar button{{background:#444;color:#fff;border:none;padding:5px 12px;border-radius:4px;cursor:pointer;font-size:12px;}}
.toolbar button:hover{{background:#666;}}
.toolbar button.active{{background:#0078d7;}}
.toolbar button:disabled{{opacity:.45;cursor:default;}}
.zoom-level{{min-width:54px;text-align:center;color:#ddd;font-variant-numeric:tabular-nums;}}
#pages-container{{padding-top:26px;}}
.debug-mode .w{{outline:1px solid rgba(0,120,215,.3);}}
.confidence-mode .w[data-conf^="0.7"],.confidence-mode .w[data-conf^="0.6"],.confidence-mode .w[data-conf^="0.5"],.confidence-mode .w[data-conf^="0.4"],.confidence-mode .w[data-conf^="0.3"]{{background:rgba(220,80,60,.25);border-radius:2px;}}
@media print{{body{{background:#fff;padding:0;}}.page{{box-shadow:none;margin:0;page-break-after:always;}}.toolbar,.page-num{{display:none;}}}}
</style>
</head>
<body>
<div class="toolbar">
  <span>📄 {len(pages)} pages · {total_words} words</span>
  <span style="opacity:.4">|</span>
  <button onclick="zoomOut()" id="btn-zoom-out" title="Zoom out">-</button>
  <span id="zoom-level" class="zoom-level">100%</span>
  <button onclick="zoomIn()" id="btn-zoom-in" title="Zoom in">+</button>
  <button onclick="fitToPage(true)" id="btn-fit" title="Fit page to viewport">Fit</button>
  <button onclick="document.body.classList.toggle('debug-mode');this.classList.toggle('active')" id="btn-dbg">Debug</button>
  <button onclick="document.body.classList.toggle('confidence-mode');this.classList.toggle('active')" id="btn-conf">Confidence</button>
</div>
<div id="pages-container">
{chr(10).join(pages_html)}
</div>
<script>
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 3.0;
const ZOOM_STEP = 0.1;
let viewerZoom = 1.0;
let autoFitOnResize = true;

function clampZoom(value) {{
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value));
}}

function updateZoomLabel() {{
  document.getElementById('zoom-level').textContent = Math.round(viewerZoom * 100) + '%';
  document.getElementById('btn-zoom-out').disabled = viewerZoom <= MIN_ZOOM + 0.001;
  document.getElementById('btn-zoom-in').disabled = viewerZoom >= MAX_ZOOM - 0.001;
}}

function applyZoom(value) {{
  viewerZoom = clampZoom(value);
  document.getElementById('pages-container').style.zoom = viewerZoom.toFixed(3);
  updateZoomLabel();
}}

function fitToPage(force = false) {{
  if (force) autoFitOnResize = true;
  if (!autoFitOnResize) return;
  const pages = Array.from(document.querySelectorAll('.page'));
  if (!pages.length) return;
  const maxWidth = Math.max(...pages.map((p) => p.offsetWidth || parseFloat(p.style.width) || 0));
  if (!maxWidth) return;
  const availableWidth = Math.max(320, window.innerWidth - 48);
  applyZoom(Math.min(1, availableWidth / maxWidth));
}}

function zoomIn() {{
  autoFitOnResize = false;
  applyZoom(viewerZoom + ZOOM_STEP);
}}

function zoomOut() {{
  autoFitOnResize = false;
  applyZoom(viewerZoom - ZOOM_STEP);
}}

window.addEventListener('load', () => fitToPage(true));
window.addEventListener('resize', () => fitToPage());
</script>
</body>
</html>"""


# ── Batch helpers ────────────────────────────────────────────────────────────

def process_folder(folder: Path, dpi: float = 150, scale: float = 1.0) -> bool:
    """Render HTML for a single document folder containing ``*_ocr.json``."""
    jsons = list(folder.glob("*_ocr.json"))
    if not jsons:
        return False

    json_path = jsons[0]
    stem = json_path.stem.replace("_ocr", "")
    html_path = folder / f"{stem}_fidelity.html"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    html_path.write_text(render_document(data, dpi, scale), encoding="utf-8")

    n_pages = len(data.get("pages", []))
    n_words = sum(len(p.get("words", [])) for p in data.get("pages", []))
    logger.info("✅ %s → %d pages, %d words", stem, n_pages, n_words)
    return True


def render_directory(input_dir: Path, dpi: float = 150, scale: float = 1.0) -> int:
    """Render HTML for every document subfolder under *input_dir*."""
    if list(input_dir.glob("*_ocr.json")):
        return 1 if process_folder(input_dir, dpi, scale) else 0

    count = 0
    for sub in sorted(input_dir.iterdir()):
        if sub.is_dir() and process_folder(sub, dpi, scale):
            count += 1
    return count
