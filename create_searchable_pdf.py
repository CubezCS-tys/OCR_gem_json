#!/usr/bin/env python3
"""
Create Searchable PDF from Azure Document Intelligence OCR.

Takes a scanned PDF and embeds invisible OCR text layer on top,
creating a searchable PDF while preserving original image quality.

Usage:
    python create_searchable_pdf.py input.pdf output_searchable.pdf
"""

import argparse
import logging
from pathlib import Path

import fitz  # PyMuPDF

from fixed_layout_pipeline.config import PipelineConfig, AzureConfig
from fixed_layout_pipeline.ingest import extract_source_metadata
from fixed_layout_pipeline.ocr_engine import analyze_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_searchable_pdf(
    input_pdf: Path,
    output_pdf: Path,
    azure_config: AzureConfig,
) -> None:
    """
    Create a searchable PDF by overlaying OCR text on the original PDF.
    
    Args:
        input_pdf: Path to input scanned PDF
        output_pdf: Path to output searchable PDF
        azure_config: Azure Document Intelligence configuration
    """
    logger.info(f"Processing: {input_pdf.name}")
    
    # Step 1: Get OCR results from Azure
    logger.info("[1/3] Running Azure Document Intelligence OCR...")
    doc = analyze_pdf(input_pdf, azure_config, page_images=None)
    logger.info(f"  Extracted {doc.total_blocks()} text blocks from {len(doc.pages)} pages")
    
    # Step 2: Open original PDF
    logger.info("[2/3] Opening original PDF...")
    pdf_doc = fitz.open(str(input_pdf))
    
    # Step 3: Add invisible text layer to each page
    logger.info("[3/3] Adding invisible text layer...")
    
    for page_idx, page_data in enumerate(doc.pages):
        if page_idx >= len(pdf_doc):
            logger.warning(f"Page {page_idx} not found in PDF, skipping")
            continue
        
        pdf_page = pdf_doc[page_idx]
        page_rect = pdf_page.rect
        
        # Scale factor: convert from pixel coordinates to PDF points
        # Azure gives us pixel coordinates based on the rasterized image
        # PDF uses points (1 point = 1/72 inch)
        if page_data.image:
            scale_x = page_rect.width / page_data.image.width_px
            scale_y = page_rect.height / page_data.image.height_px
        else:
            # Fallback: assume standard A4 at 300 DPI
            scale_x = page_rect.width / 2480  # A4 width at 300 DPI
            scale_y = page_rect.height / 3508  # A4 height at 300 DPI
        
        # Add each text block using low-level text insertion
        blocks_added = 0
        for block in page_data.blocks:
            if not block.lines:
                continue
            
            for line in block.lines:
                if not line.text.strip():
                    continue
                
                # Convert pixel bbox to PDF points
                x0 = line.bbox.x0 * scale_x
                y0 = line.bbox.y0 * scale_y
                x1 = line.bbox.x1 * scale_x
                y1 = line.bbox.y1 * scale_y
                
                # Calculate font size based on bbox height
                font_size = (y1 - y0) * 0.8
                
                # Insert text using insert_text for better control
                # Position at bottom-left of bbox (PDF text baseline)
                try:
                    # Make text invisible by setting render mode to 3 (invisible)
                    # and using a very low opacity
                    pdf_page.insert_text(
                        point=(x0, y1),  # Bottom-left corner (baseline)
                        text=line.text,
                        fontsize=font_size,
                        fontname="helv",
                        color=(0, 0, 0),  # Black text
                        render_mode=3,  # Invisible text (no stroke, no fill, add to clipping path)
                    )
                    blocks_added += 1
                except Exception as e:
                    # Fallback: try with textbox and transparent color
                    try:
                        text_rect = fitz.Rect(x0, y0, x1, y1)
                        pdf_page.insert_textbox(
                            text_rect,
                            line.text,
                            fontsize=font_size,
                            fontname="helv",
                            color=(0, 0, 0),
                            align=fitz.TEXT_ALIGN_LEFT if line.direction.value == "ltr" else fitz.TEXT_ALIGN_RIGHT,
                            overlay=False,  # Put text behind image
                        )
                        blocks_added += 1
                    except Exception as e2:
                        logger.debug(f"Failed to add text block: {e2}")
                        continue
        
        logger.info(f"  Page {page_idx + 1}/{len(doc.pages)}: Added {blocks_added} text blocks")
    
    # Step 4: Save the searchable PDF
    logger.info(f"Saving searchable PDF to: {output_pdf}")
    pdf_doc.save(str(output_pdf), garbage=4, deflate=True)
    pdf_doc.close()
    
    # Get file sizes for comparison
    input_size = input_pdf.stat().st_size / (1024 * 1024)
    output_size = output_pdf.stat().st_size / (1024 * 1024)
    
    logger.info("=" * 60)
    logger.info("COMPLETED")
    logger.info(f"  Input:  {input_pdf.name} ({input_size:.2f} MB)")
    logger.info(f"  Output: {output_pdf.name} ({output_size:.2f} MB)")
    logger.info(f"  Size increase: {(output_size - input_size):.2f} MB")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Create searchable PDF using Azure Document Intelligence OCR",
    )
    parser.add_argument(
        "input_pdf",
        type=Path,
        help="Input scanned PDF file",
    )
    parser.add_argument(
        "output_pdf",
        type=Path,
        help="Output searchable PDF file",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Check input file exists
    if not args.input_pdf.exists():
        logger.error(f"Input file not found: {args.input_pdf}")
        return 1
    
    # Load Azure config from environment
    try:
        azure_config = AzureConfig()
        azure_config.validate()
    except Exception as e:
        logger.error(f"Azure configuration error: {e}")
        logger.error("Make sure AZURE_DI_ENDPOINT and AZURE_DI_API_KEY are set")
        return 1
    
    # Create searchable PDF
    try:
        create_searchable_pdf(
            args.input_pdf,
            args.output_pdf,
            azure_config,
        )
        return 0
    except Exception as e:
        logger.error(f"Error creating searchable PDF: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
