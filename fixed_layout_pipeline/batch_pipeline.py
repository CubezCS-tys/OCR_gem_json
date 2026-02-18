"""
Unified Batch Pipeline: Scanned PDF → Searchable PDF + OCR JSON + HTML

One Azure API call per document (prebuilt-read @ $1.50/1K pages) produces:
  1. Searchable PDF (invisible text layer)
  2. OCR JSON (words, lines, bounding boxes)
  3. Replace-text HTML (scan image with text erased + clean rendered text)

All three outputs land in a per-document subfolder.

Usage:
    python -m fixed_layout_pipeline pipeline \\
        --input pdfs/2026/2026/scanned \\
        --output output_final \\
        --workers 4

    python -m fixed_layout_pipeline pipeline --dry-run
"""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Thread-local Azure clients ────────────────────────────────────────────────

_thread_clients: dict[int, object] = {}


def _get_client(endpoint: str, api_key: str):
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    tid = threading.get_ident()
    if tid not in _thread_clients:
        _thread_clients[tid] = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )
    return _thread_clients[tid]


# ── Single-document pipeline ─────────────────────────────────────────────────

def process_one(
    pdf_path: Path,
    output_dir: Path,
    endpoint: str,
    api_key: str,
    dpi: int = 200,
    render_mode: str = "replace-text",
) -> dict:
    """
    Full pipeline for one PDF:
      1. Azure prebuilt-read → searchable PDF + OCR JSON  (API call)
      2. overlay_renderer → HTML                          (local)

    Returns a result dict with status, pages, cost, timings, etc.
    """
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )

    stem = pdf_path.stem
    doc_folder = output_dir / stem
    doc_folder.mkdir(parents=True, exist_ok=True)

    out_pdf  = doc_folder / f"{stem}_searchable.pdf"
    out_json = doc_folder / f"{stem}_ocr.json"
    out_html = doc_folder / f"{stem}_{render_mode.replace('-', '_')}.html"

    # ── Skip if all three outputs exist ──────────────────────────────────
    if (out_pdf.exists() and out_pdf.stat().st_size > 0
            and out_json.exists() and out_json.stat().st_size > 0
            and out_html.exists() and out_html.stat().st_size > 0):
        logger.info("⏭  Skipping (exists): %s", stem)
        return {"file": stem, "status": "skipped", "reason": "all outputs exist"}

    start = time.time()
    n_pages = 0
    api_elapsed = 0.0

    # ── Step 1: Azure API (only if PDF or JSON missing) ──────────────────
    need_api = not (
        out_pdf.exists() and out_pdf.stat().st_size > 0
        and out_json.exists() and out_json.stat().st_size > 0
    )

    if need_api:
        try:
            pdf_bytes = pdf_path.read_bytes()
            logger.info(
                "📤 %s (%.1f KB) → Azure prebuilt-read …",
                stem, len(pdf_bytes) / 1024,
            )

            client = _get_client(endpoint, api_key)
            api_start = time.time()
            poller = client.begin_analyze_document(
                model_id="prebuilt-read",
                body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
                output=[AnalyzeOutputOption.PDF],
            )
            result = poller.result()
            op_id = poller.details["operation_id"]
            n_pages = len(result.pages) if result.pages else 0
            api_elapsed = time.time() - api_start

            # Save OCR JSON
            with open(out_json, "w", encoding="utf-8") as f:
                json_mod.dump(result.as_dict(), f, ensure_ascii=False, indent=2)

            # Download searchable PDF
            stream = client.get_analyze_result_pdf(
                model_id=result.model_id, result_id=op_id,
            )
            written = 0
            with open(out_pdf, "wb") as f:
                for chunk in stream:
                    f.write(chunk)
                    written += len(chunk)

            logger.info(
                "✅ %s → %d pages, %.1f KB PDF, %.1fs API",
                stem, n_pages, written / 1024, api_elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start
            logger.error("❌ %s Azure failed (%.1fs): %s", stem, elapsed, e)
            return {
                "file": stem, "status": "error", "error": str(e),
                "elapsed_s": round(elapsed, 1),
            }
    else:
        # Count pages from existing JSON
        try:
            ocr = json_mod.loads(out_json.read_text(encoding="utf-8"))
            n_pages = len(ocr.get("pages", []))
        except Exception:
            n_pages = 0
        logger.info("⏭  %s Azure outputs exist — skipping API call", stem)

    # ── Step 2: Render HTML (local, fast) ────────────────────────────────
    try:
        from .overlay_renderer import render_document

        render_start = time.time()
        html_str = render_document(
            out_pdf, out_json, dpi=dpi,
            replace_text=(render_mode == "replace-text"),
            text_only=(render_mode == "text-only"),
        )
        out_html.write_text(html_str, encoding="utf-8")
        render_elapsed = time.time() - render_start

        logger.info(
            "🖨  %s → %s (%.1f KB, %.1fs render)",
            stem, out_html.name, out_html.stat().st_size / 1024, render_elapsed,
        )
    except Exception as e:
        elapsed = time.time() - start
        logger.error("❌ %s HTML render failed (%.1fs): %s", stem, elapsed, e)
        return {
            "file": stem, "status": "error", "error": f"render: {e}",
            "pages": n_pages, "elapsed_s": round(elapsed, 1),
        }

    elapsed = time.time() - start
    return {
        "file": stem,
        "status": "success",
        "pages": n_pages,
        "api_s": round(api_elapsed, 1),
        "render_s": round(render_elapsed, 1),
        "elapsed_s": round(elapsed, 1),
        "pdf_kb": round(out_pdf.stat().st_size / 1024, 1),
        "html_kb": round(out_html.stat().st_size / 1024, 1),
    }


# ── Batch runner ──────────────────────────────────────────────────────────────

async def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    endpoint: str,
    api_key: str,
    max_workers: int = 4,
    dpi: int = 200,
    render_mode: str = "replace-text",
) -> list[dict]:
    """Process every PDF in *input_dir* in parallel."""
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDFs in %s", input_dir)
        return []

    logger.info(
        "📂 %d PDFs in %s → %s (%d workers, %s mode)",
        len(pdf_files), input_dir, output_dir, max_workers, render_mode,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(max_workers)

    async def _bounded(p: Path) -> dict:
        async with sem:
            return await loop.run_in_executor(
                executor,
                process_one, p, output_dir, endpoint, api_key, dpi, render_mode,
            )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = await asyncio.gather(
            *[_bounded(p) for p in pdf_files], return_exceptions=True,
        )

    final = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            final.append({
                "file": pdf_files[i].stem, "status": "error", "error": str(r),
            })
        else:
            final.append(r)
    return final


# ── Summary ───────────────────────────────────────────────────────────────────

COST_PER_PAGE = 1.50 / 1000  # $1.50 per 1K pages


def print_summary(results: list[dict]) -> None:
    ok      = [r for r in results if r["status"] == "success"]
    skipped = [r for r in results if r["status"] == "skipped"]
    errors  = [r for r in results if r["status"] == "error"]

    total_pages = sum(r.get("pages", 0) for r in ok)
    total_api   = sum(r.get("api_s", 0) for r in ok)
    total_render = sum(r.get("render_s", 0) for r in ok)
    total_time  = sum(r.get("elapsed_s", 0) for r in ok)
    cost = total_pages * COST_PER_PAGE

    print()
    print("=" * 64)
    print("        UNIFIED BATCH PIPELINE — SUMMARY")
    print("=" * 64)
    print(f"  Documents: {len(results)}")
    print(f"  ✅ Success:  {len(ok)}")
    print(f"  ⏭  Skipped:  {len(skipped)}")
    print(f"  ❌ Failed:   {len(errors)}")
    print()
    if ok:
        print(f"  📄 Pages processed:  {total_pages}")
        print(f"  ☁️  API time (sum):   {total_api:.1f}s")
        print(f"  🖨  Render time (sum): {total_render:.1f}s")
        print(f"  ⏱  Total time (sum):  {total_time:.1f}s")
        print()
        print(f"  💰 Azure cost:  ${cost:.4f}")
        print(f"     (prebuilt-read @ $1.50 / 1K pages)")
    if errors:
        print()
        print("  Failed documents:")
        for r in errors:
            print(f"    ❌ {r['file']}: {r.get('error', '?')}")
    print()
    print("  Output per document:")
    print("    {stem}_searchable.pdf   — searchable PDF")
    print("    {stem}_ocr.json         — OCR bounding boxes")
    print("    {stem}_replace_text.html — rendered HTML")
    print("=" * 64)
    print()
