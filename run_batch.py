#!/usr/bin/env python3
"""
Process all PDFs using Azure-only fixed_layout_pipeline.

Outputs: searchable PDF, OCR JSON, replace-text HTML — all with clean names
in per-document subfolders under output/.

Usage:
    python run_batch.py batch02
    python run_batch.py batch02 --api-workers 16 --render-workers 16

Runs a 2-stage pipeline:
  Stage 1: Azure API calls  (network I/O bound) — controlled by --api-workers
  Stage 2: HTML rendering   (CPU bound)         — controlled by --render-workers

Defaults to 8 API workers and 8 render workers.
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
# One client per thread — Azure SDK is not thread-safe across threads.

_thread_clients: dict[int, object] = {}
_clients_lock = threading.Lock()  # guards the dict itself


def _get_client(endpoint: str, api_key: str):
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    tid = threading.get_ident()
    if tid not in _thread_clients:
        with _clients_lock:
            # Double-checked locking
            if tid not in _thread_clients:
                _thread_clients[tid] = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=AzureKeyCredential(api_key),
                )
    return _thread_clients[tid]


# ── Per-file locks — prevents two workers ever touching the same stem ─────────
# asyncio already dispatches each pdf_path once, but this is a safety net
# in case the same folder is accidentally passed to two runs simultaneously.

_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()


def _get_file_lock(stem: str) -> threading.Lock:
    with _file_locks_lock:
        if stem not in _file_locks:
            _file_locks[stem] = threading.Lock()
        return _file_locks[stem]


# ── Fast completion scan ─────────────────────────────────────────────────────

def _scan_completed(output_dir: Path, require_html: bool = True) -> frozenset[str]:
    """
    Walk output_dir once with os.scandir() and return stems that already have
    all required outputs.  When require_html=False, only pdf+json are checked
    (used by --force-html to find docs that can skip the Azure call entirely).

    os.scandir() reads all entries in a single getdents64 syscall and caches
    stat info in each DirEntry — far cheaper than calling Path.exists() +
    Path.stat() per file for every document in the batch.
    """
    if not output_dir.exists():
        return frozenset()

    done: set[str] = set()
    try:
        with os.scandir(output_dir) as top:
            subdirs = [(e.name, e.path) for e in top if e.is_dir()]
    except OSError:
        return frozenset()

    for stem, doc_path in subdirs:
        required = {f"{stem}.pdf", f"{stem}.json"}
        if require_html:
            required.add(f"{stem}.html")
        try:
            with os.scandir(doc_path) as inner:
                present = {
                    f.name for f in inner
                    if f.name in required and f.stat(follow_symlinks=False).st_size > 0
                }
        except OSError:
            continue
        if required.issubset(present):
            done.add(stem)

    return frozenset(done)


# ── Stage 1: Azure API only ──────────────────────────────────────────────────

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a temp file then atomically rename to avoid partial writes."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text to a temp file then atomically rename to avoid partial writes."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def azure_only(pdf_path: Path, output_dir: Path, endpoint: str, api_key: str,
               force_html: bool = False, done_stems: frozenset = frozenset()) -> dict:
    """Fetch searchable PDF + OCR JSON from Azure. No HTML rendering."""
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )

    stem = pdf_path.stem

    # Per-file lock: only one worker can ever process this stem at a time
    with _get_file_lock(stem):
        doc_folder = output_dir / stem
        doc_folder.mkdir(parents=True, exist_ok=True)
        out_pdf  = doc_folder / f"{stem}.pdf"
        out_json = doc_folder / f"{stem}.json"

        # Fast O(1) pre-scan check — avoids stat() calls for already-done docs
        if stem in done_stems:
            if force_html:
                # pdf+json confirmed by pre-scan; skip Azure, go straight to render
                return {"file": stem, "status": "api_done", "out_pdf": out_pdf, "out_json": out_json}
            else:
                # all three outputs confirmed; nothing to do
                logger.info("⏭  Skipping (exists): %s", stem)
                return {"file": stem, "status": "skipped", "out_pdf": out_pdf, "out_json": out_json}

        need_pdf  = not (out_pdf.exists()  and out_pdf.stat().st_size  > 0)
        need_json = not (out_json.exists() and out_json.stat().st_size > 0)

        if not need_pdf and not need_json:
            # pdf+json exist but weren't caught by pre-scan (e.g. html missing, no --force-html)
            ocr = json.loads(out_json.read_text(encoding="utf-8"))
            n_pages = len(ocr.get("pages", []))
            return {"file": stem, "status": "api_done", "pages": n_pages, "out_pdf": out_pdf, "out_json": out_json}

        start = time.time()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                pdf_bytes = pdf_path.read_bytes()
                client = _get_client(endpoint, api_key)

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
                    # Collect stream then atomic write — no partial PDFs
                    pdf_data = b"".join(stream)
                    _atomic_write_bytes(out_pdf, pdf_data)

                if need_json:
                    n_pages = len(result.pages) if result.pages else 0
                    _atomic_write_text(out_json, json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
                else:
                    ocr = json.loads(out_json.read_text(encoding="utf-8"))
                    n_pages = len(ocr.get("pages", []))

                api_elapsed = time.time() - start
                logger.info("✅ %s → %d pages, %.1fs API", stem, n_pages, api_elapsed)
                return {"file": stem, "status": "api_done", "pages": n_pages, "out_pdf": out_pdf, "out_json": out_json}

            except Exception as e:
                if attempt < MAX_RETRIES:
                    logger.warning("⚠️  %s attempt %d failed: %s — retrying in %ds …", stem, attempt, e, RETRY_DELAY)
                    time.sleep(RETRY_DELAY)
                else:
                    elapsed = time.time() - start
                    logger.error("❌ %s Azure failed after %d attempts (%.1fs): %s", stem, MAX_RETRIES, elapsed, e)
                    return {"file": stem, "status": "error", "error": str(e)}


# ── Stage 2: HTML render only ─────────────────────────────────────────────────

_render_counter = 0
_render_counter_lock = threading.Lock()
_render_total = 0
_render_start_time = 0.0


def render_only(api_result: dict, force_html: bool = False) -> dict:
    """Render HTML from already-fetched PDF + JSON. Pure local CPU work."""
    global _render_counter
    from fixed_layout_pipeline.overlay_renderer import render_document

    if api_result["status"] in ("skipped", "error"):
        return api_result

    stem     = api_result["file"]
    out_pdf  = api_result["out_pdf"]
    out_json = api_result["out_json"]
    out_html = out_pdf.parent / f"{stem}.html"

    if not force_html and out_html.exists() and out_html.stat().st_size > 0:
        logger.info("⏭  HTML exists, skipping render: %s", stem)
        return {**api_result, "status": "success"}

    replacing = out_html.exists() and out_html.stat().st_size > 0

    try:
        start = time.time()
        html_str = render_document(out_pdf, out_json, dpi=DPI, replace_text=True)
        _atomic_write_text(out_html, html_str)  # atomic — no partial HTML files
        elapsed = time.time() - start

        with _render_counter_lock:
            _render_counter += 1
            n = _render_counter
            total = _render_total

        # Log progress every 50 renders
        if n % 50 == 0 or n == total:
            pct = n / total * 100 if total else 0
            elapsed_wall = time.time() - _render_start_time
            rate = n / elapsed_wall if elapsed_wall > 0 else 0
            eta_s = (total - n) / rate if rate > 0 else 0
            eta_m = eta_s / 60
            logger.info(
                "🖨  Progress: %d / %d (%.1f%%)  rate=%.1f/s  ETA=%.1fmin",
                n, total, pct, rate, eta_m,
            )
        else:
            action = "🔄  replacing" if replacing else "🖨  new"
            logger.info("%s %s → HTML (%.1fs render)", action, stem, elapsed)

        return {**api_result, "status": "success"}
    except Exception as e:
        logger.error("❌ %s HTML render failed: %s", stem, e)
        return {**api_result, "status": "error", "error": f"render: {e}"}


# ── Parallel batch runner ───────────────────────────────────────────────────

async def main(input_dir: Path, output_dir: Path, api_workers: int, render_workers: int, force_html: bool = False):
    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        sys.exit(f"No PDFs found in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "📂 %d PDFs in %s → %s (🌐 %d API workers | 🖨  %d render workers)",
        len(pdf_files), input_dir, output_dir, api_workers, render_workers,
    )

    # Pre-scan output dir once — builds a frozenset of already-complete stems so
    # each worker does an O(1) set lookup instead of stat() calls per document.
    # With --force-html we scan for pdf+json only (html will be re-rendered).
    done_stems = _scan_completed(output_dir, require_html=not force_html)
    if done_stems:
        if force_html:
            logger.info("⚡ Pre-scan: %d / %d docs have Azure outputs — jumping straight to render", len(done_stems), len(pdf_files))
        else:
            logger.info("⚡ Pre-scan: %d / %d docs already complete — skipping", len(done_stems), len(pdf_files))

    loop = asyncio.get_running_loop()
    t0 = time.time()

    # ── Stage 1: Azure API ────────────────────────────────────────────
    logger.info("━" * 60)
    logger.info("🌐 Stage 1: Azure API  (%d workers)", api_workers)
    logger.info("━" * 60)

    api_sem = asyncio.Semaphore(api_workers)

    async def _bounded_api(p: Path) -> dict:
        async with api_sem:
            return await loop.run_in_executor(
                api_executor, azure_only, p, output_dir, endpoint, api_key, force_html, done_stems,
            )

    with ThreadPoolExecutor(max_workers=api_workers) as api_executor:
        api_results = await asyncio.gather(
            *[_bounded_api(p) for p in pdf_files], return_exceptions=True
        )

    # Normalise exceptions from gather
    api_final = []
    for i, r in enumerate(api_results):
        if isinstance(r, Exception):
            api_final.append({"file": pdf_files[i].stem, "status": "error", "error": str(r)})
        else:
            api_final.append(r)

    api_ok     = sum(1 for r in api_final if r["status"] == "api_done")
    api_skip   = sum(1 for r in api_final if r["status"] == "skipped")
    api_errors = sum(1 for r in api_final if r["status"] == "error")
    logger.info("🌐 Stage 1 done — ✅ %d  ⏭ %d  ❌ %d", api_ok, api_skip, api_errors)

    # Only pass docs that need rendering to stage 2
    to_render = [r for r in api_final if r["status"] in ("api_done", "skipped")]

    # ── Stage 2: HTML rendering ───────────────────────────────────────
    logger.info("━" * 60)
    logger.info("🖨  Stage 2: HTML render (%d workers)", render_workers)
    logger.info("━" * 60)

    # Reset progress counter for this run
    global _render_counter, _render_total, _render_start_time
    _render_counter = 0
    _render_total   = len(to_render)
    _render_start_time = time.time()

    render_sem = asyncio.Semaphore(render_workers)

    async def _bounded_render(r: dict) -> dict:
        async with render_sem:
            return await loop.run_in_executor(render_executor, render_only, r, force_html)

    with ThreadPoolExecutor(max_workers=render_workers) as render_executor:
        render_results = await asyncio.gather(
            *[_bounded_render(r) for r in to_render], return_exceptions=True
        )

    # Merge all results
    rendered_final = []
    for i, r in enumerate(render_results):
        if isinstance(r, Exception):
            rendered_final.append({"file": to_render[i]["file"], "status": "error", "error": str(r)})
        else:
            rendered_final.append(r)

    # Add back any docs that errored in stage 1
    stage1_errors = [r for r in api_final if r["status"] == "error"]
    results = rendered_final + stage1_errors

    # ── Summary ──────────────────────────────────────────────────────
    ok      = [r for r in results if r["status"] == "success"]
    skipped = [r for r in results if r["status"] == "skipped"]
    errors  = [r for r in results if r["status"] == "error"]

    total_pages = sum(r.get("pages", 0) for r in ok)
    wall_time = time.time() - t0

    summary_lines = [
        "",
        "=" * 60,
        f"  Input: {input_dir}",
        f"  Documents: {len(results)}",
        f"  ✅ Success: {len(ok)}  ⏭ Skipped: {len(skipped)}  ❌ Failed: {len(errors)}",
        f"  📄 Pages: {total_pages}",
    ]
    if errors:
        for e in errors:
            summary_lines.append(f"     ❌ {e['file']}: {e.get('error', '?')}")
    summary_lines.append(f"  🌐 API workers: {api_workers}  🖨  Render workers: {render_workers}")
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
    parser.add_argument("folder", help="Folder of PDFs to process (e.g. batch02), or 'all' to run all remaining")
    parser.add_argument("--api-workers",    type=int, default=8,  help="Azure API workers (default: 8)")
    parser.add_argument("--render-workers", type=int, default=8,  help="HTML render workers (default: 8)")
    # Legacy --workers flag maps to both stages equally
    parser.add_argument("--workers",        type=int, default=None, help="Set both api and render workers (legacy)")
    parser.add_argument("--force-html", action="store_true", help="Re-render HTML even if it already exists (skips Azure API)")
    args = parser.parse_args()

    if args.workers is not None:
        args.api_workers    = args.workers
        args.render_workers = args.workers

    if args.folder == "all":
        batch_dir = ROOT / "batch01"
        output_root = ROOT / "output"
        folders = sorted(d.name for d in batch_dir.iterdir() if d.is_dir())

        # Determine which folders are already fully done using a fast scandir
        # pass rather than per-file Path.exists() calls.
        remaining = []
        for fname in folders:
            out_dir = output_root / f"output_{fname}"
            if not args.force_html and out_dir.exists():
                input_stems = {p.stem for p in (batch_dir / fname).glob("*.pdf")}
                if input_stems and input_stems.issubset(_scan_completed(out_dir, require_html=True)):
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
            asyncio.run(main(input_dir, output_dir, args.api_workers, args.render_workers, args.force_html))
    else:
        # Check if it's a root-level folder first (like batch02)
        input_dir = ROOT / args.folder
        if not input_dir.exists():
            # Fall back to batch01 subfolder
            input_dir = ROOT / "batch01" / args.folder

        if not input_dir.exists():
            sys.exit(f"Input directory not found: {input_dir}")

        output_dir = ROOT / "output" / f"output_{args.folder}"
        asyncio.run(main(input_dir, output_dir, args.api_workers, args.render_workers, args.force_html))
