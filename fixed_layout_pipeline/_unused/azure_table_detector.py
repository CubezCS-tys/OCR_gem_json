"""
Azure-native table detector.

Reconstructs HTML <table> elements purely from the line bounding boxes that
Azure prebuilt-read already returns — no additional API call, no LLM.

Why this works
--------------
Azure ``prebuilt-read`` gives every text line a tight *polygon* (4 corners).
Inside a table, cells from different columns sit at the same vertical position
(Y-overlap) but different horizontal positions (X-separation).  We exploit
this structure:

Algorithm
---------
1. Convert lines to (x0, y0, x1, y1) rects.
2. Greedy Y-overlap clustering → row bands (lines in the same visual row).
3. Row bands with ≥ MIN_COLS lines are "candidate table rows".
4. Consecutive candidate rows whose vertical gap ≤ MAX_ROW_GAP_FACTOR ×
   median line height are merged into one candidate table.
5. Tables with ≥ MIN_ROWS candidate rows are kept.
6. Column assignment:
   a. Collect all X-centres from cells across all rows.
   b. 1-D gap clustering with threshold COL_MERGE_THRESH × page_width
      → column centre positions (sorted right-to-left for RTL Arabic).
   c. Each cell assigned to its nearest column bin.
   d. Missing cells produce empty <td>.
7. HTML rendered with <thead> for first row, <tbody> for the rest.

Returns a list of table dicts compatible with the existing pipeline::

    {"bbox_pct": [x0_pct, y0_pct, x1_pct, y1_pct], "html": "<table>...</table>"}

These are drop-in replacements for the Gemini-generated table dicts used in
``fuzzy_text_merger.merge_structural_into_azure_json``.
"""

from __future__ import annotations

import html as html_mod
import logging
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)

# ── Tuning knobs ──────────────────────────────────────────────────────────────

# Two lines are "co-row" if their Y-overlap fraction ≥ this value
# (relative to the shorter line's height).
_Y_OVERLAP_THRESH: float = 0.35

# A candidate table row must have at least this many cells (columns).
_MIN_COLS: int = 2

# A candidate table must have at least this many rows.
_MIN_ROWS: int = 2

# Max gap between consecutive rows (as a multiple of median line height).
# Larger values tolerate thick table borders / ruling lines.
_MAX_ROW_GAP_FACTOR: float = 3.5

# Two X-centres are in the same column if they are within this fraction
# of page width from each other.
_COL_MERGE_THRESH: float = 0.05   # 5 % of page width

# Padding added around the inferred table bbox (fraction of page dimension).
_BBOX_PAD: float = 0.003          # 0.3 %


# ── Internal helpers ──────────────────────────────────────────────────────────

def _line_to_rect(line: dict) -> dict[str, Any] | None:
    """Convert an Azure line (polygon list) to a compact rect dict."""
    poly = line.get("polygon", [])
    if len(poly) < 8:
        return None
    xs = [poly[i] for i in range(0, 8, 2)]
    ys = [poly[i] for i in range(1, 8, 2)]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 <= x0 or y1 <= y0:
        return None
    return {
        "line": line,
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "cx": (x0 + x1) / 2,
        "cy": (y0 + y1) / 2,
        "w": x1 - x0,
        "h": y1 - y0,
    }


def _cluster_rows(rects: list[dict]) -> list[list[dict]]:
    """
    Group rects into row bands using greedy Y-overlap merging.

    Sort by Y-centre, then merge a rect into the current band if its
    Y-interval overlaps the band's Y-envelope by ≥ _Y_OVERLAP_THRESH of the
    shorter height.  Otherwise start a new band.
    """
    if not rects:
        return []

    sorted_r = sorted(rects, key=lambda r: r["cy"])
    rows: list[list[dict]] = []
    cur_band = [sorted_r[0]]
    band_y0: float = sorted_r[0]["y0"]
    band_y1: float = sorted_r[0]["y1"]

    for r in sorted_r[1:]:
        overlap = min(band_y1, r["y1"]) - max(band_y0, r["y0"])
        shorter_h = min(band_y1 - band_y0, r["h"])
        if shorter_h > 0 and overlap / shorter_h >= _Y_OVERLAP_THRESH:
            # Extend current band
            cur_band.append(r)
            band_y0 = min(band_y0, r["y0"])
            band_y1 = max(band_y1, r["y1"])
        else:
            rows.append(cur_band)
            cur_band = [r]
            band_y0 = r["y0"]
            band_y1 = r["y1"]

    rows.append(cur_band)
    return rows


def _group_into_tables(
    rows: list[list[dict]],
    median_lh: float,
) -> list[list[list[dict]]]:
    """
    Collect consecutive multi-column row bands into candidate tables.

    A band qualifies if it has ≥ _MIN_COLS cells.  Consecutive qualifying
    bands are merged if the vertical gap between them is ≤
    _MAX_ROW_GAP_FACTOR × median_lh.  A candidate table is kept if it has
    ≥ _MIN_ROWS qualifying rows.
    """
    max_gap = _MAX_ROW_GAP_FACTOR * median_lh
    tables: list[list[list[dict]]] = []
    current: list[list[dict]] = []
    prev_y1: float = -1e9

    for band in rows:
        n = len(band)
        band_y0 = min(r["y0"] for r in band)
        band_y1 = max(r["y1"] for r in band)
        gap = band_y0 - prev_y1

        if n >= _MIN_COLS:
            if current and gap <= max_gap:
                current.append(band)
            else:
                # Flush old table
                if len(current) >= _MIN_ROWS:
                    tables.append(current)
                current = [band]
        else:
            # Non-table band — flush
            if len(current) >= _MIN_ROWS:
                tables.append(current)
            current = []

        prev_y1 = band_y1

    if len(current) >= _MIN_ROWS:
        tables.append(current)

    return tables


def _assign_columns(
    rows: list[list[dict]],
    page_w: float,
) -> tuple[list[list[tuple[int, dict]]], int]:
    """
    Assign each cell to a column index using 1-D gap clustering on X-centres.

    Returns (assigned_rows, n_cols) where assigned_rows is a list of
    [(col_idx, rect)] rows sorted by col_idx ascending.

    Columns are sorted right-to-left (Arabic RTL): col 0 = rightmost.
    """
    thresh = _COL_MERGE_THRESH * page_w
    all_cx = sorted(r["cx"] for row in rows for r in row)

    # 1-D gap clustering
    clusters: list[list[float]] = [[all_cx[0]]]
    for cx in all_cx[1:]:
        if cx - clusters[-1][-1] <= thresh:
            clusters[-1].append(cx)
        else:
            clusters.append([cx])

    # Column centres — sort right-to-left (descending X = Arabic col 1 first)
    col_centres = sorted(
        [sum(c) / len(c) for c in clusters],
        reverse=True,
    )
    n_cols = len(col_centres)

    def nearest_col(cx: float) -> int:
        return min(range(n_cols), key=lambda i: abs(col_centres[i] - cx))

    assigned: list[list[tuple[int, dict]]] = []
    for row in rows:
        assigned.append(
            sorted([(nearest_col(r["cx"]), r) for r in row], key=lambda t: t[0])
        )

    return assigned, n_cols


def _build_html(
    assigned_rows: list[list[tuple[int, dict]]],
    n_cols: int,
) -> str:
    """Build a <table> HTML string from (col_idx, rect) rows."""

    def cell_text(r: dict) -> str:
        return html_mod.escape((r["line"].get("content") or "").strip())

    def build_row(cells: list[tuple[int, dict]], tag: str) -> str:
        row_html = "    <tr>\n"
        col_cursor = 0
        for col_idx, r in cells:
            while col_cursor < col_idx:
                row_html += f"      <{tag}></{tag}>\n"
                col_cursor += 1
            row_html += f"      <{tag}>{cell_text(r)}</{tag}>\n"
            col_cursor += 1
        while col_cursor < n_cols:
            row_html += f"      <{tag}></{tag}>\n"
            col_cursor += 1
        row_html += "    </tr>\n"
        return row_html

    parts = ["<table>\n"]
    parts.append("  <thead>\n")
    parts.append(build_row(assigned_rows[0], "th"))
    parts.append("  </thead>\n")
    if len(assigned_rows) > 1:
        parts.append("  <tbody>\n")
        for row in assigned_rows[1:]:
            parts.append(build_row(row, "td"))
        parts.append("  </tbody>\n")
    parts.append("</table>")
    return "".join(parts)


# ── Public API ────────────────────────────────────────────────────────────────

def detect_tables_from_azure_lines(
    lines: list[dict],
    page_w: float,
    page_h: float,
) -> list[dict]:
    """
    Detect tables in a page and build HTML <table> elements from Azure line data.

    Parameters
    ----------
    lines :
        Azure prebuilt-read line dicts for one page, each with ``"polygon"``
        (8 floats, inches) and ``"content"`` (string).
    page_w, page_h :
        Page dimensions in the same units as the polygon coordinates (inches).

    Returns
    -------
    list of dicts::

        {"bbox_pct": [x0, y0, x1, y1], "html": "<table>...</table>"}

    where ``bbox_pct`` values are 0–100 percentages of the page dimensions.
    Returns ``[]`` if no tables are detected or inputs are invalid.
    """
    if not lines or page_w <= 0 or page_h <= 0:
        return []

    rects = [_line_to_rect(ln) for ln in lines]
    rects = [r for r in rects if r is not None]
    if not rects:
        return []

    # Median line height (used for row-gap tolerance)
    med_lh = median(r["h"] for r in rects)
    if med_lh <= 0:
        return []

    rows = _cluster_rows(rects)
    table_groups = _group_into_tables(rows, med_lh)

    if not table_groups:
        return []

    result: list[dict] = []
    for table_rows in table_groups:
        all_rects = [r for row in table_rows for r in row]

        # Compute bbox with small padding
        x0 = max(0.0, min(r["x0"] for r in all_rects) - _BBOX_PAD * page_w)
        y0 = max(0.0, min(r["y0"] for r in all_rects) - _BBOX_PAD * page_h)
        x1 = min(page_w, max(r["x1"] for r in all_rects) + _BBOX_PAD * page_w)
        y1 = min(page_h, max(r["y1"] for r in all_rects) + _BBOX_PAD * page_h)

        bbox_pct = [
            x0 / page_w * 100,
            y0 / page_h * 100,
            x1 / page_w * 100,
            y1 / page_h * 100,
        ]

        assigned, n_cols = _assign_columns(table_rows, page_w)
        table_html = _build_html(assigned, n_cols)

        # Median height of a single table cell line (in page units, e.g. inches).
        # Used by the renderer to set a sensible per-table font size that is
        # derived from the actual cells, not from surrounding body text.
        cell_heights = [r["h"] for row in table_rows for r in row]
        cell_lh = sorted(cell_heights)[len(cell_heights) // 2] if cell_heights else 0.0

        n_rows = len(table_rows)

        logger.debug(
            "Azure table detected: %d rows × %d cols  bbox_pct=[%.1f,%.1f,%.1f,%.1f]  cell_lh=%.4f",
            n_rows, n_cols, *bbox_pct, cell_lh,
        )

        result.append({
            "bbox_pct": bbox_pct,
            "html": table_html,
            "n_rows": n_rows,
            "cell_line_height_pt": cell_lh,   # page units (inches)
        })

    logger.info(
        "azure_table_detector: %d table(s) found on this page",
        len(result),
    )
    return result
