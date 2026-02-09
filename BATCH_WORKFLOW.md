# Batch OCR to HTML Workflow

Complete command sequence for processing PDFs through batch OCR to structured HTML.

## Prerequisites

```bash
# Activate virtual environment
source venv/bin/activate
```

## Step 1: Submit Batch OCR Job

```bash
# Submit PDFs for batch processing
python3 mistral_batch_ocr.py --pdfs-dir ./pdfs --output-dir batch_markdown
```

**Output:** Batch job ID (e.g., `f549d117-7757-4c37-9e5b-3d71264d17a8`)

## Step 2: Check Batch Status

```bash
# Monitor batch job progress (default: batch_markdown)
python3 check_batch_status.py

# Or specify custom output directory
python3 check_batch_status.py --output-dir batch_markdown2
```

Wait until status shows `SUCCESS`.

## Step 3: Parse Batch Results

Extract individual markdown and JSON files from the batch JSONL:

```bash
# Replace YOUR_JOB_ID with actual batch job ID
python3 parse_batch_results.py batch_markdown/batch_YOUR_JOB_ID_raw.jsonl --output-dir batch_markdown

# Or for custom output directory (e.g., batch_markdown2)
python3 parse_batch_results.py batch_markdown2/batch_YOUR_JOB_ID_raw.jsonl --output-dir batch_markdown2
```

**Output:** For each PDF:
- `filename.md` - Raw OCR markdown
- `filename.json` - Raw OCR JSON

## Step 4: Generate Structured JSON and HTML

Convert markdown to DocumentStructure schema and render HTML:

```bash
# Process all parsed files in parallel
python3 batch_to_structured.py batch_markdown/*.json --provider gemini --parallel --workers 3
```

**Output:** For each PDF:
- `filename_structured.json` - DocumentStructure schema
- `filename.html` - Rendered HTML with RTL support

## Single Command Chain

Once batch job completes:

```bash
source venv/bin/activate
python3 parse_batch_results.py batch_markdown/batch_YOUR_JOB_ID_raw.jsonl --output-dir batch_markdown
python3 batch_to_structured.py batch_markdown/*.json --provider gemini --parallel --workers 3
```

## Example with Real Job ID

```bash
source venv/bin/activate
python3 parse_batch_results.py batch_markdown/batch_f549d117-7757-4c37-9e5b-3d71264d17a8_raw.jsonl --output-dir batch_markdown
python3 batch_to_structured.py batch_markdown/*.json --provider gemini --parallel --workers 3
```
