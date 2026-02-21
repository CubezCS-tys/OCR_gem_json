#!/usr/bin/env python3
"""
Core CLI for fixed-layout OCR processing.

Supported workflows:
1) searchable-pdf: scanned PDF -> searchable PDF + OCR JSON
2) render: searchable PDF + OCR JSON -> pixel-perfect HTML
3) pipeline: batch scanned PDFs -> searchable PDF + OCR JSON + HTML
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
    except ImportError:
        return
    load_dotenv()


def cmd_searchable_pdf(args: argparse.Namespace) -> None:
    from .config import AzureConfig
    from .searchable_pdf import generate_searchable_pdf

    _load_dotenv_if_available()
    cfg = AzureConfig()
    cfg.validate()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")

    stem = pdf_path.stem
    output_path = Path(args.output) if args.output else pdf_path.with_stem(f"{stem}_searchable")
    json_path = output_path.parent / f"{stem}_ocr.json"

    generate_searchable_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        config=cfg,
        pages=args.pages,
        output_json_path=json_path,
    )
    print(f"Searchable PDF: {output_path}")
    print(f"OCR JSON:       {json_path}")


def cmd_render(args: argparse.Namespace) -> None:
    from .overlay_renderer import process_single

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")

    if args.json:
        json_path = Path(args.json)
    else:
        stem = pdf_path.stem.replace("_searchable", "")
        json_path = pdf_path.parent / f"{stem}_ocr.json"

    if not json_path.exists():
        sys.exit(
            f"OCR JSON not found: {json_path}\n"
            "Run 'searchable-pdf' first."
        )

    stem = pdf_path.stem.replace("_searchable", "")
    output_dir = Path(args.output) if args.output else pdf_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    out_html = output_dir / f"{stem}_overlay.html"

    process_single(
        pdf_path=pdf_path,
        json_path=json_path,
        output_path=out_html,
        dpi=args.dpi,
        replace_text=(args.mode == "replace-text"),
        text_only=(args.mode == "text-only"),
    )
    print(f"HTML: {out_html}")


def cmd_pipeline(args: argparse.Namespace) -> None:
    from .batch_pipeline import print_summary, run_pipeline

    _load_dotenv_if_available()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    input_dir = Path(args.input)
    if not input_dir.exists():
        sys.exit(f"Input directory not found: {input_dir}")

    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in environment or .env")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if args.dry_run:
        print(f"[DRY RUN] {len(pdf_files)} PDFs -> {args.output}/")
        print(f"Mode={args.mode} DPI={args.dpi} Workers={args.workers}")
        for p in pdf_files:
            print(f"  {p.name}")
        return

    t0 = time.time()
    results = asyncio.run(
        run_pipeline(
            input_dir=input_dir,
            output_dir=Path(args.output),
            endpoint=endpoint,
            api_key=api_key,
            max_workers=args.workers,
            dpi=args.dpi,
            render_mode=args.mode,
        )
    )
    print_summary(results)
    print(f"Wall time: {time.time() - t0:.1f}s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixed-layout OCR core: searchable PDF + OCR JSON + pixel HTML",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_spdf = subparsers.add_parser(
        "searchable-pdf",
        help="Generate searchable PDF + OCR JSON from a scanned PDF",
    )
    p_spdf.add_argument("pdf", help="Path to scanned PDF")
    p_spdf.add_argument("-o", "--output", help="Output searchable PDF path")
    p_spdf.add_argument("--pages", help="Page range, e.g. '1-3' (1-based)")
    p_spdf.set_defaults(func=cmd_searchable_pdf)

    p_render = subparsers.add_parser(
        "render",
        help="Render pixel-perfect HTML from searchable PDF + OCR JSON",
    )
    p_render.add_argument("--pdf", required=True, help="Searchable PDF path")
    p_render.add_argument("--json", default=None, help="OCR JSON path (auto-derived if omitted)")
    p_render.add_argument("-o", "--output", help="Output directory")
    p_render.add_argument("--dpi", type=int, default=200, help="Rasterisation DPI")
    p_render.add_argument(
        "--mode",
        choices=["overlay", "replace-text", "text-only"],
        default="replace-text",
        help="Render mode",
    )
    p_render.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p_render.set_defaults(func=cmd_render)

    p_pipe = subparsers.add_parser(
        "pipeline",
        help="Batch scanned PDFs -> searchable PDF + OCR JSON + HTML",
    )
    p_pipe.add_argument("-i", "--input", type=str, default="pdfs/2026/2026/scanned")
    p_pipe.add_argument("-o", "--output", type=str, default="output_final")
    p_pipe.add_argument("-w", "--workers", type=int, default=4)
    p_pipe.add_argument("--dpi", type=int, default=200)
    p_pipe.add_argument(
        "--mode",
        choices=["replace-text", "overlay", "text-only"],
        default="replace-text",
    )
    p_pipe.add_argument("--dry-run", action="store_true")
    p_pipe.set_defaults(func=cmd_pipeline)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except Exception as exc:
        if getattr(args, "verbose", False):
            raise
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
