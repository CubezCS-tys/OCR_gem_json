# Production OCR Pipeline Review (Code + outputs_2_prompt_audit)

## Scope
- Reviewed core pipeline: `pdf_to_html.py`, `rebuild_html.py`, `rebuild_html_simple.py`, `tasks.py`, docs.
- Inspected sample outputs in `outputs_2_prompt_audit/` (JSON + HTML pairs).

## Snapshot of the sample outputs (outputs_2_prompt_audit)
- `0005-052-002-003`: 17 pages, 4 images, no tables, no multi-column.
- `0005-052-004-004`: 22 pages, 5 tables, no multi-column.
- `0008-015-001-006`: 35 pages, 30 multi-column pages, 4 images.
- `0227-041-002-002`: 39 pages, 32 tables, 44 images (image-heavy).
- `0308-036-091-007`: 60 pages, English content but `metadata.language` = Arabic (direction mismatch risk).
- `1749-000-022-008`: 23 pages, 143 equations, 23 numbered equations.

## What’s already strong
- **Structured output**: schema covers headings, lists, tables, images, equations, headers/footers, and bbox.
- **Chunked extraction**: resilient to large docs, retries missing pages, logs quality metrics.
- **Image extraction**: bbox-based cropping with PyMuPDF and DPI boosts for small figures.
- **RTL handling**: global RTL detection plus per-page English override, with bidi-safe CSS.
- **Equation transcription**: LaTeX preserved and MathJax-ready, with Arabic caption handling.

## Observed issues from sample outputs

### 1) Language/direction mismatch at document level
- Example: `outputs_2_prompt_audit/0308-036-091-007.json` has `metadata.language = "Arabic"`, but page content is English.
- Current renderer sets `<html dir="rtl">` when metadata says Arabic, then flips per-page to LTR via English detection. This works visually, but it’s semantically wrong and can break tools that rely on `<html lang/dir>`.

### 2) Multi-column layout is flattened visually
- Example: `outputs_2_prompt_audit/0008-015-001-006.html` (page 4+).
- Reading order is correct (right column then left for RTL), but the visual layout is single-column flow. This loses “column look,” especially for academic journals.

### 3) Table cell merges are not representable
- `TableCell` exists, but `Table.rows` is `list[list[str]]`, so `row_span`/`col_span` are discarded.
- Example: `outputs_2_prompt_audit/0005-052-004-004.html` shows blank cells where merged cells should be (`جدول (1)` around page 11).

### 4) Nested list levels are captured but not rendered
- JSON contains `list_level > 1` (e.g., `0005-052-004-004.json` page 21), but HTML always outputs a flat `<ul>`.

### 5) Equation numbers are captured but never rendered
- `equation_number` exists in JSON (e.g., `1749-000-022-008.json` has 23 numbered equations), but HTML never shows them.

### 6) Figure caption duplication
- Example: `outputs_2_prompt_audit/0227-041-002-002.html` page 3 shows a `<figcaption>` and a separate `<p class="caption">` with the same text.
- This likely comes from both an `image.caption` **and** a `TextBlock` caption.

### 7) Inline equation layout is brittle
- Inline equations render as standalone `<span>` elements on their own lines in the HTML (see `1749-000-022-008.html`), which can break paragraph flow.

### 8) Header/footer dedup only exact-match
- `_deduplicate_header_footer` removes exact string matches only, so near-duplicate headers/footers still appear in body text.

### 9) No title/cover page semantics
- The pipeline doesn’t classify or style cover/title pages differently.
- Example: `0308-036-091-007.json` page 1 has centered volume/issue text + title + author, but HTML uses the same body flow as normal pages.

### 10) BBox data not used for layout
- You already get bbox positions for text/tables/images, but HTML rendering only uses them for ordering (not positioning).

## Recommendations (prioritized)

### Phase 1 — Rendering fixes (no schema changes required)
- **Nested lists**: Use `list_level` to build nested `<ul>/<ol>` hierarchies.
- **Equation numbering**: Render `equation_number` with display equations; add `.equation-number` style for alignment.
- **Inline equations**: Wrap inline equations in `<p>` when they’re standalone, or allow inline merging with surrounding text when possible.
- **Caption de-dup**: If a `TextBlock` caption matches `image.caption` or `table.caption` (exact/normalized), drop one.
- **Header/footer fuzzy dedup**: Normalize numerals, strip punctuation, and compare with a similarity threshold.

### Phase 2 — Schema + prompt improvements
- **Table cells**: Change `Table.rows` to `list[list[TableCell]]` and update renderer to honor `row_span`/`col_span`.
- **Page geometry**: Add `page_width` / `page_height` to `PageContent` so bbox can be mapped to pixel layout.
- **Block style metadata**: Ask Gemini for `font_size`, `font_weight`, `alignment`, `indent`, `line_spacing` (even coarse buckets help fidelity).
- **Page classification**: Add `page_type` (cover/title/toc/body/appendix/index) to improve title-page layout.
- **Column metadata**: Ask for `column_id` and `column_bbox` for clearer column grouping.

### Phase 3 — Layout fidelity modes
- **Two rendering modes**:
  - `flow` (current): best for readability.
  - `layout`: use bbox positioning inside a fixed-size page container to mimic the original layout.
- **Column grid mode**: use CSS grid with column wrappers based on bbox clustering (no absolute positioning required).

### Phase 4 — Hybrid extraction for “searchable PDFs”
- When PDFs have embedded text, consider **extracting text/layout from PDF directly** (PyMuPDF/pdfminer) and use Gemini only for OCR/semantics on scanned content.
- This can dramatically improve font/position fidelity and reduce hallucinated ordering.

## Title/Cover Page Handling (recommended heuristics)
- Detect a cover/title page if:
  - Very few paragraphs, mostly headings/centered text.
  - High ratio of `heading` blocks or `style=centered`.
  - No running headers/footers.
- Render with larger typography, center alignment, and extra vertical spacing.

## Concrete example-driven fixes (based on outputs)
- `outputs_2_prompt_audit/0008-015-001-006.html`:
  - Multi-column layout should visually reflect two columns (CSS grid or positioned layout).
- `outputs_2_prompt_audit/0005-052-004-004.html`:
  - Add `row_span`/`col_span` so table categories don’t repeat with blank cells.
- `outputs_2_prompt_audit/0227-041-002-002.html`:
  - Remove duplicate captions (figcaption + paragraph).
- `outputs_2_prompt_audit/1749-000-022-008.html`:
  - Render `equation_number` and fix inline equation flow.
- `outputs_2_prompt_audit/0308-036-091-007.json`:
  - Improve language detection and set document-level `lang/dir` correctly.

## Suggested next steps
1) Implement renderer fixes (Phase 1).
2) Update schema for table cells and page geometry (Phase 2).
3) Add a `layout` rendering mode and column grid mode (Phase 3).
4) Build a small regression suite using `outputs_2_prompt_audit/` to verify each change.

---
If you want, I can implement Phase 1 and/or Phase 2 directly in `pdf_to_html.py` and add a simple evaluation script that compares before/after HTML on the audit set.
