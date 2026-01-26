# PDF to HTML Converter - Usage Guide

## Quick Start

### 1. Activate Virtual Environment
```bash
source venv/bin/activate
```

### 2. Set API Key (if not already set)
```bash
export GEMINI_API_KEY="your-api-key-here"
```

Get your API key at: https://aistudio.google.com/app/apikey

---

## Basic Commands

### Convert PDF to HTML (simplest)
```bash
python3 pdf_to_html.py document.pdf
```
Output: `document.html`

### Specify Output File
```bash
python3 pdf_to_html.py document.pdf output.html
```

### Convert to Both HTML and JSON
```bash
python3 pdf_to_html.py document.pdf -j
```
Output: `document.html` and `document.json`

---

## Advanced Options

### High Resolution Processing
```bash
python3 pdf_to_html.py document.pdf -r high
```
Options: `low`, `medium` (default), `high`

### Custom Chunk Size (pages per batch)
```bash
python3 pdf_to_html.py document.pdf --chunk-size 20
```
Default: 15 pages per chunk

### Disable Chunking (for small PDFs)
```bash
python3 pdf_to_html.py document.pdf --no-chunking
```

### Disable Image Extraction (faster)
```bash
python3 pdf_to_html.py document.pdf --no-images
```

### Custom Image DPI
```bash
python3 pdf_to_html.py document.pdf --image-dpi 300
```
Default: 150 DPI

### Verbose Logging
```bash
python3 pdf_to_html.py document.pdf -v
```

### Custom Retry Settings
```bash
python3 pdf_to_html.py document.pdf --retries 5 --max-tokens 100000
```

### Theme and Minification
```bash
python3 pdf_to_html.py document.pdf --theme dark --minify-html
```

### Validation and Quality Controls
```bash
python3 pdf_to_html.py document.pdf --validation-level strict --quality-threshold 80
```
Disable validation:
```bash
python3 pdf_to_html.py document.pdf --no-validation
```

### Caching and Parallel Processing
```bash
python3 pdf_to_html.py document.pdf --parallel --max-workers 4
```
Disable caching:
```bash
python3 pdf_to_html.py document.pdf --no-cache
```

### Debug Info Block in HTML
```bash
python3 pdf_to_html.py document.pdf --debug-info
```

### Fail Fast / Disable Text Fallback
```bash
python3 pdf_to_html.py document.pdf --fail-fast --no-text-fallback
```

---

## Common Use Cases

### Academic Papers (high quality, with equations)
```bash
python3 pdf_to_html.py paper.pdf -r high -j
```

### Large Documents (100+ pages)
```bash
python3 pdf_to_html.py large_doc.pdf --chunk-size 10 -v
```

### Scanned Documents (OCR)
```bash
python3 pdf_to_html.py scanned.pdf -r high
```

### Quick Preview (no images, fast)
```bash
python3 pdf_to_html.py document.pdf --no-images --no-chunking
```

### Maximum Quality
```bash
python3 pdf_to_html.py document.pdf -r high --image-dpi 300 -j -v
```

---

## Output Formats

### HTML Only (default)
```bash
python3 pdf_to_html.py document.pdf -f html
```

### JSON Only
```bash
python3 pdf_to_html.py document.pdf -f json
```

### Both HTML and JSON
```bash
python3 pdf_to_html.py document.pdf -f both
```
or
```bash
python3 pdf_to_html.py document.pdf -j
```

---

## Batch Processing

### Process Multiple PDFs
```bash
for pdf in *.pdf; do
    python3 pdf_to_html.py "$pdf" -j -v
done
```

### Process with Custom Output Directory
```bash
for pdf in *.pdf; do
    output="output/${pdf%.pdf}.html"
    python3 pdf_to_html.py "$pdf" "$output" -j
done
```

---

## Troubleshooting

### Check API Key
```bash
echo $GEMINI_API_KEY
```

### Test with Help Command
```bash
python3 pdf_to_html.py --help
```

### Enable Verbose Logging
```bash
python3 pdf_to_html.py document.pdf -v 2>&1 | tee processing.log
```

### Check Python Version
```bash
python3 --version
```
Requires Python 3.10+

### Verify Dependencies
```bash
pip list | grep -E "google|pydantic|pymupdf"
```

---

## Full Command Reference

```bash
python3 pdf_to_html.py [-h] [-j] [-r {low,medium,high}] 
                       [-f {html,json,both}] [-v] 
                       [--retries RETRIES] 
                       [--max-tokens MAX_TOKENS]
                       [--chunk-size CHUNK_SIZE] 
                       [--no-chunking] 
                       [--no-images]
                       [--image-dpi IMAGE_DPI]
                       input [output]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `input` | Input PDF file path | Required |
| `output` | Output file path | `<input>.html` |
| `-j, --json` | Also output structured JSON | `false` |
| `-r, --resolution` | Processing resolution | `medium` |
| `-f, --format` | Output format | `html` |
| `-v, --verbose` | Enable verbose logging | `false` |
| `--retries` | Number of retries on failure | `3` |
| `--max-tokens` | Max output tokens | `65536` |
| `--chunk-size` | Pages per chunk | `15` |
| `--no-chunking` | Disable chunked processing | `false` |
| `--no-images` | Disable image extraction | `false` |
| `--image-dpi` | DPI for extracted images | `150` |

---

## Examples with Real Scenarios

### Extract a 5-page report
```bash
python3 pdf_to_html.py report.pdf
```

### Extract a 50-page thesis with equations
```bash
python3 pdf_to_html.py thesis.pdf -r high -j -v
```

### Extract a 200-page manual
```bash
python3 pdf_to_html.py manual.pdf --chunk-size 10 -v
```

### Extract Arabic document (RTL support)
```bash
python3 pdf_to_html.py arabic_doc.pdf -r high
```

### Extract multi-column academic paper
```bash
python3 pdf_to_html.py paper.pdf -r medium -j
```

---

## Performance Tips

1. **Use lower resolution for text-only documents**
   ```bash
   python3 pdf_to_html.py text_doc.pdf -r low
   ```

2. **Increase chunk size for faster processing**
   ```bash
   python3 pdf_to_html.py doc.pdf --chunk-size 20
   ```

3. **Disable images if not needed**
   ```bash
   python3 pdf_to_html.py doc.pdf --no-images
   ```

4. **Use no-chunking for small docs (< 20 pages)**
   ```bash
   python3 pdf_to_html.py small.pdf --no-chunking
   ```

---

## Cost Estimation

The script automatically estimates costs before processing:

- **Input:** $0.50 per 1M tokens
- **Output:** $3.00 per 1M tokens

**Typical costs:**
- 10-page document: ~$0.02 USD
- 50-page document: ~$0.10 USD
- 100-page document: ~$0.20 USD
- 500-page document: ~$1.00 USD

*Note: Free tier available with usage limits*

---

## Environment Setup

### First Time Setup
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set API key
export GEMINI_API_KEY="your-key"
```

### Add API Key to Shell Profile (persistent)
```bash
echo 'export GEMINI_API_KEY="your-key"' >> ~/.bashrc
source ~/.bashrc
```

---

## Programmatic Usage

### Python Script Example
```python
from pdf_to_html import PDFProcessor, ProcessingConfig, MediaResolution

# Create config
config = ProcessingConfig(
    media_resolution=MediaResolution.HIGH,
    output_format="both",
    pages_per_chunk=15
)

# Process PDF
processor = PDFProcessor(config)
try:
    result = processor.process("document.pdf", "output.html")
    if result["success"]:
        print(f"HTML: {result['html_path']}")
        print(f"JSON: {result['json_path']}")
        print(f"Pages: {len(result['document'].pages)}")
    else:
        print(f"Error: {result['error']}")
finally:
    processor.cleanup()
```

---

## Features Supported

✅ Text extraction with semantic structure  
✅ Table OCR (headers + rows)  
✅ Mathematical equations (LaTeX + MathJax)  
✅ Image extraction with bounding boxes  
✅ Multi-column layout detection  
✅ RTL language support (Arabic, Hebrew, etc.)  
✅ Chunked processing for large documents  
✅ Automatic page validation and retry  
✅ Cost estimation  
✅ Quality metrics  
✅ Comprehensive error handling  

---

## Need Help?

```bash
python3 pdf_to_html.py --help
```

For issues, check the logs with `-v` flag:
```bash
python3 pdf_to_html.py document.pdf -v 2>&1 | tee debug.log
```
