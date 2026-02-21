# Fixed Layout Pipeline (Core)

This folder contains the **core OCR runtime** used in production:

1. Generate a searchable PDF from a scanned PDF (Azure Document Intelligence `prebuilt-read`)
2. Save the matching OCR JSON with words/lines and bounding polygons
3. Render pixel-perfect HTML from the PDF + OCR JSON
4. Run this in async/parallel for batch directories

## Core Files

- `batch_pipeline.py`: async/parallel batch orchestration and single-document `process_one`
- `searchable_pdf.py`: searchable PDF + OCR JSON generation
- `overlay_renderer.py`: pixel-perfect HTML renderer
- `webapp_api.py`: stable adapter functions used by `webapp`
- `config.py`: Azure config/env loading
- `__main__.py`: CLI commands

## CLI Commands

Run from repo root:

```bash
python3 -m fixed_layout_pipeline --help
```

### 1) `searchable-pdf`

Generate searchable PDF + OCR JSON for one scanned PDF.

```bash
python3 -m fixed_layout_pipeline searchable-pdf input.pdf
python3 -m fixed_layout_pipeline searchable-pdf input.pdf -o output/input_searchable.pdf
python3 -m fixed_layout_pipeline searchable-pdf input.pdf --pages 1-3
```

Outputs:

- `{stem}_searchable.pdf`
- `{stem}_ocr.json`

### 2) `render`

Render pixel-perfect HTML from searchable PDF + OCR JSON.

```bash
python3 -m fixed_layout_pipeline render --pdf output/input_searchable.pdf
python3 -m fixed_layout_pipeline render --pdf output/input_searchable.pdf --json output/input_ocr.json
python3 -m fixed_layout_pipeline render --pdf output/input_searchable.pdf --mode replace-text --dpi 300
```

Output:

- `{stem}_overlay.html` (or mode-specific output path from caller code)

### 3) `pipeline`

Batch async/parallel run: scanned PDFs -> searchable PDFs + OCR JSON + HTML.

```bash
python3 -m fixed_layout_pipeline pipeline \
  --input pdfs/scanned \
  --output output_final \
  --workers 4 \
  --dpi 200 \
  --mode replace-text
```

Dry run:

```bash
python3 -m fixed_layout_pipeline pipeline --input pdfs/scanned --dry-run
```

## Environment Variables

Minimum required:

- `AZURE_DI_ENDPOINT`
- `AZURE_DI_API_KEY`

Optional:

- `OCR_DPI` (used in some config paths)
- `OCR_DEBUG`

Template: `fixed_layout_pipeline/.env.example`

## Python API (Used by Webapp)

`webapp` should import only from `fixed_layout_pipeline.webapp_api`:

- `process_one_with_azure_env(...)`
- `generate_searchable_pdf_with_azure_env(...)`
- `generate_searchable_pdf_from_bytes_with_azure_env(...)`

This keeps webapp stable even if internal modules are refactored.

