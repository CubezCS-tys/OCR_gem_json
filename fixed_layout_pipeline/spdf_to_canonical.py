"""
Searchable-PDF → Canonical JSON converter.

Extracts text with bounding boxes from an Azure-generated searchable PDF
using PyMuPDF and builds a CanonicalDocument that can be fed to any renderer
(FidelityRenderer, SemanticRenderer, FixedLayoutRenderer, etc.).

This avoids re-running expensive per-page Azure OCR calls — the searchable
PDF already contains all positioned text.

Coordinate mapping:
    PDF coordinates are in *points* (72 DPI).
    We convert to *page pixel coordinates* at a target DPI (default 300)
    so the canonical output matches rasterised page images.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from .schema import (
    BBox,
    Block,
    BlockType,
    CanonicalDocument,
    Direction,
    DocumentSource,
    Line,
    Page,
    PageImage,
    Polygon,
    ProcessingInfo,
    ReadingOrder,
    ReadingOrderMethod,
    ReadingOrderUnit,
    Token,
)

logger = logging.getLogger(__name__)


# ─── Direction detection ─────────────────────────────────────────────────────

def _detect_direction(text: str) -> Direction:
    """Detect text direction from Unicode codepoints."""
    if not text:
        return Direction.RTL
    arabic = sum(
        1 for c in text
        if 0x0600 <= ord(c) <= 0x06FF
        or 0x0750 <= ord(c) <= 0x077F
        or 0xFB50 <= ord(c) <= 0xFEFF
        or 0x08A0 <= ord(c) <= 0x08FF
    )
    latin = sum(
        1 for c in text
        if 0x0041 <= ord(c) <= 0x005A
        or 0x0061 <= ord(c) <= 0x007A
        or 0x00C0 <= ord(c) <= 0x00FF
    )
    return Direction.RTL if arabic >= latin else Direction.LTR


def _detect_language(text: str) -> str:
    if not text.strip():
        return "und"
    d = _detect_direction(text)
    return "ar" if d == Direction.RTL else "en"


# ─── Core converter ─────────────────────────────────────────────────────────

def searchable_pdf_to_canonical(
    spdf_path: Path,
    *,
    target_dpi: int = 300,
    page_images_dir: Optional[Path] = None,
    rasterise: bool = True,
    image_format: str = "webp",
    image_quality: int = 90,
) -> CanonicalDocument:
    """
    Convert a searchable PDF into a CanonicalDocument.

    Args:
        spdf_path:       Path to the searchable PDF.
        target_dpi:      DPI for pixel coordinates (must match rasterised images).
        page_images_dir: Directory to save rasterised page images. If None,
                         images are embedded as base64.
        rasterise:       Whether to rasterise pages for background images.
        image_format:    Image format for rasterised pages.
        image_quality:   Quality for lossy formats.

    Returns:
        CanonicalDocument ready for rendering.
    """
    spdf_path = Path(spdf_path)
    if not spdf_path.exists():
        raise FileNotFoundError(f"Searchable PDF not found: {spdf_path}")

    pdf_doc = fitz.open(str(spdf_path))
    scale = target_dpi / 72.0  # PDF points → pixels

    logger.info(
        "Converting searchable PDF: %s (%d pages, scale=%.2f)",
        spdf_path.name, pdf_doc.page_count, scale,
    )

    pages: list[Page] = []

    for page_idx in range(pdf_doc.page_count):
        pdf_page = pdf_doc[page_idx]
        page_w_pt = pdf_page.rect.width
        page_h_pt = pdf_page.rect.height
        page_w_px = round(page_w_pt * scale)
        page_h_px = round(page_h_pt * scale)

        # ── Build page image ─────────────────────────────────────────────
        page_image = PageImage(
            uri="",
            width_px=page_w_px,
            height_px=page_h_px,
            dpi=target_dpi,
            format=image_format,
        )

        if rasterise:
            mat = fitz.Matrix(scale, scale)
            pix = pdf_page.get_pixmap(matrix=mat, alpha=False)

            if page_images_dir:
                page_images_dir.mkdir(parents=True, exist_ok=True)
                img_path = page_images_dir / f"page_{page_idx:04d}.{image_format}"
                if image_format == "webp":
                    # PyMuPDF can save PNG; convert via PIL for WebP
                    from PIL import Image as PILImage
                    import io, base64
                    pil_img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    buf = io.BytesIO()
                    pil_img.save(buf, format="WebP", quality=image_quality)
                    buf.seek(0)
                    img_path.write_bytes(buf.getvalue())
                    page_image.uri = str(img_path)
                else:
                    pix.save(str(img_path))
                    page_image.uri = str(img_path)
            else:
                # Embed as base64
                from PIL import Image as PILImage
                import io, base64
                pil_img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                fmt = "WebP" if image_format == "webp" else "PNG"
                pil_img.save(buf, format=fmt, quality=image_quality)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                mime = "image/webp" if image_format == "webp" else "image/png"
                page_image.uri = f"data:{mime};base64,{b64}"

        # ── Extract text structure ────────────────────────────────────────
        text_dict = pdf_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks: list[Block] = []
        block_order: list[str] = []

        for blk in text_dict.get("blocks", []):
            if blk["type"] != 0:  # skip image blocks
                continue

            blk_bbox = blk["bbox"]
            block_id = f"b_p{page_idx}_{blk['number']}"
            lines: list[Line] = []

            for line_idx, line_data in enumerate(blk.get("lines", [])):
                ln_bbox = line_data["bbox"]

                # Merge spans into tokens (words)
                tokens: list[Token] = []
                full_text_parts = []
                token_idx = 0

                for span in line_data.get("spans", []):
                    span_text = span["text"].strip()
                    if not span_text:
                        continue

                    # Each span becomes a token
                    sp_bbox = span["bbox"]
                    tok_id = f"t_p{page_idx}_b{blk['number']}_l{line_idx}_w{token_idx}"

                    # Split multi-word spans into individual tokens
                    words_in_span = span_text.split()
                    if len(words_in_span) <= 1:
                        tokens.append(Token(
                            token_id=tok_id,
                            text=span_text,
                            bbox=BBox(
                                x0=sp_bbox[0] * scale,
                                y0=sp_bbox[1] * scale,
                                x1=sp_bbox[2] * scale,
                                y1=sp_bbox[3] * scale,
                            ),
                            confidence=1.0,
                            direction=_detect_direction(span_text),
                            language=_detect_language(span_text),
                            font_size_pt=span.get("size", 0),
                        ))
                        full_text_parts.append(span_text)
                        token_idx += 1
                    else:
                        # Approximate word positions within the span
                        total_chars = sum(len(w) for w in words_in_span)
                        span_width = (sp_bbox[2] - sp_bbox[0])
                        x_cursor = sp_bbox[0]

                        for word in words_in_span:
                            word_width = span_width * (len(word) / max(total_chars, 1))
                            w_tok_id = f"t_p{page_idx}_b{blk['number']}_l{line_idx}_w{token_idx}"
                            tokens.append(Token(
                                token_id=w_tok_id,
                                text=word,
                                bbox=BBox(
                                    x0=x_cursor * scale,
                                    y0=sp_bbox[1] * scale,
                                    x1=(x_cursor + word_width) * scale,
                                    y1=sp_bbox[3] * scale,
                                ),
                                confidence=1.0,
                                direction=_detect_direction(word),
                                language=_detect_language(word),
                                font_size_pt=span.get("size", 0),
                            ))
                            full_text_parts.append(word)
                            x_cursor += word_width
                            token_idx += 1

                if not tokens:
                    continue

                line_text = " ".join(full_text_parts)
                line_dir = _detect_direction(line_text)
                line_id = f"l_p{page_idx}_b{blk['number']}_{line_idx}"

                lines.append(Line(
                    line_id=line_id,
                    text=line_text,
                    bbox=BBox(
                        x0=ln_bbox[0] * scale,
                        y0=ln_bbox[1] * scale,
                        x1=ln_bbox[2] * scale,
                        y1=ln_bbox[3] * scale,
                    ),
                    tokens=tokens,
                    direction=line_dir,
                    language=_detect_language(line_text),
                    confidence=1.0,
                ))

            if not lines:
                continue

            block_text = "\n".join(l.text for l in lines)
            block_dir = _detect_direction(block_text)

            blocks.append(Block(
                block_id=block_id,
                block_type=BlockType.TEXT,
                bbox=BBox(
                    x0=blk_bbox[0] * scale,
                    y0=blk_bbox[1] * scale,
                    x1=blk_bbox[2] * scale,
                    y1=blk_bbox[3] * scale,
                ),
                lines=lines,
                direction=block_dir,
                language=_detect_language(block_text),
                confidence=1.0,
            ))
            block_order.append(block_id)

        # ── Assemble page ─────────────────────────────────────────────────
        page_text = " ".join(b.full_text() for b in blocks)
        page_dir = _detect_direction(page_text)

        reading_units = [
            ReadingOrderUnit(unit_id=bid, ref_block_id=bid)
            for bid in block_order
        ]

        page = Page(
            page_index=page_idx,
            image=page_image,
            blocks=blocks,
            tables=[],
            principal_direction=page_dir,
            language=_detect_language(page_text),
            reading_order=ReadingOrder(
                method=ReadingOrderMethod.ENGINE,
                units=reading_units,
                sequence=block_order,
                confidence=0.90,
            ),
        )
        pages.append(page)

        block_count = len(blocks)
        token_count = sum(len(l.tokens) for b in blocks for l in b.lines)
        logger.info(
            "  Page %d: %d blocks, %d tokens",
            page_idx + 1, block_count, token_count,
        )

    pdf_doc.close()

    # ── Build document ────────────────────────────────────────────────────
    doc = CanonicalDocument(
        pages=pages,
        source=DocumentSource(
            filename=spdf_path.name,
            page_count=len(pages),
        ),
        processing=ProcessingInfo(
            ocr_engine="azure-prebuilt-read-searchable-pdf",
            raster_dpi=target_dpi,
        ),
    )

    logger.info(
        "Conversion complete: %d pages, %d blocks, avg conf=%.3f",
        len(pages), doc.total_blocks(), doc.avg_confidence(),
    )

    return doc
