#!/usr/bin/env python3
"""
process_large_pdf.py — Handle PDFs too large for Azure DI's 500 MB limit.

Splits the PDF into chunks, sends each to Azure prebuilt-read,
then merges the searchable PDFs and OCR JSONs back into single files.

Usage:
    python process_large_pdf.py path/to/big.pdf --output-dir output/output_bigdoc/

Outputs (same structure as run_batch.py):
    output/output_bigdoc/<stem>/<stem>.pdf
    output/output_bigdoc/<stem>/<stem>.json
"""

import argparse
import json
import logging
import os
import sys
import tempfile
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

AZURE_MAX_BYTES = 45 * 1024 * 1024  # 45 MB — small enough to upload before the gateway 408-timeout
MAX_RETRIES = 3
RETRY_DELAY = 15


# ── PDF splitting ─────────────────────────────────────────────────────────────

def split_pdf_chunks(pdf_path: Path, max_bytes: int = AZURE_MAX_BYTES) -> list[Path]:
    """
    Split a PDF into temp files each under max_bytes.
    Returns a list of temp paths — caller is responsible for deleting them.

    Uses an estimate of bytes-per-page from the actual file size, with a
    10 % safety margin. If a chunk still overshoots (pages with embedded
    images vary a lot), the page count is halved and retried.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    file_bytes = pdf_path.stat().st_size
    bytes_per_page = file_bytes / max(total_pages, 1)
    pages_per_chunk = max(1, int(max_bytes / bytes_per_page * 0.90))

    logger.info(
        "Splitting %s (%d MB, %d pages) — ~%d pages/chunk",
        pdf_path.name,
        file_bytes // (1024 * 1024),
        total_pages,
        pages_per_chunk,
    )

    chunks: list[Path] = []
    tmp_dir = Path(tempfile.gettempdir())
    start = 0

    while start < total_pages:
        end = min(start + pages_per_chunk, total_pages)
        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        chunk_path = tmp_dir / f"{pdf_path.stem}_chunk{len(chunks)}.pdf"
        chunk_doc.save(str(chunk_path))
        chunk_doc.close()

        chunk_mb = chunk_path.stat().st_size // (1024 * 1024)

        # If still too large and more than one page, halve chunk size and retry
        if chunk_path.stat().st_size > max_bytes and end - start > 1:
            chunk_path.unlink(missing_ok=True)
            pages_per_chunk = max(1, (end - start) // 2)
            logger.warning(
                "Chunk too large (%d MB), retrying with %d pages/chunk",
                chunk_mb, pages_per_chunk,
            )
            continue

        logger.info(
            "  Chunk %d: pages %d–%d (%d MB) → %s",
            len(chunks), start + 1, end, chunk_mb, chunk_path.name,
        )
        chunks.append(chunk_path)
        start = end

    doc.close()
    return chunks


# ── Azure call (single chunk) ─────────────────────────────────────────────────

def _call_azure(chunk_path: Path, endpoint: str, api_key: str) -> tuple[bytes | None, dict | None]:
    """
    Send one chunk to Azure prebuilt-read.
    Returns (searchable_pdf_bytes, ocr_json_dict) or raises on failure.
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeOutputOption
    from azure.core.credentials import AzureKeyCredential

    client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(api_key))
    pdf_bytes = chunk_path.read_bytes()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("  📤 %s → Azure [attempt %d] …", chunk_path.name, attempt)
            poller = client.begin_analyze_document(
                model_id="prebuilt-read",
                body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
                output=[AnalyzeOutputOption.PDF],
            )
            result = poller.result()
            op_id = poller.details["operation_id"]

            stream = client.get_analyze_result_pdf(model_id=result.model_id, result_id=op_id)
            searchable_pdf = b"".join(stream)
            ocr_dict = result.as_dict()

            logger.info(
                "  ✅ %s → %d pages",
                chunk_path.name,
                len(result.pages) if result.pages else 0,
            )
            return searchable_pdf, ocr_dict

        except Exception as e:
            if attempt < MAX_RETRIES:
                logger.warning("  ⚠️  attempt %d failed: %s — retrying in %ds …", attempt, e, RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            else:
                raise


# ── Merge helpers ─────────────────────────────────────────────────────────────

def merge_ocr_jsons(chunk_jsons: list[dict]) -> dict:
    """
    Merge multiple Azure prebuilt-read JSON dicts into one.
    Adjusts pageNumber offsets so the merged result looks like a single document.
    Only fields consumed by the rendering pipeline (pages, content) are merged.
    """
    if len(chunk_jsons) == 1:
        return chunk_jsons[0]

    merged_pages: list[dict] = []
    content_parts: list[str] = []
    page_offset = 0

    for chunk in chunk_jsons:
        pages = chunk.get("pages", [])
        for page in pages:
            adjusted = dict(page)
            # pageNumber is 1-based in Azure responses
            adjusted["pageNumber"] = page_offset + page.get("pageNumber", len(merged_pages) + 1)
            merged_pages.append(adjusted)
        page_offset += len(pages)
        if chunk.get("content"):
            content_parts.append(chunk["content"])

    return {
        "pages": merged_pages,
        "content": "\n".join(content_parts),
        "modelId": chunk_jsons[0].get("modelId", "prebuilt-read"),
        "apiVersion": chunk_jsons[0].get("apiVersion", ""),
    }


def merge_pdfs(chunk_pdf_bytes_list: list[bytes], out_path: Path) -> None:
    """Concatenate multiple PDF byte strings into one file using PyMuPDF."""
    import fitz
    merged = fitz.open()
    for pdf_bytes in chunk_pdf_bytes_list:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        merged.insert_pdf(src)
        src.close()
    merged.save(str(out_path))
    merged.close()


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


# ── Main entry point ──────────────────────────────────────────────────────────

def process_large_pdf(pdf_path: Path, output_dir: Path, endpoint: str, api_key: str) -> dict:
    """
    Split, OCR, and merge a PDF that exceeds Azure's size limit.
    Returns the same dict shape as run_batch.py's azure_only() so it can
    be dropped in as a direct replacement later.
    """
    stem = pdf_path.stem
    doc_folder = output_dir / stem
    doc_folder.mkdir(parents=True, exist_ok=True)
    out_pdf  = doc_folder / f"{stem}.pdf"
    out_json = doc_folder / f"{stem}.json"

    # Skip if already done
    if out_pdf.exists() and out_pdf.stat().st_size > 0 \
            and out_json.exists() and out_json.stat().st_size > 0:
        logger.info("⏭  Already exists, skipping: %s", stem)
        ocr = json.loads(out_json.read_text(encoding="utf-8"))
        return {"file": stem, "status": "api_done", "pages": len(ocr.get("pages", [])),
                "out_pdf": out_pdf, "out_json": out_json}

    file_mb = pdf_path.stat().st_size // (1024 * 1024)
    logger.info("📂 Processing large PDF: %s (%d MB)", stem, file_mb)

    chunk_paths: list[Path] = []
    try:
        chunk_paths = split_pdf_chunks(pdf_path)
        logger.info("Split into %d chunks", len(chunk_paths))

        chunk_pdfs: list[bytes] = []
        chunk_jsons: list[dict] = []

        for i, chunk_path in enumerate(chunk_paths):
            logger.info("Processing chunk %d/%d …", i + 1, len(chunk_paths))
            pdf_bytes, ocr_dict = _call_azure(chunk_path, endpoint, api_key)
            chunk_pdfs.append(pdf_bytes)
            chunk_jsons.append(ocr_dict)

        logger.info("Merging %d chunks …", len(chunk_paths))
        merged_json = merge_ocr_jsons(chunk_jsons)
        n_pages = len(merged_json.get("pages", []))

        merge_pdfs(chunk_pdfs, out_pdf)
        _atomic_write_text(out_json, json.dumps(merged_json, ensure_ascii=False, indent=2))

        logger.info("✅ %s → %d pages merged", stem, n_pages)
        return {"file": stem, "status": "api_done", "pages": n_pages,
                "out_pdf": out_pdf, "out_json": out_json}

    except Exception as e:
        logger.error("❌ %s failed: %s", stem, e)
        return {"file": stem, "status": "error", "error": str(e)}

    finally:
        for p in chunk_paths:
            p.unlink(missing_ok=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a PDF too large for Azure DI's 500 MB limit")
    parser.add_argument("pdf", type=Path, help="Path to the oversized PDF")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "output_large",
                        help="Output directory (default: output/output_large/)")
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_DI_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_API_KEY in .env")

    if not args.pdf.exists():
        sys.exit(f"File not found: {args.pdf}")

    file_mb = args.pdf.stat().st_size // (1024 * 1024)
    if file_mb < 400:
        logger.warning(
            "%s is only %d MB — you probably don't need this script. "
            "Use run_batch.py directly.", args.pdf.name, file_mb
        )

    result = process_large_pdf(args.pdf, args.output_dir, endpoint, api_key)
    print(json.dumps(result, default=str, indent=2))
