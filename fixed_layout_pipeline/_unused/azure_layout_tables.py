"""
Azure prebuilt-layout table extractor.

Calls Azure Document Intelligence ``prebuilt-layout`` (which supports
table extraction with proper rowspan/colspan and cell-type classification)
and converts the result into the pipeline's internal table format::

    {
        "bbox_pct":           [x0, y0, x1, y1],   # % of page dims
        "html":               "<table>…</table>",
        "n_rows":             int,
        "cell_line_height_pt": float,              # median cell height, inches
    }

One dict per table, grouped by page (0-indexed list of lists).

Note: ``prebuilt-layout`` does NOT support the searchable-PDF output option.
The pipeline therefore makes TWO Azure calls in ``gemini-enhance``:
  1. ``prebuilt-read``   → searchable PDF + line-level OCR JSON
  2. ``prebuilt-layout`` → tables only (run in parallel to avoid extra latency)
"""

from __future__ import annotations

import html as html_mod
import logging
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)


# ── HTML builder ──────────────────────────────────────────────────────────────

def _table_to_html(table: dict) -> str:
    """
    Convert an Azure prebuilt-layout table dict to a <table> HTML string.

    Handles:
    - rowSpan / columnSpan (merged cells)
    - cell kinds: columnHeader / rowHeader / stub → <th>, everything else → <td>
    - RTL direction (Arabic)
    """
    row_count: int = table.get("rowCount", 0)
    col_count: int = table.get("columnCount", 0)
    if row_count == 0 or col_count == 0:
        return ""

    cells = table.get("cells", [])

    # Determine which rows are "header" rows (all cells are columnHeader/stub)
    header_cell_kinds = {"columnHeader", "stub", "description"}
    row_is_header: dict[int, bool] = {}
    for ri in range(row_count):
        row_cells = [c for c in cells if c.get("rowIndex") == ri]
        if row_cells and all(c.get("kind", "content") in header_cell_kinds for c in row_cells):
            row_is_header[ri] = True
        else:
            row_is_header[ri] = False

    # Build a 2-D occupied map to skip cells already covered by a span
    occupied: set[tuple[int, int]] = set()

    def build_row(row_idx: int, tag: str) -> str:
        row_html = "    <tr>\n"
        for col_idx in range(col_count):
            if (row_idx, col_idx) in occupied:
                continue
            # Find cell at this position
            cell = next(
                (c for c in cells
                 if c.get("rowIndex") == row_idx and c.get("columnIndex") == col_idx),
                None,
            )
            if cell is None:
                row_html += f"      <{tag}></{tag}>\n"
                continue

            rs = cell.get("rowSpan", 1) or 1
            cs = cell.get("columnSpan", 1) or 1
            kind = cell.get("kind", "content")
            use_th = kind in ("columnHeader", "rowHeader", "stub")
            elem = "th" if use_th else tag
            text = html_mod.escape((cell.get("content") or "").strip())

            span_attrs = ""
            if rs > 1:
                span_attrs += f' rowspan="{rs}"'
            if cs > 1:
                span_attrs += f' colspan="{cs}"'

            row_html += f"      <{elem}{span_attrs}>{text}</{elem}>\n"

            # Mark spanned cells as occupied
            for dr in range(rs):
                for dc in range(cs):
                    if dr > 0 or dc > 0:
                        occupied.add((row_idx + dr, col_idx + dc))

        row_html += "    </tr>\n"
        return row_html

    # Find split point between <thead> and <tbody>
    last_header_row = -1
    for ri in range(row_count):
        if row_is_header.get(ri, False):
            last_header_row = ri
        else:
            break   # header rows must be contiguous from the top

    parts = ["<table>\n"]
    if last_header_row >= 0:
        parts.append("  <thead>\n")
        for ri in range(last_header_row + 1):
            parts.append(build_row(ri, "th"))
        parts.append("  </thead>\n")
        body_start = last_header_row + 1
    else:
        body_start = 0

    if body_start < row_count:
        parts.append("  <tbody>\n")
        for ri in range(body_start, row_count):
            parts.append(build_row(ri, "td"))
        parts.append("  </tbody>\n")

    parts.append("</table>")
    return "".join(parts)


# ── bbox helpers ──────────────────────────────────────────────────────────────

def _polygon_to_bbox_pct(polygon: list[float], page_w: float, page_h: float) -> list[float] | None:
    """Convert an 8-float Azure polygon to [x0_pct, y0_pct, x1_pct, y1_pct]."""
    if len(polygon) < 8 or page_w <= 0 or page_h <= 0:
        return None
    xs = [polygon[i] for i in range(0, 8, 2)]
    ys = [polygon[i] for i in range(1, 8, 2)]
    return [
        min(xs) / page_w * 100,
        min(ys) / page_h * 100,
        max(xs) / page_w * 100,
        max(ys) / page_h * 100,
    ]


def _cell_median_height(cells: list[dict]) -> float:
    """Return the median cell polygon height (page units, e.g. inches)."""
    heights = []
    for c in cells:
        brs = c.get("boundingRegions") or []
        if brs:
            poly = brs[0].get("polygon", [])
            if len(poly) >= 8:
                ys = [poly[i] for i in range(1, 8, 2)]
                h = max(ys) - min(ys)
                if h > 0:
                    heights.append(h)
    if not heights:
        return 0.0
    return median(heights)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_layout_tables(
    pdf_bytes: bytes,
    endpoint: str,
    api_key: str,
    pages: str | None = None,
) -> list[list[dict]]:
    """
    Call Azure prebuilt-layout and extract tables per page.

    Parameters
    ----------
    pdf_bytes : bytes
        Raw PDF bytes to analyse.
    endpoint : str
        Azure Document Intelligence endpoint URL.
    api_key : str
        Azure Document Intelligence API key.
    pages : str | None
        Optional page range, e.g. ``"1-5"``.

    Returns
    -------
    list[list[dict]]
        One inner list per page (0-indexed).  Each inner list contains table
        dicts ready to be passed directly to the pipeline::

            {
                "bbox_pct":            [x0, y0, x1, y1],
                "html":                "<table>…</table>",
                "n_rows":              int,
                "cell_line_height_pt": float,
            }
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential

    logger.info("Calling Azure prebuilt-layout for table extraction …")

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
    )

    poller = client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        pages=pages,
    )
    result = poller.result()
    data = result.as_dict()

    # Build page-dimension map (1-based page number → (width, height))
    page_dims: dict[int, tuple[float, float]] = {}
    for pg in data.get("pages", []):
        pn = pg.get("pageNumber", 0)
        w = float(pg.get("width") or 0)
        h = float(pg.get("height") or 0)
        if pn and w and h:
            page_dims[pn] = (w, h)

    raw_tables = data.get("tables", [])
    logger.info("prebuilt-layout: %d table(s) found", len(raw_tables))

    # Group by page number and determine max page
    max_page = max(page_dims.keys(), default=0)
    # Initialise output list (0-indexed, so length = max_page)
    per_page: list[list[dict]] = [[] for _ in range(max_page)]

    for tbl in raw_tables:
        brs = tbl.get("boundingRegions") or []
        if not brs:
            continue
        page_num = brs[0].get("pageNumber", 0)
        if page_num < 1 or page_num > max_page:
            continue

        dims = page_dims.get(page_num)
        if not dims:
            continue
        pw, ph = dims

        polygon = brs[0].get("polygon", [])
        bbox_pct = _polygon_to_bbox_pct(polygon, pw, ph)
        if not bbox_pct:
            continue

        table_html = _table_to_html(tbl)
        if not table_html:
            continue

        n_rows = tbl.get("rowCount", 1)
        cell_lh = _cell_median_height(tbl.get("cells", []))

        page_idx = page_num - 1   # 0-indexed
        per_page[page_idx].append({
            "bbox_pct": bbox_pct,
            "html": table_html,
            "n_rows": n_rows,
            "cell_line_height_pt": cell_lh,
        })

        logger.debug(
            "Page %d: table %dr×%dc  bbox_pct=[%.1f,%.1f,%.1f,%.1f]  cell_lh=%.4f",
            page_num, n_rows, tbl.get("columnCount", 0), *bbox_pct, cell_lh,
        )

    total = sum(len(p) for p in per_page)
    logger.info("prebuilt-layout: %d table(s) parsed into %d pages", total, max_page)
    return per_page
