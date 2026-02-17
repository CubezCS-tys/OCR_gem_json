"""
Batch Searchable PDF Generator (Async + Parallel).

Processes all PDFs in an input directory through Azure Document Intelligence
``prebuilt-read`` and saves:
  1. A searchable PDF (invisible text layer behind page images)
  2. The OCR JSON (words, lines, bounding boxes — free with the call)

Usage (standalone):
    python -m fixed_layout_pipeline batch --input pdfs/scanned --output output_searchable
    python -m fixed_layout_pipeline batch --dry-run

Usage (library):
    from fixed_layout_pipeline.batch_searchable import process_all_pdfs
    results = asyncio.run(process_all_pdfs(input_dir, output_dir, endpoint, api_key))
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

# Thread-local Azure clients
_thread_clients: dict[int, object] = {}


def _get_client(endpoint: str, api_key: str):
    """Return a thread-local Azure DI client."""
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    tid = threading.get_ident()
    if tid not in _thread_clients:
        _thread_clients[tid] = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )
    return _thread_clients[tid]


def process_one_pdf(
    pdf_path: Path,
    output_dir: Path,
    endpoint: str,
    api_key: str,
) -> dict:
    """
    Send one PDF to Azure ``prebuilt-read`` and save both the searchable
    PDF and the analysis JSON.

    Returns a result dict: ``{file, status, pages?, size_kb?, elapsed_s?, error?}``.
    """
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )

    stem = pdf_path.stem
    doc_folder = output_dir / stem
    doc_folder.mkdir(parents=True, exist_ok=True)
    out_pdf = doc_folder / f"{stem}_searchable.pdf"
    out_json = doc_folder / f"{stem}_ocr.json"

    # Skip if both outputs already exist
    if (out_pdf.exists() and out_pdf.stat().st_size > 0
            and out_json.exists() and out_json.stat().st_size > 0):
        logger.info("⏭  Skipping (exists): %s", stem)
        return {"file": stem, "status": "skipped", "reason": "already exists"}

    start = time.time()
    try:
        pdf_bytes = pdf_path.read_bytes()
        logger.info("📤 %s (%.1f KB) → Azure prebuilt-read…", stem, len(pdf_bytes) / 1024)

        client = _get_client(endpoint, api_key)
        poller = client.begin_analyze_document(
            model_id="prebuilt-read",
            body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
            output=[AnalyzeOutputOption.PDF],
        )
        result = poller.result()
        op_id = poller.details["operation_id"]
        n_pages = len(result.pages) if result.pages else 0

        # Save OCR JSON
        json_mod.dump(
            result.as_dict(), open(out_json, "w", encoding="utf-8"),
            ensure_ascii=False, indent=2,
        )

        # Download searchable PDF
        stream = client.get_analyze_result_pdf(
            model_id=result.model_id, result_id=op_id,
        )
        written = 0
        with open(out_pdf, "wb") as f:
            for chunk in stream:
                f.write(chunk)
                written += len(chunk)

        elapsed = time.time() - start
        logger.info("✅ %s → %d pages, %.1f KB, %.1fs", stem, n_pages, written / 1024, elapsed)
        return {
            "file": stem, "status": "success",
            "pages": n_pages, "size_kb": round(written / 1024, 1),
            "elapsed_s": round(elapsed, 1),
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error("❌ %s failed (%.1fs): %s", stem, elapsed, e)
        return {"file": stem, "status": "error", "error": str(e), "elapsed_s": round(elapsed, 1)}


async def process_all_pdfs(
    input_dir: Path,
    output_dir: Path,
    endpoint: str,
    api_key: str,
    max_workers: int = 4,
) -> list[dict]:
    """Process every PDF in *input_dir* in parallel (ThreadPoolExecutor)."""
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDFs in %s", input_dir)
        return []

    logger.info("%d PDFs in %s — %d workers", len(pdf_files), input_dir, max_workers)
    output_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(max_workers)

    async def _bounded(p: Path) -> dict:
        async with sem:
            return await loop.run_in_executor(
                executor, process_one_pdf, p, output_dir, endpoint, api_key,
            )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = await asyncio.gather(
            *[_bounded(p) for p in pdf_files], return_exceptions=True,
        )

    final = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            final.append({"file": pdf_files[i].stem, "status": "error", "error": str(r)})
        else:
            final.append(r)
    return final


def print_summary(results: list[dict]) -> None:
    """Pretty-print a summary table."""
    ok = [r for r in results if r["status"] == "success"]
    skipped = [r for r in results if r["status"] == "skipped"]
    errors = [r for r in results if r["status"] == "error"]
    pages = sum(r.get("pages", 0) for r in ok)
    secs = sum(r.get("elapsed_s", 0) for r in ok)

    print("\n" + "=" * 60)
    print("          BATCH SEARCHABLE PDF — SUMMARY")
    print("=" * 60)
    print(f"  Total:   {len(results)}")
    print(f"  ✅ OK:    {len(ok)}  ({pages} pages, {secs:.1f}s)")
    print(f"  ⏭  Skip:  {len(skipped)}")
    print(f"  ❌ Fail:  {len(errors)}")
    if pages:
        print(f"\n  💰 Cost: ${pages * 1.50 / 1000:.4f}  (prebuilt-read @ $1.50/1K)")
    if errors:
        print("\n  Failed:")
        for r in errors:
            print(f"    - {r['file']}: {r.get('error', '?')}")
    print("=" * 60 + "\n")
