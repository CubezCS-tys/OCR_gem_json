#!/usr/bin/env python3
"""
Production-grade OCR pipeline example with all hardening features enabled.

This example shows how to integrate the new ocr_utils module with the
existing Mistral OCR pipeline for maximum reliability and production-readiness.
"""

import sys
import logging
from pathlib import Path

from ocr_utils import (
    validate_pdf_input,
    ProcessingCache,
    GracefulShutdownHandler,
    setup_correlation_logging,
    set_correlation_id,
    check_disk_space,
)
from mistral_ocr_pipeline import MistralOCRPipeline, MistralPipelineConfig

# Setup structured logging with correlation IDs
setup_correlation_logging()
logger = logging.getLogger(__name__)


def process_pdf_with_validation(
    pdf_path: str,
    output_dir: str = "outputs",
    skip_if_processed: bool = True
) -> bool:
    """
    Process a PDF with full validation and caching.

    Args:
        pdf_path: Path to PDF file
        output_dir: Output directory
        skip_if_processed: Skip if already in cache

    Returns:
        True if processed successfully, False otherwise
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Set correlation ID for logging (use PDF filename)
    set_correlation_id(pdf_path.stem)
    logger.info(f"Starting processing: {pdf_path}")

    # 1. Validate PDF input
    logger.info("Validating PDF...")
    validation = validate_pdf_input(str(pdf_path), max_size_mb=200)

    if not validation.is_valid:
        logger.error(f"Validation failed: {validation.errors}")
        for warning in validation.warnings:
            logger.warning(warning)
        return False

    logger.info(
        f"Validation passed: {validation.file_size_bytes / (1024*1024):.1f} MB, "
        f"hash={validation.file_hash[:12]}..."
    )
    for warning in validation.warnings:
        logger.warning(warning)

    # 2. Check processing cache
    cache = ProcessingCache(output_dir / ".ocr_cache.json")

    if skip_if_processed and cache.is_processed(validation.file_hash):
        cached_output = cache.get_output_path(validation.file_hash)
        logger.info(f"Already processed (cache hit): {cached_output}")
        return True

    # 3. Check disk space
    has_space, space_msg = check_disk_space(output_dir, required_mb=500)
    logger.info(f"Disk space check: {space_msg}")
    if not has_space:
        logger.error("Insufficient disk space")
        return False

    # 4. Process with Mistral OCR pipeline
    try:
        logger.info("Running Mistral OCR pipeline...")

        config = MistralPipelineConfig(
            output_dir=str(output_dir),
            save_raw_markdown=True,
            save_structured_json=True,
            save_html=True,
            pages_per_chunk=5,
            parallel=False,  # Set to True for parallel processing
            workers=4,
        )

        pipeline = MistralOCRPipeline(config)
        doc = pipeline.process(str(pdf_path))

        # Pipeline cleanup is handled in finally block of process()

        logger.info(f"Processing complete: {doc.metadata.total_pages} pages")

        # 5. Mark as processed in cache
        output_path = output_dir / f"{pdf_path.stem}.html"
        cache.mark_processed(
            file_hash=validation.file_hash,
            input_path=str(pdf_path),
            output_path=str(output_path),
            metadata={
                "title": doc.metadata.title,
                "pages": doc.metadata.total_pages,
                "language": doc.metadata.language,
            }
        )

        logger.info(f"Cached result: {validation.file_hash[:12]}...")
        return True

    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        return False


def process_directory_with_graceful_shutdown(
    pdf_dir: str,
    output_dir: str = "outputs"
):
    """
    Process all PDFs in a directory with graceful shutdown handling.

    Args:
        pdf_dir: Directory containing PDFs
        output_dir: Output directory
    """
    pdf_dir = Path(pdf_dir)
    pdf_files = sorted(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        logger.warning(f"No PDFs found in {pdf_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDFs to process")

    # Setup graceful shutdown
    shutdown_handler = GracefulShutdownHandler()
    shutdown_handler.setup()

    # Register cleanup callback
    def cleanup():
        logger.info("Graceful shutdown: cleaning up...")
        # Add any cleanup logic here (e.g., save partial results)

    shutdown_handler.register_cleanup(cleanup)

    # Process PDFs
    processed = 0
    failed = 0
    skipped = 0

    for pdf_path in pdf_files:
        if shutdown_handler.should_exit:
            logger.warning("Shutdown signal received, stopping processing")
            break

        logger.info(f"Processing {processed + 1}/{len(pdf_files)}: {pdf_path.name}")

        try:
            success = process_pdf_with_validation(
                str(pdf_path),
                output_dir=output_dir,
                skip_if_processed=True
            )

            if success:
                processed += 1
            else:
                failed += 1

        except KeyboardInterrupt:
            logger.warning("Interrupted by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            failed += 1

    # Summary
    logger.info(
        f"\n{'='*60}\n"
        f"  Processing Summary\n"
        f"  Total PDFs:  {len(pdf_files)}\n"
        f"  Processed:   {processed}\n"
        f"  Failed:      {failed}\n"
        f"  Interrupted: {len(pdf_files) - processed - failed}\n"
        f"{'='*60}"
    )


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Production OCR pipeline with validation and caching"
    )
    parser.add_argument(
        "input",
        help="PDF file or directory containing PDFs"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="outputs",
        help="Output directory (default: outputs/)"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable processing cache (reprocess all files)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    input_path = Path(args.input)

    if input_path.is_file():
        # Process single PDF
        success = process_pdf_with_validation(
            str(input_path),
            output_dir=args.output_dir,
            skip_if_processed=not args.no_cache
        )
        sys.exit(0 if success else 1)

    elif input_path.is_dir():
        # Process directory
        process_directory_with_graceful_shutdown(
            str(input_path),
            output_dir=args.output_dir
        )
        sys.exit(0)

    else:
        logger.error(f"Input not found: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
