#!/usr/bin/env python3
"""
Parallel Batch Processing for Fixed Layout Pipeline.

Process multiple PDFs in parallel using asyncio and threading.
Outputs JSON and searchable PDF for each document.

Usage:
    # Process all PDFs in a directory
    python batch_process_fixed_layout.py --input pdfs/2026/2026/scanned --output batch_output --workers 4
    
    # Process specific PDFs
    python batch_process_fixed_layout.py --input pdfs/2026/2026/scanned --output batch_output --workers 8 --pattern "*.pdf"
    
    # Resume failed jobs
    python batch_process_fixed_layout.py --input pdfs/2026/2026/scanned --output batch_output --resume
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

from fixed_layout_pipeline.config import PipelineConfig
from fixed_layout_pipeline.pipeline import Pipeline

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
    output_dir: Optional[Path] = None
    json_path: Optional[Path] = None
    html_path: Optional[Path] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    page_count: int = 0
    file_size_mb: float = 0.0


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
        return {
            "total_pdfs": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": f"{(self.completed / max(self.total, 1) * 100):.1f}%",
            "total_duration_seconds": round(self.total_duration, 2),
            "avg_duration_per_pdf": round(avg_duration, 2),
        }


def process_single_pdf(
    pdf_path: Path,
    output_base_dir: Path,
    config: PipelineConfig,
    page_range: Optional[tuple[int, int]] = None,
) -> ProcessingResult:
    """
    Process a single PDF through the fixed layout pipeline.
    
    Args:
        pdf_path: Path to the PDF file
        output_base_dir: Base output directory
        config: Pipeline configuration
        page_range: Optional page range to process
    
    Returns:
        ProcessingResult with status and output paths
    """
    start_time = time.time()
    result = ProcessingResult(
        pdf_path=pdf_path,
        success=False,
        file_size_mb=round(pdf_path.stat().st_size / (1024 * 1024), 2),
    )
    
    try:
        # Create output directory for this PDF
        stem = pdf_path.stem
        pdf_output_dir = output_base_dir / stem
        pdf_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Processing: {pdf_path.name}")
        
        # Run pipeline
        pipeline = Pipeline(config)
        doc, html_path = pipeline.process(
            pdf_path,
            output_dir=output_base_dir,
            page_range=page_range,
        )
        
        # Save canonical JSON
        json_path = pdf_output_dir / f"{stem}_canonical.json"
        doc.save(json_path)
        
        result.success = True
        result.output_dir = pdf_output_dir
        result.json_path = json_path
        result.html_path = html_path
        result.page_count = len(doc.pages)
        result.duration_seconds = time.time() - start_time
        
        logger.info(f"✓ Completed: {pdf_path.name} ({result.duration_seconds:.1f}s, {result.page_count} pages)")
        
    except Exception as e:
        result.error = str(e)
        result.duration_seconds = time.time() - start_time
        logger.error(f"✗ Failed: {pdf_path.name} - {str(e)}")
        logger.debug(traceback.format_exc())
    
    return result


def process_batch_parallel(
    pdf_paths: List[Path],
    output_dir: Path,
    config: PipelineConfig,
    max_workers: int = 4,
    resume: bool = False,
) -> BatchStats:
    """
    Process multiple PDFs in parallel using ThreadPoolExecutor.
    
    Args:
        pdf_paths: List of PDF paths to process
        output_dir: Output directory for all results
        config: Pipeline configuration
        max_workers: Number of parallel workers
        resume: Skip PDFs that already have outputs
    
    Returns:
        BatchStats with processing results
    """
    stats = BatchStats(total=len(pdf_paths))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter out already processed PDFs if resume=True
    pdfs_to_process = []
    for pdf_path in pdf_paths:
        stem = pdf_path.stem
        json_path = output_dir / stem / f"{stem}_canonical.json"
        
        if resume and json_path.exists():
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
            executor.submit(process_single_pdf, pdf_path, output_dir, config): pdf_path
            for pdf_path in pdfs_to_process
        }
        
        for future in as_completed(futures):
            result = future.result()
            stats.add_result(result)
            
            # Progress update
            progress = (stats.completed + stats.failed) / len(pdfs_to_process) * 100
            logger.info(f"Progress: {stats.completed}/{len(pdfs_to_process)} completed ({progress:.1f}%)")
    
    return stats


async def process_batch_async(
    pdf_paths: List[Path],
    output_dir: Path,
    config: PipelineConfig,
    max_concurrent: int = 4,
    resume: bool = False,
) -> BatchStats:
    """
    Process multiple PDFs asynchronously.
    
    Args:
        pdf_paths: List of PDF paths to process
        output_dir: Output directory for all results
        config: Pipeline configuration
        max_concurrent: Maximum concurrent tasks
        resume: Skip PDFs that already have outputs
    
    Returns:
        BatchStats with processing results
    """
    stats = BatchStats(total=len(pdf_paths))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter out already processed PDFs if resume=True
    pdfs_to_process = []
    for pdf_path in pdf_paths:
        stem = pdf_path.stem
        json_path = output_dir / stem / f"{stem}_canonical.json"
        
        if resume and json_path.exists():
            logger.info(f"⊙ Skipping (already processed): {pdf_path.name}")
            stats.skipped += 1
        else:
            pdfs_to_process.append(pdf_path)
    
    if not pdfs_to_process:
        logger.info("No PDFs to process (all already completed)")
        return stats
    
    logger.info(f"Processing {len(pdfs_to_process)} PDFs with {max_concurrent} concurrent tasks...")
    
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(pdf_path: Path):
        async with semaphore:
            # Run the synchronous processing function in a thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                process_single_pdf,
                pdf_path,
                output_dir,
                config,
                None,
            )
            stats.add_result(result)
            
            # Progress update
            progress = (stats.completed + stats.failed) / len(pdfs_to_process) * 100
            logger.info(f"Progress: {stats.completed}/{len(pdfs_to_process)} completed ({progress:.1f}%)")
            
            return result
    
    # Process all PDFs
    tasks = [process_with_semaphore(pdf_path) for pdf_path in pdfs_to_process]
    await asyncio.gather(*tasks)
    
    return stats


def save_batch_report(stats: BatchStats, output_dir: Path):
    """Save a detailed batch processing report."""
    report_path = output_dir / "batch_report.json"
    
    report = {
        "summary": stats.summary(),
        "results": [
            {
                "pdf": result.pdf_path.name,
                "success": result.success,
                "json_path": str(result.json_path) if result.json_path else None,
                "html_path": str(result.html_path) if result.html_path else None,
                "duration_seconds": round(result.duration_seconds, 2),
                "page_count": result.page_count,
                "file_size_mb": result.file_size_mb,
                "error": result.error,
            }
            for result in stats.results
        ],
    }
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Report saved: {report_path}")
    
    # Also save a simple list of failed PDFs if any
    if stats.failed > 0:
        failed_path = output_dir / "failed_pdfs.txt"
        with open(failed_path, "w") as f:
            for result in stats.results:
                if not result.success:
                    f.write(f"{result.pdf_path}\n")
        logger.info(f"Failed PDFs list: {failed_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch process PDFs with fixed_layout_pipeline in parallel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Input directory containing PDF files",
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output directory for processed results",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--pattern",
        default="*.pdf",
        help="File pattern to match (default: *.pdf)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Rasterization DPI (default: 300)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug bounding boxes",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip PDFs that already have output",
    )
    parser.add_argument(
        "--async",
        dest="use_async",
        action="store_true",
        help="Use async/await instead of ThreadPoolExecutor",
    )
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Skip preprocessing (deskew, denoise, etc.)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    
    args = parser.parse_args()
    
    # Setup
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        sys.exit(1)
    
    # Find all PDFs
    pdf_paths = sorted(input_dir.glob(args.pattern))
    
    if not pdf_paths:
        logger.error(f"No PDFs found matching pattern '{args.pattern}' in {input_dir}")
        sys.exit(1)
    
    logger.info(f"Found {len(pdf_paths)} PDF files")
    
    # Configure pipeline
    config = PipelineConfig.from_env()
    config.raster.dpi = args.dpi
    config.renderer.debug_boxes = args.debug
    config.log_level = "DEBUG" if args.verbose else "INFO"
    config.output_dir = output_dir
    
    if args.no_preprocess:
        config.preprocess.deskew = False
        config.preprocess.denoise = False
        config.preprocess.auto_orient = False
    
    # Process batch
    start_time = time.time()
    
    if args.use_async:
        stats = asyncio.run(process_batch_async(
            pdf_paths,
            output_dir,
            config,
            max_concurrent=args.workers,
            resume=args.resume,
        ))
    else:
        stats = process_batch_parallel(
            pdf_paths,
            output_dir,
            config,
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
    
    # Save report
    save_batch_report(stats, output_dir)
    
    # Exit code
    sys.exit(0 if stats.failed == 0 else 1)


if __name__ == "__main__":
    main()
