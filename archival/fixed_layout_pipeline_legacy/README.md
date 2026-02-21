# Fixed-Layout OCR Pipeline

**Pixel-accurate HTML reproduction of scanned Arabic/English/French documents.**

## Architecture

```
PDF → Rasterise (300+ DPI) → Preprocess → Azure DI OCR → Canonical JSON → HTML Overlay
                                                              ↑                ↓
                                                          QA Loop ←──── Manual Review
```

This implements the **"Canonical Representation + Fixed-Layout HTML Overlay"** pattern — the most robust architecture for strict layout fidelity and complex Arabic documents.

### How it works

1. **Page image = visual fidelity.** The original scan is rendered as a background image.
2. **Invisible text overlay = functionality.** OCR text is positioned at exact coordinates over the image — invisible to the eye, but selectable, searchable, and copy-pasteable.
3. **Canonical JSON = system-of-record.** All geometric data (word bboxes, tables, reading order) is stored in a structured JSON. HTML regenerates deterministically from this.

### Why Azure Document Intelligence?

For **Arabic-primary documents** mixed with English and French:
- Explicitly lists Arabic for handwritten + printed text extraction
- Returns word-level bounding polygons + confidence
- Table structure with cell polygons, row/col spans
- Content in reading order via paragraph spans
- Native English + French support

## Quick Start

### 1. Install dependencies

```bash
cd fixed_layout_pipeline
pip install -r requirements.txt
```

### 2. Set Azure credentials

```bash
export AZURE_DI_ENDPOINT="https://your-resource.cognitiveservices.azure.com/"
export AZURE_DI_API_KEY="your-key"
```

### 3. Process a PDF

```bash
# Full pipeline
python -m fixed_layout_pipeline process document.pdf --output ./output

# With debug bounding boxes (shows word-level boxes)
python -m fixed_layout_pipeline process document.pdf --debug

# Specific page range
python -m fixed_layout_pipeline process document.pdf --pages 0-5

# Higher DPI for small Arabic fonts
python -m fixed_layout_pipeline process document.pdf --dpi 400

# With LLM reading order repair
python -m fixed_layout_pipeline process document.pdf --llm-enrich
```

### 4. Python API

```python
from fixed_layout_pipeline import Pipeline, PipelineConfig

config = PipelineConfig.from_env()
config.raster.dpi = 300
config.renderer.debug_boxes = False

pipeline = Pipeline(config)
doc, html_path = pipeline.process("document.pdf", output_dir="./output")

print(doc.summary())
# {'pages': 10, 'total_blocks': 85, 'avg_confidence': 0.92, ...}
```

### 5. QA Loop (edit JSON → regenerate HTML)

```bash
# Inspect document
python -m fixed_layout_pipeline info output/doc_canonical.json -v

# Edit the canonical JSON (fix reading order, correct text)
# ... manual edits ...

# Regenerate HTML deterministically
python -m fixed_layout_pipeline regenerate output/doc_canonical.json

# Run QA metrics
python -m fixed_layout_pipeline qa output/doc_canonical.json -v
```

## Output Structure

```
output/
└── document_name/
    ├── document_name.html           # Fixed-layout HTML (the deliverable)
    ├── document_name_canonical.json  # Canonical JSON (system-of-record)
    └── pages/                        # Rasterised page images
        ├── page_0000.webp
        ├── page_0001.webp
        └── ...
```

## Canonical JSON Schema

The JSON stores everything needed to reproduce the HTML:

```json
{
  "document_id": "uuid",
  "source": { "filename": "scan.pdf", "page_count": 128 },
  "pages": [{
    "page_index": 0,
    "image": { "uri": "pages/page_0000.webp", "width_px": 2480, "height_px": 3508, "dpi": 300 },
    "blocks": [{
      "block_id": "b_p0_b0",
      "block_type": "text",
      "bbox": { "x0": 100, "y0": 200, "x1": 2300, "y1": 280 },
      "direction": "rtl",
      "language": "ar",
      "confidence": 0.93,
      "lines": [{
        "line_id": "l_p0_l0",
        "tokens": [{
          "token_id": "t_p0_w0",
          "text": "بسم",
          "bbox": { "x0": 2100, "y0": 205, "x1": 2290, "y1": 275 },
          "confidence": 0.95
        }]
      }]
    }],
    "tables": [{ "cells with row/col/spans/polygons" }],
    "reading_order": {
      "sequence": ["b_p0_b0", "b_p0_b1", "b_p0_tb0"],
      "confidence": 0.85,
      "method": "engine"
    }
  }]
}
```

## Pipeline Stages

| Stage | Module | What it does |
|-------|--------|-------------|
| **1. Ingest** | `ingest.py` | PDF → page images at configured DPI |
| **2. Preprocess** | `preprocess.py` | Deskew, denoise, dewarp, orientation detection |
| **3. OCR** | `ocr_engine.py` | Azure DI → word/line bboxes, tables, paragraphs |
| **4. Reading Order** | `reading_order.py` | Heuristic column detection + RTL ordering |
| **5. Render** | `html_renderer.py` | Page image + invisible text overlay HTML |
| **6. QA** | `qa_evaluation.py` | CER/WER, Kendall τ, TEDS, SSIM, confidence flags |
| **Optional** | `llm_enrichment.py` | LLM-based reading order repair (Gemini/Mistral) |

## HTML Features

- **Text selection** — select, copy, search invisible text over the scan
- **Debug mode** — toggle to see bounding boxes colored by confidence (green/orange/red)
- **Text visibility toggle** — show/hide the text layer for comparison
- **Confidence tooltips** — hover over text to see OCR confidence
- **RTL/BiDi** — proper `dir="rtl"` on Arabic spans, LTR for Latin
- **Print support** — clean print layout
- **Toolbar** — document title, page count, debug/text toggles

## Evaluation Metrics

| Metric | Measures | Tool |
|--------|----------|------|
| **CER** | Character-level OCR accuracy | `qa_evaluation.py` |
| **WER** | Word-level OCR accuracy | `qa_evaluation.py` |
| **Kendall τ** | Reading order correctness | `reading_order.py` |
| **TEDS** | Table structure fidelity | `qa_evaluation.py` |
| **SSIM** | Visual fidelity (HTML vs scan) | `qa_evaluation.py` |
| **Confidence flags** | Low-confidence elements for review | `qa_evaluation.py` |

## Configuration

All settings are in `config.py` with sensible defaults:

```python
PipelineConfig(
    azure=AzureConfig(model_id="prebuilt-layout"),
    raster=RasterConfig(dpi=300, image_format="webp"),
    preprocess=PreprocessConfig(deskew=True, denoise=True),
    renderer=RendererConfig(text_opacity=0.0, debug_boxes=False),
    llm=LLMEnrichmentConfig(enabled=False),
    qa=QAConfig(confidence_threshold=0.80),
)
```

## vs. Previous Pipeline

| | Previous (Mistral → reflow HTML) | This (Azure DI → fixed-layout overlay) |
|---|---|---|
| **Layout** | CSS flow, `max-width: 900px` | Pixel-accurate, absolute positioning |
| **Visual fidelity** | Approximated by CSS | Exact — page scan is the image |
| **Text selection** | Visible styled text | Invisible overlay on scan |
| **Coordinates** | Discarded | Preserved per word |
| **Reading order** | LLM-inferred `reading_order` int | Explicit sequence with provenance |
| **Confidence** | Not available | Per-word from Azure DI |
| **QA loop** | Edit JSON → rebuild HTML | Edit canonical JSON → regenerate HTML |
| **Tables** | Semantic `<table>` | Positioned overlay + semantic fallback |
