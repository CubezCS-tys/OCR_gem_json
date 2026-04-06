"""
Fuzzy text merger — combines Azure geometry with Gemini text quality.

Problem
-------
Azure Document Intelligence (prebuilt-read) gives excellent bounding-box
geometry but can misread characters in degraded / Arabic-primary scans.
Gemini's vision model reads Arabic, French, and mixed-script text more
accurately, but returns no geometry.

Solution
--------
For every Azure OCR *line* (which has a tight polygon on the page) we find
the most similar line in Gemini's extracted text and replace
``line["content"]`` with Gemini's version, keeping Azure's polygon intact.

The existing overlay renderer (overlay_renderer.py) consumes lines at
exactly this level, so no other changes are needed downstream.

Matching strategy
-----------------
1.  Split Gemini's per-page text into candidate lines on ``\\n``.
2.  For each Azure line, search a sliding window (±window_radius) around a
    running cursor in the Gemini line list.
3.  Score with ``token_sort_ratio`` (handles minor word-order differences
    and differing amounts of diacritics) plus ``partial_ratio`` (handles
    Azure line being a subset/superset of Gemini line).  Take the max.
4.  Accept matches ≥ min_similarity.  Advance the cursor on a match; nudge
    it slightly on a miss so lines stay roughly in sync.
5.  Never reuse a Gemini line for two Azure lines.

Tuning tips
-----------
- Lower  min_similarity (e.g. 45) → more aggressive replacement (risky if
  lines differ substantially).
- Higher min_similarity (e.g. 75) → conservative; only very close matches
  are replaced.
- Larger window_radius → tolerates Gemini inserting / missing lines.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from .azure_table_detector import detect_tables_from_azure_lines

logger = logging.getLogger(__name__)

# ── Fuzzy backend ─────────────────────────────────────────────────────────────

try:
    from rapidfuzz import fuzz as _rfuzz  # type: ignore[import]

    def _score(a: str, b: str) -> float:
        """Combined similarity: higher of token-sort and partial ratios."""
        return max(
            _rfuzz.token_sort_ratio(a, b),
            _rfuzz.partial_ratio(a, b),
        )

    _BACKEND = "rapidfuzz"

except ImportError:
    from difflib import SequenceMatcher

    def _score(a: str, b: str) -> float:  # type: ignore[misc]
        """Character-level similarity via difflib (fallback)."""
        a_low, b_low = a.lower(), b.lower()
        ratio = SequenceMatcher(None, a_low, b_low).ratio() * 100.0
        # Rough partial-match approximation: check if shorter is in longer
        shorter, longer = (a_low, b_low) if len(a) <= len(b) else (b_low, a_low)
        if shorter and shorter in longer:
            return max(ratio, 85.0)
        return ratio

    _BACKEND = "difflib"

logger.debug("fuzzy_text_merger: using %s backend", _BACKEND)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bbox_pct_to_polygon(
    bbox_pct: list[float], page_w: float, page_h: float
) -> list[float]:
    """
    Convert a Gemini bbox_pct [x0,y0,x1,y1] to an Azure-style flat polygon.

    Azure polygons are 8 floats in page-unit coordinates (usually inches),
    ordered clockwise from top-left: [x0,y0, x1,y0, x1,y1, x0,y1].
    """
    x0 = bbox_pct[0] / 100.0 * page_w
    y0 = bbox_pct[1] / 100.0 * page_h
    x1 = bbox_pct[2] / 100.0 * page_w
    y1 = bbox_pct[3] / 100.0 * page_h
    return [x0, y0, x1, y0, x1, y1, x0, y1]


# ── Public API ────────────────────────────────────────────────────────────────


def merge_gemini_text_into_azure_json(
    azure_result: dict,
    gemini_pages: list[list[dict]],
    *,
    min_similarity: float = 58.0,
    window_radius: int = 10,
    update_top_level_content: bool = True,
) -> dict:
    """
    Return an enhanced Azure OCR result with Gemini's text substituted in,
    and Azure-missed lines injected as synthetic entries.

    Parameters
    ----------
    azure_result :
        Raw dict from ``result.as_dict()`` (Azure DI prebuilt-read).
    gemini_pages :
        Per-page structured lines from
        :func:`gemini_text_extractor.extract_text_from_pdf`.
        Each page is a list of ``{"text": str, "bbox_pct": [x0,y0,x1,y1]}``.
    min_similarity :
        Fuzzy score threshold (0–100) to accept a match.
        58 is a good default for Arabic (diacritics vary between Azure/Gemini).
    window_radius :
        ±lines around the running cursor to search for a match.
        Larger values tolerate Gemini inserting / skipping blank lines.
    update_top_level_content :
        Rebuild the document-level ``"content"`` field from updated lines.

    Returns
    -------
    dict
        Deep copy of ``azure_result`` with:
        - ``line["content"]`` replaced by Gemini text where matched.
        - Extra synthetic lines appended for Gemini lines with no Azure match,
          tagged ``"_source": "gemini_fallback"`` for debuggability.
    """
    result = copy.deepcopy(azure_result)
    pages: list[dict[str, Any]] = result.get("pages", [])

    stats_replaced = 0
    stats_skipped = 0
    stats_injected = 0
    stats_no_gemini = 0

    for page_idx, page in enumerate(pages):
        if page_idx >= len(gemini_pages):
            logger.debug("Page %d: no Gemini data — keeping Azure as-is", page_idx + 1)
            stats_no_gemini += len(page.get("lines", []))
            continue

        gem_lines: list[dict] = gemini_pages[page_idx]
        if not gem_lines:
            logger.debug("Page %d: Gemini returned no lines — keeping Azure", page_idx + 1)
            stats_no_gemini += len(page.get("lines", []))
            continue

        # Page dimensions (inches) — needed to synthesise polygons
        page_w: float = float(page.get("width") or 0)
        page_h: float = float(page.get("height") or 0)

        azure_lines: list[dict[str, Any]] = page.get("lines", [])

        used_gem: set[int] = set()
        gem_cursor: int = 0
        replaced = 0
        skipped = 0

        # ── Pass 1: match each Azure line to a Gemini line ───────────────────
        for line in azure_lines:
            az_text = (line.get("content") or "").strip()
            if not az_text:
                continue

            lo = max(0, gem_cursor - window_radius)
            hi = min(len(gem_lines), gem_cursor + window_radius + 1)

            best_score: float = 0.0
            best_gi: int = -1

            for gi in range(lo, hi):
                if gi in used_gem:
                    continue
                s = _score(az_text, gem_lines[gi]["text"])
                if s > best_score:
                    best_score = s
                    best_gi = gi

            if best_score >= min_similarity and best_gi >= 0:
                new_text = gem_lines[best_gi]["text"]
                if new_text != az_text:
                    logger.debug(
                        "p%d  %.0f%%  '%s'  →  '%s'",
                        page_idx + 1, best_score,
                        az_text[:50], new_text[:50],
                    )
                line["content"] = new_text
                used_gem.add(best_gi)
                gem_cursor = best_gi + 1
                replaced += 1
            else:
                gem_cursor = min(len(gem_lines), gem_cursor + 1)
                skipped += 1

        # ── Pass 2: inject Gemini lines that Azure missed entirely ───────────
        injected = 0
        if page_w > 0 and page_h > 0:
            for gi, gem_line in enumerate(gem_lines):
                if gi in used_gem:
                    continue
                bbox_pct = gem_line.get("bbox_pct")
                if not bbox_pct:
                    continue
                polygon = _bbox_pct_to_polygon(bbox_pct, page_w, page_h)
                synthetic: dict[str, Any] = {
                    "content": gem_line["text"],
                    "polygon": polygon,
                    "_source": "gemini_fallback",
                }
                azure_lines.append(synthetic)
                injected += 1
                logger.debug(
                    "p%d  injected (Azure missed): '%s'",
                    page_idx + 1, gem_line["text"][:60],
                )
        else:
            unclaimed = sum(1 for gi in range(len(gem_lines)) if gi not in used_gem)
            if unclaimed:
                logger.warning(
                    "Page %d: %d Gemini-only lines could not be injected "
                    "(page dimensions missing from Azure JSON)",
                    page_idx + 1, unclaimed,
                )

        pct = 100.0 * replaced / max(1, len(azure_lines))
        logger.info(
            "Page %d: %d/%d lines replaced (%.0f%%), %d unmatched, %d injected",
            page_idx + 1, replaced, len(azure_lines), pct, skipped, injected,
        )
        stats_replaced += replaced
        stats_skipped += skipped
        stats_injected += injected

    # ── Rebuild top-level content ────────────────────────────────────────────
    if update_top_level_content and "content" in result:
        all_lines: list[str] = []
        for page in pages:
            for line in page.get("lines", []):
                c = line.get("content", "")
                if c:
                    all_lines.append(c)
        result["content"] = "\n".join(all_lines)

    logger.info(
        "Fuzzy merge complete — replaced: %d, unmatched: %d, "
        "injected (Azure-missed): %d, no-gemini: %d",
        stats_replaced, stats_skipped, stats_injected, stats_no_gemini,
    )
    return result


# ── Overlap helpers for table/equation suppression ────────────────────────────


def _azure_line_bbox_pct(
    line: dict, page_w: float, page_h: float
) -> tuple[float, float, float, float] | None:
    """
    Convert an Azure line polygon to (x0_pct, y0_pct, x1_pct, y1_pct).
    Returns None if polygon is missing or page dimensions are zero.
    """
    polygon = line.get("polygon", [])
    if len(polygon) < 8 or page_w <= 0 or page_h <= 0:
        return None
    xs = [polygon[i] for i in range(0, 8, 2)]
    ys = [polygon[i] for i in range(1, 8, 2)]
    x0 = min(xs) / page_w * 100.0
    y0 = min(ys) / page_h * 100.0
    x1 = max(xs) / page_w * 100.0
    y1 = max(ys) / page_h * 100.0
    return (x0, y0, x1, y1)


def _overlap_fraction(
    ax0: float, ay0: float, ax1: float, ay1: float,
    bx0: float, by0: float, bx1: float, by1: float,
) -> float:
    """
    Fraction of rect A that is covered by rect B.
    All coords in the same unit system (e.g. percentages).
    """
    a_area = (ax1 - ax0) * (ay1 - ay0)
    if a_area <= 0:
        return 0.0
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0) / a_area


# ── Structural merge (text + tables + equations) ─────────────────────────────


def merge_structural_into_azure_json(
    azure_result: dict,
    gemini_pages: list[dict],
    *,
    min_similarity: float = 58.0,
    min_length_ratio: float = 0.55,
    window_radius: int = 10,
    overlap_threshold: float = 0.40,
    update_top_level_content: bool = True,
    layout_tables_by_page: list[list[dict]] | None = None,
    inject_unmatched: bool = True,
    protect_table_lines: bool = False,
) -> dict:
    """
    Merge Gemini structural extraction into Azure OCR JSON.

    This is the unified replacement for the old text-only merge +
    separate equation pipeline.

    For each page:
    1. Identify Azure lines that overlap table/equation bounding
       boxes by ≥ ``overlap_threshold`` — these are **suppressed** (removed
       from the Azure lines) because they'll be replaced by real HTML
       tables or MathJax equations.
    2. Fuzzy-merge remaining Azure lines with Gemini text lines
       (same algorithm as ``merge_gemini_text_into_azure_json``).
    3. Attach tables and equations to the page dict for the renderer.

    Parameters
    ----------
    azure_result :
        Raw dict from Azure DI ``prebuilt-read``.
    gemini_pages :
        Per-page structural dicts from
        :func:`gemini_structural_extractor.extract_structural_from_pdf`.
        Each page has ``"lines"``, ``"tables"``, ``"equations"``.
    min_similarity :
        Fuzzy threshold for text-line matching (0–100).
    window_radius :
        ±lines around cursor for fuzzy search.
    overlap_threshold :
        Fraction of Azure line bbox that must be inside a table/equation
        region for the line to be suppressed (0–1).  0.40 = suppress if
        40%+ of the line is inside the region.
    update_top_level_content :
        Rebuild document-level ``"content"`` from merged lines.
    layout_tables_by_page :
        Optional list of per-page table lists produced by
        :func:`azure_layout_tables.extract_layout_tables`.  When provided,
        these authoritative tables (from ``prebuilt-layout``) are used
        **instead of** the geometric detector for every page.  Pass
        ``None`` (default) to fall back to ``azure_table_detector``.

    Returns
    -------
    dict
        Enhanced Azure result with:
        - ``line["content"]`` replaced by Gemini text where fuzzy-matched
        - Lines inside table/equation regions removed
        - ``page["_tables"]`` — list of table dicts
        - ``page["_equations"]`` — list of Gemini equation dicts
        - Synthetic lines injected for Gemini text lines Azure missed
    """
    result = copy.deepcopy(azure_result)
    pages: list[dict[str, Any]] = result.get("pages", [])

    stats = {
        "replaced": 0,
        "skipped": 0,
        "injected": 0,
        "suppressed": 0,
        "tables": 0,
        "equations": 0,
        "no_gemini": 0,
    }

    for page_idx, page in enumerate(pages):
        if page_idx >= len(gemini_pages):
            logger.debug("Page %d: no Gemini data — running table detection only", page_idx + 1)
            stats["no_gemini"] += len(page.get("lines", []))
            if protect_table_lines:
                page["_tables"] = []
            elif layout_tables_by_page is not None and page_idx < len(layout_tables_by_page):
                page["_tables"] = layout_tables_by_page[page_idx]
                logger.debug("Page %d: using %d prebuilt-layout table(s)",
                             page_idx + 1, len(page["_tables"]))
            else:
                page_w_ng: float = float(page.get("width") or 0)
                page_h_ng: float = float(page.get("height") or 0)
                page["_tables"] = detect_tables_from_azure_lines(
                    page.get("lines", []), page_w_ng, page_h_ng
                )
            page["_equations"] = []
            stats["tables"] += len(page["_tables"])
            continue

        gem_data = gemini_pages[page_idx]
        gem_lines: list[dict] = gem_data.get("lines", [])
        gem_equations: list[dict] = gem_data.get("equations", [])

        page_w: float = float(page.get("width") or 0)
        page_h: float = float(page.get("height") or 0)
        azure_lines: list[dict[str, Any]] = page.get("lines", [])

        # ── Table source: prebuilt-layout (preferred) or geometric fallback ─
        if layout_tables_by_page is not None and page_idx < len(layout_tables_by_page):
            azure_tables = layout_tables_by_page[page_idx]
            if azure_tables:
                logger.info(
                    "Page %d: %d table(s) from prebuilt-layout",
                    page_idx + 1, len(azure_tables),
                )
        else:
            azure_tables = detect_tables_from_azure_lines(azure_lines, page_w, page_h)
            if azure_tables:
                logger.info(
                    "Page %d: %d table(s) detected from Azure geometry",
                    page_idx + 1, len(azure_tables),
                )

        # ── Collect table/equation bboxes (in pct coords) ────────────────
        # protect_table_lines mode: table regions shield Azure cell text from
        # Gemini replacement rather than suppressing the lines entirely.
        protection_regions: list[tuple[float, float, float, float]] = []
        suppression_regions: list[tuple[float, float, float, float]] = []
        for tbl in azure_tables:
            bbox = tbl.get("bbox_pct")
            if bbox and len(bbox) == 4:
                if protect_table_lines:
                    protection_regions.append(tuple(bbox))  # type: ignore[arg-type]
                else:
                    suppression_regions.append(tuple(bbox))  # type: ignore[arg-type]
        if not protect_table_lines:
            for eq in gem_equations:
                bbox = eq.get("bbox_pct")
                if bbox and len(bbox) == 4:
                    suppression_regions.append(tuple(bbox))  # type: ignore[arg-type]

        # ── Suppress Azure lines inside table/equation regions ───────────
        surviving_lines: list[dict[str, Any]] = []
        suppressed_count = 0
        for line in azure_lines:
            if suppression_regions and page_w > 0 and page_h > 0:
                line_bbox = _azure_line_bbox_pct(line, page_w, page_h)
                if line_bbox:
                    suppress = any(
                        _overlap_fraction(
                            line_bbox[0], line_bbox[1],
                            line_bbox[2], line_bbox[3],
                            reg[0], reg[1], reg[2], reg[3],
                        ) >= overlap_threshold
                        for reg in suppression_regions
                    )
                    if suppress:
                        suppressed_count += 1
                        continue
            surviving_lines.append(line)

        if suppressed_count:
            logger.info(
                "Page %d: suppressed %d Azure lines inside %d table/equation regions",
                page_idx + 1, suppressed_count, len(suppression_regions),
            )
        stats["suppressed"] += suppressed_count

        # ── Fuzzy-merge surviving lines with Gemini text ─────────────────
        if not gem_lines:
            logger.debug("Page %d: Gemini returned no text lines", page_idx + 1)
            page["lines"] = surviving_lines
            page["_tables"] = [] if protect_table_lines else azure_tables
            page["_equations"] = [] if protect_table_lines else gem_equations
            stats["tables"] += 0 if protect_table_lines else len(azure_tables)
            stats["equations"] += 0 if protect_table_lines else len(gem_equations)
            continue

        used_gem: set[int] = set()
        gem_cursor: int = 0
        replaced = 0
        skipped = 0

        for line in surviving_lines:
            az_text = (line.get("content") or "").strip()
            if not az_text:
                continue

            # In protect_table_lines mode: leave Azure cell text untouched.
            if protection_regions and page_w > 0 and page_h > 0:
                line_bbox = _azure_line_bbox_pct(line, page_w, page_h)
                if line_bbox and any(
                    _overlap_fraction(
                        line_bbox[0], line_bbox[1],
                        line_bbox[2], line_bbox[3],
                        reg[0], reg[1], reg[2], reg[3],
                    ) >= overlap_threshold
                    for reg in protection_regions
                ):
                    skipped += 1
                    continue

            lo = max(0, gem_cursor - window_radius)
            hi = min(len(gem_lines), gem_cursor + window_radius + 1)

            best_score: float = 0.0
            best_gi: int = -1

            for gi in range(lo, hi):
                if gi in used_gem:
                    continue
                s = _score(az_text, gem_lines[gi]["text"])
                if s > best_score:
                    best_score = s
                    best_gi = gi

            if best_score >= min_similarity and best_gi >= 0:
                new_text = gem_lines[best_gi]["text"]
                # Reject if Gemini text is a short fragment of the Azure line
                # (Gemini splits long Azure lines; keep Azure text to avoid gaps)
                length_ok = len(new_text) >= len(az_text) * min_length_ratio
                if not length_ok:
                    logger.debug(
                        "p%d  fragment rejected (%.0f%% len)  '%s'  →  '%s'",
                        page_idx + 1, 100.0 * len(new_text) / max(1, len(az_text)),
                        az_text[:50], new_text[:50],
                    )
                    gem_cursor = min(len(gem_lines), gem_cursor + 1)
                    skipped += 1
                else:
                    if new_text != az_text:
                        logger.debug(
                            "p%d  %.0f%%  '%s'  →  '%s'",
                            page_idx + 1, best_score,
                            az_text[:50], new_text[:50],
                        )
                    line["content"] = new_text
                    used_gem.add(best_gi)
                    gem_cursor = best_gi + 1
                    replaced += 1
            else:
                gem_cursor = min(len(gem_lines), gem_cursor + 1)
                skipped += 1

        # ── Inject Gemini-only text lines ────────────────────────────────
        injected = 0
        if inject_unmatched and page_w > 0 and page_h > 0:
            for gi, gem_line in enumerate(gem_lines):
                if gi in used_gem:
                    continue
                bbox_pct = gem_line.get("bbox_pct")
                if not bbox_pct:
                    continue
                # Don't inject text lines that are inside table/equation
                # regions — those are handled by the table/equation data.
                if suppression_regions:
                    inside = any(
                        _overlap_fraction(
                            bbox_pct[0], bbox_pct[1],
                            bbox_pct[2], bbox_pct[3],
                            reg[0], reg[1], reg[2], reg[3],
                        ) >= overlap_threshold
                        for reg in suppression_regions
                    )
                    if inside:
                        continue
                polygon = _bbox_pct_to_polygon(bbox_pct, page_w, page_h)
                synthetic: dict[str, Any] = {
                    "content": gem_line["text"],
                    "polygon": polygon,
                    "_source": "gemini_fallback",
                }
                surviving_lines.append(synthetic)
                injected += 1

        page["lines"] = surviving_lines
        page["_tables"] = [] if protect_table_lines else azure_tables
        page["_equations"] = [] if protect_table_lines else gem_equations

        stats["replaced"] += replaced
        stats["skipped"] += skipped
        stats["injected"] += injected
        stats["tables"] += 0 if protect_table_lines else len(azure_tables)
        stats["equations"] += 0 if protect_table_lines else len(gem_equations)

        pct = 100.0 * replaced / max(1, len(surviving_lines))
        logger.info(
            "Page %d: %d/%d lines replaced (%.0f%%), %d unmatched, "
            "%d injected, %d suppressed, %d azure_tables, %d equations",
            page_idx + 1, replaced, len(surviving_lines), pct,
            skipped, injected, suppressed_count,
            len(azure_tables), len(gem_equations),
        )

    # ── Rebuild top-level content ────────────────────────────────────────
    if update_top_level_content and "content" in result:
        all_lines: list[str] = []
        for page in pages:
            for line in page.get("lines", []):
                c = line.get("content", "")
                if c:
                    all_lines.append(c)
        result["content"] = "\n".join(all_lines)

    logger.info(
        "Structural merge complete — replaced: %d, unmatched: %d, "
        "injected: %d, suppressed: %d, tables: %d, equations: %d",
        stats["replaced"], stats["skipped"], stats["injected"],
        stats["suppressed"], stats["tables"], stats["equations"],
    )
    return result
