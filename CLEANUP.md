# Repo Cleanup Plan

## ✅ Active / Keep
- `fixed_layout_pipeline/` — main pipeline code
- `run_batch.py` — main batch runner
- `.env`, `requirements.txt`, `.gitignore`
- `output/` — current active outputs
- `newTestInput/`

---

## 🗑️ Safe to Delete (obvious junk)
- `--gemini-key`, `--gemini-workers`, `--hybrid-v2`, `--json`, `--mode`, `--pdf`, `-o` — accidental files from mistyped CLI command
- `2026.zip` — 1.9 GB zip in root
- `celery_worker.log`, `celery_worker1.log` … `celery_worker6.log`
- `pipeline_0008.log`, `pipeline_full.log`
- `searchable_output.pdf`
- `test_searchable_DEBUG.pdf`
- `test_searchable_fixed.pdf`
- `test_searchable_from_json.pdf`
- `python run batch py batch24.txt` — file with spaces in name

---

## 💾 Big Space Hogs (decide per item)

| Folder | Size | Notes |
|---|---|---|
| `2026/` | 2.2 GB | Raw input PDFs — move to external storage? |
| `viewer-frontend/` | 1.3 GB | Likely node_modules — `rm -rf node_modules`, keep source |
| `venv/` | 1.2 GB | Rebuildable from `requirements.txt` — safe to delete |
| `output_final/` | 1.2 GB | Old output run — archive or delete |
| `ocr-viewer/` | 816 MB | Likely node_modules — `rm -rf node_modules`, keep source |
| `output_searchable/` | 411 MB | Old output run — archive or delete |
| `webapp/` | 361 MB | Likely node_modules — `rm -rf node_modules`, keep source |
| `output_test/` | 157 MB | Old output run |
| `archival/` | 142 MB | Already labelled archival — compress or move |
| `new_pipeline/` | 33 MB | Old experiment |
| `mistral_test_ouput/` | 17 MB | Old Mistral era |
| `output_with_figures/` | 16 MB | Old output run |

---

## 🗄️ Old Experiment Clutter (probably delete)

**Mistral-era outputs (superseded by Azure pipeline):**
- `mistral_output/`
- `mistral_only_output/`
- `mistral_gemini_output/`
- `mistral_test_ouput/`

**Stale output directories (12 total):**
- `output_batch/`, `output_batch_2/`, `output_batch_3/`
- `output_test/`, `output_formulas_test/`
- `output_0118_enhance/`, `output_run1/`, `output_read_test/`
- `output_gem_1/`, `outputs/`, `output_with_figures/`, `random_out/`

**Experiment folders:**
- `flash_2/`
- `image_resize/`
- `html_only_testing/`
- `batch_markdown/`
- `random_pdfs/`
- `test_figures/`
- `TEST/`
- `llm_pipelines/` — old Mistral pipeline code

**Old/duplicate scripts in root (superseded by `run_batch.py`):**
- `batch_create_searchable_pdfs.py`
- `batch_process_fixed_layout.py`
- `create_searchable_pdf.py`
- `json_to_searchable_pdf.py`
- `run_batch_fixed_layout.sh`
- `tasks.py` (Celery worker remnant)

---

## 📋 Suggested Order

1. Delete safe junk (no risk, frees ~2 GB from zip alone)
2. Strip `node_modules` from frontend dirs (frees ~2.5 GB, source code stays)
3. Delete `venv/` and rebuild: `python -m venv venv && pip install -r requirements.txt`
4. Decide on old output dirs (most can go — data is in `2026/` if re-processing needed)
5. Move `2026/` to external storage or a separate data volume
6. Archive or delete `archival/` and Mistral-era folders
7. Clean up root-level old scripts
