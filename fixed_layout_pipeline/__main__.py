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

    # Run QA report
    python -m fixed_layout_pipeline qa output/doc_canonical.json
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

    if args.llm_enrich:
        config.llm.enabled = True

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


def cmd_render(args):
    """Generate dual-output HTML + Markdown from canonical JSON."""
    from pathlib import Path
    from .dual_renderer import render_all, FidelityRenderer, SemanticRenderer, MarkdownRenderer
    from .schema import CanonicalDocument

    json_path = Path(args.json_file)
    output_dir = Path(args.output) if args.output else json_path.parent

    which = set(args.which.split(",")) if args.which else {"all"}

    doc = CanonicalDocument.load(json_path)
    stem = json_path.stem.replace("_canonical", "")
    output_dir.mkdir(parents=True, exist_ok=True)

    if "all" in which or "fidelity" in which:
        path = output_dir / f"{stem}_fidelity.html"
        html = FidelityRenderer(scale=args.scale, show_tokens=args.tokens).render(doc)
        path.write_text(html, encoding="utf-8")
        print(f"  Fidelity → {path}")

    if "all" in which or "semantic" in which:
        path = output_dir / f"{stem}_semantic.html"
        html = SemanticRenderer().render(doc)
        path.write_text(html, encoding="utf-8")
        print(f"  Semantic → {path}")

    if "all" in which or "markdown" in which:
        path = output_dir / f"{stem}.md"
        md = MarkdownRenderer().render(doc)
        path.write_text(md, encoding="utf-8")
        print(f"  Markdown → {path}")

    print("Done.")


def cmd_qa(args):
    """Run QA report on a canonical JSON."""
    from .schema import CanonicalDocument
    from .qa_evaluation import generate_qa_report, flag_low_confidence

    doc = CanonicalDocument.load(Path(args.json_file))

    gt_doc = None
    if args.ground_truth:
        gt_doc = CanonicalDocument.load(Path(args.ground_truth))

    report = generate_qa_report(
        doc, gt_doc,
        confidence_threshold=args.threshold,
    )
    print(report.summary())

    if args.verbose and report.low_confidence_blocks:
        print(f"\n--- Low confidence items (< {args.threshold}) ---")
        for item in report.low_confidence_blocks[:20]:
            print(f"  Page {item['page']}: {item.get('text', item.get('text_preview', ''))[:50]} "
                  f"(conf={item['confidence']:.2f})")


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
    p_process.add_argument("--llm-enrich", action="store_true", help="Enable LLM reading order repair")
    p_process.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p_process.set_defaults(func=cmd_process)

    # ─── regenerate ──────────────────────────────────────────
    p_regen = subparsers.add_parser("regenerate", help="Regenerate HTML from canonical JSON")
    p_regen.add_argument("json_file", help="Path to canonical JSON")
    p_regen.add_argument("-o", "--output", help="Output HTML path")
    p_regen.add_argument("--debug", action="store_true", help="Enable debug bounding boxes")
    p_regen.set_defaults(func=cmd_regenerate)

    # ─── render ───────────────────────────────────────────────
    p_render = subparsers.add_parser("render", help="Generate fidelity HTML, semantic HTML, and Markdown")
    p_render.add_argument("json_file", help="Path to canonical JSON")
    p_render.add_argument("-o", "--output", help="Output directory (default: same as JSON)")
    p_render.add_argument("--which", default="all",
                          help="Which outputs: all, fidelity, semantic, markdown (comma-separated)")
    p_render.add_argument("--scale", type=float, default=1.0, help="Scale factor (default: 1.0)")
    p_render.add_argument("--tokens", action="store_true", help="Include token overlay in fidelity HTML")
    p_render.set_defaults(func=cmd_render)

    # ─── info ────────────────────────────────────────────────
    p_info = subparsers.add_parser("info", help="Show document info from canonical JSON")
    p_info.add_argument("json_file", help="Path to canonical JSON")
    p_info.add_argument("-v", "--verbose", action="store_true", help="Show per-page details")
    p_info.set_defaults(func=cmd_info)

    # ─── qa ──────────────────────────────────────────────────
    p_qa = subparsers.add_parser("qa", help="Run QA evaluation report")
    p_qa.add_argument("json_file", help="Path to canonical JSON")
    p_qa.add_argument("--ground-truth", help="Path to ground truth canonical JSON")
    p_qa.add_argument("--threshold", type=float, default=0.80, help="Confidence threshold (default: 0.80)")
    p_qa.add_argument("-v", "--verbose", action="store_true", help="Show low confidence details")
    p_qa.set_defaults(func=cmd_qa)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
