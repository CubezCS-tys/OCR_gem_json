# Batch Processing with Fixed Layout Pipeline

Process multiple PDFs in parallel using the fixed_layout_pipeline to generate JSON and searchable HTML outputs.

## Quick Start

### Process all scanned PDFs with 4 parallel workers:
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_fixed_output \
  --workers 4
```

### Process with 8 workers (faster, more memory):
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_fixed_output \
  --workers 8
```

### Use async mode (alternative to threading):
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_fixed_output \
  --workers 6 \
  --async
```

### Resume after interruption (skip completed):
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_fixed_output \
  --workers 4 \
  --resume
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `-i, --input` | Input directory with PDFs | Required |
| `-o, --output` | Output directory | Required |
| `-w, --workers` | Number of parallel workers | 4 |
| `--pattern` | File pattern to match | `*.pdf` |
| `--dpi` | Rasterization DPI | 300 |
| `--debug` | Enable debug bounding boxes | False |
| `--resume` | Skip already processed PDFs | False |
| `--async` | Use async/await mode | False |
| `--no-preprocess` | Skip preprocessing | False |
| `-v, --verbose` | Verbose logging | False |

## Output Structure

For each PDF, the script creates:

```
batch_fixed_output/
├── PDF_NAME/
│   ├── PDF_NAME_canonical.json    # Canonical document structure
│   ├── PDF_NAME_fidelity.html     # Pixel-perfect HTML
│   └── pages/                     # Rasterized page images
├── batch_report.json              # Processing summary
└── failed_pdfs.txt                # List of failed PDFs (if any)
```

## Examples

### Process specific PDFs only:
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_output \
  --pattern "0118-*.pdf" \
  --workers 4
```

### High quality with debug boxes:
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_output \
  --dpi 400 \
  --debug \
  --workers 4
```

### Fast processing (skip preprocessing):
```bash
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_output \
  --no-preprocess \
  --workers 8
```

## Performance Tips

1. **Workers**: Start with 4 workers, increase based on CPU/RAM
   - More workers = faster but more memory usage
   - Each worker processes ~1 PDF at a time
   - Monitor system resources during processing

2. **Async vs Threading**:
   - Default (threading) is usually faster
   - `--async` may help with I/O-bound workloads
   - Try both if unsure

3. **Resume**: Always use `--resume` when restarting
   - Skips completed PDFs
   - Safe to interrupt and restart

4. **DPI**: Higher DPI = better quality but slower
   - 300 DPI (default) is good for most documents
   - 400 DPI for high-quality outputs
   - 200 DPI for quick previews

## Monitoring Progress

The script logs:
- Each PDF as it starts processing
- Completion time and page count
- Progress percentage
- Any errors encountered

## Output Files

### Canonical JSON
`PDF_NAME_canonical.json` contains:
- Document structure (pages, blocks, tables)
- Text content and reading order
- Bounding boxes and coordinates
- OCR confidence scores

### Fidelity HTML
`PDF_NAME_fidelity.html` provides:
- Pixel-accurate layout matching the original PDF
- Searchable text overlays
- Preserved fonts, sizes, and positioning
- Can be opened in any browser

### Batch Report
`batch_report.json` includes:
- Total PDFs processed
- Success/failure counts
- Processing times
- Individual PDF results

## Troubleshooting

### Out of memory
Reduce `--workers` or process in smaller batches

### Slow processing
- Increase `--workers` if CPU/RAM available
- Use `--no-preprocess` for faster processing
- Lower `--dpi` for quicker results

### Azure Document Intelligence errors
Check `.env` file for valid credentials:
```
AZURE_DI_ENDPOINT=your_endpoint
AZURE_DI_KEY=your_key
```

### Resume not working
Ensure output directory path is exactly the same
