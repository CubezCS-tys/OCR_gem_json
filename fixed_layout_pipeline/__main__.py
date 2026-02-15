#!/usr/bin/env python3
"""
CLI entry point for the Fixed-Layout OCR Pipeline.

Usage:
    # Process a PDF (full pipeline)
    python -m fixed_layout_pipeline process document.pdf --output ./output

    # Process with debug mode (visible bounding boxes)
    python -m fixed_layout_pipeline process document.pdf --debug

    # Regenerate HTML from canonical JSON (after manual edits)
    python -m fixed_layout_pipeline regenerate output/doc_canonical.json

    # Show document info from canonical JSON
    python -m fixed_layout_pipeline info output/doc_canonical.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path


def cmd_process(args):
    """Run the full pipeline on a PDF."""
    from .config import PipelineConfig
    from .pipeline import Pipeline

    config = PipelineConfig.from_env()
    config.raster.dpi = args.dpi
    config.renderer.debug_boxes = args.debug
    config.log_level = "DEBUG" if args.verbose else "INFO"

    if args.output:
        config.output_dir = Path(args.output)

    if args.no_preprocess:
        config.preprocess.deskew = False
        config.preprocess.denoise = False
        config.preprocess.auto_orient = False

    pipeline = Pipeline(config)

    page_range = None
    if args.pages:
        parts = args.pages.split("-")
        page_range = (int(parts[0]), int(parts[1]) + 1)

    doc, html_path = pipeline.process(
        args.pdf,
        page_range=page_range,
    )

    print(f"\nDone. HTML: {html_path}")
    print(json.dumps(doc.summary(), indent=2, ensure_ascii=False))


def cmd_regenerate(args):
    """Regenerate HTML from canonical JSON."""
    from .config import PipelineConfig
    from .pipeline import Pipeline

    config = PipelineConfig.from_env()
    config.renderer.debug_boxes = args.debug

    pipeline = Pipeline(config)
    output = pipeline.regenerate_html(
        args.json_file,
        args.output,
    )
    print(f"Regenerated: {output}")


def cmd_info(args):
    """Show document info from canonical JSON."""
    from .schema import CanonicalDocument

    doc = CanonicalDocument.load(Path(args.json_file))
    summary = doc.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.verbose:
        for page in doc.pages:
            print(f"\n--- Page {page.page_index + 1} ---")
            print(f"  Direction: {page.principal_direction.value}")
            print(f"  Blocks: {len(page.blocks)}")
            print(f"  Tables: {len(page.tables)}")
            print(f"  Reading order: {page.reading_order.method.value} "
                  f"(conf={page.reading_order.confidence:.2f})")
            for block in page.blocks_in_reading_order():
                text = block.full_text()[:60].replace("\n", " ")
                print(f"    [{block.block_type.value}] {block.block_id}: "
                      f"({block.bbox.x0:.0f},{block.bbox.y0:.0f}) "
                      f"conf={block.confidence:.2f} "
                      f'"{text}..."')


def main():
    parser = argparse.ArgumentParser(
        description="Fixed-Layout OCR Pipeline: scanned PDFs → pixel-accurate HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ─── process ─────────────────────────────────────────────
    p_process = subparsers.add_parser("process", help="Process a PDF file")
    p_process.add_argument("pdf", help="Path to the PDF file")
    p_process.add_argument("-o", "--output", help="Output directory")
    p_process.add_argument("--dpi", type=int, default=300, help="Rasterisation DPI (default: 300)")
    p_process.add_argument("--debug", action="store_true", help="Enable debug bounding boxes")
    p_process.add_argument("--pages", help="Page range, e.g. '0-5'")
    p_process.add_argument("--no-preprocess", action="store_true", help="Skip preprocessing")
    p_process.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p_process.set_defaults(func=cmd_process)

    # ─── regenerate ──────────────────────────────────────────
    p_regen = subparsers.add_parser("regenerate", help="Regenerate HTML from canonical JSON")
    p_regen.add_argument("json_file", help="Path to canonical JSON")
    p_regen.add_argument("-o", "--output", help="Output HTML path")
    p_regen.add_argument("--debug", action="store_true", help="Enable debug bounding boxes")
    p_regen.set_defaults(func=cmd_regenerate)

    # ─── info ────────────────────────────────────────────────
    p_info = subparsers.add_parser("info", help="Show document info from canonical JSON")
    p_info.add_argument("json_file", help="Path to canonical JSON")
    p_info.add_argument("-v", "--verbose", action="store_true", help="Show per-page details")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
