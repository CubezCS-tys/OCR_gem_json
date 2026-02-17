"""
Dual-call pipeline: Searchable PDF + Layout OCR in parallel.

Makes exactly TWO Azure API calls for the entire document:
  1. prebuilt-read  + output=[PDF]  → searchable PDF
  2. prebuilt-layout + all features → rich canonical JSON

Both calls send the full PDF once and run in parallel via threading.
The canonical JSON comes from prebuilt-layout (paragraphs, tables,
reading order, font styles, formulas, language detection) — much
richer than extracting from the searchable PDF.

The searchable PDF provides the background page images for the
fidelity HTML via PyMuPDF rasterisation.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from .config import AzureConfig
from .schema import BlockType, CanonicalDocument, PageImage

logger = logging.getLogger(__name__)


def _extract_figures(
    doc: CanonicalDocument,
    pages_dir: Path,
    output_dir: Path,
    image_format: str = "webp",
    image_quality: int = 90,
) -> int:
    """Crop figure regions from rasterised page images.

    For each FIGURE block with a bounding box, open the corresponding
    page image, crop the bbox region (with a small pad), and save it
    to ``output_dir/figures/``.  The block's ``figure_uri`` is set to
    a path relative to ``output_dir`` so the fidelity HTML can
    reference it directly via ``<img src="...">``.

    Returns the number of figures extracted.
    """
    from PIL import Image as PILImage

    figures_dir = output_dir / "figures"
    count = 0

    for page in doc.pages:
        if not page.image or not page.image.uri:
            continue

        page_img = None  # lazy-loaded

        for block in page.blocks:
            if block.block_type != BlockType.FIGURE:
                continue
            if not block.bbox:
                continue

            # Lazy-load page image on first figure
            if page_img is None:
                page_path = Path(page.image.uri)
                if not page_path.exists():
                    logger.warning("Page image not found: %s", page_path)
                    break
                page_img = PILImage.open(page_path)

            # Crop with 2px pad to avoid edge clipping
            pad = 2
            left = max(0, int(block.bbox.x0) - pad)
            upper = max(0, int(block.bbox.y0) - pad)
            right = min(page_img.width, int(block.bbox.x1) + pad)
            lower = min(page_img.height, int(block.bbox.y1) + pad)

            if right <= left or lower <= upper:
                continue

            crop = page_img.crop((left, upper, right, lower))

            figures_dir.mkdir(parents=True, exist_ok=True)
            fig_name = f"{block.block_id}.{image_format}"
            fig_path = figures_dir / fig_name

            if image_format == "webp":
                crop.save(str(fig_path), format="WebP", quality=image_quality)
            else:
                crop.save(str(fig_path))

            # Relative path from output_dir (where the HTML lives)
            block.figure_uri = f"figures/{fig_name}"
            count += 1
            logger.debug(
                "Extracted figure %s → %s (%dx%d)",
                block.block_id, fig_path, crop.width, crop.height,
            )

        if page_img is not None:
            page_img.close()

    if count:
        logger.info("Extracted %d figure images to %s", count, figures_dir)
    return count


def _call_searchable_pdf(
    pdf_bytes: bytes,
    output_path: Path,
    config: AzureConfig,
) -> Path:
    """Thread target: get searchable PDF from prebuilt-read."""
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )
    from azure.core.credentials import AzureKeyCredential

    start = time.time()
    logger.info("[Call 1] prebuilt-read → searchable PDF...")

    client = DocumentIntelligenceClient(
        endpoint=config.endpoint,
        credential=AzureKeyCredential(config.api_key),
    )

    poller = client.begin_analyze_document(
        model_id="prebuilt-read",
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        output=[AnalyzeOutputOption.PDF],
    )

    result = poller.result()
    operation_id = poller.details["operation_id"]

    pdf_stream = client.get_analyze_result_pdf(
        model_id=result.model_id,
        result_id=operation_id,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    with open(output_path, "wb") as out:
        for chunk in pdf_stream:
            out.write(chunk)
            bytes_written += len(chunk)

    elapsed = time.time() - start
    logger.info(
        "[Call 1] Searchable PDF done in %.1fs (%.1f KB)",
        elapsed, bytes_written / 1024,
    )
    return output_path


def _call_layout_ocr(
    pdf_bytes: bytes,
    config: AzureConfig,
    page_images: Optional[list[PageImage]] = None,
) -> CanonicalDocument:
    """Thread target: get layout OCR from prebuilt-layout."""
    from .ocr_engine import analyze_pdf as _analyze_pdf_internal
    import tempfile, os

    start = time.time()
    logger.info("[Call 2] prebuilt-layout → canonical JSON...")

    # analyze_pdf needs a file path, write to temp
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        doc = _analyze_pdf_internal(tmp_path, config, page_images)
    finally:
        os.unlink(tmp_path)

    elapsed = time.time() - start
    logger.info(
        "[Call 2] Layout OCR done in %.1fs (%d pages, %d blocks)",
        elapsed, len(doc.pages), doc.total_blocks(),
    )
    return doc


def dual_process(
    pdf_path: Path,
    output_dir: Path,
    config: AzureConfig,
    *,
    dpi: int = 300,
    image_format: str = "webp",
    image_quality: int = 90,
) -> tuple[CanonicalDocument, Path, Path]:
    """
    Run both Azure calls in parallel and produce all outputs.

    Args:
        pdf_path:      Input scanned PDF.
        output_dir:    Where to write outputs.
        config:        Azure credentials.
        dpi:           Rasterisation DPI for page images.
        image_format:  Image format for page images.
        image_quality: Quality for lossy formats.

    Returns:
        (canonical_doc, searchable_pdf_path, fidelity_html_path)
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    config.validate()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    # Read once, share between threads
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    logger.info("="*60)
    logger.info("DUAL-CALL PIPELINE: %s (%.1f KB)", pdf_path.name, len(pdf_bytes)/1024)
    logger.info("="*60)

    spdf_path = output_dir / f"{stem}_searchable.pdf"
    start = time.time()

    # ── Run both Azure calls in parallel ─────────────────────────────────
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_spdf = pool.submit(_call_searchable_pdf, pdf_bytes, spdf_path, config)
        fut_layout = pool.submit(_call_layout_ocr, pdf_bytes, config)

        # Wait for both
        spdf_result = fut_spdf.result()
        doc = fut_layout.result()

    api_elapsed = time.time() - start
    logger.info("Both API calls complete in %.1fs", api_elapsed)

    # ── Rasterise page images from searchable PDF ────────────────────────
    logger.info("Rasterising page images from searchable PDF...")
    import fitz
    from PIL import Image as PILImage
    import io, base64

    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0

    spdf_doc = fitz.open(str(spdf_path))
    num_pages_to_raster = min(spdf_doc.page_count, len(doc.pages))

    for page_idx in range(num_pages_to_raster):
        pdf_page = spdf_doc[page_idx]
        mat = fitz.Matrix(scale, scale)
        pix = pdf_page.get_pixmap(matrix=mat, alpha=False)

        pil_img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img_path = pages_dir / f"page_{page_idx:04d}.{image_format}"

        if image_format == "webp":
            pil_img.save(str(img_path), format="WebP", quality=image_quality)
        else:
            pil_img.save(str(img_path))

        # Update canonical doc page images
        if page_idx < len(doc.pages):
            doc.pages[page_idx].image = PageImage(
                uri=str(img_path),
                width_px=pix.width,
                height_px=pix.height,
                dpi=dpi,
                format=image_format,
            )

    spdf_doc.close()
    logger.info("  Rasterised %d page images", num_pages_to_raster)

    # ── Extract figure images ────────────────────────────────────────────
    _extract_figures(doc, pages_dir, output_dir, image_format, image_quality)

    # ── Save canonical JSON ──────────────────────────────────────────────
    json_path = output_dir / f"{stem}_canonical.json"
    doc.save(json_path)
    logger.info("Canonical JSON: %s", json_path)

    # ── Render fidelity HTML ─────────────────────────────────────────────
    from .dual_renderer import FidelityRenderer
    fid_html = FidelityRenderer(scale=1.0).render(doc)
    fid_path = output_dir / f"{stem}_fidelity.html"
    fid_path.write_text(fid_html, encoding="utf-8")
    logger.info("Fidelity HTML:  %s", fid_path)

    total_elapsed = time.time() - start
    logger.info("="*60)
    logger.info("DUAL-CALL PIPELINE COMPLETE in %.1fs", total_elapsed)
    logger.info("  Searchable PDF: %s", spdf_path)
    logger.info("  Canonical JSON: %s", json_path)
    logger.info("  Fidelity HTML:  %s", fid_path)
    logger.info("="*60)

    return doc, spdf_path, fid_path
