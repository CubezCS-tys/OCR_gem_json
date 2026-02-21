# LLM Pipelines

Consolidated Gemini/Mistral OCR stack used by the project.

## What Lives Here

- `pdf_to_html.py`
  Gemini-based semantic extraction and HTML rendering pipeline.
- `mistral_ocr_pipeline.py`
  Two-pass Mistral OCR pipeline (OCR -> structuring -> optional HTML).
- `mistral_batch_ocr.py`
  Batch OCR submission/polling/retrieval for Mistral API.
- `batch_to_structured.py`
  Converts batch OCR markdown to structured JSON.
- `rebuild_html.py`, `rebuild_html_simple.py`
  Regenerate HTML from structured JSON outputs.
- `parse_batch_results.py`
  Parse Mistral batch JSONL outputs into per-document artifacts.
- `image_utils.py`
  Shared image/data-URI normalization helpers.
- `check_batch_status.py`, `check_mistral_account.py`, `example_batch_ocr.py`, `mistral.py`
  Operational helpers and quick-run scripts.

## Runtime Consumers

- `webapp/ocr_service.py` imports:
  - `llm_pipelines.pdf_to_html` for `semantic_html`
  - `llm_pipelines.mistral_ocr_pipeline` for `markdown`
- `tasks.py` imports `llm_pipelines.pdf_to_html` models/processor.

## CLI Usage

Preferred (module form):

```bash
python3 -m llm_pipelines.pdf_to_html input.pdf output.html
python3 -m llm_pipelines.mistral_ocr_pipeline input.pdf --output-dir outputs
python3 -m llm_pipelines.mistral_batch_ocr --pdfs-dir ./pdfs --output-dir ./batch_out
```

## Environment Variables

Set as needed per workflow:

- `GEMINI_API_KEY`
- `MISTRAL_API_KEY`
- `MODEL_NAME` (optional model override)

`webapp` also needs Azure credentials for searchable PDF + pixel HTML:

- `AZURE_DI_ENDPOINT`
- `AZURE_DI_API_KEY`

## Notes For Refactors

- Keep package imports as `from llm_pipelines...` from external modules.
- Inside this package, prefer relative imports (`from .module import ...`).
