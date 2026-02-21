"""
PDF Ingest — rasterise PDF pages to high-resolution images.

Converts each page of a scanned PDF to a raster image at the configured DPI,
producing the page images that serve as the visual background in the
fixed-layout HTML overlay. Also extracts basic PDF metadata.

Resolution guidance (from the reference document):
- 300 DPI: standard for OCR
- 400-600 DPI: recommended for small Arabic fonts
- >600 DPI: diminishing returns for typical documents
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from .config import RasterConfig
from .schema import DocumentSource, PageImage

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_source_metadata(pdf_path: Path) -> DocumentSource:
    """Extract metadata from the PDF file."""
    doc = fitz.open(str(pdf_path))
    source = DocumentSource(
        filename=pdf_path.name,
        file_hash=compute_file_hash(pdf_path),
        page_count=len(doc),
        file_size_bytes=pdf_path.stat().st_size,
    )
    doc.close()
    return source


def rasterise_page(
    doc: fitz.Document,
    page_index: int,
    config: RasterConfig,
    output_dir: Optional[Path] = None,
    embed_base64: bool = True,
) -> PageImage:
    """
    Rasterise a single PDF page to an image.

    Args:
        doc: Open PyMuPDF document.
        page_index: 0-based page index.
        config: Rasterisation settings.
        output_dir: If provided, save image file here.
        embed_base64: If True, store image as base64 data URI.

    Returns:
        PageImage with dimensions and URI (file path or data URI).
    """
    page = doc[page_index]

    # Scale factor: PyMuPDF default is 72 DPI
    scale = config.dpi / 72.0
    matrix = fitz.Matrix(scale, scale)

    # Render to pixmap
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)

    logger.info(
        f"Page {page_index}: rasterised to {pixmap.width}x{pixmap.height}px "
        f"at {config.dpi} DPI"
    )

    # Convert to target format
    if config.image_format == "webp":
        # PyMuPDF can output PNG; we convert to WebP via PIL if available
        try:
            from PIL import Image as PILImage
            pil_img = PILImage.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            buf = io.BytesIO()
            pil_img.save(buf, format="WebP", quality=config.image_quality)
            img_bytes = buf.getvalue()
            mime = "image/webp"
            ext = "webp"
        except ImportError:
            # Fallback to PNG
            img_bytes = pixmap.tobytes("png")
            mime = "image/png"
            ext = "png"
    elif config.image_format == "png":
        img_bytes = pixmap.tobytes("png")
        mime = "image/png"
        ext = "png"
    elif config.image_format == "jpeg":
        img_bytes = pixmap.tobytes("jpeg")
        mime = "image/jpeg"
        ext = "jpg"
    else:
        img_bytes = pixmap.tobytes("png")
        mime = "image/png"
        ext = "png"

    # Build URI
    uri = ""
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        img_path = output_dir / f"page_{page_index:04d}.{ext}"
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        uri = str(img_path)
        logger.debug(f"Page {page_index}: saved to {img_path}")

    if embed_base64:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        uri = f"data:{mime};base64,{b64}"

    return PageImage(
        uri=uri,
        width_px=pixmap.width,
        height_px=pixmap.height,
        dpi=config.dpi,
        format=ext,
    )


def rasterise_pdf(
    pdf_path: Path,
    config: RasterConfig,
    output_dir: Optional[Path] = None,
    embed_base64: bool = True,
    page_range: Optional[tuple[int, int]] = None,
) -> list[PageImage]:
    """
    Rasterise all pages of a PDF.

    Args:
        pdf_path: Path to the PDF file.
        config: Rasterisation settings.
        output_dir: Directory to save page images.
        embed_base64: Embed images as data URIs.
        page_range: Optional (start, end) 0-based page range.

    Returns:
        List of PageImage objects, one per page.
    """
    doc = fitz.open(str(pdf_path))
    total = len(doc)

    start = page_range[0] if page_range else 0
    end = page_range[1] if page_range else total

    logger.info(
        f"Rasterising {pdf_path.name}: pages {start}-{end-1} of {total} "
        f"at {config.dpi} DPI ({config.image_format})"
    )

    images = []
    for i in range(start, min(end, total)):
        img = rasterise_page(
            doc, i, config,
            output_dir=output_dir,
            embed_base64=embed_base64,
        )
        images.append(img)

    doc.close()
    logger.info(f"Rasterised {len(images)} pages from {pdf_path.name}")
    return images


def get_pdf_page_count(pdf_path: Path) -> int:
    """Quick page count without full rasterisation."""
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count
