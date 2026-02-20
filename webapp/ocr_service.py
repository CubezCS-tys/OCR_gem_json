"""
OCR Service — wraps existing pipelines without modifying them.

All Azure work uses a single prebuilt-read call ($1.50/1K pages) which
produces the searchable PDF, OCR JSON, and overlay HTML in one shot.
Gemini and Mistral run on top of those outputs.

Output formats:
  1. Searchable PDF    (Azure prebuilt-read)
  2. Pixel-Perfect HTML (overlay_renderer on prebuilt-read JSON)
  3. Semantic HTML      (gemini_html.render on prebuilt-read JSON + PDF)
  4. Markdown + Images  (Mistral OCR pipeline — independent)
"""

from __future__ import annotations

import io
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF — for page counting
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp"}
SUPPORTED_PDF_EXTS = {".pdf"}


def _is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_IMAGE_EXTS


def _is_pdf(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_PDF_EXTS


# ---------------------------------------------------------------------------
# Page counting (free, instant, no API call)
# ---------------------------------------------------------------------------

def count_pages(file_bytes: bytes, filename: str) -> int:
    """Count pages in a PDF or return 1 for images."""
    if _is_image(filename):
        return 1
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return 1


# ---------------------------------------------------------------------------
# Image → PDF helper
# ---------------------------------------------------------------------------

def _image_to_pdf_bytes(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=300)
    return buf.getvalue()


def _ensure_pdf(file_bytes: bytes, filename: str, work_dir: Path) -> Path:
    """Write input to disk as a PDF (converting images if needed)."""
    pdf_path = work_dir / "input.pdf"
    if _is_image(filename):
        pdf_path.write_bytes(_image_to_pdf_bytes(file_bytes))
    else:
        pdf_path.write_bytes(file_bytes)
    return pdf_path


# ---------------------------------------------------------------------------
# Individual pipeline workers (each runs in its own thread)
# ---------------------------------------------------------------------------

def _run_azure(pdf_path: Path, work_dir: Path, formats: list[str]) -> dict[str, Path | None]:
    """Azure prebuilt-read → searchable PDF + pixel-perfect HTML."""
    partial: dict[str, Path | None] = {}
    try:
        from fixed_layout_pipeline.batch_pipeline import process_one
        from fixed_layout_pipeline.config import AzureConfig

        config = AzureConfig()
        config.validate()

        azure_out = work_dir / "azure_output"
        azure_out.mkdir(parents=True, exist_ok=True)

        res = process_one(
            pdf_path=pdf_path,
            output_dir=azure_out,
            endpoint=config.endpoint,
            api_key=config.api_key,
            dpi=300,
            render_mode="replace-text",
        )

        doc_folder = azure_out / pdf_path.stem
        spdf  = doc_folder / f"{pdf_path.stem}_searchable.pdf"
        html_ = doc_folder / f"{pdf_path.stem}_replace_text.html"

        if spdf.exists():
            if "searchable_pdf" in formats:
                partial["searchable_pdf"] = spdf
            if "pixel_html" in formats:
                partial["pixel_html"] = html_ if html_.exists() else None
            logger.info("Azure done (status=%s)", res.get("status"))
        else:
            logger.error("Azure returned no PDF: %s", res)
            for f in ["searchable_pdf", "pixel_html"]:
                if f in formats:
                    partial[f] = None
    except Exception as e:
        logger.error("Azure pipeline failed: %s", e)
        for f in ["searchable_pdf", "pixel_html"]:
            if f in formats:
                partial[f] = None
    return partial


def _run_gemini(pdf_path: Path, work_dir: Path, stem: str) -> dict[str, Path | None]:
    """Gemini (pdf_to_html.py) → semantic HTML."""
    try:
        import sys as _sys
        root = str(Path(__file__).resolve().parent.parent)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from pdf_to_html import pdf_to_html as _pdf_to_html
        sem_path = work_dir / f"{stem}_semantic.html"
        res = _pdf_to_html(str(pdf_path), str(sem_path))
        result = sem_path if sem_path.exists() else None
        logger.info("Gemini done — %s", res.get("method"))
        return {"semantic_html": result}
    except Exception as e:
        logger.error("Gemini/semantic HTML failed: %s", e)
        return {"semantic_html": None}


def _run_mistral(pdf_path: Path, work_dir: Path) -> dict[str, Path | None]:
    """Mistral OCR Pass 1 only → raw markdown (no LLM structuring pass)."""
    try:
        from mistral_ocr_pipeline import MistralOCRPipeline, MistralPipelineConfig

        mistral_out = work_dir / "mistral_output"
        mistral_out.mkdir(parents=True, exist_ok=True)

        # Minimal config — Pass 2 options are irrelevant since we skip it
        config = MistralPipelineConfig(output_dir=str(mistral_out))
        pipeline = MistralOCRPipeline(config)

        # Pass 1 only: upload → OCR
        file_id = pipeline._upload_pdf(str(pdf_path))
        ocr_pages = pipeline._run_ocr(file_id)

        # Write the raw OCR markdown
        stem = pdf_path.stem
        md_path = mistral_out / f"{stem}_raw_ocr.md"
        with open(md_path, "w", encoding="utf-8") as f:
            for pg in ocr_pages:
                f.write(f"\n\n---\n## PAGE {pg['page_index'] + 1}\n\n")
                f.write(pg["markdown"])

        # Save any images extracted by Mistral OCR into images/
        import base64 as _b64
        images_dir = mistral_out / "images"
        img_count = 0
        for pg in ocr_pages:
            for img in pg.get("images", []):
                b64 = img.get("image_base64")
                if not b64:
                    continue
                images_dir.mkdir(parents=True, exist_ok=True)
                img_id = img.get("id") or f"img{img_count}"
                img_path = images_dir / f"page{pg['page_index'] + 1}_{img_id}.png"
                try:
                    # Strip data-URI prefix if present
                    raw = b64.split(",", 1)[-1] if "," in b64 else b64
                    img_path.write_bytes(_b64.b64decode(raw))
                    img_count += 1
                except Exception as img_err:
                    logger.warning("Could not save image %s: %s", img_id, img_err)

        logger.info(
            "Mistral OCR done (Pass 1 only) — %d pages, %d images → %s",
            len(ocr_pages), img_count, md_path.name,
        )
        partial: dict[str, Path | None] = {"markdown": md_path}
        if img_count:
            partial["mistral_images_dir"] = images_dir
        return partial
    except Exception as e:
        logger.error("Mistral pipeline failed: %s", e)
        return {"markdown": None}


# ---------------------------------------------------------------------------
# Main processing — Azure + Gemini + Mistral in parallel
# ---------------------------------------------------------------------------

def process_document(
    file_bytes: bytes,
    filename: str,
    work_dir: Path,
    formats: list[str],
) -> dict[str, Path | None]:
    """
    Run Azure, Gemini and Mistral concurrently in a thread pool.
    Each pipeline is independent — a failure in one doesn't block the others.
    Returns a dict mapping format names to output file paths.
    """
    import sys
    from concurrent.futures import ThreadPoolExecutor, as_completed

    parent = str(Path(__file__).resolve().parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    pdf_path = _ensure_pdf(file_bytes, filename, work_dir)
    stem = Path(filename).stem
    results: dict[str, Path | None] = {}

    need_azure   = any(f in formats for f in ["searchable_pdf", "pixel_html"])
    need_gemini  = "semantic_html" in formats
    need_mistral = "markdown" in formats

    futures = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if need_azure:
            futures["azure"]   = pool.submit(_run_azure,   pdf_path, work_dir, formats)
        if need_gemini:
            futures["gemini"]  = pool.submit(_run_gemini,  pdf_path, work_dir, stem)
        if need_mistral:
            futures["mistral"] = pool.submit(_run_mistral, pdf_path, work_dir)

        for name, fut in futures.items():
            try:
                results.update(fut.result())
            except Exception as e:
                logger.error("%s future raised: %s", name, e)

    logger.info(
        "Parallel processing complete — produced: %s",
        [k for k, v in results.items() if v is not None],
    )
    return results


# ---------------------------------------------------------------------------
# ZIP packaging — bundle all outputs into a single download
# ---------------------------------------------------------------------------

def package_results(results: dict[str, Path | None], stem: str, work_dir: Path) -> Path:
    """
    Package all results into a ZIP file for download.
    Returns path to the ZIP.
    """
    zip_path = work_dir / f"{stem}_scantotext.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, path in results.items():
            if path is None:
                continue
            if isinstance(path, Path) and path.is_dir():
                # Always nest directory results under images/
                for f in path.rglob("*"):
                    if f.is_file():
                        arcname = f"images/{f.name}"
                        zf.write(f, arcname)
            elif isinstance(path, Path) and path.is_file():
                # Map to nice filenames
                nice_names = {
                    "searchable_pdf": f"{stem}_searchable.pdf",
                    "pixel_html": f"{stem}_pixel_perfect.html",
                    "semantic_html": f"{stem}_semantic.html",
                    "gemini_html": f"{stem}_gemini_semantic.html",
                    "markdown": f"{stem}.md",
                }
                arcname = nice_names.get(key, path.name)
                zf.write(path, arcname)

    return zip_path


# ---------------------------------------------------------------------------
# Free tier: searchable PDF only (no subscription needed)
# ---------------------------------------------------------------------------

def generate_searchable_pdf_only(
    file_bytes: bytes,
    filename: str,
    work_dir: Path,
) -> Path:
    """Free tier: just searchable PDF."""
    import sys
    parent = str(Path(__file__).resolve().parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    from fixed_layout_pipeline.config import AzureConfig
    from fixed_layout_pipeline.searchable_pdf import (
        generate_searchable_pdf,
        generate_searchable_pdf_from_bytes,
    )

    config = AzureConfig()
    config.validate()
    output_path = work_dir / f"{Path(filename).stem}_searchable.pdf"

    if _is_pdf(filename):
        input_pdf = work_dir / "input.pdf"
        input_pdf.write_bytes(file_bytes)
        generate_searchable_pdf(input_pdf, output_path, config)
    else:
        pdf_bytes = _image_to_pdf_bytes(file_bytes)
        generate_searchable_pdf_from_bytes(pdf_bytes, output_path, config)

    return output_path
