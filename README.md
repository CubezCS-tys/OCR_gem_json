# OCR_gem_json

OCR conversion platform with three active engines:

- Azure Document Intelligence for searchable PDFs and pixel-perfect overlays
- Gemini for semantic HTML
- Mistral for markdown + images

## Active Components

- `webapp/` - FastAPI backend used in production
- `frontend/` - customer-facing Next.js frontend
- `fixed_layout_pipeline/` - Azure pipeline core (searchable PDF + OCR JSON + overlay HTML)
- `llm_pipelines/` - consolidated Gemini/Mistral stack

## Output Formats

The webapp supports:

- `searchable_pdf` (Azure)
- `pixel_html` (Azure + overlay renderer)
- `semantic_html` (Gemini)
- `markdown` (Mistral OCR pass 1)

## Quick Start (Current Stack)

### 1) Setup

```bash
cd OCR_gem_json
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r webapp/requirements.txt
```

### 2) Configure Environment

Create/update `.env` in repo root and set at minimum:

- `AZURE_DI_ENDPOINT`
- `AZURE_DI_API_KEY`
- `GEMINI_API_KEY`
- `MISTRAL_API_KEY`
- `JWT_SECRET`

### 3) Run Backend

```bash
cd webapp
python3 run.py --reload
```

### 4) Run Frontend

```bash
cd frontend
npm install
npm run dev
```

## CLI Entry Points

### Fixed-layout pipeline (Azure)

```bash
python3 -m fixed_layout_pipeline --help
python3 -m fixed_layout_pipeline pipeline --input pdfs/scanned --output output_final --workers 4 --dpi 200 --mode replace-text
```

### LLM pipelines (Gemini/Mistral)

Preferred command style:

```bash
python3 -m llm_pipelines.pdf_to_html input.pdf output.html
python3 -m llm_pipelines.mistral_ocr_pipeline input.pdf --output-dir outputs
python3 -m llm_pipelines.mistral_fidelity_pipeline input.pdf --output-dir outputs
python3 -m llm_pipelines.mistral_batch_ocr --pdfs-dir ./pdfs --output-dir ./batch_out
```

## Current Project Structure

```text
OCR_gem_json/
├── webapp/
├── frontend/
├── fixed_layout_pipeline/
├── llm_pipelines/
├── batch1_flp/
├── archival/
├── requirements.txt
├── .env
└── README.md
```

## Documentation

- `webapp/README.md` - API/backend runtime and process flow
- `fixed_layout_pipeline/README.md` - Azure pipeline CLI/API
- `llm_pipelines/README.md` - Gemini/Mistral module map and usage

## Legacy/Archived Items

Older docs, control-panel tooling, old viewers, and test scripts were moved under:

- `archival/root_cleanup_2026-02-21/`

Use those only if you explicitly need legacy workflows.
