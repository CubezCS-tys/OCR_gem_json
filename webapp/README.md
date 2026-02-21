# ScanToText Webapp

FastAPI backend for upload/process/download OCR jobs with free and pro tiers.

## What This Folder Does

- Accepts PDF/image uploads
- Free flow: generate searchable PDF
- Pro flow: runs parallel processors and returns a ZIP with requested formats
- Stores job/user state in DB (SQLite by default, PostgreSQL supported)
- Handles auth (Google OAuth + JWT), Stripe billing, admin endpoints

## Key Files

- `app.py`: FastAPI app + routes
- `ocr_service.py`: processing orchestration
- `run.py`: local dev runner
- `db.py`: SQLAlchemy models and job/user operations
- `auth.py`: JWT + Google auth
- `stripe_service.py`: Stripe checkout/webhook
- `alembic/`: DB migrations

## Run Commands

### 1) Install

```bash
cd webapp
pip install -r requirements.txt
```

### 2) Configure env

```bash
cp .env.example .env
```

Set at minimum:

- `AZURE_DI_ENDPOINT`
- `AZURE_DI_API_KEY`
- `JWT_SECRET`

If you use billing/auth features, also set Stripe and Google OAuth variables from `.env.example`.

### 3) Start (dev)

```bash
cd webapp
python3 run.py --reload
```

Equivalent direct command:

```bash
cd webapp
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 4) Start (prod-style)

```bash
cd webapp
gunicorn app:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --keep-alive 5
```

### 5) Database migration commands

```bash
cd webapp
alembic upgrade head
alembic revision -m "your_migration_name"
```

## API Workflow Commands

### Free flow

Upload:

```bash
curl -F "file=@/path/to/input.pdf" http://localhost:8000/api/upload
```

Process free:

```bash
curl -X POST http://localhost:8000/api/process/free/<job_id>
```

Check status:

```bash
curl http://localhost:8000/api/status/<job_id>
```

Download:

```bash
curl -L http://localhost:8000/api/download/<job_id> -o result.pdf
```

### Pro flow

Requires bearer JWT:

```bash
curl -X POST "http://localhost:8000/api/process/pro/<job_id>?formats=searchable_pdf,pixel_html,semantic_html,markdown" \
  -H "Authorization: Bearer <jwt_token>"
```

## Output Formats in Pro

- `searchable_pdf`
- `pixel_html`
- `semantic_html`
- `markdown`

`ocr_service.py` runs Azure/Gemini/Mistral workers in parallel and packages outputs into ZIP.

Format-to-engine mapping:

- `searchable_pdf` -> Azure DI (`fixed_layout_pipeline.webapp_api`)
- `pixel_html` -> Azure DI + overlay renderer (`fixed_layout_pipeline.webapp_api`)
- `semantic_html` -> Gemini (`llm_pipelines.pdf_to_html`)
- `markdown` -> Mistral OCR pass 1 (`llm_pipelines.mistral_ocr_pipeline`)

## Integration Boundary

Webapp imports OCR runtime through:

- `fixed_layout_pipeline.webapp_api` (Azure searchable/pdf+overlay)
- `llm_pipelines.pdf_to_html` (Gemini semantic HTML)
- `llm_pipelines.mistral_ocr_pipeline` (Mistral markdown/images)

This keeps webapp functionality stable even when internal OCR modules are refactored.

## Repo Layout Note

`llm_pipelines/` contains the real Gemini/Mistral implementation code.
New code should import from `llm_pipelines.*`.
