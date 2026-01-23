# 📄 PDF Processing Guide

## Overview

The OCR pipeline has **full native support** for PDF documents. PDFs are automatically converted to high-quality images (300 DPI) before processing, ensuring optimal OCR accuracy.

## ✅ Features

- ✅ **Multi-page PDF support** - Process entire documents automatically
- ✅ **Page range selection** - Process specific pages (e.g., pages 1-5)
- ✅ **Automatic conversion** - PDF → 300 DPI images → OCR
- ✅ **Batch processing** - Process multiple PDFs in one go
- ✅ **Individual HTML files** - Each page becomes a separate HTML file
- ✅ **Progress tracking** - Monitor processing page by page
- ✅ **Validation per page** - Quality checks for each page

## 🚀 Quick Start

### Command Line

```bash
# Process entire PDF
python -m src.main document.pdf -o output_directory/

# Process specific pages (e.g., pages 1-5)
python -m src.main document.pdf -o output/ --start-page 1 --end-page 5

# Process single page
python -m src.main document.pdf -o output/ --start-page 3 --end-page 3

# With debug mode (visualize bounding boxes)
python -m src.main document.pdf --debug -o output/
```

### Python API

```python
import asyncio
from src.main import OCRPipeline

async def process_pdf():
    pipeline = OCRPipeline()
    
    # Process entire PDF
    results = await pipeline.process_pdf(
        pdf_path="document.pdf",
        output_dir="output_html/"
    )
    
    # Print summary
    print(f"Processed {len(results)} pages")
    
    for i, result in enumerate(results, 1):
        score = result.validation_report.confidence_score
        blocks = len(result.text_data.content_blocks)
        print(f"Page {i}: {score:.1f}/100, {blocks} text blocks")

asyncio.run(process_pdf())
```

## 📂 Output Structure

When processing a PDF named `invoice.pdf` with 3 pages:

```
output_directory/
├── invoice_page_1.html
├── invoice_page_2.html
└── invoice_page_3.html
```

Each HTML file is a standalone, pixel-perfect reproduction of that page.

## 🎯 Use Cases

### 1. Invoice Processing
```bash
python -m src.main invoices/january_2026.pdf -o processed_invoices/
```

### 2. Contract Analysis
```bash
# Process first 10 pages only
python -m src.main contract.pdf -o contract_output/ --start-page 1 --end-page 10
```

### 3. Scientific Papers
```bash
python -m src.main research_paper.pdf -o paper_html/
```

### 4. Legal Documents
```bash
python -m src.main legal_doc.pdf -o legal_html/ --debug
```

### 5. Scanned Multi-page Documents
```bash
# Preprocessing is especially important for scans
python -m src.main scanned_doc.pdf -o output/
# (Preprocessing is enabled by default)
```

## 🔧 Advanced Usage

### Process Specific Pages

```python
# Process pages 5-10
results = await pipeline.process_pdf(
    pdf_path="large_document.pdf",
    output_dir="output/",
    start_page=5,
    end_page=10
)
```

### Batch Process Multiple PDFs

```python
import asyncio
from pathlib import Path
from src.main import OCRPipeline

async def batch_process():
    pipeline = OCRPipeline()
    
    for pdf_file in Path("input_pdfs").glob("*.pdf"):
        print(f"Processing {pdf_file.name}...")
        
        output_dir = Path("output_html") / pdf_file.stem
        results = await pipeline.process_pdf(pdf_file, output_dir)
        
        avg_score = sum(r.validation_report.confidence_score for r in results) / len(results)
        print(f"  ✓ {len(results)} pages, avg: {avg_score:.1f}/100")

asyncio.run(batch_process())
```

### With Validation Checks

```python
results = await pipeline.process_pdf("document.pdf", "output/")

# Check which pages passed validation
for result in results:
    if not result.validation_report.validation_passed:
        print(f"⚠️  Page {result.page_number} failed validation")
        print(f"   Confidence: {result.validation_report.confidence_score:.1f}/100")
        for error in result.validation_report.errors:
            print(f"   - {error}")
```

## ⚙️ Configuration

### PDF Conversion Settings

The system uses **300 DPI** for PDF-to-image conversion, which is controlled in the code. This provides excellent quality for most documents.

### Preprocessing for PDFs

All PDF pages go through the same preprocessing pipeline as images:
- Deskewing (if rotated)
- Noise reduction
- Contrast enhancement
- Border removal

To disable preprocessing:
```bash
python -m src.main document.pdf --no-preprocess -o output/
```

Or in Python:
```python
from src.config import get_config
config = get_config()
config.preprocessing_enabled = False

pipeline = OCRPipeline()
```

## 📊 Performance

### Typical Performance
- **Single page PDF**: 2-3 seconds per page
- **10-page PDF**: ~25-30 seconds total
- **100-page PDF**: ~4-5 minutes total

### Optimization Tips
1. **Process specific pages** if you don't need the entire document
2. **Batch process** during off-hours for large volumes
3. **Disable preprocessing** for high-quality digital PDFs (not scans)

### Cost
- **~$0.003-0.005 per page** using Gemini Flash models
- 100-page PDF = ~$0.30-0.50

## 🐛 Troubleshooting

### PyMuPDF Not Installed

**Error**: `PyMuPDF is required for PDF processing`

**Solution**:
```bash
pip install pymupdf
```

### Large PDFs Take Too Long

**Solutions**:
1. Process specific page ranges
2. Disable preprocessing for digital PDFs
3. Process in batches

### Poor Quality for Scanned PDFs

**Solutions**:
1. Ensure preprocessing is enabled (default)
2. Check original PDF quality (aim for 300 DPI scans)
3. Try debug mode to visualize bounding boxes

### Memory Issues with Large PDFs

**Solution**: Process pages in batches
```python
# Process 10 pages at a time
for start in range(1, 101, 10):
    end = min(start + 9, 100)
    results = await pipeline.process_pdf(
        "large.pdf",
        f"output/batch_{start}_{end}/",
        start_page=start,
        end_page=end
    )
```

## 📝 Output Quality

### What to Expect

✅ **Best Results**:
- Digital PDFs with clear text
- Well-formatted documents
- Standard fonts and layouts

✅ **Good Results**:
- High-quality scans (300+ DPI)
- Clean, crisp text
- Minimal background noise

⚠️ **May Need Manual Review**:
- Low-quality scans (<150 DPI)
- Handwritten text
- Complex multi-column layouts
- Heavy background images/watermarks

## 🎓 Examples

See `examples/example_pdf_processing.py` for complete working examples:

1. **Example 1**: Process entire PDF
2. **Example 2**: Process specific pages
3. **Example 3**: Batch process multiple PDFs
4. **Example 4**: Process with validation checks

Run an example:
```bash
# Edit the file to uncomment the example you want
python examples/example_pdf_processing.py
```

## 📚 Related Documentation

- [QUICKSTART.md](../QUICKSTART.md) - Installation and basic usage
- [README.md](../README.md) - Project overview
- [docs/claude.md](../docs/claude.md) - Complete technical documentation

## 💡 Tips

1. **Always specify an output directory** for PDFs (not a single file)
2. **Use debug mode** when first testing with a new document type
3. **Check validation reports** to identify problem pages
4. **Process page ranges** during development/testing
5. **Enable preprocessing** for scanned documents (default: on)

## 🎯 Command Quick Reference

```bash
# Basic
python -m src.main doc.pdf -o output/

# Specific pages
python -m src.main doc.pdf -o output/ --start-page 5 --end-page 10

# Debug mode
python -m src.main doc.pdf --debug -o output/

# No preprocessing
python -m src.main doc.pdf --no-preprocess -o output/

# Custom API key
python -m src.main doc.pdf --api-key YOUR_KEY -o output/
```

---

**Your PDF documents are fully supported! 🎉**
