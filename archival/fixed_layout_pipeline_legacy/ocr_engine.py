"""
Azure Document Intelligence OCR Engine — geometry-first OCR.

Uses Azure's prebuilt-layout model which provides:
- Word-level bounding polygons + confidence
- Line-level geometry
- Paragraph/block detection
- Table structure (cells with row/col/spans/polygons)
- Reading order via content spans
- Arabic, English, French natively supported (print + handwriting)

This module converts Azure's response into our canonical schema,
preserving ALL geometric data.
"""

from __future__ import annotations

import bisect
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from .config import AzureConfig
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
    Table,
    TableCell,
    Token,
)

logger = logging.getLogger(__name__)


# ─── Azure polygon → our schema helpers ──────────────────────────────────────

def _azure_polygon_to_schema(
    polygon: list[float],
    page_width_inch: float,
    page_height_inch: float,
    image_width_px: int,
    image_height_px: int,
) -> tuple[Polygon, BBox]:
    """
    Convert Azure's flat polygon [x1,y1, x2,y2, ...] (in inches)
    to our Polygon and BBox (in page pixel coordinates).

    Azure DI returns coordinates in inches from the top-left.
    We convert to pixel coordinates matching our rasterised page image.
    """
    scale_x = image_width_px / page_width_inch
    scale_y = image_height_px / page_height_inch

    points = []
    for i in range(0, len(polygon), 2):
        px = polygon[i] * scale_x
        py = polygon[i + 1] * scale_y
        points.append([px, py])

    poly = Polygon(points=points)
    bbox = poly.to_bbox()
    return poly, bbox


def _detect_direction(text: str) -> Direction:
    """Detect text direction based on character analysis."""
    if not text:
        return Direction.LTR

    arabic_count = 0
    latin_count = 0
    for char in text:
        cp = ord(char)
        # Arabic Unicode ranges
        if (0x0600 <= cp <= 0x06FF or   # Arabic
            0x0750 <= cp <= 0x077F or   # Arabic Supplement
            0xFB50 <= cp <= 0xFDFF or   # Arabic Presentation Forms-A
            0xFE70 <= cp <= 0xFEFF or   # Arabic Presentation Forms-B
            0x08A0 <= cp <= 0x08FF):    # Arabic Extended-A
            arabic_count += 1
        elif (0x0041 <= cp <= 0x005A or  # Latin uppercase
              0x0061 <= cp <= 0x007A or  # Latin lowercase
              0x00C0 <= cp <= 0x00FF):   # Latin Extended-A
            latin_count += 1

    return Direction.RTL if arabic_count >= latin_count else Direction.LTR


def _detect_language(text: str) -> str:
    """Simple language detection based on script."""
    if not text.strip():
        return "und"  # undefined

    arabic_count = 0
    latin_count = 0
    for char in text:
        cp = ord(char)
        if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0xFB50 <= cp <= 0xFEFF:
            arabic_count += 1
        elif 0x0041 <= cp <= 0x007A or 0x00C0 <= cp <= 0x00FF:
            latin_count += 1

    if arabic_count > latin_count:
        return "ar"
    elif latin_count > 0:
        # Could be English or French — default to "en"
        # (full language ID would need a proper model)
        return "en"
    return "ar"  # Default for Arabic-primary documents


# ─── Main Azure DI Analysis ─────────────────────────────────────────────────

def analyze_pdf(
    pdf_path: Path,
    config: AzureConfig,
    page_images: Optional[list[PageImage]] = None,
) -> CanonicalDocument:
    """
    Analyze a PDF with Azure Document Intelligence.

    Sends the entire PDF to Azure's prebuilt-layout model and converts
    the response into our canonical schema with full geometry.

    Args:
        pdf_path: Path to the PDF file.
        config: Azure configuration.
        page_images: Pre-rasterised page images (for dimension mapping).

    Returns:
        CanonicalDocument with all geometry, text, tables, and reading order.
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        DocumentAnalysisFeature,
    )
    from azure.core.credentials import AzureKeyCredential

    config.validate()

    logger.info(f"Sending {pdf_path.name} to Azure DI ({config.model_id})...")
    start_time = time.time()

    # Initialize client
    client = DocumentIntelligenceClient(
        endpoint=config.endpoint,
        credential=AzureKeyCredential(config.api_key),
    )

    # Read PDF bytes
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Analyze with layout model
    # Features: enable relevant add-ons.
    # NOTE: FORMULAS is OFF by default — it causes Azure to eat Arabic
    # paragraph text and replace it with formula objects, losing content.
    features = [
        DocumentAnalysisFeature.OCR_HIGH_RESOLUTION,
        DocumentAnalysisFeature.STYLE_FONT,
        DocumentAnalysisFeature.LANGUAGES,
    ]
    # Check PipelineConfig if available (passed through config attribute)
    if config.enable_formulas:
        features.append(DocumentAnalysisFeature.FORMULAS)
        logger.info("FORMULAS add-on enabled")

    poller = client.begin_analyze_document(
        model_id=config.model_id,
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        features=features,
        output_content_format="text",
    )

    result = poller.result()
    elapsed = time.time() - start_time
    logger.info(f"Azure DI analysis complete in {elapsed:.1f}s")

    # Convert to canonical schema
    doc = _convert_azure_result(result, pdf_path, page_images, elapsed, config)
    return doc


def analyze_page_image(
    image_bytes: bytes,
    config: AzureConfig,
    page_image: Optional[PageImage] = None,
) -> Page:
    """
    Analyze a single page image with Azure Document Intelligence.

    Useful when preprocessing has been applied and you want to send
    the processed image rather than the original PDF.

    Args:
        image_bytes: Image bytes (PNG/JPEG/WebP).
        config: Azure configuration.
        page_image: PageImage metadata for coordinate mapping.

    Returns:
        Page object with all geometry data.
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        DocumentAnalysisFeature,
    )
    from azure.core.credentials import AzureKeyCredential

    config.validate()

    client = DocumentIntelligenceClient(
        endpoint=config.endpoint,
        credential=AzureKeyCredential(config.api_key),
    )

    features = [
        DocumentAnalysisFeature.OCR_HIGH_RESOLUTION,
        DocumentAnalysisFeature.STYLE_FONT,
        DocumentAnalysisFeature.LANGUAGES,
    ]
    if config.enable_formulas:
        features.append(DocumentAnalysisFeature.FORMULAS)

    poller = client.begin_analyze_document(
        model_id=config.model_id,
        body=AnalyzeDocumentRequest(bytes_source=image_bytes),
        features=features,
        output_content_format="text",
    )

    result = poller.result()

    if result.pages:
        page = _convert_azure_page(result, 0, page_image)
        # Apply font styles and language detection to this page
        _apply_font_styles(result, [page])
        _apply_language_detection(result, [page])
        return page

    return Page()


# ─── Azure Result → Canonical Schema Conversion ─────────────────────────────

def _convert_azure_result(
    result,
    pdf_path: Path,
    page_images: Optional[list[PageImage]],
    elapsed: float,
    config: AzureConfig,
) -> CanonicalDocument:
    """Convert Azure DI AnalyzeResult to our CanonicalDocument."""

    doc = CanonicalDocument(
        source=DocumentSource(
            filename=pdf_path.name,
            page_count=len(result.pages) if result.pages else 0,
        ),
        processing=ProcessingInfo(
            ocr_engine="azure-document-intelligence",
            ocr_model=config.model_id,
            processing_time_seconds=elapsed,
        ),
    )

    if not result.pages:
        return doc

    # Process each page
    for page_idx, azure_page in enumerate(result.pages):
        page_image = page_images[page_idx] if page_images and page_idx < len(page_images) else None
        page = _convert_azure_page(result, page_idx, page_image)
        doc.pages.append(page)

    # Apply font styles from Azure's styles collection
    _apply_font_styles(result, doc.pages)

    # Apply language detection from Azure's languages collection
    _apply_language_detection(result, doc.pages)

    # Extract formulas and add as EQUATION blocks (only if FORMULAS was enabled)
    if config.enable_formulas:
        _apply_formula_extraction(result, doc.pages, page_images)

    # Clean :formula: markers from line text (Azure injects these even
    # without the FORMULAS add-on in some cases)
    _clean_formula_markers(doc.pages)

    # Extract reading order from Azure's content + paragraphs
    _apply_azure_reading_order(result, doc)

    return doc


def _convert_azure_page(
    result,
    page_idx: int,
    page_image: Optional[PageImage],
) -> Page:
    """Convert a single Azure page to our Page schema."""
    azure_page = result.pages[page_idx]

    # Resolve page dimensions
    page_width_inch = azure_page.width or 8.5
    page_height_inch = azure_page.height or 11.0

    if page_image:
        img_w = page_image.width_px
        img_h = page_image.height_px
    else:
        # Estimate from DPI (Azure uses 72 DPI internally)
        img_w = int(page_width_inch * 300)
        img_h = int(page_height_inch * 300)

    page = Page(
        page_index=page_idx,
        image=page_image or PageImage(
            width_px=img_w, height_px=img_h, dpi=300
        ),
    )

    # Detect principal direction from the page's text
    page_text = ""
    if azure_page.lines:
        page_text = " ".join(line.content for line in azure_page.lines)
    page.principal_direction = _detect_direction(page_text)
    page.content_text = page_text

    # ─── Convert words to tokens ─────────────────────────────────
    word_map: dict[str, Token] = {}  # Map by position for line grouping

    if azure_page.words:
        for w_idx, word in enumerate(azure_page.words):
            if not word.polygon or len(word.polygon) < 4:
                continue

            poly, bbox = _azure_polygon_to_schema(
                word.polygon, page_width_inch, page_height_inch, img_w, img_h
            )

            token = Token(
                token_id=f"t_p{page_idx}_w{w_idx}",
                text=word.content or "",
                bbox=bbox,
                polygon=poly,
                confidence=word.confidence or 0.0,
                language=_detect_language(word.content or ""),
                direction=_detect_direction(word.content or ""),
            )
            word_map[token.token_id] = token

    # ─── Convert lines ───────────────────────────────────────────
    line_objects: list[Line] = []

    if azure_page.lines:
        for l_idx, azure_line in enumerate(azure_page.lines):
            if not azure_line.polygon or len(azure_line.polygon) < 4:
                continue

            poly, bbox = _azure_polygon_to_schema(
                azure_line.polygon, page_width_inch, page_height_inch, img_w, img_h
            )

            # Find words that belong to this line (by vertical overlap)
            line_tokens = []
            if azure_page.words:
                for w_idx, word in enumerate(azure_page.words):
                    if not word.polygon or len(word.polygon) < 4:
                        continue
                    _, w_bbox = _azure_polygon_to_schema(
                        word.polygon, page_width_inch, page_height_inch, img_w, img_h
                    )
                    # Check if word center is within line bbox
                    w_cy = (w_bbox.y0 + w_bbox.y1) / 2
                    if bbox.y0 <= w_cy <= bbox.y1:
                        w_cx = (w_bbox.x0 + w_bbox.x1) / 2
                        if bbox.x0 - 5 <= w_cx <= bbox.x1 + 5:
                            token = Token(
                                token_id=f"t_p{page_idx}_w{w_idx}",
                                text=word.content or "",
                                bbox=w_bbox,
                                confidence=word.confidence or 0.0,
                                language=_detect_language(word.content or ""),
                                direction=_detect_direction(word.content or ""),
                            )
                            line_tokens.append(token)

            # Sort tokens by x position (RTL pages: right to left)
            direction = _detect_direction(azure_line.content or "")
            if direction == Direction.RTL:
                line_tokens.sort(key=lambda t: -t.bbox.x0)
            else:
                line_tokens.sort(key=lambda t: t.bbox.x0)

            line = Line(
                line_id=f"l_p{page_idx}_l{l_idx}",
                text=azure_line.content or "",
                bbox=bbox,
                polygon=poly,
                tokens=line_tokens,
                confidence=sum(t.confidence for t in line_tokens) / len(line_tokens) if line_tokens else 0.0,
                language=_detect_language(azure_line.content or ""),
                direction=direction,
            )
            line_objects.append(line)

    # ─── Build blocks from paragraphs ────────────────────────────
    if result.paragraphs:
        block_idx = 0
        for para in result.paragraphs:
            # Check if this paragraph belongs to this page
            if not _paragraph_on_page(para, page_idx):
                continue

            poly = None
            bbox = None
            if para.bounding_regions:
                for br in para.bounding_regions:
                    if br.page_number == page_idx + 1:  # Azure is 1-based
                        if br.polygon:
                            poly, bbox = _azure_polygon_to_schema(
                                br.polygon, page_width_inch, page_height_inch, img_w, img_h
                            )
                        break

            if bbox is None:
                continue

            # Determine block type
            block_type = BlockType.TEXT
            role = getattr(para, "role", None)
            if role == "title" or role == "sectionHeading":
                block_type = BlockType.HEADER
            elif role == "footnote":
                block_type = BlockType.FOOTNOTE
            elif role == "pageHeader":
                block_type = BlockType.HEADER
            elif role == "pageFooter":
                block_type = BlockType.FOOTER
            elif role == "pageNumber":
                block_type = BlockType.PAGE_NUMBER
            elif role == "formulaBlock":
                block_type = BlockType.EQUATION

            # Find lines that fall within this paragraph's bbox
            para_lines = []
            for line in line_objects:
                line_cy = (line.bbox.y0 + line.bbox.y1) / 2
                line_cx = (line.bbox.x0 + line.bbox.x1) / 2
                if (bbox.y0 - 5 <= line_cy <= bbox.y1 + 5 and
                    bbox.x0 - 5 <= line_cx <= bbox.x1 + 5):
                    para_lines.append(line)

            block = Block(
                block_id=f"b_p{page_idx}_b{block_idx}",
                block_type=block_type,
                bbox=bbox,
                polygon=poly,
                direction=_detect_direction(para.content or ""),
                language=_detect_language(para.content or ""),
                confidence=sum(l.confidence for l in para_lines) / len(para_lines) if para_lines else 0.0,
                lines=para_lines,
            )
            page.blocks.append(block)
            block_idx += 1
    else:
        # Fallback: create one block per line
        for l_idx, line in enumerate(line_objects):
            block = Block(
                block_id=f"b_p{page_idx}_b{l_idx}",
                block_type=BlockType.TEXT,
                bbox=line.bbox,
                direction=line.direction or Direction.RTL,
                language=line.language,
                confidence=line.confidence,
                lines=[line],
            )
            page.blocks.append(block)

    # ─── Convert tables ──────────────────────────────────────────
    if result.tables:
        for t_idx, azure_table in enumerate(result.tables):
            if not _table_on_page(azure_table, page_idx):
                continue

            table = _convert_azure_table(
                azure_table, page_idx, t_idx,
                page_width_inch, page_height_inch, img_w, img_h
            )
            page.tables.append(table)

            # Also add as a block
            block = Block(
                block_id=f"b_p{page_idx}_tb{t_idx}",
                block_type=BlockType.TABLE,
                bbox=table.bbox,
                confidence=table.confidence,
                table=table,
            )
            page.blocks.append(block)

    # ─── Convert figures ─────────────────────────────────────────
    if hasattr(result, 'figures') and result.figures:
        for f_idx, azure_figure in enumerate(result.figures):
            if not _figure_on_page(azure_figure, page_idx):
                continue

            block = _convert_azure_figure(
                azure_figure, page_idx, f_idx,
                page_width_inch, page_height_inch, img_w, img_h
            )
            page.blocks.append(block)

    return page


def _paragraph_on_page(para, page_idx: int) -> bool:
    """Check if a paragraph belongs to a specific page."""
    if not para.bounding_regions:
        return False
    return any(br.page_number == page_idx + 1 for br in para.bounding_regions)


def _table_on_page(table, page_idx: int) -> bool:
    """Check if a table belongs to a specific page."""
    if not table.bounding_regions:
        return False
    return any(br.page_number == page_idx + 1 for br in table.bounding_regions)


def _figure_on_page(figure, page_idx: int) -> bool:
    """Check if a figure belongs to a specific page."""
    if not figure.bounding_regions:
        return False
    return any(br.page_number == page_idx + 1 for br in figure.bounding_regions)


def _convert_azure_table(
    azure_table,
    page_idx: int,
    table_idx: int,
    page_width_inch: float,
    page_height_inch: float,
    img_w: int,
    img_h: int,
) -> Table:
    """Convert an Azure table to our Table schema."""
    # Get table bounding box
    table_bbox = BBox(x0=0, y0=0, x1=img_w, y1=img_h)
    table_poly = None

    if azure_table.bounding_regions:
        for br in azure_table.bounding_regions:
            if br.page_number == page_idx + 1 and br.polygon:
                table_poly, table_bbox = _azure_polygon_to_schema(
                    br.polygon, page_width_inch, page_height_inch, img_w, img_h
                )
                break

    cells = []
    if azure_table.cells:
        for cell in azure_table.cells:
            cell_bbox = None
            cell_poly = None

            if cell.bounding_regions:
                for br in cell.bounding_regions:
                    if br.page_number == page_idx + 1 and br.polygon:
                        cell_poly, cell_bbox = _azure_polygon_to_schema(
                            br.polygon, page_width_inch, page_height_inch, img_w, img_h
                        )
                        break

            is_header = getattr(cell, "kind", "") == "columnHeader"

            cells.append(TableCell(
                row=cell.row_index or 0,
                col=cell.column_index or 0,
                row_span=cell.row_span or 1,
                col_span=cell.column_span or 1,
                bbox=cell_bbox,
                polygon=cell_poly,
                text=cell.content or "",
                is_header=is_header,
                confidence=0.9,  # Azure doesn't provide per-cell confidence
            ))

    return Table(
        table_id=f"tb_p{page_idx}_t{table_idx}",
        bbox=table_bbox,
        polygon=table_poly,
        row_count=azure_table.row_count or 0,
        col_count=azure_table.column_count or 0,
        cells=cells,
        confidence=0.9,
    )


def _convert_azure_figure(
    azure_figure,
    page_idx: int,
    figure_idx: int,
    page_width_inch: float,
    page_height_inch: float,
    img_w: int,
    img_h: int,
) -> Block:
    """Convert an Azure figure to our Block schema with FIGURE type."""
    # Get figure bounding box
    figure_bbox = BBox(x0=0, y0=0, x1=100, y1=100)
    figure_poly = None

    if azure_figure.bounding_regions:
        for br in azure_figure.bounding_regions:
            if br.page_number == page_idx + 1 and br.polygon:
                figure_poly, figure_bbox = _azure_polygon_to_schema(
                    br.polygon, page_width_inch, page_height_inch, img_w, img_h
                )
                break

    # Extract caption if available
    caption = None
    if hasattr(azure_figure, 'caption') and azure_figure.caption:
        caption = azure_figure.caption.content if hasattr(azure_figure.caption, 'content') else str(azure_figure.caption)
    
    # The figure_uri will be set later during image extraction
    # For now, we just mark where the figure is located
    figure_id = f"fig_p{page_idx}_f{figure_idx}"

    return Block(
        block_id=f"b_p{page_idx}_fig{figure_idx}",
        block_type=BlockType.FIGURE,
        bbox=figure_bbox,
        polygon=figure_poly,
        confidence=0.85,
        figure_uri=None,  # Will be populated during image extraction
        figure_caption=caption,
    )


# ─── Font Style Extraction ───────────────────────────────────────────────────

def _apply_font_styles(result, pages: list[Page]) -> None:
    """
    Apply font property data from Azure's styles collection to tokens.

    Azure returns styles as spans referencing character offsets in the
    top-level 'content' string.  We build an offset map for every token
    and use range-overlap to decide which tokens receive each style.

    Style properties: similarFontFamily, fontStyle (italic/normal),
    fontWeight (bold/normal), color, backgroundColor.
    """
    if not hasattr(result, 'styles') or not result.styles:
        logger.debug("No font style data in Azure response")
        return

    content = result.content or ""
    if not content:
        return

    # ── Build token offset map ───────────────────────────────────
    # Walk content sequentially, mapping each line's text to its
    # absolute offset. Then map each token within the line.
    token_ranges: list[tuple[int, int, Token]] = []   # (start, end, Token)
    search_from = 0

    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                if not line.text:
                    continue
                line_offset = content.find(line.text, search_from)
                if line_offset < 0:
                    # Fuzzy: try first 30 chars
                    snippet = line.text[:30]
                    line_offset = content.find(snippet, search_from)
                if line_offset < 0:
                    continue
                search_from = line_offset + len(line.text)

                if line.tokens:
                    # Map individual tokens within the line text
                    tok_search = line_offset
                    for tok in line.tokens:
                        if not tok.text:
                            continue
                        tok_pos = content.find(tok.text, tok_search)
                        if tok_pos < 0 or tok_pos > line_offset + len(line.text) + 10:
                            # Fallback: skip this token
                            continue
                        tok_end = tok_pos + len(tok.text)
                        token_ranges.append((tok_pos, tok_end, tok))
                        tok_search = tok_end
                else:
                    # No tokens — map the whole line as a pseudo-token
                    pass

    if not token_ranges:
        return

    # Sort by start offset for binary-search later
    token_ranges.sort(key=lambda x: x[0])

    # ── Apply styles via offset overlap ──────────────────────────
    styles_applied = 0
    for style in result.styles:
        # Extract style properties
        font_weight = getattr(style, 'font_weight', None)
        font_style = getattr(style, 'font_style', None)
        color = getattr(style, 'color', None)
        bg_color = getattr(style, 'background_color', None)

        # Normalise
        if font_weight == "normal":
            font_weight = None
        if font_style == "normal":
            font_style = None
        if color:
            color = f"#{color}" if not color.startswith('#') else color
        if bg_color:
            bg_color = f"#{bg_color}" if not bg_color.startswith('#') else bg_color

        if not any([font_weight, font_style, color, bg_color]):
            continue

        if not hasattr(style, 'spans') or not style.spans:
            continue

        for span in style.spans:
            sp_start = span.offset
            sp_end = sp_start + span.length

            # Find overlapping tokens (binary-search start)
            lo = bisect.bisect_right(
                [r[0] for r in token_ranges], sp_start
            ) - 1
            lo = max(lo - 1, 0)

            for idx in range(lo, len(token_ranges)):
                tok_start, tok_end, token = token_ranges[idx]
                if tok_start >= sp_end:
                    break  # past the span
                if tok_end <= sp_start:
                    continue  # before the span

                # Overlap — apply style
                if font_weight:
                    token.font_weight = font_weight
                if font_style:
                    token.font_style = font_style
                if color:
                    token.text_color = color
                styles_applied += 1

    # ── Propagate dominant style from tokens to lines ────────────
    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                if not line.tokens:
                    continue
                bold_count = sum(1 for t in line.tokens if t.font_weight == "bold")
                italic_count = sum(1 for t in line.tokens if t.font_style == "italic")
                if bold_count > len(line.tokens) // 2:
                    line.font_weight = "bold"
                if italic_count > len(line.tokens) // 2:
                    line.font_style = "italic"

    logger.info(f"Applied font styles to {styles_applied} token-style pairs")


# ─── Language Detection ──────────────────────────────────────────────────────

def _apply_language_detection(result, pages: list[Page]) -> None:
    """
    Apply Azure's per-line language detection to lines and tokens.

    Azure returns languages as spans referencing character offsets in
    the top-level 'content' string, with an ISO language code and
    confidence score.

    This replaces the naive Unicode-range-based heuristic with
    Azure's actual language detection.
    """
    if not hasattr(result, 'languages') or not result.languages:
        logger.debug("No language detection data in Azure response")
        return

    content = result.content or ""
    if not content:
        return

    # Build a map of character offset → language
    # Each language entry covers a span of the content string
    offset_lang_map: list[tuple[int, int, str, float]] = []  # (offset, length, locale, confidence)
    for lang_entry in result.languages:
        locale = lang_entry.locale or "und"
        confidence = lang_entry.confidence or 0.0
        if hasattr(lang_entry, 'spans') and lang_entry.spans:
            for span in lang_entry.spans:
                offset_lang_map.append((
                    span.offset, span.length, locale, confidence
                ))

    if not offset_lang_map:
        return

    # Sort by offset for efficient lookup
    offset_lang_map.sort(key=lambda x: x[0])

    def _find_language_at_offset(offset: int) -> tuple[str, float]:
        """Find the language for a given content offset."""
        for sp_offset, sp_length, locale, conf in offset_lang_map:
            if sp_offset <= offset < sp_offset + sp_length:
                # Normalize locale to ISO 639-1 (e.g. "ar-SA" → "ar")
                lang_code = locale.split("-")[0] if "-" in locale else locale
                return lang_code, conf
        return "und", 0.0

    # Map lines to their content offsets and apply language
    languages_applied = 0
    for page in pages:
        page_text = page.content_text or ""
        for block in page.blocks:
            for line in block.lines:
                if not line.text:
                    continue
                # Find this line's text in the global content
                line_offset = content.find(line.text)
                if line_offset >= 0:
                    lang_code, conf = _find_language_at_offset(line_offset)
                    if lang_code != "und":
                        line.language = lang_code
                        languages_applied += 1
                        # Apply to tokens in this line too
                        for token in line.tokens:
                            token.language = lang_code

            # Update block language from dominant child language
            line_langs = [l.language for l in block.lines if l.language and l.language != "und"]
            if line_langs:
                # Most common language in the block
                lang_counts = Counter(line_langs)
                block.language = lang_counts.most_common(1)[0][0]

    logger.info(f"Applied Azure language detection to {languages_applied} lines")


# ─── Formula marker cleanup ─────────────────────────────────────────────────

def _clean_formula_markers(pages: list[Page]) -> None:
    """
    Remove ':formula:' markers that Azure injects into line text.

    When the FORMULAS add-on is enabled (or sometimes even without it),
    Azure inserts ':formula:' tokens into regular text where it detects
    mathematical content. This corrupts the actual paragraph text.

    We strip these markers and update the line's stored text +
    remove any tokens whose text is exactly ':formula:'.
    """
    cleaned = 0
    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                if ':formula:' in (line.text or ''):
                    line.text = re.sub(r'\s*:formula:\s*', ' ', line.text).strip()
                    cleaned += 1
                # Remove :formula: tokens
                if line.tokens:
                    line.tokens = [
                        t for t in line.tokens
                        if t.text != ':formula:'
                    ]
    if cleaned:
        logger.info(f"Cleaned :formula: markers from {cleaned} lines")


# ─── Formula Extraction ─────────────────────────────────────────────────────

def _apply_formula_extraction(
    result,
    pages: list[Page],
    page_images: Optional[list[PageImage]],
) -> None:
    """
    Extract formulas from Azure's response and add them as EQUATION blocks.

    Azure returns formulas in result.pages[].formulas with:
    - kind: "inline" or "display"
    - value: LaTeX representation
    - polygon: bounding polygon
    - confidence: detection confidence

    Each formula becomes a Block with block_type=EQUATION and
    equation_latex populated.
    """
    total_formulas = 0

    for page_idx, azure_page in enumerate(result.pages):
        if not hasattr(azure_page, 'formulas') or not azure_page.formulas:
            continue

        if page_idx >= len(pages):
            break

        page = pages[page_idx]

        # Resolve page dimensions for coordinate conversion
        page_width_inch = azure_page.width or 8.5
        page_height_inch = azure_page.height or 11.0

        if page_images and page_idx < len(page_images):
            img_w = page_images[page_idx].width_px
            img_h = page_images[page_idx].height_px
        elif page.image:
            img_w = page.image.width_px
            img_h = page.image.height_px
        else:
            img_w = int(page_width_inch * 300)
            img_h = int(page_height_inch * 300)

        formula_idx = 0
        for formula in azure_page.formulas:
            kind = getattr(formula, 'kind', 'display')  # "inline" or "display"
            latex_value = getattr(formula, 'value', '') or ''
            confidence = getattr(formula, 'confidence', 0.0) or 0.0
            polygon = getattr(formula, 'polygon', None)

            if not latex_value:
                continue

            # Convert polygon to our schema
            formula_bbox = BBox(x0=0, y0=0, x1=100, y1=30)
            formula_poly = None
            if polygon and len(polygon) >= 4:
                formula_poly, formula_bbox = _azure_polygon_to_schema(
                    polygon, page_width_inch, page_height_inch, img_w, img_h
                )

            block = Block(
                block_id=f"b_p{page_idx}_eq{formula_idx}",
                block_type=BlockType.EQUATION,
                bbox=formula_bbox,
                polygon=formula_poly,
                confidence=confidence,
                equation_latex=latex_value,
                direction=Direction.LTR,  # Math is inherently LTR
                language="math",
            )
            page.blocks.append(block)
            formula_idx += 1
            total_formulas += 1

    if total_formulas > 0:
        logger.info(f"Extracted {total_formulas} formulas as EQUATION blocks")


def _apply_azure_reading_order(result, doc: CanonicalDocument) -> None:
    """
    Apply reading order from Azure's paragraph ordering.

    Azure DI returns paragraphs in reading order — the order of
    paragraphs in the response IS the reading order. We use this
    directly as our canonical reading order.
    """
    for page_idx, page in enumerate(doc.pages):
        units = []
        sequence = []

        for block in page.blocks:
            unit = ReadingOrderUnit(
                unit_id=block.block_id,
                ref_block_id=block.block_id,
                ref_table_id=block.table.table_id if block.table else None,
            )
            units.append(unit)
            sequence.append(block.block_id)

        page.reading_order = ReadingOrder(
            units=units,
            sequence=sequence,
            confidence=0.85,
            method=ReadingOrderMethod.ENGINE,
        )
