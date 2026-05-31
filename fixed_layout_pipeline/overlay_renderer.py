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
        try:
            pix = page.get_pixmap(matrix=mat, alpha=False)
        except Exception as e:
            logger.warning(
                "Page %d render error (%s) — substituting blank page",
                page.number + 1, e,
            )
            w = max(1, int(page.rect.width * zoom))
            h = max(1, int(page.rect.height * zoom))
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
            pix.set_rect(pix.irect, (255, 255, 255))
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


def _contrast_text_color(bg: tuple[int, int, int]) -> str:
    """Return '#000' or '#fff' to contrast with the given background RGB."""
    # Relative luminance (ITU-R BT.709)
    lum = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]
    return "#fff" if lum < 140 else "#000"


def _sample_line_colors(
    img,
    regions: list[dict],
    scale_x: float,
    scale_y: float,
) -> list[str]:
    """Sample background behind each line and return contrasting text colors."""
    colors = []
    for region in regions:
        polygon = region.get("polygon", [])
        if len(polygon) < 8:
            colors.append("#000")
            continue
        lx, ly, lw, lh = _polygon_to_rect(polygon)
        left = int(round(lx * scale_x))
        top = int(round(ly * scale_y))
        width = int(round(lw * scale_x))
        height = int(round(lh * scale_y))
        if width < 1 or height < 1:
            colors.append("#000")
            continue
        bg = _sample_bg_color(img, left, top, width, height)
        colors.append(_contrast_text_color(bg))
    return colors


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
) -> tuple[list[PageRaster], list[list[str]]]:
    """
    Rasterise each page, sample text colors, erase OCR text regions,
    and return base64 data URIs + per-page line color lists.
    """
    from PIL import Image as _PILImage

    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat  = fitz.Matrix(zoom, zoom)
    data_uris: list[PageRaster] = []
    all_line_colors: list[list[str]] = []

    for page_idx, page in enumerate(doc):
        try:
            pix = page.get_pixmap(matrix=mat, alpha=False)
        except Exception as e:
            logger.warning(
                "Page %d render error (%s) — substituting blank page",
                page_idx + 1, e,
            )
            w = max(1, int(page.rect.width * zoom))
            h = max(1, int(page.rect.height * zoom))
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
            pix.set_rect(pix.irect, (255, 255, 255))
        img = _PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)

        # Sample text colors + erase text from the raster
        page_colors: list[str] = []
        if page_idx < len(ocr_pages):
            page_data = ocr_pages[page_idx]
            scale_x, scale_y, _, _ = _compute_page_scale_and_size(
                page_data, pix.width, pix.height, dpi,
            )
            regions = page_data.get("lines", [])
            # Sample BEFORE erasing
            page_colors = _sample_line_colors(img, regions, scale_x, scale_y)
            n = _erase_text_regions(img, regions, scale_x, scale_y, use_polygons=False)
            logger.debug("Page %d: erased %d text regions", page_idx + 1, n)

        all_line_colors.append(page_colors)
        data_uris.append((_pil_to_data_uri(img, image_format, image_quality), pix.width, pix.height))

    doc.close()
    return data_uris, all_line_colors


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
    line_colors: list[str] | None = None,
) -> str:
    """Render one page in v1 mode: line-level axis-aligned overlays."""

    scale_x, scale_y, pw, ph = _compute_page_scale_and_size(
        page_data, raster_width_px, raster_height_px, dpi_fallback,
    )

    lines_html = []
    color_idx = 0

    for line in page_data.get("lines", []):
        polygon = line.get("polygon", [])
        if len(polygon) < 8:
            color_idx += 1
            continue

        text = line.get("content", "").strip()
        if not text:
            color_idx += 1
            continue

        lx, ly, lw, lh = _polygon_to_rect(polygon)
        left_px = lx * scale_x
        top_px = ly * scale_y
        width_px = lw * scale_x
        height_px = lh * scale_y

        if width_px < 1 or height_px < 1:
            color_idx += 1
            continue

        # Direction
        line_dir = _first_strong_dir(text)

        # Font size: match the line height
        font_size = max(0, height_px * 0.75)

        # Text color from sampled background
        color_style = ""
        if line_colors and color_idx < len(line_colors):
            color_style = f" color:{line_colors[color_idx]};"

        escaped = html_mod.escape(text)

        lines_html.append(
            f'        <div class="tw tw-line" dir="{line_dir}" '
            f'data-fit="legacy" data-angle="0" '
            f'style="left:{left_px:.1f}px; top:{top_px:.1f}px; '
            f'width:{width_px:.1f}px; height:{height_px:.1f}px; '
            f'font-size:{font_size:.1f}px; line-height:{height_px:.1f}px;{color_style}">'
            f'{escaped}</div>'
        )
        color_idx += 1

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
        all_line_colors: list[list[str]] = []
    elif replace_text:
        logger.info(
            "Replace-text mode — rasterising %s at %d DPI + erasing text …",
            pdf_path.name, dpi,
        )
        page_images, all_line_colors = _rasterise_and_erase(
            pdf_path, pages, dpi, image_format, image_quality,
        )
    else:
        logger.info("Rasterising %s at %d DPI …", pdf_path.name, dpi)
        page_images = rasterise_pdf(pdf_path, dpi, image_format, image_quality)
        all_line_colors = []

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
        page_colors = all_line_colors[i] if i < len(all_line_colors) else None
        pages_html.append(
            render_page_overlay(
                page_data,
                img_uri,
                i,
                raster_width_px=raster_w,
                raster_height_px=raster_h,
                dpi_fallback=dpi,
                text_only=show_text_only,
                line_colors=page_colors,
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


# ── Hybrid mode helpers ───────────────────────────────────────────────────────

def _line_overlaps_region(
    lx: float, ly: float, lw: float, lh: float,
    rx: float, ry: float, rw: float, rh: float,
    threshold: float = 0.3,
) -> bool:
    """True if line bbox overlaps region by > threshold fraction of line area."""
    ix0, iy0 = max(lx, rx), max(ly, ry)
    ix1, iy1 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    inter = (ix1 - ix0) * (iy1 - iy0)
    return inter / max(lw * lh, 1) > threshold


def _bbox_pct_to_px(
    bbox_pct: list,
    page_w: float,
    page_h: float,
) -> tuple[float, float, float, float] | None:
    """[x0%, y0%, x1%, y1%] → (left_px, top_px, width_px, height_px)."""
    if not isinstance(bbox_pct, (list, tuple)) or len(bbox_pct) != 4:
        return None

    vals: list[float] = []
    for v in bbox_pct:
        if isinstance(v, bool):
            return None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        vals.append(max(0.0, min(100.0, fv)))

    x0, y0, x1, y1 = vals
    x_lo, x_hi = sorted((x0, x1))
    y_lo, y_hi = sorted((y0, y1))
    w_pct = x_hi - x_lo
    h_pct = y_hi - y_lo
    if w_pct <= 0.0 or h_pct <= 0.0:
        return None

    return (
        x_lo / 100.0 * page_w,
        y_lo / 100.0 * page_h,
        w_pct / 100.0 * page_w,
        h_pct / 100.0 * page_h,
    )


# ── Hybrid v2: Azure text + Gemini equations-only ────────────────────────────

def _line_is_equation_like(text: str) -> bool:
    """
    Heuristic: True if line looks like a math equation
    (lots of symbols, operators, short Latin with subscripts, etc).
    Used to decide whether to suppress an Azure line in favour of Gemini LaTeX.
    """
    if not text or len(text.strip()) < 2:
        return False
    stripped = text.strip()
    # Count math-like characters
    math_chars = sum(1 for c in stripped if c in "=+-*/^_(){}[]|∫∑∏∂∇√≤≥≠∞∈∉⊂⊃∪∩")
    # Count digits
    digits = sum(1 for c in stripped if c.isdigit())
    # Count Latin letters (variable names)
    latin = sum(1 for c in stripped if c.isascii() and c.isalpha())
    total = len(stripped)
    if total == 0:
        return False
    # If >25% of characters are math operators/digits, likely an equation
    math_ratio = (math_chars + digits * 0.3) / total
    return math_ratio > 0.15 and latin + math_chars + digits > total * 0.4


def _shrink_bbox(
    rx: float, ry: float, rw: float, rh: float,
    shrink_px: float = 8.0,
) -> tuple[float, float, float, float]:
    """Shrink a bbox inward by shrink_px on each side to avoid eating adjacent text."""
    rx2 = rx + shrink_px
    ry2 = ry + shrink_px
    rw2 = max(1, rw - 2 * shrink_px)
    rh2 = max(1, rh - 2 * shrink_px)
    return rx2, ry2, rw2, rh2


def _bbox_px_to_pct(
    left: float,
    top: float,
    width: float,
    height: float,
    page_w: float,
    page_h: float,
) -> list[float] | None:
    """(left, top, width, height) pixels -> [x0%, y0%, x1%, y1%]."""
    if page_w <= 0 or page_h <= 0:
        return None
    x0 = max(0.0, min(float(page_w), left))
    y0 = max(0.0, min(float(page_h), top))
    x1 = max(0.0, min(float(page_w), left + width))
    y1 = max(0.0, min(float(page_h), top + height))
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
        return None
    return [
        x0 / page_w * 100.0,
        y0 / page_h * 100.0,
        x1 / page_w * 100.0,
        y1 / page_h * 100.0,
    ]


def _merge_equation_candidate_boxes(
    boxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """Merge nearby equation-like line boxes into equation regions."""
    if not boxes:
        return []

    merged = list(sorted(boxes, key=lambda b: (b[1], b[0])))
    changed = True

    def _v_gap(a0: float, a1: float, b0: float, b1: float) -> float:
        if a1 < b0:
            return b0 - a1
        if b1 < a0:
            return a0 - b1
        return 0.0

    while changed:
        changed = False
        out: list[tuple[float, float, float, float]] = []
        used = [False] * len(merged)
        for i, a in enumerate(merged):
            if used[i]:
                continue
            ax, ay, aw, ah = a
            ax0, ay0, ax1, ay1 = ax, ay, ax + aw, ay + ah
            used[i] = True

            for j in range(i + 1, len(merged)):
                if used[j]:
                    continue
                bx, by, bw, bh = merged[j]
                bx0, by0, bx1, by1 = bx, by, bx + bw, by + bh
                inter_x = max(0.0, min(ax1, bx1) - max(ax0, bx0))
                min_w = max(1.0, min(ax1 - ax0, bx1 - bx0))
                x_overlap_ratio = inter_x / min_w
                y_gap = _v_gap(ay0, ay1, by0, by1)
                min_h = min(ay1 - ay0, by1 - by0)
                max_h = max(ay1 - ay0, by1 - by0)
                max_gap = max(4.0, 0.35 * min_h)
                union_h = max(ay1, by1) - min(ay0, by0)
                max_union_h = max_h * 2.8 + 8.0

                should_merge = (
                    x_overlap_ratio >= 0.45
                    and y_gap <= max_gap
                    and union_h <= max_union_h
                )
                if not should_merge:
                    continue

                ax0 = min(ax0, bx0)
                ay0 = min(ay0, by0)
                ax1 = max(ax1, bx1)
                ay1 = max(ay1, by1)
                used[j] = True
                changed = True

            out.append((ax0, ay0, ax1 - ax0, ay1 - ay0))
        merged = out

    return sorted(merged, key=lambda b: (b[1], b[0]))


def _collect_equation_candidates(
    page_data: dict,
    scale_x: float,
    scale_y: float,
    page_w_px: float,
    page_h_px: float,
    max_candidates: int = 80,
) -> list[dict]:
    """
    Build OCR-anchored equation candidate regions from Azure lines.

    Candidates are equation-like lines expanded and merged into region boxes.
    """
    seed_boxes: list[tuple[float, float, float, float]] = []
    for line in page_data.get("lines", []):
        polygon = line.get("polygon", [])
        if len(polygon) < 8:
            continue
        text = (line.get("content") or "").strip()
        if not text or not _line_is_equation_like(text):
            continue

        lx, ly, lw, lh = _polygon_to_rect(polygon)
        left_px = lx * scale_x
        top_px = ly * scale_y
        width_px = lw * scale_x
        height_px = lh * scale_y
        if width_px < 8 or height_px < 6:
            continue

        pad_x = max(6.0, width_px * 0.06)
        pad_y = max(3.0, height_px * 0.20)
        x0 = max(0.0, left_px - pad_x)
        y0 = max(0.0, top_px - pad_y)
        x1 = min(page_w_px, left_px + width_px + pad_x)
        y1 = min(page_h_px, top_px + height_px + pad_y)
        if x1 - x0 < 8.0 or y1 - y0 < 6.0:
            continue
        seed_boxes.append((x0, y0, x1 - x0, y1 - y0))

    merged = _merge_equation_candidate_boxes(seed_boxes)
    candidates: list[dict] = []
    for box in merged[:max_candidates]:
        if box[3] > page_h_px * 0.22:
            continue
        if (box[2] * box[3]) > (page_w_px * page_h_px * 0.18):
            continue
        pct = _bbox_px_to_pct(*box, page_w_px, page_h_px)
        if not pct:
            continue
        candidates.append({"id": len(candidates) + 1, "bbox_pct": pct})
    return candidates


def render_page_hybrid_v2(
    page_data: dict,
    page_index: int,
    gemini_result: dict,
    raster_width_px: float | None,
    raster_height_px: float | None,
    dpi_fallback: int = DEFAULT_DPI,
    page_image_uri: str | None = None,
    overlap_threshold: float = 0.50,
    bbox_shrink_px: float = 8.0,
) -> str:
    """
    Render one page: Azure text for everything + Gemini equations as LaTeX.

    No table extraction from Gemini — Azure handles text (including tabular
    layouts) fine, and the scan image provides visual fidelity.

    Behavior:
    - Only equations from Gemini (no table extraction)
    - Tighter overlap threshold — only suppress lines that
      are >50% inside an equation bbox
    - Bbox shrink — Gemini bboxes are padded inward to avoid eating adjacent text
    - Equation-like heuristic — only suppress lines that actually look like
      math, not Arabic prose that happens to be near an equation
    """
    scale_x, scale_y, pw, ph = _compute_page_scale_and_size(
        page_data, raster_width_px, raster_height_px, dpi_fallback,
    )

    equations = gemini_result.get("equations") or []

    # Build pixel-space equation regions (shrunk to avoid eating neighbours)
    equation_regions = []
    equation_regions_full = []  # un-shrunk for rendering
    for eq in equations:
        if not isinstance(eq, dict):
            continue
        bbox = eq.get("bbox_pct")
        full_region = _bbox_pct_to_px(bbox, pw, ph)
        if not full_region:
            continue
        equation_regions_full.append(full_region)
        equation_regions.append(_shrink_bbox(*full_region, shrink_px=bbox_shrink_px))

    # Render Azure text lines, suppressing only equation-like lines inside equation bboxes
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

        # Only suppress if: (a) line overlaps an equation region AND
        #                    (b) the line content looks like math
        suppress = False
        if equation_regions and _line_is_equation_like(text):
            suppress = any(
                _line_overlaps_region(
                    left_px, top_px, width_px, height_px,
                    rx, ry, rw, rh,
                    threshold=overlap_threshold,
                )
                for rx, ry, rw, rh in equation_regions
            )

        if suppress:
            continue

        line_dir = _first_strong_dir(text)
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

    # Render equations as positioned MathJax blocks
    hybrid_html = []
    for i, eq in enumerate(equations):
        if not isinstance(eq, dict):
            continue
        bbox = eq.get("bbox_pct")
        latex = (eq.get("latex") or "").strip()
        if not bbox or not latex:
            continue
        if i >= len(equation_regions_full):
            continue
        ex, ey, ew, eh = equation_regions_full[i]
        escaped_latex = html_mod.escape(latex)
        font_size = max(16, min(90, eh * 0.6))
        hybrid_html.append(
            f'        <div class="hybrid-equation" '
            f'style="left:{ex:.1f}px; top:{ey:.1f}px; '
            f'width:{ew:.1f}px; min-height:{eh:.1f}px; '
            f'font-size:{font_size:.0f}px;">'
            f'\\[{escaped_latex}\\]</div>'
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
        lines_html + hybrid_html,
        text_only=(page_image_uri is None),
    )


# ── Structural rendering: Azure text + Gemini tables + Gemini equations ───────

def render_page_structural(
    page_data: dict,
    page_index: int,
    raster_width_px: float | None,
    raster_height_px: float | None,
    dpi_fallback: int = DEFAULT_DPI,
    page_image_uri: str | None = None,
) -> str:
    """
    Render one page using structurally merged data.

    Consumes the enhanced Azure JSON produced by
    ``fuzzy_text_merger.merge_structural_into_azure_json``:

    - ``page["lines"]``      → positioned invisible text (Azure bbox + Gemini text)
    - ``page["_tables"]``    → positioned HTML <table> elements (Gemini bbox + HTML)
    - ``page["_equations"]`` → positioned MathJax blocks (Gemini bbox + LaTeX)

    Azure lines that overlapped table/equation regions were already
    suppressed by the merger, so there's no double-rendering.
    """
    scale_x, scale_y, pw, ph = _compute_page_scale_and_size(
        page_data, raster_width_px, raster_height_px, dpi_fallback,
    )

    # ── Text lines (Azure bbox, Gemini text via fuzzy merge) ─────────────
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

        line_dir = _first_strong_dir(text)
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

    # ── Tables (Azure bbox + HTML built from Azure line geometry) ──────────
    tables_html = []
    for tbl in page_data.get("_tables", []):
        bbox = tbl.get("bbox_pct")
        table_html = (tbl.get("html") or "").strip()
        if not bbox or not table_html:
            continue
        region = _bbox_pct_to_px(bbox, pw, ph)
        if not region:
            continue
        tx, ty, tw, th = region

        # Font size: from actual cell line heights stored by the detector.
        # cell_line_height_pt is in page units (inches); scale_y → px.
        cell_lh_pt = tbl.get("cell_line_height_pt", 0.0)
        if cell_lh_pt and cell_lh_pt > 0:
            cell_font_px = cell_lh_pt * scale_y * 0.72
        else:
            cell_font_px = ph * 0.010 * 0.72

        # Cap so rows never overflow the detected bbox height.
        n_rows = tbl.get("n_rows", max(1, table_html.count("<tr>")))
        row_budget_px = th / max(n_rows, 1)
        max_font_by_fit = max(8.0, row_budget_px - 10)

        font_px = max(8.0, min(cell_font_px, max_font_by_fit))

        tables_html.append(
            f'        <div class="structural-table" '
            f'style="left:{tx:.1f}px; top:{ty:.1f}px; '
            f'width:{tw:.1f}px; min-height:{th:.1f}px; '
            f'font-size:{font_px:.1f}px;">'
            f'{table_html}</div>'
        )


    # ── Equations (transparent overlay + copy-LaTeX button) ────────────
    equations_html = []
    for eq_idx, eq in enumerate(page_data.get("_equations", [])):
        bbox = eq.get("bbox_pct")
        latex = (eq.get("latex") or "").strip()
        if not bbox or not latex:
            continue
        region = _bbox_pct_to_px(bbox, pw, ph)
        if not region:
            continue
        ex, ey, ew, eh = region
        # Escape for safe embedding in HTML data attribute and hidden span
        escaped_latex = html_mod.escape(latex)
        eq_id = f"eq-{page_index}-{eq_idx}"
        equations_html.append(
            f'        <div class="structural-equation" '
            f'style="left:{ex:.1f}px; top:{ey:.1f}px; '
            f'width:{ew:.1f}px; min-height:{eh:.1f}px;">'
            f'<span class="eq-latex-hidden">{escaped_latex}</span>'
            f'<button class="eq-copy-btn" '
            f'onclick="copyLatex(this)" '
            f'title="Copy LaTeX">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            f'<rect x="9" y="9" width="13" height="13" rx="2"/>'
            f'<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>'
            f'</svg>'
            f'</button>'
            f'</div>'
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
        lines_html + tables_html + equations_html,
        text_only=(page_image_uri is None),
    )


def render_document_structural(
    pdf_path: str | Path,
    ocr_json_path: str | Path,
    dpi: int = DEFAULT_DPI,
    replace_text: bool = False,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
) -> str:
    """
    Render a PDF + structurally enhanced OCR JSON to self-contained HTML.

    The enhanced JSON is produced by the ``gemini-enhance`` pipeline:
      Azure prebuilt-read → Gemini structural extraction → fuzzy merge

    Pages contain:
      - ``lines``       : Azure bbox + Gemini text (fuzzy merged)
      - ``_tables``     : Gemini HTML tables with bboxes
      - ``_equations``  : Gemini LaTeX equations with bboxes
    """
    pdf_path = Path(pdf_path)
    ocr_json_path = Path(ocr_json_path)

    logger.info("Parsing enhanced OCR JSON %s …", ocr_json_path.name)
    ocr_data = parse_ocr_json(ocr_json_path)
    pages = ocr_data.get("pages", [])

    has_tables = any(len(p.get("_tables", [])) > 0 for p in pages)
    has_equations = any(len(p.get("_equations", [])) > 0 for p in pages)
    has_structural = has_tables or has_equations

    if replace_text:
        logger.info(
            "Replace-text + structural mode — rasterising %s at %d DPI …",
            pdf_path.name, dpi,
        )
        page_images, _line_colors2 = _rasterise_and_erase(
            pdf_path, pages, dpi, image_format, image_quality,
        )
    else:
        logger.info("Rasterising %s at %d DPI …", pdf_path.name, dpi)
        page_images = rasterise_pdf(pdf_path, dpi, image_format, image_quality)

    if len(pages) != len(page_images):
        logger.warning(
            "Page count mismatch: OCR has %d pages, PDF has %d pages",
            len(pages), len(page_images),
        )

    pages_html = []
    for i, page_data in enumerate(pages):
        if i < len(page_images):
            img_uri, raster_w, raster_h = page_images[i]
        else:
            img_uri, raster_w, raster_h = None, None, None

        pages_html.append(
            render_page_structural(
                page_data, i,
                raster_width_px=raster_w,
                raster_height_px=raster_h,
                dpi_fallback=dpi,
                page_image_uri=img_uri,
            )
        )

    title = html_mod.escape(pdf_path.stem)
    doc_dir = _first_strong_dir(ocr_data.get("content", ""))

    total_lines = sum(len(p.get("lines", [])) for p in pages)
    total_tables = sum(len(p.get("_tables", [])) for p in pages)
    total_eqs = sum(len(p.get("_equations", [])) for p in pages)
    logger.info(
        "Structural render: %d pages, %d lines, %d tables, %d equations",
        len(pages), total_lines, total_tables, total_eqs,
    )

    return _wrap_html(
        title, doc_dir, "\n".join(pages_html), len(pages),
        replace_text=replace_text,
        hybrid=False,  # no MathJax needed — equations are image + copy button
    )

def render_page_with_formulas(
    page_data: dict,
    page_index: int,
    raster_width_px: float | None,
    raster_height_px: float | None,
    dpi_fallback: int = DEFAULT_DPI,
    page_image_uri: str | None = None,
    overlap_threshold: float = 0.50,
) -> str:
    """
    Render one page: Azure text lines + Azure formulas as MathJax.

    Azure's prebuilt-layout with FORMULAS add-on returns formulas in the
    same coordinate system as text lines (polygon in page units), so no
    coordinate conversion is needed — just the standard polygon→rect→pixel
    pipeline.

    Text lines that overlap formula regions by >overlap_threshold are
    suppressed to avoid double-rendering.
    """
    scale_x, scale_y, pw, ph = _compute_page_scale_and_size(
        page_data, raster_width_px, raster_height_px, dpi_fallback,
    )

    # Build formula pixel rects for overlap suppression
    formulas = page_data.get("formulas", [])
    formula_rects: list[tuple[float, float, float, float]] = []
    for formula in formulas:
        polygon = formula.get("polygon", [])
        if len(polygon) < 8:
            continue
        lx, ly, lw, lh = _polygon_to_rect(polygon)
        formula_rects.append((
            lx * scale_x, ly * scale_y,
            lw * scale_x, lh * scale_y,
        ))

    # Render Azure text lines, suppressing those under formula regions
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

        # Suppress lines that overlap formula regions
        if formula_rects:
            suppress = any(
                _line_overlaps_region(
                    left_px, top_px, width_px, height_px,
                    fx, fy, fw, fh,
                    threshold=overlap_threshold,
                )
                for fx, fy, fw, fh in formula_rects
            )
            if suppress:
                continue

        line_dir = _first_strong_dir(text)
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

    # Render formulas as positioned MathJax blocks
    formula_html = []
    for i, formula in enumerate(formulas):
        polygon = formula.get("polygon", [])
        if len(polygon) < 8:
            continue
        value = (formula.get("value") or "").strip()
        if not value:
            continue

        lx, ly, lw, lh = _polygon_to_rect(polygon)
        left_px = lx * scale_x
        top_px = ly * scale_y
        width_px = lw * scale_x
        height_px = lh * scale_y

        if width_px < 1 or height_px < 1:
            continue

        kind = formula.get("kind", "display")
        escaped_latex = html_mod.escape(value)
        font_size = max(16, min(90, height_px * 0.6))

        if kind == "inline":
            latex_wrap = f'\\({escaped_latex}\\)'
        else:
            latex_wrap = f'\\[{escaped_latex}\\]'

        formula_html.append(
            f'        <div class="azure-formula" '
            f'style="left:{left_px:.1f}px; top:{top_px:.1f}px; '
            f'width:{width_px:.1f}px; min-height:{height_px:.1f}px; '
            f'font-size:{font_size:.0f}px;">'
            f'{latex_wrap}</div>'
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
        lines_html + formula_html,
        text_only=(page_image_uri is None),
    )


def render_document_with_formulas(
    pdf_path: str | Path,
    ocr_json_path: str | Path,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
    replace_text: bool = False,
) -> str:
    """
    Render a PDF + Azure prebuilt-layout OCR JSON (with FORMULAS add-on)
    to a self-contained HTML file with MathJax-rendered equations.

    Azure formulas are in the same coordinate system as text lines,
    so no coordinate conversion or heuristic merging is needed.
    """
    pdf_path = Path(pdf_path)
    ocr_json_path = Path(ocr_json_path)

    logger.info("Parsing OCR JSON %s …", ocr_json_path.name)
    ocr_data = parse_ocr_json(ocr_json_path)
    pages = ocr_data.get("pages", [])

    # Check if any page has formulas
    has_formulas = any(len(p.get("formulas", [])) > 0 for p in pages)

    if replace_text:
        logger.info(
            "Replace-text + formulas mode — rasterising %s at %d DPI + erasing text …",
            pdf_path.name, dpi,
        )
        page_images, _line_colors = _rasterise_and_erase(
            pdf_path, pages, dpi, image_format, image_quality,
        )
    else:
        logger.info("Rasterising %s at %d DPI …", pdf_path.name, dpi)
        page_images = rasterise_pdf(pdf_path, dpi, image_format, image_quality)

    if len(pages) != len(page_images):
        logger.warning(
            "Page count mismatch: OCR has %d pages, PDF has %d pages",
            len(pages), len(page_images),
        )

    pages_html = []
    for i, page_data in enumerate(pages):
        if i < len(page_images):
            img_uri, raster_w, raster_h = page_images[i]
        else:
            img_uri, raster_w, raster_h = None, None, None

        pages_html.append(
            render_page_with_formulas(
                page_data, i,
                raster_width_px=raster_w,
                raster_height_px=raster_h,
                dpi_fallback=dpi,
                page_image_uri=img_uri,
            )
        )

    title = html_mod.escape(pdf_path.stem)
    doc_dir = _first_strong_dir(ocr_data.get("content", ""))

    total_lines = sum(len(p.get("lines", [])) for p in pages)
    total_formulas = sum(len(p.get("formulas", [])) for p in pages)
    logger.info(
        "Rendered %d pages, %d lines, %d formulas",
        len(pages), total_lines, total_formulas,
    )

    return _wrap_html(
        title, doc_dir, "\n".join(pages_html), len(pages),
        replace_text=replace_text,
        hybrid=has_formulas,
    )


def render_document_hybrid_v2(
    pdf_path: str | Path,
    ocr_json_path: str | Path,
    gemini_api_key: str,
    gemini_model: str = "gemini-3-flash-preview",
    dpi: int = DEFAULT_DPI,
    replace_text: bool = False,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
    gemini_workers: int = 4,
    gemini_dpi: int = 150,
) -> str:
    """
    Hybrid v2: Azure text + Gemini equations-only.

    Azure text + Gemini equations-only hybrid renderer.
    Geometry is anchored to Azure OCR candidate regions.
    """
    import concurrent.futures
    from google import genai
    from .gemini_equations_extractor import extract_equations_in_regions

    pdf_path = Path(pdf_path)
    ocr_json_path = Path(ocr_json_path)

    logger.info("Parsing OCR JSON %s …", ocr_json_path.name)
    ocr_data = parse_ocr_json(ocr_json_path)
    pages = ocr_data.get("pages", [])

    logger.info(
        "Rasterising %s at %d DPI for display, %d DPI for Gemini …",
        pdf_path.name, dpi, gemini_dpi,
    )
    doc = fitz.open(str(pdf_path))
    display_mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    gemini_mat = fitz.Matrix(gemini_dpi / 72.0, gemini_dpi / 72.0)

    raw_pixmaps = []
    gemini_pngs = []
    for page in doc:
        raw_pixmaps.append(page.get_pixmap(matrix=display_mat, alpha=False))
        gemini_pngs.append(page.get_pixmap(matrix=gemini_mat, alpha=False).tobytes("png"))
    doc.close()

    page_rasters: list[tuple[bytes, str | None, int, int]] = []
    if replace_text:
        from PIL import Image as _PILImage
        for i, pix in enumerate(raw_pixmaps):
            img = _PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
            if i < len(pages):
                scale_x, scale_y, _, _ = _compute_page_scale_and_size(
                    pages[i], pix.width, pix.height, dpi,
                )
                _erase_text_regions(img, pages[i].get("lines", []), scale_x, scale_y)
            img_uri = _pil_to_data_uri(img, image_format, image_quality)
            page_rasters.append((gemini_pngs[i], img_uri, pix.width, pix.height))
    else:
        for i, pix in enumerate(raw_pixmaps):
            page_rasters.append((gemini_pngs[i], None, pix.width, pix.height))

    if len(pages) != len(page_rasters):
        logger.warning(
            "Page count mismatch: OCR has %d pages, PDF has %d pages",
            len(pages), len(page_rasters),
        )

    client = genai.Client(api_key=gemini_api_key)

    logger.info(
        "Calling Gemini (equations-only, Azure-anchored) for %d pages (%d workers) …",
        len(pages), gemini_workers,
    )

    def _gemini_page(args):
        i, png_bytes, page_data, raster_w, raster_h = args
        if not png_bytes or not page_data:
            return i, {"equations": []}

        scale_x, scale_y, pw, ph = _compute_page_scale_and_size(
            page_data, raster_w, raster_h, dpi,
        )
        candidates = _collect_equation_candidates(page_data, scale_x, scale_y, pw, ph)
        if not candidates:
            logger.info("Page %d: no equation candidates from Azure lines", i + 1)
            return i, {"equations": []}

        result = extract_equations_in_regions(
            client, gemini_model, png_bytes, candidates,
        )
        n_e = len(result.get("equations") or [])
        logger.info(
            "Page %d: %d/%d equation(s) from Gemini over Azure candidates",
            i + 1, n_e, len(candidates),
        )
        return i, result

    gemini_inputs = [
        (
            i,
            page_rasters[i][0] if i < len(page_rasters) else b"",
            pages[i] if i < len(pages) else {},
            page_rasters[i][2] if i < len(page_rasters) else None,
            page_rasters[i][3] if i < len(page_rasters) else None,
        )
        for i in range(len(pages))
    ]
    gemini_results: list[dict] = [{"equations": []}] * len(pages)

    with concurrent.futures.ThreadPoolExecutor(max_workers=gemini_workers) as pool:
        for i, result in pool.map(_gemini_page, gemini_inputs):
            gemini_results[i] = result

    pages_html = []
    for i, page_data in enumerate(pages):
        if i < len(page_rasters):
            _, img_uri, raster_w, raster_h = page_rasters[i]
        else:
            img_uri, raster_w, raster_h = None, None, None

        pages_html.append(
            render_page_hybrid_v2(
                page_data, i, gemini_results[i],
                raster_w, raster_h, dpi,
                page_image_uri=img_uri,
            )
        )

    title = html_mod.escape(pdf_path.stem)
    doc_dir = _first_strong_dir(ocr_data.get("content", ""))

    total_lines = sum(len(p.get("lines", [])) for p in pages)
    total_eqs = sum(len(r.get("equations") or []) for r in gemini_results)
    logger.info(
        "Hybrid v2 rendered %d pages, %d lines, %d equations",
        len(pages), total_lines, total_eqs,
    )

    return _wrap_html(
        title, doc_dir, "\n".join(pages_html), len(pages),
        hybrid=True, replace_text=replace_text,
    )


def render_document_hybrid(
    pdf_path: str | Path,
    ocr_json_path: str | Path,
    gemini_api_key: str,
    gemini_model: str = "gemini-3-flash-preview",
    dpi: int = DEFAULT_DPI,
    replace_text: bool = False,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    image_quality: int = DEFAULT_IMAGE_QUALITY,
    gemini_workers: int = 4,
    gemini_dpi: int = 150,
) -> str:
    """
    Backward-compatible entry point for hybrid rendering.

    Legacy table+equation hybrid was removed; this now routes to
    equations-only hybrid rendering.
    """
    return render_document_hybrid_v2(
        pdf_path=pdf_path,
        ocr_json_path=ocr_json_path,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        dpi=dpi,
        replace_text=replace_text,
        image_format=image_format,
        image_quality=image_quality,
        gemini_workers=gemini_workers,
        gemini_dpi=gemini_dpi,
    )


def _wrap_html(
    title: str, direction: str, body: str, page_count: int,
    text_only: bool = False, replace_text: bool = False,
    hybrid: bool = False,
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
  text-align: right;
}}

.tw[dir="ltr"] {{
  transform-origin: left top;
  text-align: left;
}}

.tw-ar {{
  font-family: 'Traditional Arabic', 'Noto Naskh Arabic', 'Amiri',
               'Simplified Arabic', 'Tahoma', serif;
}}

.tw-la {{
  font-family: 'Noto Serif', 'Times New Roman', 'Georgia', serif;
}}

/* Text-only / replace-text mode: visible text with sampled color */
body.text-only .tw,
body.replace-text .tw {{
  color: #000;
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

/* ── Hybrid mode: visible Azure text + Gemini equation islands ── */
body.hybrid .tw {{
  color: #000 !important;
}}
body.hybrid .tw::selection,
body.hybrid .tw *::selection {{
  background: rgba(0, 120, 215, 0.35);
  color: #000;
}}

.hybrid-equation {{
  position: absolute;
  background: #fff;
  text-align: center;
  padding: 6px;
  pointer-events: auto;
  z-index: 3;
}}

.azure-formula {{
  position: absolute;
  background: #fff;
  text-align: center;
  padding: 4px;
  pointer-events: auto;
  z-index: 3;
}}

/* ── Structural mode: Gemini tables + equations ───────────────────── */
.structural-table {{
  position: absolute;
  background: #fff;
  pointer-events: auto;
  z-index: 3;
  overflow: visible;
  box-sizing: border-box;
  font-family: 'Noto Naskh Arabic', 'Traditional Arabic', 'Noto Serif',
               'Times New Roman', serif;
  /* font-size and min-height are set inline per-table */
  line-height: 1.35;
  color: #000;
}}

.structural-table table {{
  width: 100%;
  border-collapse: collapse;
  direction: rtl;
  table-layout: auto;
}}

.structural-table th,
.structural-table td {{
  border: 1px solid #888;
  padding: 2px 6px;
  text-align: right;
  vertical-align: middle;
  font-size: inherit;
  overflow: visible;
  white-space: normal;
  word-break: break-word;
}}

.structural-table thead th {{
  background: #e8e8e8;
  font-weight: bold;
}}

.structural-table tbody tr:nth-child(even) {{
  background: #f8f8f8;
}}

.structural-equation {{
  position: absolute;
  background: transparent;
  pointer-events: auto;
  z-index: 3;
  cursor: default;
}}

.eq-latex-hidden {{
  /* Invisible but selectable — allows Ctrl+A / copy from page */
  position: absolute;
  left: 0; top: 0; width: 100%; height: 100%;
  color: transparent;
  font-size: 1px;
  line-height: 1;
  overflow: hidden;
  user-select: text;
  pointer-events: none;
  white-space: pre-wrap;
  word-break: break-all;
}}

.eq-copy-btn {{
  position: absolute;
  top: 2px; right: 2px;
  width: 26px; height: 26px;
  background: rgba(30, 30, 30, 0.75);
  color: #eee;
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  opacity: 0;
  transition: opacity 0.15s;
  padding: 0;
}}

.structural-equation:hover .eq-copy-btn {{
  opacity: 1;
}}

.eq-copy-btn:hover {{
  background: rgba(60, 120, 220, 0.9);
}}

.eq-copy-btn.copied {{
  background: rgba(40, 167, 69, 0.9) !important;
  opacity: 1;
}}

/* Outline equation region on hover for discoverability */
.structural-equation:hover {{
  outline: 2px solid rgba(60, 120, 220, 0.5);
  outline-offset: -1px;
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
{'<script>window.MathJax = {tex: {inlineMath: [[\'\\\\(\', \'\\\\)\'], [\'$\', \'$\']], displayMath: [[\'\\\\[\', \'\\\\]\'], [\'$$\', \'$$\']]}}</script><script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" async></script>' if hybrid else ''}
</head>
<body{' class="hybrid"' if hybrid else (' class="text-only"' if text_only else (' class="replace-text"' if replace_text else ''))}>

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

function copyLatex(btn) {{
  event.preventDefault();
  event.stopPropagation();
  const container = btn.closest('.structural-equation');
  const span = container.querySelector('.eq-latex-hidden');
  const latex = span ? span.textContent : '';

  function onSuccess() {{
    btn.classList.add('copied');
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>';
    setTimeout(() => {{
      btn.classList.remove('copied');
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
    }}, 1500);
  }}

  function fallbackCopy(text) {{
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {{ document.execCommand('copy'); onSuccess(); }}
    catch(e) {{ console.error('Copy failed', e); }}
    document.body.removeChild(ta);
  }}

  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(latex).then(onSuccess).catch(() => fallbackCopy(latex));
  }} else {{
    fallbackCopy(latex);
  }}
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
    el.style.width = "auto";  /* measure natural width */
    const natural = el.scrollWidth;
    if (natural <= 0) break;
    const ratio = targetW / natural;
    if (ratio > 0.99 && ratio < 1.01) break;
    fontSize = fontSize * ratio;
    fontSize = Math.max(4, Math.min(fontSize, targetH * 1.1));
  }}

  el.style.fontSize = fontSize.toFixed(2) + "px";
  el.style.lineHeight = targetH.toFixed(1) + "px";
  el.style.width = "auto";  /* one final measurement */
  const finalNatural = el.scrollWidth;
  if (finalNatural > 0 && targetW > 0) {{
    const scaleX = Math.min(1.5, targetW / finalNatural);
    el.style.transform = "scaleX(" + scaleX.toFixed(6) + ")";
  }} else {{
    el.style.transform = "none";
  }}
  /* Restore the declared box width so layout matches the OCR polygon.
     Leaving width:auto lets the element grow to naturalWidth in Chrome,
     which (combined with the transform) causes words to overflow the page. */
  el.style.width = targetW.toFixed(1) + "px";
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
