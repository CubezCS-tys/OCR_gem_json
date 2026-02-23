"""
correction_api.py — FastAPI router for OCR Correction Tool.

Endpoints
---------
GET  /api/corrections/tool                   → Serve correction_tool.html
GET  /api/corrections/docs                   → List available documents
GET  /api/corrections/docs/{doc_id}          → Serve replace_text.html for a doc
POST /api/corrections/docs/{doc_id}          → Save corrected HTML
GET  /api/corrections/docs/{doc_id}/corrected → Serve saved corrected version
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("scantotext.corrections")

# ── Paths ──────────────────────────────────────────────────────────────────
_REPO_DIR        = Path(__file__).parent.parent
BATCH_DIR        = _REPO_DIR / "batch1_flp"
TOOL_PATH        = Path(__file__).parent / "correction_tool.html"
CORRECTIONS_DIR  = Path(__file__).parent / "corrections"
CORRECTIONS_DIR.mkdir(exist_ok=True)

# ── Router ─────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/corrections", tags=["corrections"])


# ── Models ─────────────────────────────────────────────────────────────────
class SaveRequest(BaseModel):
    html_content: str


# ── Helpers ────────────────────────────────────────────────────────────────
def _find_source_html(doc_id: str) -> Path | None:
    """
    Look for a replace_text HTML for the given doc_id.
    Search order:
      1. batch1_flp/{doc_id}/{doc_id}_replace_text.html   (standard batch output)
      2. batch1_flp/{doc_id}/replace_text.html            (older naming)
      3. webapp/uploads/{doc_id}/replace_text.html        (user uploads)
    """
    candidates = [
        BATCH_DIR / doc_id / f"{doc_id}_replace_text.html",
        BATCH_DIR / doc_id / "replace_text.html",
        Path(__file__).parent / "uploads" / doc_id / "replace_text.html",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _list_docs() -> list[dict]:
    """Return a list of doc metadata dicts from batch1_flp."""
    docs = []
    if not BATCH_DIR.is_dir():
        return docs

    for doc_dir in sorted(BATCH_DIR.iterdir()):
        if not doc_dir.is_dir():
            continue
        doc_id = doc_dir.name
        html_path = _find_source_html(doc_id)
        if html_path is None:
            continue

        # Count pages by scanning .page occurrences (fast heuristic)
        try:
            content = html_path.read_text(errors="replace")
            page_count = content.count('class="page"') or content.count("class='page'")
        except OSError:
            page_count = 0

        corrected = (CORRECTIONS_DIR / f"{doc_id}_corrected.html").is_file()

        docs.append({
            "doc_id": doc_id,
            "html_size": html_path.stat().st_size,
            "page_count": page_count,
            "has_correction": corrected,
        })

    return docs


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/tool", summary="Serve the OCR correction tool")
async def serve_tool() -> FileResponse:
    if not TOOL_PATH.is_file():
        raise HTTPException(status_code=404, detail="correction_tool.html not found")
    return FileResponse(TOOL_PATH, media_type="text/html")


@router.get("/docs", summary="List available documents")
async def list_docs() -> JSONResponse:
    return JSONResponse({"docs": _list_docs()})


@router.get("/docs/{doc_id}", summary="Get source replace_text HTML for a document")
async def get_doc(doc_id: str) -> FileResponse:
    # Security: prevent path traversal
    if ".." in doc_id or "/" in doc_id or "\\" in doc_id:
        raise HTTPException(status_code=400, detail="Invalid doc_id")

    # Prefer corrected version if it exists
    corrected = CORRECTIONS_DIR / f"{doc_id}_corrected.html"
    if corrected.is_file():
        return FileResponse(corrected, media_type="text/html")

    html_path = _find_source_html(doc_id)
    if html_path is None:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

    return FileResponse(html_path, media_type="text/html")


@router.post("/docs/{doc_id}", summary="Save corrected HTML for a document")
async def save_doc(doc_id: str, body: SaveRequest) -> JSONResponse:
    if ".." in doc_id or "/" in doc_id or "\\" in doc_id:
        raise HTTPException(status_code=400, detail="Invalid doc_id")

    if not body.html_content.strip():
        raise HTTPException(status_code=400, detail="html_content is empty")

    out_path = CORRECTIONS_DIR / f"{doc_id}_corrected.html"
    try:
        out_path.write_text(body.html_content, encoding="utf-8")
    except OSError as e:
        logger.error("Failed to save correction for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail="Failed to write file")

    logger.info("Saved correction for %s → %s (%d bytes)", doc_id, out_path, len(body.html_content))
    return JSONResponse({"status": "ok", "doc_id": doc_id, "bytes": len(body.html_content)})


@router.get("/docs/{doc_id}/corrected", summary="Get saved corrected HTML")
async def get_corrected(doc_id: str) -> FileResponse:
    if ".." in doc_id or "/" in doc_id or "\\" in doc_id:
        raise HTTPException(status_code=400, detail="Invalid doc_id")

    corrected = CORRECTIONS_DIR / f"{doc_id}_corrected.html"
    if not corrected.is_file():
        raise HTTPException(status_code=404, detail=f"No correction saved for '{doc_id}'")

    return FileResponse(corrected, media_type="text/html")
