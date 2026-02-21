"""
Reading Order Resolution — heuristic and model-based reading order repair.

Azure DI provides an initial reading order via paragraph sequence, but
complex Arabic documents (multi-column, tables, marginalia) may need
additional heuristic or LLM-based correction.

The reference document notes:
- "For strict reading order and geometry preservation, the 'glue' around
  OCR matters as much as OCR itself."
- "Reading order is a first-class evaluation target."
"""

from __future__ import annotations

import logging
from typing import Optional

from .schema import (
    Block,
    BlockType,
    Direction,
    Page,
    ReadingOrder,
    ReadingOrderMethod,
    ReadingOrderUnit,
)

logger = logging.getLogger(__name__)


def resolve_reading_order(
    page: Page,
    method: str = "heuristic",
) -> ReadingOrder:
    """
    Resolve or repair reading order for a page.

    Args:
        page: Page with blocks that need ordering.
        method: "engine" (keep Azure's order) or "heuristic" (rule-based).

    Returns:
        Updated ReadingOrder.
    """
    if method == "engine":
        # Keep the existing order from Azure
        return page.reading_order

    if method == "heuristic":
        return _heuristic_reading_order(page)

    logger.warning(f"Unknown method '{method}', falling back to heuristic")
    return _heuristic_reading_order(page)


def _heuristic_reading_order(page: Page) -> ReadingOrder:
    """
    Rule-based reading order for Arabic-primary documents.

    Strategy:
    1. Separate headers/footers/page numbers from body content.
    2. Detect columns by horizontal clustering of block centers.
    3. Within each column, sort top-to-bottom.
    4. For RTL pages: read right column first, then left.
    5. Tables are inserted at their vertical position.

    This follows the document's recommendation:
    "Prefer column-wise reading consistent with the layout."
    """
    if not page.blocks:
        return ReadingOrder()

    # Separate by role
    headers = []
    footers = []
    page_numbers = []
    body_blocks = []

    for block in page.blocks:
        if block.block_type == BlockType.HEADER:
            headers.append(block)
        elif block.block_type == BlockType.FOOTER:
            footers.append(block)
        elif block.block_type == BlockType.PAGE_NUMBER:
            page_numbers.append(block)
        else:
            body_blocks.append(block)

    # Sort headers top-to-bottom
    headers.sort(key=lambda b: b.bbox.y0)

    # Detect columns in body content
    columns = _detect_columns(body_blocks, page)

    # Build ordered sequence
    ordered_blocks = []

    # 1. Headers first
    ordered_blocks.extend(headers)

    # 2. Body columns
    if page.principal_direction == Direction.RTL:
        # Arabic: right column first
        columns.sort(key=lambda col: -_column_center_x(col))
    else:
        # LTR: left column first
        columns.sort(key=lambda col: _column_center_x(col))

    for column in columns:
        # Within column, sort top-to-bottom
        column.sort(key=lambda b: b.bbox.y0)
        ordered_blocks.extend(column)

    # 3. Footers and page numbers last
    footers.sort(key=lambda b: b.bbox.y0)
    ordered_blocks.extend(footers)
    ordered_blocks.extend(page_numbers)

    # Build ReadingOrder
    units = []
    sequence = []
    for block in ordered_blocks:
        unit = ReadingOrderUnit(
            unit_id=block.block_id,
            ref_block_id=block.block_id,
            ref_table_id=block.table.table_id if block.table else None,
        )
        units.append(unit)
        sequence.append(block.block_id)

    return ReadingOrder(
        units=units,
        sequence=sequence,
        confidence=0.70,
        method=ReadingOrderMethod.HEURISTIC,
    )


def _detect_columns(
    blocks: list[Block],
    page: Page,
) -> list[list[Block]]:
    """
    Detect column structure by clustering block centers horizontally.

    Uses a simple gap-based approach:
    1. Find horizontal gaps between blocks.
    2. If a significant gap exists, split into columns.
    """
    if not blocks:
        return []

    if len(blocks) == 1:
        return [blocks]

    page_width = page.image.width_px or 2480

    # Compute x-center for each block
    centers = [(block, (block.bbox.x0 + block.bbox.x1) / 2) for block in blocks]
    centers.sort(key=lambda c: c[1])

    # Find gaps between consecutive block centers
    columns: list[list[Block]] = [[]]

    # Minimum gap to consider a column break (20% of page width)
    min_gap = page_width * 0.15

    for i, (block, cx) in enumerate(centers):
        if i == 0:
            columns[-1].append(block)
            continue

        prev_cx = centers[i - 1][1]
        gap = cx - prev_cx

        # Also check for non-overlapping x extents
        prev_block = centers[i - 1][0]
        x_overlap = min(block.bbox.x1, prev_block.bbox.x1) - max(block.bbox.x0, prev_block.bbox.x0)

        if gap > min_gap and x_overlap < 0:
            # Start new column
            columns.append([block])
        else:
            columns[-1].append(block)

    # Filter out empty columns
    columns = [col for col in columns if col]

    # If we detected too many columns (>4), likely a false positive — merge
    if len(columns) > 4:
        logger.warning(
            f"Detected {len(columns)} columns, likely false positive. "
            f"Merging to single column."
        )
        return [blocks]

    logger.info(f"Detected {len(columns)} column(s)")
    return columns


def _column_center_x(column: list[Block]) -> float:
    """Average x-center of blocks in a column."""
    if not column:
        return 0.0
    return sum((b.bbox.x0 + b.bbox.x1) / 2 for b in column) / len(column)


# ─── Kendall Tau for evaluation ──────────────────────────────────────────────

def kendall_tau_distance(order_a: list[str], order_b: list[str]) -> float:
    """
    Compute normalised Kendall Tau distance between two orderings.

    Used for reading order evaluation:
    0.0 = identical order
    1.0 = completely reversed

    Both lists must contain the same elements.
    """
    if set(order_a) != set(order_b):
        # Only compare common elements
        common = set(order_a) & set(order_b)
        order_a = [x for x in order_a if x in common]
        order_b = [x for x in order_b if x in common]

    if len(order_a) <= 1:
        return 0.0

    # Map elements to their position in order_b
    pos_b = {elem: idx for idx, elem in enumerate(order_b)}

    # Count discordant pairs
    n = len(order_a)
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            # If the relative order differs between a and b
            if pos_b[order_a[i]] > pos_b[order_a[j]]:
                discordant += 1

    # Normalize by total pairs
    total_pairs = n * (n - 1) / 2
    return discordant / total_pairs if total_pairs > 0 else 0.0
