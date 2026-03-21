#!/usr/bin/env python3
"""
Process all PDFs in a batch01 subfolder using Azure-only fixed_layout_pipeline.

Outputs: searchable PDF, OCR JSON, replace-text HTML — all with clean names
in per-document subfolders under output/.

Usage:
    python run_batch.py 0046
    python run_batch.py 0046 --workers 6

Runs in parallel with 4 workers by default.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ── Setup ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DPI = 300
MAX_RETRIES = 3
RETRY_DELAY = 15  # seconds between retries

# ── Thread-local Azure clients ──────────────────────────────────────────────

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


# ── Single-document processing ──────────────────────────────────────────────

def process_one(pdf_path: Path, output_dir: Path, endpoint: str, api_key: str) -> dict:
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )
    from fixed_layout_pipeline.overlay_renderer import render_document

    stem = pdf_path.stem
    doc_folder = output_dir / stem
    doc_folder.mkdir(parents=True, exist_ok=True)
    out_pdf  = doc_folder / f"{stem}.pdf"
    out_json = doc_folder / f"{stem}.json"
    out_html = doc_folder / f"{stem}.html"

    # Skip if all three outputs already exist
    if (out_pdf.exists() and out_pdf.stat().st_size > 0
            and out_json.exists() and out_json.stat().st_size > 0
            and out_html.exists() and out_html.stat().st_size > 0):
        logger.info("⏭  Skipping (exists): %s", stem)
        return {"file": stem, "status": "skipped"}

    start = time.time()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            pdf_bytes = pdf_path.read_bytes()
            client = _get_client(endpoint, api_key)

            # ── Single call: prebuilt-read → searchable PDF + OCR JSON ──
            need_pdf  = not (out_pdf.exists()  and out_pdf.stat().st_size  > 0)
            need_json = not (out_json.exists() and out_json.stat().st_size > 0)

            if need_pdf or need_json:
                logger.info("📤 %s → Azure prebuilt-read … [attempt %d]", stem, attempt)
                poller = client.begin_analyze_document(
                    model_id="prebuilt-read",
                    body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
                    output=[AnalyzeOutputOption.PDF],
                )
                result = poller.result()
                op_id = poller.details["operation_id"]

                if need_pdf:
                    stream = client.get_analyze_result_pdf(
                        model_id=result.model_id, result_id=op_id,
                    )
                    with open(out_pdf, "wb") as f:
                        for chunk in stream:
                            f.write(chunk)

                if need_json:
                    n_pages = len(result.pages) if result.pages else 0
                    with open(out_json, "w", encoding="utf-8") as f:
                        json.dump(result.as_dict(), f, ensure_ascii=False, indent=2)
                else:
                    ocr = json.loads(out_json.read_text(encoding="utf-8"))
                    n_pages = len(ocr.get("pages", []))
            else:
                ocr = json.loads(out_json.read_text(encoding="utf-8"))
                n_pages = len(ocr.get("pages", []))

            api_elapsed = time.time() - start
            logger.info("✅ %s → %d pages, %.1fs API", stem, n_pages, api_elapsed)
            break  # success

        except Exception as e:
            if attempt < MAX_RETRIES:
                logger.warning("⚠️  %s attempt %d failed: %s — retrying in %ds …", stem, attempt, e, RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            else:
                elapsed = time.time() - start
                logger.error("❌ %s Azure failed after %d attempts (%.1fs): %s", stem, MAX_RETRIES, elapsed, e)
                return {"file": stem, "status": "error", "error": str(e)}

    # ── Step 2: Render replace-text HTML (local) ─────────────────────
    try:
        render_start = time.time()
        html_str = render_document(
            out_pdf, out_json, dpi=DPI, replace_text=True,
        )
        out_html.write_text(html_str, encoding="utf-8")
        render_elapsed = time.time() - render_start
        logger.info("🖨  %s → HTML (%.1fs render)", stem, render_elapsed)

    except Exception as e:
        elapsed = time.time() - start
        logger.error("❌ %s HTML render failed (%.1fs): %s", stem, elapsed, e)
        return {"file": stem, "status": "error", "error": f"render: {e}"}

    elapsed = time.time() - start
    return {"file": stem, "status": "success", "pages": n_pages, "elapsed_s": round(elapsed, 1)}


# ── Parallel batch runner ───────────────────────────────────────────────────

async def main(input_dir: Path, output_dir: Path, workers: int):
    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        sys.exit(f"No PDFs found in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("📂 %d PDFs in %s → %s (%d workers)", len(pdf_files), input_dir, output_dir, workers)

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(workers)

    async def _bounded(p: Path) -> dict:
        async with sem:
            return await loop.run_in_executor(
                executor, process_one, p, output_dir, endpoint, api_key,
            )

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = await asyncio.gather(*[_bounded(p) for p in pdf_files], return_exceptions=True)

    # ── Summary ──────────────────────────────────────────────────────
    final = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            final.append({"file": pdf_files[i].stem, "status": "error", "error": str(r)})
        else:
            final.append(r)

    ok      = [r for r in final if r["status"] == "success"]
    skipped = [r for r in final if r["status"] == "skipped"]
    errors  = [r for r in final if r["status"] == "error"]

    total_pages = sum(r.get("pages", 0) for r in ok)
    wall_time = time.time() - t0

    summary_lines = [
        "",
        "=" * 60,
        f"  Input: {input_dir}",
        f"  Documents: {len(final)}",
        f"  ✅ Success: {len(ok)}  ⏭ Skipped: {len(skipped)}  ❌ Failed: {len(errors)}",
        f"  📄 Pages: {total_pages}",
    ]
    if errors:
        for e in errors:
            summary_lines.append(f"     ❌ {e['file']}: {e.get('error', '?')}")
    summary_lines.append(f"  Wall time: {wall_time:.1f}s")
    summary_lines.append("=" * 60)

    summary_text = "\n".join(summary_lines)
    print(summary_text)

    # Save metrics to file
    metrics_path = output_dir / "metrics.txt"
    with open(metrics_path, "a", encoding="utf-8") as f:
        f.write(summary_text.strip() + "\n")
    logger.info("📊 Metrics appended to %s", metrics_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Azure-only batch OCR pipeline")
    parser.add_argument("folder", help="Subfolder name inside batch01/ (e.g. 0046), or 'all' to run all remaining")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers (default: 4)")
    args = parser.parse_args()

    if args.folder == "all":
        batch_dir = ROOT / "batch01"
        output_root = ROOT / "output"
        folders = sorted(d.name for d in batch_dir.iterdir() if d.is_dir())

        # Determine which folders are already fully done (output dir exists and
        # every input PDF has all 3 output files: .pdf, .json, .html)
        remaining = []
        for fname in folders:
            out_dir = output_root / f"output_{fname}"
            if out_dir.exists():
                input_pdfs = list((batch_dir / fname).glob("*.pdf"))
                all_done = input_pdfs and all(
                    (out_dir / p.stem / f"{p.stem}.pdf").exists()
                    and (out_dir / p.stem / f"{p.stem}.json").exists()
                    and (out_dir / p.stem / f"{p.stem}.html").exists()
                    for p in input_pdfs
                )
                if all_done:
                    logger.info("⏭  Folder %s already complete — skipping", fname)
                    continue
            remaining.append(fname)

        logger.info("📋 %d/%d folders remaining to process", len(remaining), len(folders))

        for i, fname in enumerate(remaining, 1):
            logger.info("━" * 60)
            logger.info("📂 Processing folder %s (%d/%d)", fname, i, len(remaining))
            logger.info("━" * 60)
            input_dir = batch_dir / fname
            output_dir = output_root / f"output_{fname}"
            asyncio.run(main(input_dir, output_dir, args.workers))
    else:
        input_dir = ROOT / "batch01" / args.folder
        output_dir = ROOT / "output" / f"output_{args.folder}"
        if not input_dir.exists():
            sys.exit(f"Input directory not found: {input_dir}")

        asyncio.run(main(input_dir, output_dir, args.workers))
