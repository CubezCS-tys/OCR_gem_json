#!/usr/bin/env python3
"""
process_large_pdf.py — Handle PDFs >= 100 MB by splitting into individual pages.

Approach
--------
1.  Split the PDF into single-page PDFs, one at a time.
2.  Send each page to Azure prebuilt-read, save the searchable PDF and JSON
    result to a checkpoint folder immediately.
3.  Merge all per-page searchable PDFs into one combined PDF.
4.  Merge all per-page OCR JSONs into one combined JSON.
    (HTML rendering happens downstream via run_batch_large.py as normal.)

Checkpoint folder — safe to restart at any point, finished pages are skipped:
    <output_dir>/<stem>/
        pages/
            page_NNNN.pdf       ← single page input (deleted after Azure succeeds)
            result_NNNN.pdf     ← searchable PDF from Azure
            result_NNNN.json    ← OCR JSON from Azure
        <stem>.pdf              ← final merged searchable PDF
        <stem>.json             ← final merged OCR JSON

Usage
-----
    python process_large_pdf.py path/to/big.pdf
    python process_large_pdf.py path/to/big.pdf --output-dir output/output_large/
"""

import argparse
import json
import logging
import os
import sys
import time
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

LARGE_PDF_MB    = 100   # files at or above this threshold belong here
MAX_RETRIES     = 5
RETRY_BASE_WAIT = 20    # seconds; doubles each attempt (20, 40, 80, 160, 320)

AZURE_CONNECT_TIMEOUT = 30
AZURE_READ_TIMEOUT    = 300   # per-page results are small, 5 min is plenty


# ── Azure ─────────────────────────────────────────────────────────────────────

def _make_client(endpoint: str, api_key: str):
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential
    return DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
        connection_timeout=AZURE_CONNECT_TIMEOUT,
        read_timeout=AZURE_READ_TIMEOUT,
    )


def _send_page(page_path: Path, client, result_pdf_path: Path, result_json_path: Path) -> None:
    """
    Send a single-page PDF to Azure prebuilt-read.
    Writes searchable PDF and OCR JSON directly to disk.
    Raises after MAX_RETRIES with exponential backoff.
    """
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeOutputOption

    pdf_bytes = page_path.read_bytes()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("  📤 %s → Azure [attempt %d/%d] …", page_path.name, attempt, MAX_RETRIES)
            poller = client.begin_analyze_document(
                model_id="prebuilt-read",
                body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
                output=[AnalyzeOutputOption.PDF],
            )
            result = poller.result()
            op_id  = poller.details["operation_id"]

            stream = client.get_analyze_result_pdf(model_id=result.model_id, result_id=op_id)
            result_pdf_path.write_bytes(b"".join(stream))
            result_json_path.write_text(
                json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("  ✅ %s done", page_path.name)
            return

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BASE_WAIT * (2 ** (attempt - 1))
                logger.warning("  ⚠️  attempt %d failed: %s — retrying in %ds …", attempt, e, wait)
                time.sleep(wait)
            else:
                logger.error("  ❌ all %d attempts failed for %s", MAX_RETRIES, page_path.name)
                raise


# ── Merge ─────────────────────────────────────────────────────────────────────

def _merge_pdfs(result_pdf_paths: list[Path], out_path: Path) -> None:
    """Concatenate per-page searchable PDFs into one file."""
    import fitz
    merged = fitz.open()
    for p in result_pdf_paths:
        src = fitz.open(str(p))
        merged.insert_pdf(src)
        src.close()
    merged.save(str(out_path))
    merged.close()


def _merge_jsons(result_json_paths: list[Path]) -> dict:
    """
    Merge per-page Azure OCR JSONs into one document.
    Fixes pageNumber so the result looks like a single document.
    """
    merged_pages: list[dict] = []
    content_parts: list[str] = []
    first: dict | None = None

    for page_num, path in enumerate(result_json_paths, start=1):
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


# ── Main ──────────────────────────────────────────────────────────────────────

def process_large_pdf(pdf_path: Path, output_dir: Path, endpoint: str, api_key: str) -> dict:
    """
    Split PDF into pages, OCR each page via Azure, merge results.
    Checkpoints every page so a restart skips already-finished pages.
    Returns a dict compatible with run_batch.py / run_batch_large.py.
    """
    import fitz

    stem       = pdf_path.stem
    doc_folder = output_dir / stem
    page_dir   = doc_folder / "pages"
    out_pdf    = doc_folder / f"{stem}.pdf"
    out_json   = doc_folder / f"{stem}.json"

    doc_folder.mkdir(parents=True, exist_ok=True)
    page_dir.mkdir(exist_ok=True)

    # Already fully done
    if out_pdf.exists() and out_pdf.stat().st_size > 0 \
            and out_json.exists() and out_json.stat().st_size > 0:
        logger.info("⏭  Already done, skipping: %s", stem)
        ocr = json.loads(out_json.read_text(encoding="utf-8"))
        return {
            "file": stem, "status": "api_done",
            "pages": len(ocr.get("pages", [])),
            "out_pdf": out_pdf, "out_json": out_json,
        }

    file_mb = pdf_path.stat().st_size // (1024 * 1024)
    doc     = fitz.open(str(pdf_path))
    total   = len(doc)
    logger.info("📂 %s (%d MB, %d pages)", stem, file_mb, total)

    client = _make_client(endpoint, api_key)

    result_pdfs : list[Path] = []
    result_jsons: list[Path] = []

    try:
        for i in range(total):
            result_pdf_p  = page_dir / f"result_{i:04d}.pdf"
            result_json_p = page_dir / f"result_{i:04d}.json"
            page_input_p  = page_dir / f"page_{i:04d}.pdf"

            # Resume: page already processed in a previous run
            if result_pdf_p.exists() and result_pdf_p.stat().st_size > 0 \
                    and result_json_p.exists() and result_json_p.stat().st_size > 0:
                logger.info("  ⏭  page %04d already done, skipping", i)
                result_pdfs.append(result_pdf_p)
                result_jsons.append(result_json_p)
                continue

            # Extract this single page to its own PDF
            page_doc = fitz.open()
            page_doc.insert_pdf(doc, from_page=i, to_page=i)
            page_doc.save(str(page_input_p))
            page_doc.close()

            page_mb = page_input_p.stat().st_size // (1024 * 1024) or "<1"
            logger.info("  Page %04d / %04d (%s MB)", i + 1, total, page_mb)

            # Send to Azure; always delete the input page after (pass or fail)
            try:
                _send_page(page_input_p, client, result_pdf_p, result_json_p)
            finally:
                page_input_p.unlink(missing_ok=True)

            result_pdfs.append(result_pdf_p)
            result_jsons.append(result_json_p)

    finally:
        doc.close()

    logger.info("All %d pages done. Merging …", total)

    try:
        _merge_pdfs(result_pdfs, out_pdf)
        merged_json = _merge_jsons(result_jsons)
        n_pages     = len(merged_json.get("pages", []))

        tmp = out_json.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(merged_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(out_json)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

        logger.info("✅ %s — %d pages merged", stem, n_pages)

        # Clean up page checkpoint folder
        for p in result_pdfs + result_jsons:
            p.unlink(missing_ok=True)
        try:
            page_dir.rmdir()
        except OSError:
            pass

        return {
            "file": stem, "status": "api_done", "pages": n_pages,
            "out_pdf": out_pdf, "out_json": out_json,
        }

    except Exception as e:
        logger.error("❌ %s merge failed: %s", stem, e)
        # Leave page results intact as checkpoints for the next run
        return {"file": stem, "status": "error", "error": str(e)}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Process a PDF >= {LARGE_PDF_MB} MB by splitting into pages and OCR-ing each"
    )
    parser.add_argument("pdf", type=Path, help="Path to the large PDF")
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "output" / "output_large",
        help="Output directory (default: output/output_large/)",
    )
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    if not args.pdf.exists():
        sys.exit(f"File not found: {args.pdf}")

    file_mb = args.pdf.stat().st_size // (1024 * 1024)
    if file_mb < LARGE_PDF_MB:
        logger.warning(
            "%s is only %d MB (threshold %d MB) — consider run_batch.py instead.",
            args.pdf.name, file_mb, LARGE_PDF_MB,
        )

    result = process_large_pdf(args.pdf, args.output_dir, endpoint, api_key)
    print(json.dumps(result, default=str, indent=2))
