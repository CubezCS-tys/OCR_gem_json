#!/usr/bin/env python3
"""
Batch OCR pipeline for large PDFs (>= 100 MB).

Mirrors run_batch.py exactly, but the Azure stage splits each PDF into
individual pages, OCRs each page, then merges the results — instead of
sending the whole file at once.

Per-page results are checkpointed so a restart skips already-finished pages.

Two-stage pipeline:
  Stage 1: Page split + Azure API  (network I/O bound) — --api-workers
  Stage 2: HTML rendering          (CPU bound)         — --render-workers

Usage:
    python run_batch_large.py batch33-add
    python run_batch_large.py batch33-add --api-workers 3 --render-workers 8
    python run_batch_large.py batch33-add --force-html
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

DPI             = 300
MAX_RETRIES     = 5
RETRY_BASE_WAIT = 20   # doubles each attempt: 20s, 40s, 80s, 160s, 320s


# ── Thread-local Azure clients (one per thread, same as run_batch.py) ─────────

_thread_clients: dict[int, object] = {}
_clients_lock = threading.Lock()


def _get_client(endpoint: str, api_key: str):
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential
    tid = threading.get_ident()
    if tid not in _thread_clients:
        with _clients_lock:
            if tid not in _thread_clients:
                _thread_clients[tid] = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=AzureKeyCredential(api_key),
                )
    return _thread_clients[tid]


# ── Per-file locks (same as run_batch.py) ─────────────────────────────────────

_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()


def _get_file_lock(stem: str) -> threading.Lock:
    with _file_locks_lock:
        if stem not in _file_locks:
            _file_locks[stem] = threading.Lock()
        return _file_locks[stem]


# ── Fast completion scan (same as run_batch.py) ───────────────────────────────

def _scan_completed(output_dir: Path, require_html: bool = True) -> frozenset[str]:
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


# ── Atomic write helpers (same as run_batch.py) ───────────────────────────────

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── Merge helpers ─────────────────────────────────────────────────────────────

def _merge_pdfs(paths: list[Path], out_path: Path) -> None:
    import fitz
    merged = fitz.open()
    for p in paths:
        src = fitz.open(str(p))
        merged.insert_pdf(src)
        src.close()
    merged.save(str(out_path))
    merged.close()


def _merge_jsons(paths: list[Path]) -> dict:
    merged_pages: list[dict] = []
    content_parts: list[str] = []
    first: dict | None = None
    for page_num, path in enumerate(paths, start=1):
        chunk = json.loads(path.read_text(encoding="utf-8"))
        if first is None:
            first = chunk
        for page in chunk.get("pages", []):
            adjusted = dict(page)
            adjusted["pageNumber"] = page_num
            merged_pages.append(adjusted)
        if chunk.get("content"):
            content_parts.append(chunk["content"])
    return {
        "pages":      merged_pages,
        "content":    "\n".join(content_parts),
        "modelId":    (first or {}).get("modelId", "prebuilt-read"),
        "apiVersion": (first or {}).get("apiVersion", ""),
    }


# ── Stage 1: Azure (page-by-page) ────────────────────────────────────────────

def azure_only(pdf_path: Path, output_dir: Path, endpoint: str, api_key: str,
               force_html: bool = False, done_stems: frozenset = frozenset()) -> dict:
    """
    Split pdf_path into individual pages, OCR each via Azure prebuilt-read,
    merge results into a single searchable PDF + OCR JSON.

    Same return shape as run_batch.py's azure_only() so Stage 2 is identical.
    Per-page results saved to <stem>/pages/ as checkpoints — restarts skip done pages.
    """
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeOutputOption
    import fitz

    stem = pdf_path.stem

    with _get_file_lock(stem):
        doc_folder = output_dir / stem
        page_dir   = doc_folder / "pages"
        out_pdf    = doc_folder / f"{stem}.pdf"
        out_json   = doc_folder / f"{stem}.json"

        # Pre-scan fast skip
        if stem in done_stems:
            if force_html:
                return {"file": stem, "status": "api_done", "out_pdf": out_pdf, "out_json": out_json}
            logger.info("⏭  Skipping (complete): %s", stem)
            return {"file": stem, "status": "skipped", "out_pdf": out_pdf, "out_json": out_json}

        # pdf+json already exist — skip Azure, let Stage 2 render HTML
        if not force_html \
                and out_pdf.exists() and out_pdf.stat().st_size > 0 \
                and out_json.exists() and out_json.stat().st_size > 0:
            ocr = json.loads(out_json.read_text(encoding="utf-8"))
            return {"file": stem, "status": "api_done",
                    "pages": len(ocr.get("pages", [])),
                    "out_pdf": out_pdf, "out_json": out_json}

        doc_folder.mkdir(parents=True, exist_ok=True)
        page_dir.mkdir(exist_ok=True)

        doc    = fitz.open(str(pdf_path))
        total  = len(doc)
        client = _get_client(endpoint, api_key)

        file_mb = pdf_path.stat().st_size // (1024 * 1024)
        logger.info("📂 %s (%d MB, %d pages)", stem, file_mb, total)

        result_pdfs : list[Path] = []
        result_jsons: list[Path] = []
        t0 = time.time()

        try:
            for i in range(total):
                result_pdf_p  = page_dir / f"result_{i:04d}.pdf"
                result_json_p = page_dir / f"result_{i:04d}.json"

                # Checkpoint resume: page already done in a previous run
                if result_pdf_p.exists() and result_pdf_p.stat().st_size > 0 \
                        and result_json_p.exists() and result_json_p.stat().st_size > 0:
                    logger.info("  ⏭  page %04d/%04d already done", i + 1, total)
                    result_pdfs.append(result_pdf_p)
                    result_jsons.append(result_json_p)
                    continue

                # Extract page to bytes in memory (pages are small, no temp file needed)
                page_doc = fitz.open()
                page_doc.insert_pdf(doc, from_page=i, to_page=i)
                page_bytes = page_doc.tobytes(deflate=True, garbage=4)
                page_doc.close()

                # Send to Azure with exponential backoff retries
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        logger.info(
                            "  📤 %s page %04d/%04d → Azure [attempt %d] …",
                            stem, i + 1, total, attempt,
                        )
                        poller = client.begin_analyze_document(
                            model_id="prebuilt-read",
                            body=AnalyzeDocumentRequest(bytes_source=page_bytes),
                            output=[AnalyzeOutputOption.PDF],
                        )
                        result = poller.result()
                        op_id  = poller.details["operation_id"]

                        stream = client.get_analyze_result_pdf(
                            model_id=result.model_id, result_id=op_id,
                        )
                        result_pdf_p.write_bytes(b"".join(stream))
                        result_json_p.write_text(
                            json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        logger.info("  ✅ page %04d/%04d done", i + 1, total)
                        break

                    except Exception as e:
                        if attempt < MAX_RETRIES:
                            wait = RETRY_BASE_WAIT * (2 ** (attempt - 1))
                            logger.warning(
                                "  ⚠️  page %04d attempt %d failed: %s — retrying in %ds …",
                                i + 1, attempt, e, wait,
                            )
                            time.sleep(wait)
                        else:
                            raise

                del page_bytes  # free memory immediately — pages can be 200+ MB
                result_pdfs.append(result_pdf_p)
                result_jsons.append(result_json_p)

        finally:
            doc.close()

        logger.info("All %d pages sent (%.1fs). Merging …", total, time.time() - t0)

        try:
            _merge_pdfs(result_pdfs, out_pdf)
            merged_json = _merge_jsons(result_jsons)
            n_pages     = len(merged_json.get("pages", []))
            _atomic_write_text(out_json, json.dumps(merged_json, ensure_ascii=False, indent=2))

            logger.info("✅ %s → %d pages (%.1fs total)", stem, n_pages, time.time() - t0)

            # Clean up page checkpoint folder
            for p in result_pdfs + result_jsons:
                p.unlink(missing_ok=True)
            try:
                page_dir.rmdir()
            except OSError:
                pass

            return {"file": stem, "status": "api_done", "pages": n_pages,
                    "out_pdf": out_pdf, "out_json": out_json}

        except Exception as e:
            logger.error("❌ %s merge failed: %s — page results kept as checkpoints", stem, e)
            return {"file": stem, "status": "error", "error": str(e)}


# ── Stage 2: HTML render (identical to run_batch.py) ─────────────────────────

def render_only(api_result: dict, force_html: bool = False) -> dict:
    from fixed_layout_pipeline.overlay_renderer import render_document

    if api_result["status"] in ("skipped", "error"):
        return api_result

    stem     = api_result["file"]
    out_pdf  = api_result["out_pdf"]
    out_json = api_result["out_json"]
    out_html = out_pdf.parent / f"{stem}.html"

    if not force_html and out_html.exists() and out_html.stat().st_size > 0:
        logger.info("⏭  HTML exists, skipping: %s", stem)
        return {**api_result, "status": "success"}

    try:
        start    = time.time()
        html_str = render_document(out_pdf, out_json, dpi=DPI, replace_text=True)
        _atomic_write_text(out_html, html_str)
        logger.info("🖨  %s → HTML (%.1fs)", stem, time.time() - start)
        return {**api_result, "status": "success"}
    except Exception as e:
        logger.error("❌ %s HTML render failed: %s", stem, e)
        return {**api_result, "status": "error", "error": f"render: {e}"}


# ── Parallel batch runner (mirrors run_batch.py) ──────────────────────────────

async def main(input_dir: Path, output_dir: Path, api_workers: int,
               render_workers: int, force_html: bool = False):
    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        sys.exit(f"No PDFs found in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "📂 %d PDFs in %s → %s  (🌐 %d API workers | 🖨  %d render workers)",
        len(pdf_files), input_dir, output_dir, api_workers, render_workers,
    )

    done_stems = _scan_completed(output_dir, require_html=not force_html)
    if done_stems:
        logger.info("⚡ Pre-scan: %d / %d already complete — skipping", len(done_stems), len(pdf_files))

    loop = asyncio.get_running_loop()
    t0   = time.time()

    # ── Stage 1: Azure ────────────────────────────────────────────────────────
    logger.info("━" * 60)
    logger.info("🌐 Stage 1: Azure page-by-page OCR  (%d workers)", api_workers)
    logger.info("━" * 60)

    api_sem = asyncio.Semaphore(api_workers)

    async def _bounded_api(p: Path) -> dict:
        async with api_sem:
            return await loop.run_in_executor(
                api_executor, azure_only, p, output_dir, endpoint, api_key, force_html, done_stems,
            )

    with ThreadPoolExecutor(max_workers=api_workers) as api_executor:
        api_results = await asyncio.gather(
            *[_bounded_api(p) for p in pdf_files], return_exceptions=True,
        )

    api_final: list[dict] = []
    for i, r in enumerate(api_results):
        if isinstance(r, Exception):
            api_final.append({"file": pdf_files[i].stem, "status": "error", "error": str(r)})
        else:
            api_final.append(r)

    api_ok     = sum(1 for r in api_final if r["status"] == "api_done")
    api_skip   = sum(1 for r in api_final if r["status"] == "skipped")
    api_errors = sum(1 for r in api_final if r["status"] == "error")
    logger.info("🌐 Stage 1 done — ✅ %d  ⏭ %d  ❌ %d", api_ok, api_skip, api_errors)

    to_render = [r for r in api_final if r["status"] in ("api_done", "skipped")]

    # ── Stage 2: HTML render ──────────────────────────────────────────────────
    logger.info("━" * 60)
    logger.info("🖨  Stage 2: HTML render  (%d workers)", render_workers)
    logger.info("━" * 60)

    render_sem = asyncio.Semaphore(render_workers)

    async def _bounded_render(r: dict) -> dict:
        async with render_sem:
            return await loop.run_in_executor(render_executor, render_only, r, force_html)

    with ThreadPoolExecutor(max_workers=render_workers) as render_executor:
        render_results = await asyncio.gather(
            *[_bounded_render(r) for r in to_render], return_exceptions=True,
        )

    rendered_final: list[dict] = []
    for i, r in enumerate(render_results):
        if isinstance(r, Exception):
            rendered_final.append({"file": to_render[i]["file"], "status": "error", "error": str(r)})
        else:
            rendered_final.append(r)

    results     = rendered_final + [r for r in api_final if r["status"] == "error"]
    ok          = [r for r in results if r["status"] == "success"]
    skipped     = [r for r in results if r["status"] == "skipped"]
    errors      = [r for r in results if r["status"] == "error"]
    total_pages = sum(r.get("pages", 0) for r in ok)
    wall_time   = time.time() - t0

    summary_lines = [
        "",
        "=" * 60,
        f"  Input:     {input_dir}",
        f"  Documents: {len(results)}",
        f"  ✅ Success: {len(ok)}  ⏭ Skipped: {len(skipped)}  ❌ Failed: {len(errors)}",
        f"  📄 Pages:   {total_pages}",
    ]
    if errors:
        for e in errors:
            summary_lines.append(f"     ❌ {e['file']}: {e.get('error', '?')}")
    summary_lines.append(f"  🌐 API workers: {api_workers}  🖨  Render workers: {render_workers}")
    summary_lines.append(f"  Wall time: {wall_time:.1f}s  ({wall_time / 60:.1f}min)")
    summary_lines.append("=" * 60)

    summary_text = "\n".join(summary_lines)
    print(summary_text)

    metrics_path = output_dir / "metrics.txt"
    with open(metrics_path, "a", encoding="utf-8") as f:
        f.write(summary_text.strip() + "\n")
    logger.info("📊 Metrics appended to %s", metrics_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch OCR pipeline for large PDFs (>= 100 MB)")
    parser.add_argument("folder", help="Folder of large PDFs (e.g. batch33-add)")
    parser.add_argument("--api-workers",    type=int, default=3,
                        help="Concurrent files through Azure (default: 3)")
    parser.add_argument("--render-workers", type=int, default=8,
                        help="HTML render workers (default: 8)")
    parser.add_argument("--force-html", action="store_true",
                        help="Re-render HTML even if it already exists")
    args = parser.parse_args()

    input_dir = ROOT / args.folder
    if not input_dir.exists():
        sys.exit(f"Input directory not found: {input_dir}")

    output_dir = ROOT / "output" / f"output_{args.folder}"
    asyncio.run(main(input_dir, output_dir, args.api_workers, args.render_workers, args.force_html))
