"""
Image-Overlay HTML Renderer — pixel-perfect fidelity with selectable text.

Architecture
────────────
  ┌──────────────────────────────┐
  │  <div class="page">         │
  │    <img … base64 page/>     │  ← visual fidelity (rasterised page)
  │    <div class="text-layer"> │
  │      <div dir="rtl">…</div> │  ← invisible, selectable text
  │    </div>                   │
  │  </div>                     │
  └──────────────────────────────┘

The scanned page image provides 100% visual fidelity.
The invisible text overlay (color:transparent) enables:
  • text selection / highlighting
  • Ctrl-F search
  • copy-paste
  • screen-reader accessibility

Input:  PDF file  +  Azure prebuilt-read OCR JSON
Output: single self-contained HTML (images base64-embedded)

Cost:  prebuilt-read = $1.50 / 1K pages (cheapest Azure DI tier)
"""

from __future__ import annotations

import argparse
import base64
import html as html_mod
import json
import logging
import sys
import unicodedata
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_DPI = 200          # good quality / file-size balance
DEFAULT_IMAGE_FORMAT = "webp"
DEFAULT_IMAGE_QUALITY = 85
PageRaster = tuple[str, int, int]  # (data_uri, width_px, height_px)

# ── BiDi helpers ──────────────────────────────────────────────────────────────

_RTL_BIDI    = frozenset({"R", "AL"})


def _first_strong_dir(text: str) -> str:
    """Return 'rtl' or 'ltr' based on the first strong BiDi character."""
    for ch in text:
        cat = unicodedata.bidirectional(ch)
        if cat in _RTL_BIDI:
            return "rtl"
        if cat == "L":
            return "ltr"
    return "rtl"  # default for Arabic docs


def _pixmap_to_data_uri(
    pix,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
) -> str:
    """Encode a PyMuPDF pixmap to a base64 data URI."""
    buf = BytesIO()
    if image_format == "webp":
        # PyMuPDF doesn't support webp natively; fall back to PNG or use Pillow
        try:
            from PIL import Image as PILImage
            img = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img.save(buf, format="WEBP", quality=image_quality)
            mime = "image/webp"
        except ImportError:
            buf.write(pix.tobytes("png"))
            mime = "image/png"
    elif image_format == "jpeg":
        buf.write(pix.tobytes("jpeg"))
        mime = "image/jpeg"
    else:
        buf.write(pix.tobytes("png"))
        mime = "image/png"
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _pil_to_data_uri(
    img,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
) -> str:
    """Encode a PIL image to a base64 data URI."""
    buf = BytesIO()
    if image_format == "webp":
        img.save(buf, format="WEBP", quality=image_quality)
        mime = "image/webp"
    elif image_format == "jpeg":
        img.save(buf, format="JPEG", quality=image_quality)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG")
        mime = "image/png"
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ── Page rasterisation ────────────────────────────────────────────────────────

def rasterise_pdf(
    pdf_path: str | Path,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
) -> list[PageRaster]:
    """
    Rasterise every page of *pdf_path* and return a list of
    (base64 data URI, width_px, height_px) tuples (one per page).
    """
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    data_uris: list[PageRaster] = []

    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        data_uris.append((_pixmap_to_data_uri(pix, image_format, image_quality), pix.width, pix.height))

    doc.close()
    return data_uris


# ── OCR JSON parsing ─────────────────────────────────────────────────────────

def parse_ocr_json(ocr_path: str | Path) -> dict:
    """Load and return the Azure prebuilt-read OCR JSON."""
    with open(ocr_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _polygon_to_rect(polygon: list[float]) -> tuple[float, float, float, float]:
    """
    Convert Azure's 8-point polygon (x0,y0,x1,y1,x2,y2,x3,y3) in inches
    to (left, top, width, height) in inches.
    Takes the bounding rectangle of the 4 corners.
    """
    xs = [polygon[i] for i in range(0, 8, 2)]
    ys = [polygon[i] for i in range(1, 8, 2)]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return x_min, y_min, x_max - x_min, y_max - y_min


def _polygon_to_points(polygon: list[float]) -> list[tuple[float, float]]:
    """Convert a flattened polygon list into point tuples."""
    return [(polygon[i], polygon[i + 1]) for i in range(0, len(polygon) - 1, 2)]


def _safe_float(value) -> float | None:
    """Best-effort float conversion for OCR numeric fields."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_unit(unit: str | None) -> str:
    """Normalise OCR page unit labels to a small canonical set."""
    unit_norm = (unit or "inch").strip().lower()
    if unit_norm in {"in", "inch", "inches"}:
        return "inch"
    if unit_norm in {"px", "pixel", "pixels"}:
        return "pixel"
    if unit_norm in {"pt", "pts", "point", "points"}:
        return "point"
    return unit_norm


def _compute_page_scale_and_size(
    page_data: dict,
    raster_width_px: float | None,
    raster_height_px: float | None,
    dpi_fallback: float,
) -> tuple[float, float, float, float]:
    """
    Return (scale_x, scale_y, page_width_px, page_height_px).

    Preferred mapping is always OCR-page-units -> actual raster pixel size.
    Falls back to historical DPI logic only when raster/page dimensions are missing.
    """
    page_w = _safe_float(page_data.get("width")) or 0.0
    page_h = _safe_float(page_data.get("height")) or 0.0
    unit = _normalise_unit(page_data.get("unit"))

    if (
        raster_width_px is not None
        and raster_height_px is not None
        and page_w > 0
        and page_h > 0
    ):
        scale_x = float(raster_width_px) / page_w
        scale_y = float(raster_height_px) / page_h
        return scale_x, scale_y, float(raster_width_px), float(raster_height_px)

    if page_w <= 0 or page_h <= 0:
        width_px = float(raster_width_px) if raster_width_px is not None else 0.0
        height_px = float(raster_height_px) if raster_height_px is not None else 0.0
        return 1.0, 1.0, width_px, height_px

    # No raster dimensions available (text-only path): keep sensible fallback.
    if unit == "pixel":
        scale_x = 1.0
        scale_y = 1.0
    else:
        scale_x = float(dpi_fallback)
        scale_y = float(dpi_fallback)

    width_px = float(raster_width_px) if raster_width_px is not None else page_w * scale_x
    height_px = float(raster_height_px) if raster_height_px is not None else page_h * scale_y
    return scale_x, scale_y, width_px, height_px


# ── Text replacement helpers ──────────────────────────────────────────────────

def _sample_bg_color(
    img,  # PIL Image
    left: int, top: int, width: int, height: int,
    margin: int = 4,
) -> tuple[int, int, int]:
    """
    Sample background colour from a thin margin strip *around* a text bbox.
    Filters out dark (text) pixels and returns the median light colour.
    """
    iw, ih = img.size
    x0 = max(0, left - margin)
    x1 = min(iw, left + width + margin)

    strips = []
    # Top strip
    ty0, ty1 = max(0, top - margin), max(0, top)
    if ty1 > ty0 and x1 > x0:
        strips.append(img.crop((x0, ty0, x1, ty1)))
    # Bottom strip
    by0, by1 = min(ih, top + height), min(ih, top + height + margin)
    if by1 > by0 and x1 > x0:
        strips.append(img.crop((x0, by0, x1, by1)))
    # Left strip
    lx0, lx1 = max(0, left - margin), max(0, left)
    if lx1 > lx0:
        strips.append(img.crop((lx0, top, lx1, min(ih, top + height))))
    # Right strip
    rx0, rx1 = min(iw, left + width), min(iw, left + width + margin)
    if rx1 > rx0:
        strips.append(img.crop((rx0, top, rx1, min(ih, top + height))))

    if not strips:
        return (255, 255, 255)

    all_pixels: list[tuple] = []
    for strip in strips:
        all_pixels.extend(list(strip.get_flattened_data()))

    if not all_pixels:
        return (255, 255, 255)

    # Keep only light pixels (avg channel > 150) to avoid sampling text
    light = [p for p in all_pixels if (p[0] + p[1] + p[2]) > 450]
    if not light:
        light = all_pixels  # fallback

    light.sort(key=lambda p: p[0] + p[1] + p[2])
    m = light[len(light) // 2]
    return (m[0], m[1], m[2])


def _erase_text_regions(
    img,
    regions: list[dict],
    scale_x: float,
    scale_y: float,
    padding: int = 2,
    *,
    use_polygons: bool = False,
):
    """Paint over OCR text regions with sampled background colour."""
    from PIL import ImageDraw as _ImageDraw

    draw = _ImageDraw.Draw(img)
    erased = 0

    for region in regions:
        polygon = region.get("polygon", [])
        if len(polygon) < 8:
            continue
        text = region.get("content", "").strip()
        if not text:
            continue

        lx, ly, lw, lh = _polygon_to_rect(polygon)
        left = int(round(lx * scale_x))
        top = int(round(ly * scale_y))
        width = int(round(lw * scale_x))
        height = int(round(lh * scale_y))
        if width < 1 or height < 1:
            continue

        bg = _sample_bg_color(img, left, top, width, height)
        points = _polygon_to_points(polygon)
        if use_polygons and len(points) >= 4:
            poly_px = []
            for x, y in points[:4]:
                poly_px.append((x * scale_x, y * scale_y))
            draw.polygon(poly_px, fill=bg)
        else:
            draw.rectangle(
                [left - padding, top - padding,
                 left + width + padding, top + height + padding],
                fill=bg,
            )
        erased += 1

    return erased


def _rasterise_and_erase(
    pdf_path: str | Path,
    ocr_pages: list[dict],
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
) -> list[PageRaster]:
    """
    Rasterise each page, erase OCR text regions with background colour,
    and return base64 data URIs.
    """
    from PIL import Image as _PILImage

    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat  = fitz.Matrix(zoom, zoom)
    data_uris: list[PageRaster] = []

    for page_idx, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = _PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)

        # Erase text from the raster
        if page_idx < len(ocr_pages):
            # Use line regions for clean replacement coverage.
            page_data = ocr_pages[page_idx]
            scale_x, scale_y, _, _ = _compute_page_scale_and_size(
                page_data, pix.width, pix.height, dpi,
            )
            regions = page_data.get("lines", [])
            n = _erase_text_regions(img, regions, scale_x, scale_y, use_polygons=False)
            logger.debug("Page %d: erased %d text regions", page_idx + 1, n)

        data_uris.append((_pil_to_data_uri(img, image_format, image_quality), pix.width, pix.height))

    doc.close()
    return data_uris


# ── HTML builder ──────────────────────────────────────────────────────────────

def _render_page_container(
    page_index: int,
    page_dir: str,
    page_width_px: float,
    page_height_px: float,
    page_image_uri: str | None,
    text_html: list[str],
    *,
    text_only: bool = False,
) -> str:
    img_tag = (
        ""
        if text_only or not page_image_uri
        else f'      <img class="page-img" src="{page_image_uri}"\n'
             f'           alt="Page {page_index + 1}" loading="lazy" />\n'
    )
    return f'''
    <div class="page" id="page-{page_index}" dir="{page_dir}"
         style="width:{page_width_px:.0f}px; height:{page_height_px:.0f}px;">
{img_tag}      <div class="text-layer">
{chr(10).join(text_html)}
      </div>
      <div class="page-num">{page_index + 1}</div>
    </div>'''


def render_page_overlay(
    page_data: dict,
    page_image_uri: str | None,
    page_index: int,
    *,
    raster_width_px: float | None = None,
    raster_height_px: float | None = None,
    dpi_fallback: int = DEFAULT_DPI,
    text_only: bool = False,
) -> str:
    """Render one page in v1 mode: line-level axis-aligned overlays."""

    scale_x, scale_y, pw, ph = _compute_page_scale_and_size(
        page_data, raster_width_px, raster_height_px, dpi_fallback,
    )

    lines_html = []

    for line in page_data.get("lines", []):
        polygon = line.get("polygon", [])
        if len(polygon) < 8:
            continue

        text = line.get("content", "").strip()
        if not text:
            continue

        lx, ly, lw, lh = _polygon_to_rect(polygon)
        left_px = lx * scale_x
        top_px = ly * scale_y
        width_px = lw * scale_x
        height_px = lh * scale_y

        if width_px < 1 or height_px < 1:
            continue

        # Direction
        line_dir = _first_strong_dir(text)

        # Font size: match the line height
        font_size = max(0, height_px * 0.75)

        escaped = html_mod.escape(text)

        lines_html.append(
            f'        <div class="tw tw-line" dir="{line_dir}" '
            f'data-fit="legacy" data-angle="0" '
            f'style="left:{left_px:.1f}px; top:{top_px:.1f}px; '
            f'width:{width_px:.1f}px; height:{height_px:.1f}px; '
            f'font-size:{font_size:.1f}px; line-height:{height_px:.1f}px;">'
            f'{escaped}</div>'
        )

    page_dir = _first_strong_dir(
        " ".join(l.get("content", "") for l in page_data.get("lines", []))
    )

    return _render_page_container(
        page_index,
        page_dir,
        pw,
        ph,
        page_image_uri,
        lines_html,
        text_only=text_only,
    )


# ── Full document ─────────────────────────────────────────────────────────────

def render_document(
    pdf_path: str | Path,
    ocr_json_path: str | Path,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
    text_only: bool = False,
    replace_text: bool = False,
) -> str:
    """
    Render a complete PDF + OCR JSON to a self-contained HTML file.

    Parameters
    ----------
    pdf_path : path to the searchable (or original) PDF
    ocr_json_path : path to the Azure prebuilt-read OCR JSON
    dpi : rasterisation resolution
    image_format : webp, png, or jpeg
    image_quality : quality for lossy formats
    text_only : if True, skip image rasterisation and show visible text
    replace_text : if True, erase text from scan image and overlay visible text
    """
    pdf_path = Path(pdf_path)
    ocr_json_path = Path(ocr_json_path)

    # Parse OCR first (needed before rasterisation in replace-text mode)
    logger.info("Parsing OCR JSON %s …", ocr_json_path.name)
    ocr_data = parse_ocr_json(ocr_json_path)
    pages = ocr_data.get("pages", [])

    if text_only:
        logger.info("Text-only mode — skipping image rasterisation")
        page_images = None
    elif replace_text:
        logger.info(
            "Replace-text mode — rasterising %s at %d DPI + erasing text …",
            pdf_path.name, dpi,
        )
        page_images = _rasterise_and_erase(
            pdf_path, pages, dpi, image_format, image_quality,
        )
    else:
        logger.info("Rasterising %s at %d DPI …", pdf_path.name, dpi)
        page_images = rasterise_pdf(pdf_path, dpi, image_format, image_quality)

    if page_images is not None and len(pages) != len(page_images):
        logger.warning(
            "Page count mismatch: OCR has %d pages, PDF has %d pages",
            len(pages), len(page_images),
        )

    # In replace-text mode, keep image but show visible text
    show_text_only = text_only  # don't strip image in replace-text mode
    pages_html = []
    for i, page_data in enumerate(pages):
        if page_images and i < len(page_images):
            img_uri, raster_w, raster_h = page_images[i]
        else:
            img_uri, raster_w, raster_h = None, None, None
        pages_html.append(
            render_page_overlay(
                page_data,
                img_uri,
                i,
                raster_width_px=raster_w,
                raster_height_px=raster_h,
                dpi_fallback=dpi,
                text_only=show_text_only,
            )
        )

    title = html_mod.escape(pdf_path.stem)
    doc_dir = _first_strong_dir(ocr_data.get("content", ""))

    total_lines = sum(len(p.get("lines", [])) for p in pages)
    total_words = sum(len(p.get("words", [])) for p in pages)
    logger.info(
        "Rendered %d pages, %d lines, %d words",
        len(pages), total_lines, total_words,
    )

    return _wrap_html(
        title, doc_dir, "\n".join(pages_html), len(pages),
        text_only=text_only, replace_text=replace_text,
    )


def _wrap_html(
    title: str, direction: str, body: str, page_count: int,
    text_only: bool = False, replace_text: bool = False,
) -> str:
    return f'''<!DOCTYPE html>
<html lang="ar" dir="{direction}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
/* ── Reset ────────────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  background: #525659;
  font-family: 'Traditional Arabic', 'Noto Naskh Arabic', 'Amiri',
               'Noto Serif', 'Times New Roman', serif;
  padding: 20px 0;
  direction: ltr;  /* page-level layout is always LTR (left-to-right stacking) */
}}

/* ── Toolbar ──────────────────────────────────────────────────────── */
.toolbar {{
  position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
  background: #1e1e1e; color: #ccc;
  padding: 6px 16px; display: flex; gap: 12px; align-items: center;
  font-family: system-ui, sans-serif; font-size: 13px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.4);
}}
.toolbar button {{
  background: #3c3c3c; color: #ccc; border: 1px solid #555;
  padding: 4px 12px; border-radius: 4px; cursor: pointer;
  font-size: 12px;
}}
.toolbar button:hover {{ background: #505050; }}
.toolbar button.active {{ background: #0078d4; color: #fff; border-color: #0078d4; }}
.toolbar button:disabled {{ opacity: 0.45; cursor: default; }}
.toolbar .spacer {{ flex: 1; }}
.toolbar .info {{ font-size: 11px; color: #888; }}
.zoom-level {{
  min-width: 54px;
  text-align: center;
  color: #ddd;
  font-variant-numeric: tabular-nums;
}}
.pages-container {{
  padding-top: 26px;
}}

/* ── Page ─────────────────────────────────────────────────────────── */
.page {{
  position: relative;
  margin: 40px auto 20px auto;
  background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  overflow: hidden;
}}

.page-img {{
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  display: block;
  user-select: none;
  -webkit-user-select: none;
  pointer-events: none;
}}

/* ── Text layer ───────────────────────────────────────────────────── */
.text-layer {{
  position: absolute; inset: 0;
  z-index: 2;
  pointer-events: none;
  /* Allow text selection on the transparent layer */
}}

.tw {{
  position: absolute;
  color: transparent;
  white-space: pre;
  overflow: visible;
  transform-origin: left top;
  pointer-events: auto;
}}

.tw[dir="rtl"] {{
  transform-origin: right top;
}}

.tw[dir="ltr"] {{
  transform-origin: left top;
}}

.tw-ar {{
  font-family: 'Traditional Arabic', 'Noto Naskh Arabic', 'Amiri',
               'Simplified Arabic', 'Tahoma', serif;
}}

.tw-la {{
  font-family: 'Noto Serif', 'Times New Roman', 'Georgia', serif;
}}

/* Text-only / replace-text mode: visible black text */
body.text-only .tw,
body.replace-text .tw {{
  color: #000 !important;
}}
body.text-only .tw::selection,
body.text-only .tw *::selection,
body.replace-text .tw::selection,
body.replace-text .tw *::selection {{
  background: rgba(0, 120, 215, 0.35);
  color: #000;
}}

/* Selection highlight — visible feedback when selecting invisible text */
.tw::selection,
.tw *::selection {{
  background: rgba(0, 120, 215, 0.35);
  color: transparent;
}}

/* ── Page number ──────────────────────────────────────────────────── */
.page-num {{
  position: absolute; bottom: -24px; left: 50%;
  transform: translateX(-50%);
  font-size: 12px; color: #999;
  font-family: system-ui, sans-serif;
}}

/* ── Debug mode ───────────────────────────────────────────────────── */
body.debug-text .tw {{
  color: rgba(220, 40, 40, 0.7) !important;
  outline: 1px solid rgba(220, 40, 40, 0.15);
}}

body.debug-boxes .tw {{
  outline: 1px solid rgba(0, 120, 215, 0.4);
  background: rgba(0, 120, 215, 0.05);
}}

body.hide-image .page-img {{
  opacity: 0.08;
}}
</style>
</head>
<body{' class="text-only"' if text_only else (' class="replace-text"' if replace_text else '')}>

<div class="toolbar">
  <strong style="color:#fff;">OCR Overlay Viewer</strong>
  <div class="spacer"></div>
  <button id="btn-zoom-out" onclick="zoomOut()" title="Zoom out">-</button>
  <span id="zoom-level" class="zoom-level">100%</span>
  <button id="btn-zoom-in" onclick="zoomIn()" title="Zoom in">+</button>
  <button id="btn-fit" onclick="fitToPage(true)" title="Fit page to viewport">Fit</button>
  <button id="btn-debug" onclick="toggleDebug()" title="Show text overlay in red">Debug Text</button>
  <button id="btn-boxes" onclick="toggleBoxes()" title="Show line bounding boxes">Boxes</button>
  <button id="btn-image" onclick="toggleImage()" title="Fade out page image">Hide Image</button>
  <div class="info">{page_count} page{"s" if page_count != 1 else ""}</div>
</div>

<!-- Pages -->
<div id="pages-container" class="pages-container">
{body}
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
  document.getElementById("zoom-level").textContent = Math.round(viewerZoom * 100) + "%";
  document.getElementById("btn-zoom-out").disabled = viewerZoom <= MIN_ZOOM + 0.001;
  document.getElementById("btn-zoom-in").disabled = viewerZoom >= MAX_ZOOM - 0.001;
}}

function applyZoom(value) {{
  viewerZoom = clampZoom(value);
  const container = document.getElementById("pages-container");
  container.style.zoom = viewerZoom.toFixed(3);
  updateZoomLabel();
}}

function fitToPage(force = false) {{
  if (force) autoFitOnResize = true;
  if (!force && !autoFitOnResize) return;
  const pages = Array.from(document.querySelectorAll(".page"));
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

function toggleDebug() {{
  document.body.classList.toggle("debug-text");
  document.getElementById("btn-debug").classList.toggle("active");
}}
function toggleBoxes() {{
  document.body.classList.toggle("debug-boxes");
  document.getElementById("btn-boxes").classList.toggle("active");
}}
function toggleImage() {{
  document.body.classList.toggle("hide-image");
  document.getElementById("btn-image").classList.toggle("active");
}}

// ── Text fitting ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async function() {{
  if (document.fonts && document.fonts.ready) {{
    try {{
      await document.fonts.ready;
    }} catch (err) {{
      // Ignore font-loading errors and proceed with available metrics.
    }}
  }}
  fitAllWords();
  fitToPage(true);
}});

window.addEventListener("resize", function() {{
  fitToPage();
}});

function legacyFit(el, targetW, targetH) {{
  let fontSize = parseFloat(el.style.fontSize) || (targetH * 0.75);
  const maxIter = 8;
  for (let i = 0; i < maxIter; i++) {{
    el.style.fontSize = fontSize.toFixed(2) + "px";
    el.style.lineHeight = targetH.toFixed(1) + "px";
    el.style.width = "auto";
    const natural = el.scrollWidth;
    if (natural <= 0) break;
    const ratio = targetW / natural;
    if (ratio > 0.99 && ratio < 1.01) break;
    fontSize = fontSize * ratio;
    fontSize = Math.max(4, Math.min(fontSize, targetH * 1.1));
  }}

  el.style.fontSize = fontSize.toFixed(2) + "px";
  el.style.lineHeight = targetH.toFixed(1) + "px";
  el.style.width = "auto";
  const finalNatural = el.scrollWidth;
  if (finalNatural > 0 && targetW > 0) {{
    const scaleX = targetW / finalNatural;
    el.style.transform = "scaleX(" + scaleX.toFixed(6) + ")";
  }} else {{
    el.style.transform = "none";
  }}
}}

function fitAllWords() {{
  const els = document.querySelectorAll(".tw[data-fit]");
  els.forEach(el => {{
    const targetW = parseFloat(el.style.width);
    const targetH = parseFloat(el.style.height);
    if (targetW <= 0 || targetH <= 0) return;
    legacyFit(el, targetW, targetH);
  }});
}}
</script>

</body>
</html>'''


# ── CLI ───────────────────────────────────────────────────────────────────────

def process_single(
    pdf_path: Path,
    json_path: Path,
    output_path: Path | None = None,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
    text_only: bool = False,
    replace_text: bool = False,
) -> Path:
    """Process a single PDF+JSON pair and write HTML."""
    if output_path is None:
        if text_only:
            suffix = "_text_only.html"
        elif replace_text:
            suffix = "_replaced.html"
        else:
            suffix = "_overlay.html"
        output_path = pdf_path.with_name(pdf_path.stem.replace("_searchable", "") + suffix)

    html_str = render_document(
        pdf_path, json_path, dpi, image_format, image_quality,
        text_only=text_only,
        replace_text=replace_text,
    )
    output_path.write_text(html_str, encoding="utf-8")
    logger.info("Written %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
    return output_path


def process_directory(
    input_dir: Path,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
    text_only: bool = False,
    replace_text: bool = False,
) -> list[Path]:
    """
    Process all PDF+JSON pairs found in subdirectories of input_dir.
    Expects structure: input_dir/<doc_id>/<doc_id>_searchable.pdf + <doc_id>_ocr.json
    """
    results = []
    for subdir in sorted(input_dir.iterdir()):
        if not subdir.is_dir():
            continue

        # Find PDF and JSON
        pdfs = list(subdir.glob("*_searchable.pdf")) + list(subdir.glob("*.pdf"))
        jsons = list(subdir.glob("*_ocr.json"))

        if not pdfs or not jsons:
            logger.warning("Skipping %s — missing PDF or JSON", subdir.name)
            continue

        pdf = pdfs[0]
        json_f = jsons[0]
        if text_only:
            suffix = "_text_only.html"
        elif replace_text:
            suffix = "_replaced.html"
        else:
            suffix = "_overlay.html"
        out = subdir / (subdir.name + suffix)

        try:
            result = process_single(
                pdf, json_f, out, dpi, image_format, image_quality,
                text_only=text_only,
                replace_text=replace_text,
            )
            results.append(result)
        except Exception as e:
            logger.error("Failed %s: %s", subdir.name, e)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Render PDF + OCR JSON as image-overlay HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file:
  python -m fixed_layout_pipeline.overlay_renderer \\
    --pdf output/doc/doc_searchable.pdf \\
    --json output/doc/doc_ocr.json

  # All subdirectories:
  python -m fixed_layout_pipeline.overlay_renderer \\
    --input-dir output_read_test/
        """,
    )
    parser.add_argument("--pdf", type=Path, help="Single PDF file")
    parser.add_argument("--json", type=Path, help="Single OCR JSON file")
    parser.add_argument("--input-dir", "-i", type=Path, help="Directory of doc subdirectories")
    parser.add_argument("--output", "-o", type=Path, help="Output HTML path (single mode)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"Rasterisation DPI (default: {DEFAULT_DPI})")
    parser.add_argument("--format", choices=["webp", "png", "jpeg"], default=DEFAULT_IMAGE_FORMAT)
    parser.add_argument("--quality", type=int, default=DEFAULT_IMAGE_QUALITY)
    parser.add_argument("--text-only", action="store_true",
                        help="Skip images; render visible text on white background")
    parser.add_argument("--replace-text", action="store_true",
                        help="Erase scanned text from image, overlay clean rendered text")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.input_dir:
        results = process_directory(
            args.input_dir, args.dpi, args.format, args.quality,
            text_only=args.text_only, replace_text=args.replace_text,
        )
        print(f"\nProcessed {len(results)} documents")
        for r in results:
            print(f"  {r}")
    elif args.pdf and args.json:
        result = process_single(
            args.pdf, args.json, args.output, args.dpi, args.format, args.quality,
            text_only=args.text_only, replace_text=args.replace_text,
        )
        print(f"Output: {result}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
