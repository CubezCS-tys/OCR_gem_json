"""
Azure Searchable PDF Generator.

Sends a scanned (analog) PDF to Azure Document Intelligence's prebuilt-read
model and retrieves a searchable PDF with an invisible text layer embedded
behind the page images.  The resulting file looks identical visually but
supports Ctrl-F text search and copy/paste.

Note: Azure's searchable-PDF output is currently only supported by the
``prebuilt-read`` model.  Other models (prebuilt-layout, custom, etc.)
will return an HTTP 400 error.

API flow
--------
1. ``begin_analyze_document("prebuilt-read", body, output=[PDF])``
2. Poll until ``poller.result()`` completes.
3. ``get_analyze_result_pdf(model_id, result_id)`` → ``Iterator[bytes]``
4. Write chunks to disk.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .config import AzureConfig

logger = logging.getLogger(__name__)


def generate_searchable_pdf(
    pdf_path: Path,
    output_path: Path,
    config: AzureConfig,
    *,
    pages: Optional[str] = None,
    output_json_path: Optional[Path] = None,
) -> Path:
    """
    Generate a searchable PDF from a scanned PDF via Azure DI (prebuilt-read).

    Args:
        pdf_path:         Path to the input (analog / scanned) PDF.
        output_path:      Where to write the searchable PDF.
        config:           Azure DI credentials (endpoint + api_key).
        pages:            Optional page range string, e.g. ``"1-3"`` (1-based).
        output_json_path: If provided, the Azure OCR result JSON is saved here.

    Returns:
        The *output_path* for convenience.

    Raises:
        FileNotFoundError: If ``pdf_path`` does not exist.
        ValueError:        If Azure credentials are missing.
        HttpResponseError: On any Azure API failure.
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )
    from azure.core.credentials import AzureKeyCredential

    # ── Validate inputs ──────────────────────────────────────────────────────
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    config.validate()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Read source PDF ──────────────────────────────────────────────────────
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    logger.info(
        "Sending %s (%.1f KB) to Azure DI prebuilt-read for searchable PDF...",
        pdf_path.name,
        len(pdf_bytes) / 1024,
    )
    start = time.time()

    # ── Call Azure DI ────────────────────────────────────────────────────────
    client = DocumentIntelligenceClient(
        endpoint=config.endpoint,
        credential=AzureKeyCredential(config.api_key),
    )

    poller = client.begin_analyze_document(
        model_id="prebuilt-read",                       # must be prebuilt-read
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        output=[AnalyzeOutputOption.PDF],               # request searchable PDF
        pages=pages,
    )

    result = poller.result()                             # blocks until done
    operation_id = poller.details["operation_id"]

    elapsed_analysis = time.time() - start
    logger.info(
        "Azure analysis complete in %.1fs  (model=%s, pages=%d)",
        elapsed_analysis,
        result.model_id,
        len(result.pages) if result.pages else 0,
    )

    # ── Save OCR JSON (Azure prebuilt-read result) ────────────────────────────
    if output_json_path is not None:
        output_json_path = Path(output_json_path)
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as jf:
            json.dump(result.as_dict(), jf, ensure_ascii=False, indent=2)
        logger.info("OCR JSON saved: %s", output_json_path)

    # ── Download the searchable PDF ──────────────────────────────────────────
    logger.info("Downloading searchable PDF (result_id=%s)...", operation_id)
    pdf_stream = client.get_analyze_result_pdf(
        model_id=result.model_id,
        result_id=operation_id,
    )

    bytes_written = 0
    with open(output_path, "wb") as out:
        for chunk in pdf_stream:
            out.write(chunk)
            bytes_written += len(chunk)

    elapsed_total = time.time() - start
    logger.info(
        "Searchable PDF saved: %s  (%.1f KB, %.1fs total)",
        output_path,
        bytes_written / 1024,
        elapsed_total,
    )

    return output_path


def generate_searchable_pdf_from_bytes(
    pdf_bytes: bytes,
    output_path: Path,
    config: AzureConfig,
    *,
    pages: Optional[str] = None,
    output_json_path: Optional[Path] = None,
) -> Path:
    """
    Same as :func:`generate_searchable_pdf` but accepts raw bytes.

    Useful when the PDF is already in memory (e.g. during pipeline
    processing).
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        AnalyzeOutputOption,
    )
    from azure.core.credentials import AzureKeyCredential

    config.validate()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Generating searchable PDF from in-memory bytes (%.1f KB)...",
        len(pdf_bytes) / 1024,
    )
    start = time.time()

    client = DocumentIntelligenceClient(
        endpoint=config.endpoint,
        credential=AzureKeyCredential(config.api_key),
    )

    poller = client.begin_analyze_document(
        model_id="prebuilt-read",
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        output=[AnalyzeOutputOption.PDF],
        pages=pages,
    )

    result = poller.result()
    operation_id = poller.details["operation_id"]

    # ── Save OCR JSON ────────────────────────────────────────────────────────
    if output_json_path is not None:
        output_json_path = Path(output_json_path)
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as jf:
            json.dump(result.as_dict(), jf, ensure_ascii=False, indent=2)
        logger.info("OCR JSON saved: %s", output_json_path)

    pdf_stream = client.get_analyze_result_pdf(
        model_id=result.model_id,
        result_id=operation_id,
    )

    bytes_written = 0
    with open(output_path, "wb") as out:
        for chunk in pdf_stream:
            out.write(chunk)
            bytes_written += len(chunk)

    elapsed = time.time() - start
    logger.info(
        "Searchable PDF saved: %s  (%.1f KB, %.1fs)",
        output_path,
        bytes_written / 1024,
        elapsed,
    )

    return output_path
