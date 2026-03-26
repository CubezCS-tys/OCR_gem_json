#!/usr/bin/env python3
"""
Create Searchable PDF from Existing JSON (No Azure API Call).

Uses pre-existing canonical JSON from Azure OCR to create searchable PDF.
No API calls required - perfect for when you already have the OCR data!

Usage:
    python json_to_searchable_pdf.py input.pdf canonical.json output_searchable.pdf
"""

import argparse
import logging
from pathlib import Path

import fitz  # PyMuPDF

from fixed_layout_pipeline.schema import CanonicalDocument

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_searchable_pdf_from_json(
    input_pdf: Path,
    json_path: Path,
    output_pdf: Path,
    debug: bool = False,
) -> None:
    """
    Create a searchable PDF using existing JSON OCR data.
    
    Args:
        input_pdf: Path to input scanned PDF
        json_path: Path to canonical JSON with OCR data
        output_pdf: Path to output searchable PDF
        debug: If True, make text visible (red semi-transparent) for debugging
    """
    logger.info(f"Loading OCR data from: {json_path.name}")
    
    # Load the canonical JSON
    doc = CanonicalDocument.load(json_path)
    logger.info(f"  Loaded {len(doc.pages)} pages with {doc.total_blocks()} text blocks")
    
    # Open original PDF
    logger.info(f"Opening original PDF: {input_pdf.name}")
    pdf_doc = fitz.open(str(input_pdf))
    
    # Add invisible text layer to each page
    logger.info("Adding invisible text layer...")
    
    for page_idx, page_data in enumerate(doc.pages):
        if page_idx >= len(pdf_doc):
            logger.warning(f"Page {page_idx} not found in PDF, skipping")
            continue
        
        pdf_page = pdf_doc[page_idx]
        page_rect = pdf_page.rect
        
        # Scale factor: convert from pixel coordinates to PDF points
        if page_data.image:
            scale_x = page_rect.width / page_data.image.width_px
            scale_y = page_rect.height / page_data.image.height_px
        else:
            # Fallback
            scale_x = page_rect.width / 2480
            scale_y = page_rect.height / 3508
        
        # Add text blocks
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
                
                # Calculate font size
                font_size = (y1 - y0) * 0.8
                if font_size < 1:
                    font_size = 10
                
                # Insert text (invisible or visible for debug)
                try:
                    if debug:
                        # Debug mode: visible red text
                        pdf_page.insert_text(
                            point=(x0, y1),  # Bottom-left baseline
                            text=line.text,
                            fontsize=font_size,
                            fontname="helv",
                            color=(1, 0, 0),  # Red
                            render_mode=0,  # Normal (visible)
                        )
                    else:
                        # Normal mode: invisible text
                        pdf_page.insert_text(
                            point=(x0, y1),  # Bottom-left baseline
                            text=line.text,
                            fontsize=font_size,
                            fontname="helv",
                            color=(0, 0, 0),
                            render_mode=3,  # Invisible but selectable
                        )
                    blocks_added += 1
                except Exception as e:
                    # Fallback: use textbox
                    try:
                        text_rect = fitz.Rect(x0, y0, x1, y1)
                        if debug:
                            # Debug: visible red text
                            pdf_page.insert_textbox(
                                text_rect,
                                line.text,
                                fontsize=font_size,
                                fontname="helv",
                                color=(1, 0, 0),
                                align=fitz.TEXT_ALIGN_LEFT,
                                overlay=True,
                            )
                        else:
                            # Normal: invisible
                            pdf_page.insert_textbox(
                                text_rect,
                                line.text,
                                fontsize=font_size,
                                fontname="helv",
                                color=(0, 0, 0),
                                align=fitz.TEXT_ALIGN_LEFT,
                                overlay=False,
                            )
                        blocks_added += 1
                    except Exception as e2:
                        logger.debug(f"Failed to add text: {e2}")
                        continue
        
        logger.info(f"  Page {page_idx + 1}/{len(doc.pages)}: Added {blocks_added} text blocks")
    
    # Save the searchable PDF
    logger.info(f"Saving searchable PDF to: {output_pdf}")
    pdf_doc.save(str(output_pdf), garbage=4, deflate=True)
    pdf_doc.close()
    
    # Show file sizes
    input_size = input_pdf.stat().st_size / (1024 * 1024)
    output_size = output_pdf.stat().st_size / (1024 * 1024)
    
    logger.info("=" * 60)
    logger.info("COMPLETED")
    logger.info(f"  Input PDF:  {input_pdf.name} ({input_size:.2f} MB)")
    logger.info(f"  Input JSON: {json_path.name}")
    logger.info(f"  Output PDF: {output_pdf.name} ({output_size:.2f} MB)")
    logger.info(f"  Size change: {(output_size - input_size):+.2f} MB")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Create searchable PDF from existing JSON (no Azure API call)",
    )
    parser.add_argument("input_pdf", type=Path, help="Input scanned PDF file")
    parser.add_argument("json_file", type=Path, help="Canonical JSON file with OCR data")
    parser.add_argument("output_pdf", type=Path, help="Output searchable PDF file")
    parser.add_argument("--debug", action="store_true", help="Make text visible (red semi-transparent) for debugging")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate inputs
    if not args.input_pdf.exists():
        logger.error(f"Input PDF not found: {args.input_pdf}")
        return 1
    
    if not args.json_file.exists():
        logger.error(f"JSON file not found: {args.json_file}")
        return 1
    
    # Create searchable PDF
    try:
        create_searchable_pdf_from_json(
            args.input_pdf,
            args.json_file,
            args.output_pdf,
            debug=args.debug,
        )
        return 0
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
