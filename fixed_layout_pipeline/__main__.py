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


def cmd_searchable_pdf(args):
    """Generate a searchable PDF from a scanned PDF via Azure DI."""
    from .config import AzureConfig
    from .searchable_pdf import generate_searchable_pdf

    azure_cfg = AzureConfig()
    pdf_path = Path(args.pdf)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = pdf_path.with_stem(pdf_path.stem + "_searchable")

    generate_searchable_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        config=azure_cfg,
        pages=args.pages,
    )

    print(f"\nSearchable PDF: {output_path}")


def cmd_render(args):
    """Render fidelity/semantic/markdown from a searchable PDF or canonical JSON."""
    import logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    input_path = Path(args.input)
    output_dir = Path(args.output) if args.output else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem.replace("_searchable", "").replace("_canonical", "")

    # Load or build canonical document
    if input_path.suffix == ".pdf":
        from .spdf_to_canonical import searchable_pdf_to_canonical
        doc = searchable_pdf_to_canonical(
            input_path,
            target_dpi=args.dpi,
            page_images_dir=output_dir / "pages",
        )
        # Save the canonical JSON too
        json_path = output_dir / f"{stem}_canonical.json"
        doc.save(json_path)
        print(f"Canonical JSON: {json_path}")
    else:
        from .schema import CanonicalDocument
        doc = CanonicalDocument.load(input_path)

    from .dual_renderer import FidelityRenderer, SemanticRenderer, MarkdownRenderer

    # Fidelity HTML
    fid_html = FidelityRenderer(scale=1.0, show_tokens=args.tokens).render(doc)
    fid_path = output_dir / f"{stem}_fidelity.html"
    fid_path.write_text(fid_html, encoding="utf-8")
    print(f"Fidelity HTML:  {fid_path}")

    # Semantic HTML
    sem_html = SemanticRenderer().render(doc)
    sem_path = output_dir / f"{stem}_semantic.html"
    sem_path.write_text(sem_html, encoding="utf-8")
    print(f"Semantic HTML:  {sem_path}")

    # Markdown
    md_text = MarkdownRenderer().render(doc)
    md_path = output_dir / f"{stem}.md"
    md_path.write_text(md_text, encoding="utf-8")
    print(f"Markdown:       {md_path}")


def cmd_dual(args):
    """Run dual-call pipeline: searchable PDF + layout OCR in parallel."""
    import logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from .config import AzureConfig
    from .dual_call import dual_process

    azure_cfg = AzureConfig()
    pdf_path = Path(args.pdf)
    output_dir = Path(args.output) if args.output else Path("output") / pdf_path.stem

    doc, spdf_path, fid_path = dual_process(
        pdf_path=pdf_path,
        output_dir=output_dir,
        config=azure_cfg,
        dpi=args.dpi,
    )

    print(f"\nSearchable PDF: {spdf_path}")
    print(f"Fidelity HTML:  {fid_path}")
    print(f"Pages: {len(doc.pages)}, Blocks: {doc.total_blocks()}")


def cmd_batch(args):
    """Batch process scanned PDFs → searchable PDFs + OCR JSON."""
    import asyncio as _asyncio
    import os
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    from .batch_searchable import process_all_pdfs, print_summary
    import time as _time

    input_dir = Path(args.input)
    if not input_dir.exists():
        sys.exit(f"Input directory not found: {input_dir}")

    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if args.dry_run:
        print(f"\n[DRY RUN] {len(pdf_files)} PDFs → {args.output}/")
        for p in pdf_files:
            print(f"  {p.name}")
        return

    t0 = _time.time()
    results = _asyncio.run(
        process_all_pdfs(input_dir, Path(args.output), endpoint, api_key, args.workers)
    )
    print_summary(results)
    print(f"Wall time: {_time.time() - t0:.1f}s")


def cmd_pipeline(args):
    """Full pipeline: scanned PDFs → searchable PDF + OCR JSON + HTML in one shot."""
    import asyncio as _asyncio
    import os
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    from dotenv import load_dotenv
    load_dotenv()

    from .batch_pipeline import run_pipeline, print_summary
    import time as _time

    input_dir = Path(args.input)
    if not input_dir.exists():
        sys.exit(f"Input directory not found: {input_dir}")

    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if args.dry_run:
        print(f"\n[DRY RUN] {len(pdf_files)} PDFs → {args.output}/")
        print(f"  Mode: {args.mode} | DPI: {args.dpi} | Workers: {args.workers}")
        for p in pdf_files:
            print(f"  {p.name}")
        return

    t0 = _time.time()
    results = _asyncio.run(
        run_pipeline(
            input_dir, Path(args.output), endpoint, api_key,
            max_workers=args.workers, dpi=args.dpi, render_mode=args.mode,
        )
    )
    print_summary(results)
    print(f"Wall time: {_time.time() - t0:.1f}s")


def cmd_validate(args):
    """Validate searchable PDFs for corruption."""
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    from .validate_pdfs import validate_directory, print_summary

    input_dir = Path(args.input)
    if not input_dir.exists():
        sys.exit(f"Directory not found: {input_dir}")

    valid, corrupted, empty = validate_directory(input_dir, fix=args.fix)
    print_summary(valid, corrupted, empty)
    if corrupted or empty:
        sys.exit(1)


def cmd_gemini_html(args):
    """Generate fidelity HTML via Gemini classification."""
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    from .gemini_html import render
    import os

    pdf_path = Path(args.pdf)
    json_path = Path(args.json)
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")
    if not json_path.exists():
        sys.exit(f"JSON not found: {json_path}")

    output = Path(args.output) if args.output else (
        pdf_path.parent / f"{pdf_path.stem.replace('_searchable', '')}_gemini.html"
    )
    model = args.model or os.environ.get("MODEL_NAME", "gemini-2.0-flash")
    render(pdf_path, json_path, output, model=model, page_num=args.page,
           use_gemini=not args.no_gemini)


def cmd_render_read(args):
    """Render word-level fidelity HTML from prebuilt-read OCR JSON."""
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    from .read_html_renderer import render_directory

    input_dir = Path(args.input)
    if not input_dir.exists():
        sys.exit(f"Directory not found: {input_dir}")

    count = render_directory(input_dir, dpi=args.dpi, scale=args.scale)
    print(f"Rendered {count} document(s)")


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

    # ─── searchable-pdf ─────────────────────────────────────
    p_spdf = subparsers.add_parser(
        "searchable-pdf",
        help="Generate a searchable PDF from a scanned PDF (Azure DI prebuilt-read)",
    )
    p_spdf.add_argument("pdf", help="Path to the scanned PDF file")
    p_spdf.add_argument("-o", "--output", help="Output searchable PDF path")
    p_spdf.add_argument("--pages", help="Page range, e.g. '1-3' (1-based)")
    p_spdf.set_defaults(func=cmd_searchable_pdf)

    # ─── render ──────────────────────────────────────────────
    p_render = subparsers.add_parser(
        "render",
        help="Render fidelity/semantic/markdown from a searchable PDF or canonical JSON",
    )
    p_render.add_argument("input", help="Searchable PDF (.pdf) or canonical JSON (.json)")
    p_render.add_argument("-o", "--output", help="Output directory")
    p_render.add_argument("--dpi", type=int, default=300, help="Target DPI (default: 300)")
    p_render.add_argument("--tokens", action="store_true", help="Show token-level boxes")
    p_render.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p_render.set_defaults(func=cmd_render)

    # ─── dual ────────────────────────────────────────────────
    p_dual = subparsers.add_parser(
        "dual",
        help="2 parallel Azure calls: searchable PDF + layout OCR → fidelity HTML",
    )
    p_dual.add_argument("pdf", help="Path to the scanned PDF file")
    p_dual.add_argument("-o", "--output", help="Output directory")
    p_dual.add_argument("--dpi", type=int, default=300, help="Target DPI (default: 300)")
    p_dual.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p_dual.set_defaults(func=cmd_dual)

    # ─── batch ───────────────────────────────────────────
    p_batch = subparsers.add_parser(
        "batch",
        help="Batch convert scanned PDFs → searchable PDFs + OCR JSON",
    )
    p_batch.add_argument("-i", "--input", type=str, default="pdfs/2026/2026/scanned")
    p_batch.add_argument("-o", "--output", type=str, default="output_searchable")
    p_batch.add_argument("-w", "--workers", type=int, default=4)
    p_batch.add_argument("--dry-run", action="store_true")
    p_batch.set_defaults(func=cmd_batch)

    # ─── pipeline (unified) ──────────────────────────────────
    p_pipe = subparsers.add_parser(
        "pipeline",
        help="Full pipeline: scanned PDFs → searchable PDF + OCR JSON + HTML",
    )
    p_pipe.add_argument("-i", "--input", type=str, default="pdfs/2026/2026/scanned")
    p_pipe.add_argument("-o", "--output", type=str, default="output_final")
    p_pipe.add_argument("-w", "--workers", type=int, default=4)
    p_pipe.add_argument("--dpi", type=int, default=200, help="Rasterisation DPI (default: 200)")
    p_pipe.add_argument("--mode", choices=["replace-text", "overlay", "text-only"],
                        default="replace-text", help="HTML render mode (default: replace-text)")
    p_pipe.add_argument("--dry-run", action="store_true")
    p_pipe.set_defaults(func=cmd_pipeline)

    # ─── validate ────────────────────────────────────────────
    p_val = subparsers.add_parser("validate", help="Validate PDFs for corruption")
    p_val.add_argument("-i", "--input", type=str, default="output_searchable")
    p_val.add_argument("--fix", action="store_true", help="Attempt repair")
    p_val.set_defaults(func=cmd_validate)

    # ─── gemini-html ─────────────────────────────────────────
    p_gem = subparsers.add_parser(
        "gemini-html",
        help="Fidelity HTML with Gemini semantic classification",
    )
    p_gem.add_argument("--pdf", required=True, help="Searchable PDF")
    p_gem.add_argument("--json", required=True, help="OCR JSON")
    p_gem.add_argument("-o", "--output", help="Output HTML path")
    p_gem.add_argument("--model", help="Gemini model name")
    p_gem.add_argument("--page", type=int, help="Render single page")
    p_gem.add_argument("--no-gemini", action="store_true",
                       help="Skip Gemini — auto-classify only")
    p_gem.set_defaults(func=cmd_gemini_html)

    # ─── render-read ─────────────────────────────────────────
    p_rr = subparsers.add_parser(
        "render-read",
        help="Word-level fidelity HTML from prebuilt-read OCR JSON",
    )
    p_rr.add_argument("-i", "--input", type=str, default="output_read_test")
    p_rr.add_argument("--dpi", type=float, default=150)
    p_rr.add_argument("--scale", type=float, default=1.0)
    p_rr.set_defaults(func=cmd_render_read)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
