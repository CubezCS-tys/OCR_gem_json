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
    _load_dotenv_if_available()
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

    if args.formulas:
        from .overlay_renderer import render_document_with_formulas
        out_html = output_dir / f"{stem}_formulas.html"
        html_str = render_document_with_formulas(
            pdf_path, json_path,
            dpi=args.dpi,
            replace_text=(args.mode == "replace-text"),
        )
        out_html.write_text(html_str, encoding="utf-8")
    else:
        from .overlay_renderer import process_single
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
        print(f"Mode={args.mode} DPI={args.dpi} Workers={args.workers} Formulas={args.formulas}")
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
            formulas=args.formulas,
        )
    )
    print_summary(results)
    print(f"Wall time: {time.time() - t0:.1f}s")


def cmd_gemini_enhance(args: argparse.Namespace) -> None:
    """
    Hybrid structural pipeline: Azure geometry + Gemini structural extraction
    (text + equations) + Azure prebuilt-layout tables + fuzzy merge → HTML.

    Steps
    -----
    1. Azure prebuilt-read  → searchable PDF + OCR JSON (line-level bboxes)
    2. In parallel:
       2a. Gemini structural → per-page text lines + LaTeX equations
       2b. Azure prebuilt-layout → tables with rowspan/colspan (unless
           --no-layout is passed, which falls back to geometric detector)
    3. Structural merge     → Azure lines fuzzy-merged with Gemini text,
                              table/equation regions suppressed + attached
    4. Save enhanced JSON   → <stem>_enhanced_ocr.json
    5. Render HTML          → <stem>_enhanced_overlay.html  (unless --no-render)
    """
    import json as _json
    from concurrent.futures import ThreadPoolExecutor

    from .azure_layout_tables import extract_layout_tables
    from .config import AzureConfig, GeminiConfig
    from .fuzzy_text_merger import merge_structural_into_azure_json
    from .gemini_structural_extractor import extract_structural_from_pdf
    from .searchable_pdf import generate_searchable_pdf

    _load_dotenv_if_available()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")

    output_dir = Path(args.output) if args.output else pdf_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    searchable_pdf_path = output_dir / f"{stem}_searchable.pdf"
    azure_json_path     = output_dir / f"{stem}_ocr.json"
    enhanced_json_path  = output_dir / f"{stem}_enhanced_ocr.json"

    # ── 1. Azure prebuilt-read ────────────────────────────────────────────────
    azure_cfg = AzureConfig()
    try:
        azure_cfg.validate()
    except ValueError as exc:
        sys.exit(f"Azure config error: {exc}")

    print(f"[1/4] Azure prebuilt-read: {pdf_path.name} …")
    generate_searchable_pdf(
        pdf_path=pdf_path,
        output_path=searchable_pdf_path,
        config=azure_cfg,
        pages=args.pages,
        output_json_path=azure_json_path,
    )
    print(f"      Searchable PDF : {searchable_pdf_path}")
    print(f"      Azure OCR JSON : {azure_json_path}")

    # Load the Azure result dict that was just saved
    with open(azure_json_path, encoding="utf-8") as jf:
        azure_result: dict = _json.load(jf)

    page_count = len(azure_result.get("pages", []))
    pdf_bytes = pdf_path.read_bytes()

    # ── 2. Gemini structural extraction + Azure prebuilt-layout (parallel) ────
    gemini_cfg = GeminiConfig()
    try:
        gemini_cfg.validate()
    except ValueError as exc:
        sys.exit(f"Gemini config error: {exc}")

    try:
        import google.genai as genai  # noqa: PLC0415
        gemini_client = genai.Client(api_key=gemini_cfg.api_key)
    except ImportError:
        sys.exit("google-genai package not installed. Run: pip install google-genai")

    workers = getattr(args, "gemini_workers", 1) or 1
    no_tables = getattr(args, "no_tables", False)
    use_layout = not getattr(args, "no_layout", False) and not no_tables

    if no_tables:
        print(f"[2/4] Gemini structural extraction ({page_count} pages, "
              f"{workers} workers) … [tables disabled — text only]")
    elif use_layout:
        print(f"[2/4] Gemini extraction ({page_count} pages, {workers} workers) "
              f"+ Azure prebuilt-layout tables (parallel) …")
    else:
        print(f"[2/4] Gemini structural extraction ({page_count} pages, "
              f"{workers} workers) … [geometric table detector]")

    def _run_gemini() -> list[dict]:
        return extract_structural_from_pdf(
            pdf_path=pdf_path,
            client=gemini_client,
            model=gemini_cfg.model,
            expected_pages=page_count,
            page_batch_size=args.page_batch_size,
            max_workers=workers,
            include_equations=not no_tables,
        )

    def _run_layout() -> list[list[dict]]:
        return extract_layout_tables(
            pdf_bytes=pdf_bytes,
            endpoint=azure_cfg.endpoint,
            api_key=azure_cfg.api_key,
            pages=args.pages,
        )

    layout_tables: list[list[dict]] | None = None

    if no_tables:
        # layout_tables=None so the merger's geometric detector finds table
        # regions for protection (keep Azure cell text, skip Gemini replacement).
        layout_tables = None
        gemini_pages = _run_gemini()
    elif use_layout:
        with ThreadPoolExecutor(max_workers=2) as pool:
            gem_future = pool.submit(_run_gemini)
            lay_future = pool.submit(_run_layout)
            gemini_pages = gem_future.result()
            try:
                layout_tables = lay_future.result()
                n_layout = sum(len(p) for p in layout_tables)
                print(f"      prebuilt-layout: {n_layout} table(s) extracted")
            except Exception as lay_exc:
                print(f"      WARNING: prebuilt-layout failed ({lay_exc}); "
                      "falling back to geometric table detector")
                layout_tables = None
    else:
        gemini_pages = _run_gemini()

    if not gemini_pages:
        sys.exit("Gemini structural extraction returned no results — aborting.")

    n_lines = sum(len(p.get("lines", [])) for p in gemini_pages)
    n_eqs = sum(len(p.get("equations", [])) for p in gemini_pages)
    print(f"      Gemini: {len(gemini_pages)} pages, {n_lines} text lines, "
          f"{n_eqs} equations")

    # ── 3. Structural merge ───────────────────────────────────────────────────
    if no_tables:
        tbl_source = "none (text only)"
    elif layout_tables is not None:
        tbl_source = "prebuilt-layout"
    else:
        tbl_source = "geometric detector"
    print(f"[3/4] Structural merge (tables: {tbl_source}) …")
    enhanced = merge_structural_into_azure_json(
        azure_result,
        gemini_pages,
        min_similarity=args.min_similarity,
        layout_tables_by_page=layout_tables,
        inject_unmatched=not no_tables,
        protect_table_lines=no_tables,
    )

    with open(enhanced_json_path, "w", encoding="utf-8") as jf:
        _json.dump(enhanced, jf, ensure_ascii=False, indent=2)
    print(f"      Enhanced OCR JSON: {enhanced_json_path}")

    # ── 4. Render HTML ─────────────────────────────────────────────────────────
    if args.no_render:
        print("[4/4] Skipping HTML render (--no-render)")
        return

    from .overlay_renderer import render_document_structural  # noqa: PLC0415

    out_html = output_dir / f"{stem}_enhanced_overlay.html"
    print(f"[4/4] Rendering structural HTML …")
    html_str = render_document_structural(
        pdf_path=searchable_pdf_path,
        ocr_json_path=enhanced_json_path,
        dpi=args.dpi,
        replace_text=(args.mode == "replace-text"),
    )
    out_html.write_text(html_str, encoding="utf-8")
    print(f"      HTML: {out_html}")


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
    p_render.add_argument(
        "--formulas",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Render Azure formulas as MathJax (default: enabled)",
    )
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
    p_pipe.add_argument(
        "--formulas",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable Azure FORMULAS add-on (default: enabled)",
    )
    p_pipe.set_defaults(func=cmd_pipeline)

    p_enhance = subparsers.add_parser(
        "gemini-enhance",
        help=(
            "Hybrid structural: Azure bboxes + Gemini text/tables/equations "
            "→ enhanced HTML.  Runs Azure prebuilt-read then Gemini structural "
            "extraction, fuzzy-merges text, and renders tables + equations natively."
        ),
    )
    p_enhance.add_argument("pdf", help="Path to scanned PDF")
    p_enhance.add_argument("-o", "--output", help="Output directory (default: same as PDF)")
    p_enhance.add_argument("--pages", help="Azure page range, e.g. '1-5' (1-based)")
    p_enhance.add_argument(
        "--min-similarity",
        type=float,
        default=58.0,
        dest="min_similarity",
        help="Fuzzy match threshold 0-100 (default: 58)",
    )
    p_enhance.add_argument("--dpi", type=int, default=200, help="Rasterisation DPI (default: 200)")
    p_enhance.add_argument(
        "--mode",
        choices=["overlay", "replace-text"],
        default="replace-text",
        help="HTML render mode (default: replace-text)",
    )
    p_enhance.add_argument(
        "--page-batch-size",
        type=int,
        default=4,
        dest="page_batch_size",
        help="Max pages per Gemini call — lower is more reliable for "
             "dense docs with tables/equations (default: 4)",
    )
    p_enhance.add_argument(
        "--gemini-workers",
        type=int,
        default=1,
        dest="gemini_workers",
        help="Parallel Gemini calls for multi-page docs. Set equal to "
             "page_count/batch_size for max parallelism (default: 1)",
    )
    p_enhance.add_argument(
        "--no-render",
        action="store_true",
        help="Skip HTML rendering; only produce the enhanced OCR JSON",
    )
    p_enhance.add_argument(
        "--no-layout",
        action="store_true",
        dest="no_layout",
        help="Skip Azure prebuilt-layout table call; use geometric table "
             "detector instead (cheaper but less accurate)",
    )
    p_enhance.add_argument(
        "--no-tables",
        action="store_true",
        dest="no_tables",
        help="Disable all table detection and rendering; table content is "
             "kept as ordinary text lines (simplest output)",
    )
    p_enhance.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p_enhance.set_defaults(func=cmd_gemini_enhance)

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
