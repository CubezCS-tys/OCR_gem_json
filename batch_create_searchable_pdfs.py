#!/usr/bin/env python3
"""
Batch Create Searchable PDFs using Azure Document Intelligence.

Process multiple scanned PDFs in parallel, creating searchable PDFs
with invisible OCR text layer on top of original images.

Usage:
    python batch_create_searchable_pdfs.py --input pdfs/2026/2026/scanned --output searchable_pdfs --workers 4
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
import traceback

import fitz  # PyMuPDF

from fixed_layout_pipeline.config import AzureConfig
from fixed_layout_pipeline.ocr_engine import analyze_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single PDF."""
    pdf_path: Path
    success: bool
    output_path: Optional[Path] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    page_count: int = 0
    input_size_mb: float = 0.0
    output_size_mb: float = 0.0


@dataclass
class BatchStats:
    """Tracking statistics for the batch run."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total_duration: float = 0.0
    results: List[ProcessingResult] = field(default_factory=list)
    
    def add_result(self, result: ProcessingResult):
        self.results.append(result)
        self.completed += 1 if result.success else 0
        self.failed += 1 if not result.success else 0
        self.total_duration += result.duration_seconds
    
    def summary(self) -> Dict[str, Any]:
        avg_duration = self.total_duration / max(self.completed, 1)
        total_input_size = sum(r.input_size_mb for r in self.results)
        total_output_size = sum(r.output_size_mb for r in self.results)
        return {
            "total_pdfs": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": f"{(self.completed / max(self.total, 1) * 100):.1f}%",
            "total_duration_seconds": round(self.total_duration, 2),
            "avg_duration_per_pdf": round(avg_duration, 2),
            "total_input_size_mb": round(total_input_size, 2),
            "total_output_size_mb": round(total_output_size, 2),
            "size_increase_mb": round(total_output_size - total_input_size, 2),
        }


def process_single_pdf(
    pdf_path: Path,
    output_dir: Path,
    azure_config: AzureConfig,
) -> ProcessingResult:
    """
    Process a single PDF to create searchable version.
    
    Args:
        pdf_path: Path to input PDF
        output_dir: Output directory
        azure_config: Azure configuration
    
    Returns:
        ProcessingResult with status
    """
    start_time = time.time()
    result = ProcessingResult(
        pdf_path=pdf_path,
        success=False,
        input_size_mb=round(pdf_path.stat().st_size / (1024 * 1024), 2),
    )
    
    try:
        # Output path
        output_path = output_dir / f"{pdf_path.stem}_searchable.pdf"
        
        logger.info(f"Processing: {pdf_path.name}")
        
        # Get OCR results from Azure
        doc = analyze_pdf(pdf_path, azure_config, page_images=None)
        
        # Open original PDF
        pdf_doc = fitz.open(str(pdf_path))
        
        # Add text layer to each page
        for page_idx, page_data in enumerate(doc.pages):
            if page_idx >= len(pdf_doc):
                continue
            
            pdf_page = pdf_doc[page_idx]
            page_rect = pdf_page.rect
            
            # Scale factor
            if page_data.image:
                scale_x = page_rect.width / page_data.image.width_px
                scale_y = page_rect.height / page_data.image.height_px
            else:
                scale_x = page_rect.width / 2480
                scale_y = page_rect.height / 3508
            
            # Add text blocks
            for block in page_data.blocks:
                if not block.lines:
                    continue
                
                for line in block.lines:
                    if not line.text.strip():
                        continue
                    
                    x0 = line.bbox.x0 * scale_x
                    y0 = line.bbox.y0 * scale_y
                    x1 = line.bbox.x1 * scale_x
                    y1 = line.bbox.y1 * scale_y
                    
                    text_rect = fitz.Rect(x0, y0, x1, y1)
                    font_size = (y1 - y0) * 0.8
                    
                    try:
                        pdf_page.insert_textbox(
                            text_rect,
                            line.text,
                            fontsize=font_size,
                            fontname="helv",
                            color=(1, 1, 1),  # Invisible white
                            align=fitz.TEXT_ALIGN_LEFT if line.direction.value == "ltr" else fitz.TEXT_ALIGN_RIGHT,
                            render_mode=3,
                        )
                    except Exception:
                        continue
        
        # Save searchable PDF
        pdf_doc.save(str(output_path), garbage=4, deflate=True)
        pdf_doc.close()
        
        result.success = True
        result.output_path = output_path
        result.page_count = len(doc.pages)
        result.output_size_mb = round(output_path.stat().st_size / (1024 * 1024), 2)
        result.duration_seconds = time.time() - start_time
        
        logger.info(
            f"✓ Completed: {pdf_path.name} ({result.duration_seconds:.1f}s, "
            f"{result.page_count} pages, {result.input_size_mb:.1f}→{result.output_size_mb:.1f}MB)"
        )
        
    except Exception as e:
        result.error = str(e)
        result.duration_seconds = time.time() - start_time
        logger.error(f"✗ Failed: {pdf_path.name} - {str(e)}")
        logger.debug(traceback.format_exc())
    
    return result


def process_batch_parallel(
    pdf_paths: List[Path],
    output_dir: Path,
    azure_config: AzureConfig,
    max_workers: int = 4,
    resume: bool = False,
) -> BatchStats:
    """Process multiple PDFs in parallel."""
    stats = BatchStats(total=len(pdf_paths))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter already processed
    pdfs_to_process = []
    for pdf_path in pdf_paths:
        output_path = output_dir / f"{pdf_path.stem}_searchable.pdf"
        
        if resume and output_path.exists():
            logger.info(f"⊙ Skipping (already processed): {pdf_path.name}")
            stats.skipped += 1
        else:
            pdfs_to_process.append(pdf_path)
    
    if not pdfs_to_process:
        logger.info("No PDFs to process (all already completed)")
        return stats
    
    logger.info(f"Processing {len(pdfs_to_process)} PDFs with {max_workers} workers...")
    
    # Process in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_pdf, pdf_path, output_dir, azure_config): pdf_path
            for pdf_path in pdfs_to_process
        }
        
        for future in as_completed(futures):
            result = future.result()
            stats.add_result(result)
            
            progress = (stats.completed + stats.failed) / len(pdfs_to_process) * 100
            logger.info(f"Progress: {stats.completed}/{len(pdfs_to_process)} completed ({progress:.1f}%)")
    
    return stats


async def process_batch_async(
    pdf_paths: List[Path],
    output_dir: Path,
    azure_config: AzureConfig,
    max_concurrent: int = 4,
    resume: bool = False,
) -> BatchStats:
    """Process multiple PDFs asynchronously."""
    stats = BatchStats(total=len(pdf_paths))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter already processed
    pdfs_to_process = []
    for pdf_path in pdf_paths:
        output_path = output_dir / f"{pdf_path.stem}_searchable.pdf"
        
        if resume and output_path.exists():
            logger.info(f"⊙ Skipping (already processed): {pdf_path.name}")
            stats.skipped += 1
        else:
            pdfs_to_process.append(pdf_path)
    
    if not pdfs_to_process:
        logger.info("No PDFs to process (all already completed)")
        return stats
    
    logger.info(f"Processing {len(pdfs_to_process)} PDFs with {max_concurrent} concurrent tasks...")
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(pdf_path: Path):
        async with semaphore:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                process_single_pdf,
                pdf_path,
                output_dir,
                azure_config,
            )
            stats.add_result(result)
            
            progress = (stats.completed + stats.failed) / len(pdfs_to_process) * 100
            logger.info(f"Progress: {stats.completed}/{len(pdfs_to_process)} completed ({progress:.1f}%)")
            
            return result
    
    tasks = [process_with_semaphore(pdf_path) for pdf_path in pdfs_to_process]
    await asyncio.gather(*tasks)
    
    return stats


def save_batch_report(stats: BatchStats, output_dir: Path):
    """Save batch processing report."""
    report_path = output_dir / "batch_report.json"
    
    report = {
        "summary": stats.summary(),
        "results": [
            {
                "pdf": result.pdf_path.name,
                "success": result.success,
                "output_path": str(result.output_path) if result.output_path else None,
                "duration_seconds": round(result.duration_seconds, 2),
                "page_count": result.page_count,
                "input_size_mb": result.input_size_mb,
                "output_size_mb": result.output_size_mb,
                "error": result.error,
            }
            for result in stats.results
        ],
    }
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Report saved: {report_path}")
    
    if stats.failed > 0:
        failed_path = output_dir / "failed_pdfs.txt"
        with open(failed_path, "w") as f:
            for result in stats.results:
                if not result.success:
                    f.write(f"{result.pdf_path}\n")
        logger.info(f"Failed PDFs list: {failed_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch create searchable PDFs with Azure Document Intelligence",
    )
    
    parser.add_argument("-i", "--input", required=True, help="Input directory with PDFs")
    parser.add_argument("-o", "--output", required=True, help="Output directory for searchable PDFs")
    parser.add_argument("-w", "--workers", type=int, default=4, help="Parallel workers (default: 4)")
    parser.add_argument("--pattern", default="*.pdf", help="File pattern (default: *.pdf)")
    parser.add_argument("--resume", action="store_true", help="Skip already processed PDFs")
    parser.add_argument("--async", dest="use_async", action="store_true", help="Use async mode")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        sys.exit(1)
    
    pdf_paths = sorted(input_dir.glob(args.pattern))
    
    if not pdf_paths:
        logger.error(f"No PDFs found matching '{args.pattern}' in {input_dir}")
        sys.exit(1)
    
    logger.info(f"Found {len(pdf_paths)} PDF files")
    
    # Load Azure config
    try:
        azure_config = AzureConfig()
        azure_config.validate()
    except Exception as e:
        logger.error(f"Azure configuration error: {e}")
        sys.exit(1)
    
    # Process batch
    start_time = time.time()
    
    if args.use_async:
        stats = asyncio.run(process_batch_async(
            pdf_paths,
            output_dir,
            azure_config,
            max_concurrent=args.workers,
            resume=args.resume,
        ))
    else:
        stats = process_batch_parallel(
            pdf_paths,
            output_dir,
            azure_config,
            max_workers=args.workers,
            resume=args.resume,
        )
    
    total_time = time.time() - start_time
    
    # Print summary
    print("\n" + "="*60)
    print("BATCH PROCESSING COMPLETE")
    print("="*60)
    print(json.dumps(stats.summary(), indent=2))
    print(f"\nTotal wall time: {total_time:.1f}s")
    print(f"Output directory: {output_dir}")
    
    save_batch_report(stats, output_dir)
    
    sys.exit(0 if stats.failed == 0 else 1)


if __name__ == "__main__":
    main()
