"""
Figure Extraction — crop and save figure regions from page images.

Extracts figure bounding boxes from page images and saves them as separate
image files for embedding in HTML/semantic outputs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from .schema import Block, BlockType, CanonicalDocument, Page

logger = logging.getLogger(__name__)


def extract_figures(
    doc: CanonicalDocument,
    output_dir: Path,
    page_images: Optional[list[Image.Image]] = None,
) -> CanonicalDocument:
    """
    Extract all figures from the document and save them as images.
    
    Updates the figure_uri field in each FIGURE block to point to the
    extracted image file.
    
    Args:
        doc: The canonical document with FIGURE blocks
        output_dir: Directory to save extracted figure images
        page_images: List of PIL Images for each page. If None, loads from doc.pages[].image.uri
        
    Returns:
        Updated document with figure_uri fields populated
    """
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True, parents=True)
    
    stem = doc.source.filename.replace('.pdf', '').replace('.PDF', '')
    
    for page_idx, page in enumerate(doc.pages):
        # Get the page image
        page_img = None
        if page_images and page_idx < len(page_images):
            page_img = page_images[page_idx]
        elif page.image.uri:
            # Load from URI
            img_path = output_dir / page.image.uri
            if img_path.exists():
                try:
                    page_img = Image.open(img_path)
                except Exception as e:
                    logger.warning(f"Could not load page image {img_path}: {e}")
                    continue
        
        if page_img is None:
            logger.warning(f"No image available for page {page_idx}, skipping figure extraction")
            continue
        
        # Extract figures from this page
        figure_count = 0
        for block in page.blocks:
            if block.block_type != BlockType.FIGURE:
                continue
                
            figure_count += 1
            
            # Crop the figure region
            bbox = block.bbox
            x0, y0, x1, y1 = int(bbox.x0), int(bbox.y0), int(bbox.x1), int(bbox.y1)
            
            # Ensure coordinates are within image bounds
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(page_img.width, x1)
            y1 = min(page_img.height, y1)
            
            if x1 <= x0 or y1 <= y0:
                logger.warning(f"Invalid figure bbox on page {page_idx}: {bbox}")
                continue
            
            try:
                # Crop the figure
                figure_img = page_img.crop((x0, y0, x1, y1))
                
                # Save the figure
                figure_filename = f"{stem}_p{page_idx}_fig{figure_count}.webp"
                figure_path = figures_dir / figure_filename
                
                # Save as WebP for better compression
                figure_img.save(figure_path, format='WEBP', quality=85)
                
                # Update the block's figure_uri (relative path)
                block.figure_uri = f"figures/{figure_filename}"
                
                logger.info(f"Extracted figure: {figure_filename} ({x1-x0}x{y1-y0}px)")
                
            except Exception as e:
                logger.error(f"Failed to extract figure from page {page_idx}: {e}")
                continue
    
    return doc


def extract_figure_from_page(
    page_img: Image.Image,
    block: Block,
    output_path: Path,
) -> Optional[str]:
    """
    Extract a single figure from a page image.
    
    Args:
        page_img: PIL Image of the page
        block: FIGURE block with bbox
        output_path: Where to save the extracted image
        
    Returns:
        Path to saved figure, or None if extraction failed
    """
    if block.block_type != BlockType.FIGURE:
        return None
    
    bbox = block.bbox
    x0, y0, x1, y1 = int(bbox.x0), int(bbox.y0), int(bbox.x1), int(bbox.y1)
    
    # Ensure coordinates are within image bounds
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(page_img.width, x1)
    y1 = min(page_img.height, y1)
    
    if x1 <= x0 or y1 <= y0:
        logger.warning(f"Invalid figure bbox: {bbox}")
        return None
    
    try:
        figure_img = page_img.crop((x0, y0, x1, y1))
        output_path.parent.mkdir(exist_ok=True, parents=True)
        figure_img.save(output_path, format='WEBP', quality=85)
        return str(output_path)
    except Exception as e:
        logger.error(f"Failed to extract figure: {e}")
        return None
