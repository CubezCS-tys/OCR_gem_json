"""
End-to-end Pipeline Orchestrator.

Coordinates all stages:
  PDF → Rasterise → Preprocess → OCR (Azure DI) → Reading Order →
  Canonical JSON → Fixed-Layout HTML

Can also regenerate HTML from an existing canonical JSON (the QA loop).
"""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import Optional

from .config import PipelineConfig
from .figure_extractor import extract_figures
from .html_renderer import FixedLayoutRenderer
from .ingest import extract_source_metadata, rasterise_pdf
from .ocr_engine import analyze_pdf, analyze_page_image
from .preprocess import PreprocessResult, preprocess_page, load_image_from_bytes
from .reading_order import resolve_reading_order
from .schema import (
    CanonicalDocument,
    Page,
    PageImage,
    ProcessingInfo,
)

logger = logging.getLogger(__name__)


class Pipeline:
    """
    Fixed-Layout OCR Pipeline.

    Usage:
        config = PipelineConfig.from_env()
        pipeline = Pipeline(config)
        doc, html_path = pipeline.process("document.pdf")
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig.from_env()
        self.renderer = FixedLayoutRenderer(self.config.renderer)

        # Setup logging
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    def process(
        self,
        pdf_path: str | Path,
        output_dir: Optional[str | Path] = None,
        page_range: Optional[tuple[int, int]] = None,
    ) -> tuple[CanonicalDocument, Path]:
        """
        Run the full pipeline on a PDF.

        Args:
            pdf_path: Path to the input PDF.
            output_dir: Where to write outputs. Defaults to config.output_dir.
            page_range: Optional (start, end) 0-based page range.

        Returns:
            (CanonicalDocument, html_output_path)
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        output_dir = Path(output_dir) if output_dir else self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        stem = pdf_path.stem
        start_time = time.time()

        logger.info(f"{'='*60}")
        logger.info(f"PIPELINE START: {pdf_path.name}")
        logger.info(f"{'='*60}")

        # ─── Stage 1: Extract source metadata ────────────────────
        logger.info("[1/6] Extracting source metadata...")
        source = extract_source_metadata(pdf_path)
        logger.info(f"  Pages: {source.page_count}, Size: {source.file_size_bytes:,} bytes")

        # ─── Stage 2: Rasterise pages ────────────────────────────
        logger.info(f"[2/6] Rasterising at {self.config.raster.dpi} DPI...")
        page_images_dir = output_dir / stem / "pages" if self.config.keep_intermediates else None

        page_images = rasterise_pdf(
            pdf_path,
            config=self.config.raster,
            output_dir=page_images_dir,
            embed_base64=self.config.renderer.embed_images,
            page_range=page_range,
        )
        logger.info(f"  Rasterised {len(page_images)} pages")

        # ─── Stage 3: Preprocess (optional) ──────────────────────
        preprocessed_images: Optional[list[bytes]] = None
        preprocessing_steps: list[str] = []

        if any([
            self.config.preprocess.deskew,
            self.config.preprocess.denoise,
            self.config.preprocess.dewarp,
            self.config.preprocess.binarise,
            self.config.preprocess.auto_orient,
        ]):
            logger.info("[3/6] Preprocessing pages...")
            preprocessed_images = []
            for i, page_img in enumerate(page_images):
                # Load the rasterised image
                if page_img.uri.startswith("data:"):
                    # Extract bytes from data URI
                    header, b64data = page_img.uri.split(",", 1)
                    img_bytes = base64.b64decode(b64data)
                else:
                    with open(page_img.uri, "rb") as f:
                        img_bytes = f.read()

                import cv2
                import numpy as np
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if img is not None:
                    result = preprocess_page(img, self.config.preprocess)
                    # Encode back to image bytes
                    _, enc = cv2.imencode(".png", result.image)
                    preprocessed_images.append(enc.tobytes())
                    if i == 0:
                        preprocessing_steps = result.steps_applied
                else:
                    preprocessed_images.append(img_bytes)

            logger.info(f"  Applied: {preprocessing_steps}")
        else:
            logger.info("[3/6] Preprocessing: skipped (all toggles off)")

        # ─── Stage 4: OCR with Azure Document Intelligence ───────
        logger.info("[4/6] Running Azure Document Intelligence OCR...")

        if preprocessed_images:
            # Send preprocessed images one by one
            # (Azure DI can handle individual images)
            doc = self._ocr_preprocessed_pages(
                preprocessed_images, page_images
            )
        else:
            # Send the original PDF directly (most efficient)
            doc = analyze_pdf(
                pdf_path, self.config.azure, page_images
            )

        # Update source metadata
        doc.source = source
        doc.processing.raster_dpi = self.config.raster.dpi
        doc.processing.preprocessing = preprocessing_steps

        logger.info(f"  Blocks: {doc.total_blocks()}, Avg confidence: {doc.avg_confidence():.3f}")

        # ─── Stage 5: Extract figures ────────────────────────────
        if self.config.extract_figures:
            logger.info("[5/7] Extracting figures from pages...")
            figure_count = sum(1 for p in doc.pages for b in p.blocks if b.block_type.value == "figure")
            if figure_count > 0:
                # Load PIL images for figure extraction
                from PIL import Image
                import numpy as np
                import cv2
                
                pil_images = []
                for page_img in page_images:
                    if page_img.uri.startswith("data:"):
                        # Extract from data URI
                        header, b64data = page_img.uri.split(",", 1)
                        img_bytes = base64.b64decode(b64data)
                    else:
                        with open(page_img.uri, "rb") as f:
                            img_bytes = f.read()
                    
                    # Convert to PIL Image
                    arr = np.frombuffer(img_bytes, dtype=np.uint8)
                    cv_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if cv_img is not None:
                        # Convert BGR to RGB
                        rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(rgb_img)
                        pil_images.append(pil_img)
                    else:
                        pil_images.append(None)
                
                doc = extract_figures(doc, output_dir / stem, pil_images)
                logger.info(f"  Extracted {figure_count} figures")
            else:
                logger.info("  No figures detected")
        else:
            logger.info("[5/7] Figure extraction: disabled")

        # ─── Stage 6: Reading order resolution ───────────────────
        logger.info("[6/7] Resolving reading order...")
        for page in doc.pages:
            # Start with engine order, optionally refine
            reading_order = resolve_reading_order(page, method="heuristic")
            # Only override if heuristic confidence is higher
            if reading_order.confidence > page.reading_order.confidence:
                page.reading_order = reading_order
                logger.debug(
                    f"  Page {page.page_index}: reading order updated "
                    f"({reading_order.method.value}, conf={reading_order.confidence:.2f})"
                )

        # ─── Optional: LLM enrichment ────────────────────────────
        if self.config.llm.enabled:
            logger.info("[6b/7] LLM enrichment...")
            try:
                from .llm_enrichment import enrich_reading_order
                for page in doc.pages:
                    enriched = enrich_reading_order(page, self.config.llm)
                    if enriched:
                        page.reading_order = enriched
            except Exception as e:
                logger.warning(f"LLM enrichment failed: {e}")

        # ─── Stage 7: Render HTML ────────────────────────────────
        logger.info("[7/7] Rendering fixed-layout HTML...")
        html_path = output_dir / stem / f"{stem}.html"
        self.renderer.render_to_file(doc, html_path)

        # Save canonical JSON
        json_path = output_dir / stem / f"{stem}_canonical.json"
        doc.save(json_path)
        logger.info(f"  Canonical JSON: {json_path}")

        elapsed = time.time() - start_time
        doc.processing.processing_time_seconds = elapsed

        logger.info(f"{'='*60}")
        logger.info(f"PIPELINE COMPLETE in {elapsed:.1f}s")
        logger.info(f"  HTML:  {html_path}")
        logger.info(f"  JSON:  {json_path}")
        logger.info(f"{'='*60}")

        return doc, html_path

    def _ocr_preprocessed_pages(
        self,
        preprocessed_images: list[bytes],
        page_images: list[PageImage],
    ) -> CanonicalDocument:
        """OCR preprocessed page images individually."""
        doc = CanonicalDocument()

        for i, img_bytes in enumerate(preprocessed_images):
            page_img = page_images[i] if i < len(page_images) else None
            logger.info(f"  OCR page {i+1}/{len(preprocessed_images)}...")

            page = analyze_page_image(
                img_bytes, self.config.azure, page_img
            )
            page.page_index = i
            if page_img:
                page.image = page_img
            doc.pages.append(page)

        return doc

    def regenerate_html(
        self,
        canonical_json_path: str | Path,
        output_html_path: Optional[str | Path] = None,
    ) -> Path:
        """
        Regenerate HTML from an existing canonical JSON.

        This is the QA loop: edit the JSON (fix reading order, correct text),
        then regenerate HTML deterministically.

        Args:
            canonical_json_path: Path to the canonical JSON file.
            output_html_path: Output HTML path (default: same dir as JSON).

        Returns:
            Path to the generated HTML file.
        """
        json_path = Path(canonical_json_path)
        doc = CanonicalDocument.load(json_path)

        if output_html_path is None:
            output_html_path = json_path.with_suffix(".html")
        else:
            output_html_path = Path(output_html_path)

        self.renderer.render_to_file(doc, output_html_path)
        logger.info(f"Regenerated HTML from {json_path.name} → {output_html_path.name}")
        return output_html_path


def process_pdf(
    pdf_path: str | Path,
    output_dir: Optional[str | Path] = None,
    dpi: int = 300,
    debug: bool = False,
) -> tuple[CanonicalDocument, Path]:
    """
    Convenience function to process a PDF with default settings.

    Args:
        pdf_path: Path to the PDF.
        output_dir: Output directory.
        dpi: Rasterisation DPI.
        debug: Enable debug bounding boxes.

    Returns:
        (CanonicalDocument, html_path)
    """
    config = PipelineConfig.from_env()
    config.raster.dpi = dpi
    config.renderer.debug_boxes = debug

    if output_dir:
        config.output_dir = Path(output_dir)

    pipeline = Pipeline(config)
    return pipeline.process(pdf_path)
