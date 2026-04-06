"""
Build a searchable PDF with correct text selection order.

Azure's searchable-PDF output has words positioned correctly but written
into the PDF content stream in the wrong order, so multi-word selections
come out jumbled.  This module rebuilds the searchable PDF from:

  1. The original scanned PDF (page images via PyMuPDF)
  2. The Azure OCR JSON (word positions + correct reading order)

Strategy:
  - Write each OCR **line** as a single invisible text segment (one Tj
    operator) so that PDF viewers cannot re-sort individual words by
    x-position (which reverses Arabic RTL reading order).
  - Use python-bidi's get_display() to convert logical → visual order,
    cancelling ReportLab's internal Arabic reversal.
  - Use DejaVu Sans as a single font for all text (Arabic, Latin,
    digits, punctuation) to avoid run-splitting issues.
"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF — used only for rasterising source pages
from bidi.algorithm import get_display
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# ── Font registration ────────────────────────────────────────────────────────

_FONT_PATHS = [
    # DejaVu covers Arabic + Latin + digits + punctuation in one font
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # Fallbacks
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
_FONT_REGISTERED = False
_FONT_NAME = "SearchableFont"


def _ensure_fonts() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    for p in _FONT_PATHS:
        if Path(p).exists():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, p))
            logger.info("Registered font: %s", p)
            _FONT_REGISTERED = True
            return
    raise FileNotFoundError(
        "No suitable font found. Install fonts-dejavu-core or fonts-noto."
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def build_searchable_pdf(
    source_pdf_path: Path,
    ocr_json_path: Path,
    output_path: Path,
    *,
    dpi: int = 200,
) -> Path:
    """
    Build a searchable PDF from a scanned PDF + Azure OCR JSON.

    Args:
        source_pdf_path: Original scanned (analog) PDF.
        ocr_json_path:   Azure OCR JSON (prebuilt-read or prebuilt-layout).
        output_path:     Where to write the searchable PDF.
        dpi:             Resolution for rasterising source pages.

    Returns:
        output_path for convenience.
    """
    source_pdf_path = Path(source_pdf_path)
    ocr_json_path = Path(ocr_json_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _ensure_fonts()

    with open(ocr_json_path, "r", encoding="utf-8") as f:
        ocr = json.load(f)

    src_doc = fitz.open(str(source_pdf_path))
    pages_data = ocr.get("pages", [])

    # ── Build PDF with ReportLab ─────────────────────────────────────
    pdf_buf = BytesIO()
    # Use first page to determine initial size (will be overridden per page)
    c = canvas.Canvas(pdf_buf)

    for page_info in pages_data:
        page_num = page_info["pageNumber"] - 1  # 0-based
        if page_num >= len(src_doc):
            logger.warning("Page %d not in source PDF, skipping", page_num + 1)
            continue

        src_page = src_doc[page_num]
        page_rect = src_page.rect
        page_w_pt = page_rect.width   # points
        page_h_pt = page_rect.height  # points

        # Set this page's size
        c.setPageSize((page_w_pt, page_h_pt))

        # ── Rasterise source page → PNG in memory ────────────────────
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = src_page.get_pixmap(matrix=mat, alpha=False)
        img_buf = BytesIO(pix.tobytes("png"))
        img_reader = ImageReader(img_buf)

        # Draw page image as background (full page)
        c.drawImage(img_reader, 0, 0, width=page_w_pt, height=page_h_pt)

        # ── Overlay invisible text ───────────────────────────────────
        ocr_w_in = page_info["width"]   # inches
        ocr_h_in = page_info["height"]  # inches

        # Scale: OCR inches → PDF points
        sx = page_w_pt / (ocr_w_in * 72)
        sy = page_h_pt / (ocr_h_in * 72)

        _overlay_lines(c, page_info, sx, sy, page_h_pt)

        c.showPage()

    c.save()
    src_doc.close()

    # Write to disk
    output_path.write_bytes(pdf_buf.getvalue())

    logger.info(
        "Searchable PDF built: %s (%d pages, %.1f KB)",
        output_path, len(pages_data), output_path.stat().st_size / 1024,
    )
    return output_path


def _is_arabic(ch: str) -> bool:
    """Return True if a character is in an Arabic Unicode block."""
    return (
        "\u0600" <= ch <= "\u06FF"
        or "\u0750" <= ch <= "\u077F"
        or "\u08A0" <= ch <= "\u08FF"
        or "\uFB50" <= ch <= "\uFDFF"
        or "\uFE70" <= ch <= "\uFEFF"
    )


# BiDi bracket mirroring: get_display() mirrors paired brackets for visual
# display, but ReportLab's internal Arabic reversal mirrors them again.
# Undo the first mirroring so only ReportLab's pass takes effect.
_MIRROR = str.maketrans("()[]{}«»", ")(][}{»«")


def _prepare_content(text: str) -> str:
    """Prepare a line's text for ReportLab, handling Arabic BiDi."""
    has_arabic = any(_is_arabic(ch) for ch in text)
    if not has_arabic:
        return text
    return get_display(text).translate(_MIRROR)


def _overlay_lines(
    c: canvas.Canvas,
    page_info: dict,
    sx: float,
    sy: float,
    page_h_pt: float,
) -> None:
    """
    Place each OCR line as a single invisible text segment.

    Writing a whole line as one Tj operation prevents PDF viewers from
    re-sorting individual words by x-position (which reverses Arabic
    reading order).  python-bidi's get_display() converts logical → visual
    byte order, cancelling ReportLab's internal Arabic reversal so that
    copy-paste recovers the correct logical text.
    """
    lines = page_info.get("lines", [])
    if not lines:
        return

    for line in lines:
        content = line["content"]
        if not content.strip():
            continue

        poly = line["polygon"]
        xs = [poly[i] for i in range(0, len(poly), 2)]
        ys = [poly[i] for i in range(1, len(poly), 2)]

        # OCR coords (inches) → PDF points, y-flip (PDF origin = bottom-left)
        x_min_pt = min(xs) * 72 * sx
        y_max_pt = max(ys) * 72 * sy
        y_min_pt = min(ys) * 72 * sy

        line_h = y_max_pt - y_min_pt
        if line_h <= 0:
            continue

        fontsize = max(line_h * 0.80, 1.0)
        baseline_y = page_h_pt - y_max_pt + line_h * 0.15

        prepared = _prepare_content(content)

        # One beginText/drawText per line keeps each line as a single
        # text object, preventing cross-line word reordering.
        text_obj = c.beginText()
        text_obj.setTextRenderMode(3)  # invisible
        text_obj.setFont(_FONT_NAME, fontsize)
        text_obj.setTextOrigin(x_min_pt, baseline_y)
        text_obj.textOut(prepared)
        c.drawText(text_obj)
