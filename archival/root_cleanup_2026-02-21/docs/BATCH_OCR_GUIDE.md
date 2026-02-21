# Mistral Batch OCR Guide

**50% cost savings** on OCR processing using Mistral's Batch API.

## Overview

The Mistral Batch OCR pipeline enables cost-efficient processing of large PDF archives:

- **Cost**: $1 per 1,000 pages (vs $2 regular)
- **Capacity**: Up to 1M requests per batch
- **Async processing**: Submit and poll later
- **State recovery**: Automatic job tracking and resume

## Quick Start

### 1. Basic Usage (CLI)

```bash
# Process all PDFs in a directory
python mistral_batch_ocr.py --pdfs-dir ./pdfs --output-dir ./ocr_output

# Custom batch size (PDFs per job)
python mistral_batch_ocr.py --pdfs-dir ./pdfs --batch-size 1000

# Submit without waiting
python mistral_batch_ocr.py --pdfs-dir ./pdfs --no-wait

# Poll existing jobs
python mistral_batch_ocr.py --pdfs-dir ./pdfs --poll-only
```

### 2. Python API

```python
from mistral_batch_ocr import MistralBatchOCR
from pathlib import Path

# Simple usage
pipeline = MistralBatchOCR()
result = pipeline.process_directory(
    pdf_dir=Path("./pdfs"),
    wait_for_completion=True
)

print(f"Processed {result['pdfs_saved']} PDFs")
```

## Workflow

### Phase 1: Upload PDFs

```python
# Parallel upload (8-16 workers recommended)
pdf_paths = [Path("doc1.pdf"), Path("doc2.pdf"), ...]
file_id_map = pipeline.upload_pdfs_parallel(pdf_paths)
# Returns: {"doc1": "file-abc123", "doc2": "file-def456", ...}
```

**Performance**: ~100-500 PDFs/minute depending on file sizes and network

### Phase 2: Create Batch Jobs

```python
# Automatic chunking
batch_jobs = pipeline.create_batch_jobs_chunked(
    file_id_map,
    metadata={"project": "archive_2025"}
)
# Creates multiple batch jobs if > batch_size PDFs
```

**Recommendation**: 500-1000 PDFs per batch job

### Phase 3: Poll for Completion

```python
# Poll all jobs until complete
poll_result = pipeline.poll_all_jobs(timeout=86400)  # 24 hours max

print(f"Completed: {len(poll_result['completed'])}")
print(f"Running: {len(poll_result['incomplete'])}")
```

**Processing time**: Varies by queue load, typically 6-48 hours for large batches

### Phase 4: Download Results

```python
# Download and save markdown for all completed jobs
stats = pipeline.process_all_results()

print(f"Saved {stats['pdfs_saved']} PDFs")
```

**Output format**: `{pdf_name}_raw_ocr.md` per document

## Configuration Options

```python
from mistral_batch_ocr import BatchOCRConfig

config = BatchOCRConfig(
    model="mistral-ocr-2512",         # OCR model
    batch_size=500,                   # PDFs per batch job
    include_image_base64=True,        # Extract embedded images
    max_upload_workers=8,             # Parallel uploads
    poll_interval=300,                # Status check interval (seconds)
    max_poll_time=86400,              # Max wait time (24 hours)
    output_dir="batch_ocr_output",    # Output directory
    save_raw_json=True,               # Save raw batch results
    save_markdown=True,               # Save extracted markdown
)

pipeline = MistralBatchOCR(config)
```

## Use Cases

### Scenario 1: Small Archive (100 PDFs)

```bash
python mistral_batch_ocr.py --pdfs-dir ./docs --batch-size 100
```

- **Upload**: 1-2 minutes
- **Processing**: 1-4 hours
- **Cost**: ~$3 (assuming 30 pages/doc)

### Scenario 2: Medium Archive (10,000 PDFs)

```python
config = BatchOCRConfig(batch_size=500)  # 20 batch jobs
pipeline = MistralBatchOCR(config)

result = pipeline.process_directory(
    pdf_dir=Path("./archive"),
    wait_for_completion=False  # Submit and poll later
)
```

- **Upload**: 30-60 minutes
- **Processing**: 12-24 hours
- **Cost**: ~$300 (assuming 30 pages/doc)

### Scenario 3: Large Archive (50,000 PDFs)

```python
config = BatchOCRConfig(
    batch_size=500,           # 100 batch jobs
    max_upload_workers=16,    # Faster uploads
)

pipeline = MistralBatchOCR(config)

# Submit jobs
result = pipeline.process_directory(
    pdf_dir=Path("/data/documents"),
    wait_for_completion=False
)

# Later (hours/days), poll for results
poll_result = pipeline.poll_all_jobs()
stats = pipeline.process_all_results()
```

- **Upload**: 2-6 hours
- **Processing**: 24-48 hours
- **Cost**: ~$1,500 (assuming 30 pages/doc savings: $1,500!)

## State Management

The pipeline automatically saves state to `{output_dir}/batch_state.json`:

```json
{
  "batch_jobs": [
    {
      "job_id": "batch-abc123",
      "custom_ids": ["doc1", "doc2", ...],
      "status": "SUCCESS",
      "output_file_id": "file-xyz789"
    }
  ],
  "updated_at": 1707408000
}
```

**Recovery**: If script stops, restart and it will resume polling existing jobs:

```bash
python mistral_batch_ocr.py --pdfs-dir ./pdfs --poll-only
```

## Cost Comparison

| PDFs | Pages/PDF | Total Pages | Regular Cost | Batch Cost | Savings |
|------|-----------|-------------|--------------|------------|---------|
| 100 | 10 | 1,000 | $2.00 | $1.00 | $1.00 |
| 1,000 | 20 | 20,000 | $40.00 | $20.00 | $20.00 |
| 10,000 | 30 | 300,000 | $600.00 | $300.00 | $300.00 |
| 50,000 | 30 | 1,500,000 | $3,000.00 | $1,500.00 | **$1,500.00** |

## Integration with Structuring Pipeline

After batch OCR completes, use the raw markdown for structuring:

```python
from mistral_batch_ocr import MistralBatchOCR
from mistral_ocr_pipeline import MistralOCRPipeline, MistralPipelineConfig

# Step 1: Batch OCR
batch_pipeline = MistralBatchOCR()
batch_result = batch_pipeline.process_directory(
    pdf_dir=Path("./pdfs"),
    wait_for_completion=True
)

# Step 2: Structure the raw OCR output
for md_file in Path("./batch_ocr_output").glob("*_raw_ocr.md"):
    pdf_path = Path("./pdfs") / f"{md_file.stem.replace('_raw_ocr', '')}.pdf"
    
    # Run structuring pass (uses existing raw markdown internally)
    config = MistralPipelineConfig(
        structuring_provider="mistral",  # or "gemini"
        pages_per_chunk=5
    )
    
    struct_pipeline = MistralOCRPipeline(config)
    doc = struct_pipeline.process(str(pdf_path))
```

## Monitoring

Check batch job status programmatically:

```python
pipeline = MistralBatchOCR()

for job in pipeline.batch_jobs:
    print(f"Job {job.job_id}:")
    print(f"  Status: {job.status}")
    print(f"  PDFs: {len(job.custom_ids)}")
    if job.completed_at:
        elapsed = job.completed_at - job.created_at
        print(f"  Duration: {elapsed/3600:.1f} hours")
```

## Troubleshooting

### Issue: Upload fails

**Solution**: Check file sizes and network. Try reducing `max_upload_workers`.

### Issue: Batch job stuck in QUEUED

**Solution**: Mistral's queue may be busy. Wait longer or contact support.

### Issue: Script stops during polling

**Solution**: Restart with `--poll-only` flag. State is automatically recovered.

### Issue: Results missing images

**Solution**: Set `include_image_base64=True` in config (increases processing time).

## Best Practices

1. **Chunk sensibly**: 500-1000 PDFs per batch job
2. **Upload in parallel**: Use 8-16 workers for faster uploads
3. **Don't wait synchronously**: Submit jobs and poll later for large batches
4. **Monitor state file**: Track progress via `batch_state.json`
5. **Separate concerns**: Use batch OCR for extraction, then structure separately

## API Reference

See [mistral_batch_ocr.py](mistral_batch_ocr.py) for complete API documentation.

## Limitations

- Batch jobs take hours to complete (not real-time)
- No streaming results (all-or-nothing per job)
- Rate limits on job creation (~10/minute estimated)
- Maximum 1M requests per batch (pages scale independently)

## Future Enhancements

- [ ] Automatic retry for failed uploads
- [ ] Progress bar UI
- [ ] Cost estimation before submission
- [ ] Email/webhook notifications on completion
- [ ] Direct integration with Celery workers
