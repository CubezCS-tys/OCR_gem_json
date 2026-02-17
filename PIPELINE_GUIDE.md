# Scanned PDF → Searchable PDF → HTML Pipeline

End-to-end pipeline for converting scanned Arabic PDFs into searchable PDFs and
pixel-perfect HTML with selectable text.

---

## Overview

```
┌─────────────┐      ┌──────────────────────┐      ┌──────────────────┐
│ Scanned PDF │ ───▶ │ Azure prebuilt-read   │ ───▶ │ Searchable PDF   │
│ (image-only)│      │ ($1.50 / 1K pages)    │      │ + OCR JSON       │
└─────────────┘      └──────────────────────┘      └────────┬─────────┘
                                                            │
                                          ┌─────────────────┼─────────────────┐
                                          ▼                 ▼                 ▼
                                   ┌────────────┐   ┌────────────┐   ┌────────────┐
                                   │  Overlay    │   │ Replace-   │   │ Text-only  │
                                   │  (default)  │   │ text       │   │            │
                                   └────────────┘   └────────────┘   └────────────┘
```

| Step | Tool | Cost |
|------|------|------|
| 1. Searchable PDF + OCR JSON | Azure `prebuilt-read` | **$1.50 / 1K pages** |
| 2. HTML rendering | Local (PyMuPDF + Pillow) | **Free** |

---

## Prerequisites

### 1. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install azure-ai-documentintelligence pymupdf Pillow python-dotenv
```

### 2. Environment variables

Create a `.env` file in the project root:

```env
AZURE_DI_ENDPOINT=https://your-instance.cognitiveservices.azure.com/
AZURE_DI_API_KEY=your-api-key-here
```

---

## Step 1: Batch Searchable PDF Generation

Sends scanned PDFs to Azure Document Intelligence `prebuilt-read` and saves two
outputs per document:

- **Searchable PDF** — the original scan with an invisible text layer
- **OCR JSON** — full OCR results (words, lines, bounding boxes in inches)

Both are produced from a **single API call** — no extra cost for the JSON.

### Usage

```bash
# Activate the environment
source venv/bin/activate

# Dry run — see what would be processed, no API calls
python -m fixed_layout_pipeline batch \
  --input pdfs/scanned/ \
  --output output_searchable/ \
  --dry-run

# Run for real (4 parallel workers)
python -m fixed_layout_pipeline batch \
  --input pdfs/scanned/ \
  --output output_searchable/ \
  --workers 4
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--input`, `-i` | *(required)* | Directory containing scanned PDF files |
| `--output`, `-o` | *(required)* | Output directory (subdirs created per doc) |
| `--workers`, `-w` | `4` | Parallel Azure API calls |
| `--dry-run` | off | List files without processing |

### Output structure

```
output_searchable/
├── 0658-050-008-001/
│   ├── 0658-050-008-001_searchable.pdf   ← searchable PDF
│   └── 0658-050-008-001_ocr.json         ← OCR bounding boxes
├── 0658-050-008-003/
│   ├── 0658-050-008-003_searchable.pdf
│   └── 0658-050-008-003_ocr.json
└── ...
```

### Features

- **Skip logic** — already-processed docs are skipped automatically
- **Thread-safe** — per-thread Azure clients, safe for parallel processing
- **Cost tracking** — prints total pages and estimated cost on completion
- **Error resilience** — failures don't stop the batch; summary shows what failed

### Example output

```
============================================================
          BATCH SEARCHABLE PDF — SUMMARY
============================================================
  Total:   63
  ✅ OK:    63  (1878 pages, 837.7s)
  ⏭  Skip:  0
  ❌ Fail:  0

  💰 Cost: $2.8170  (prebuilt-read @ $1.50/1K)
============================================================
```

---

## Step 2: HTML Rendering

Converts the searchable PDF + OCR JSON into a self-contained HTML file.
Three rendering modes are available:

### Mode 1: Overlay (default)

Scan image as background + invisible selectable text on top.

```bash
python -m fixed_layout_pipeline.overlay_renderer \
  --pdf output_searchable/DOC_ID/DOC_ID_searchable.pdf \
  --json output_searchable/DOC_ID/DOC_ID_ocr.json \
  --dpi 200
```

- **Visual fidelity**: 100% — you see the exact scan
- **Text layer**: Invisible (`color: transparent`), but selectable/searchable
- **File size**: ~200–400 KB per page (base64 image embedded)
- **Output**: `DOC_ID_overlay.html`

### Mode 2: Replace-text ⭐ recommended

Scan image with **text erased** + clean rendered text overlaid.

```bash
python -m fixed_layout_pipeline.overlay_renderer \
  --pdf output_searchable/DOC_ID/DOC_ID_searchable.pdf \
  --json output_searchable/DOC_ID/DOC_ID_ocr.json \
  --replace-text \
  --dpi 200
```

- **Visual fidelity**: Keeps borders, lines, stamps, decorations from the scan
- **Text**: Visible, rendered in system Arabic fonts (Traditional Arabic, Amiri, etc.)
- **How it works**:
  1. Rasterises the page scan
  2. For each OCR line bbox, samples the background colour from the edges
  3. Paints a rectangle over the text area with that colour (erases scanned text)
  4. Lays clean rendered text on top at the exact OCR positions
- **File size**: ~50–130 KB per page (erased regions compress well)
- **Output**: `DOC_ID_replaced.html`

### Mode 3: Text-only

No image at all — just text positioned on a white page.

```bash
python -m fixed_layout_pipeline.overlay_renderer \
  --pdf output_searchable/DOC_ID/DOC_ID_searchable.pdf \
  --json output_searchable/DOC_ID/DOC_ID_ocr.json \
  --text-only \
  --dpi 200
```

- **Visual fidelity**: Text only, no borders or decorations
- **File size**: ~10–15 KB per page (no images)
- **Output**: `DOC_ID_text_only.html`

### Batch mode (all docs at once)

Process every subdirectory in an output folder:

```bash
# All docs → overlay (default)
python -m fixed_layout_pipeline.overlay_renderer \
  --input-dir output_searchable/ --dpi 200

# All docs → replace-text
python -m fixed_layout_pipeline.overlay_renderer \
  --input-dir output_searchable/ --replace-text --dpi 200

# All docs → text-only
python -m fixed_layout_pipeline.overlay_renderer \
  --input-dir output_searchable/ --text-only --dpi 200
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--pdf` | | Single PDF file path |
| `--json` | | Single OCR JSON file path |
| `--input-dir`, `-i` | | Directory of doc subdirectories (batch mode) |
| `--output`, `-o` | auto | Output HTML path (single mode only) |
| `--dpi` | `200` | Rasterisation resolution |
| `--format` | `webp` | Image format: `webp`, `png`, `jpeg` |
| `--quality` | `85` | Compression quality for lossy formats |
| `--replace-text` | off | Erase scan text, overlay rendered text |
| `--text-only` | off | No images, visible text on white |

### HTML toolbar

Every generated HTML includes a toolbar with debug buttons:

| Button | Effect |
|--------|--------|
| **Debug Text** | Shows text overlay in red (useful for checking alignment) |
| **Boxes** | Shows blue bounding box outlines around each line |
| **Hide Image** | Fades the background image to 8% opacity |

---

## Full workflow example

```bash
# 1. Activate environment
source venv/bin/activate

# 2. Process 63 scanned PDFs → searchable PDFs + OCR JSON
python -m fixed_layout_pipeline batch \
  --input pdfs/2026/2026/scanned/ \
  --output output_searchable/ \
  --workers 4

# 3. Render all as replace-text HTML
python -m fixed_layout_pipeline.overlay_renderer \
  --input-dir output_searchable/ \
  --replace-text --dpi 200

# 4. Open any HTML in a browser to view
```

---

## Architecture

### Searchable PDF pipeline (`batch_searchable.py`)

```
Input:   pdfs/scanned/*.pdf
           │
           ▼
   Azure prebuilt-read API
   (model: prebuilt-read, output: [PDF])
           │
           ├──▶ {stem}_searchable.pdf   (searchable PDF with invisible text)
           └──▶ {stem}_ocr.json         (full OCR: pages → lines → words + polygons)
```

The API returns both the searchable PDF and the OCR analysis in one call.
`ThreadPoolExecutor` runs up to N workers in parallel, each with its own
Azure client instance.

### HTML renderer (`overlay_renderer.py`)

```
Input:   {stem}_searchable.pdf + {stem}_ocr.json
           │
           ▼
   PyMuPDF rasterisation (200 DPI → webp base64)
           │
           ▼  (replace-text only)
   For each OCR line bbox:
     1. Sample background colour from 4px margin strip
     2. Filter out dark text pixels, take median of light pixels
     3. Paint fill rectangle over text area
           │
           ▼
   Build HTML:
     • <img> with base64 data URI (page scan)
     • <div class="tw"> per OCR line, positioned via CSS left/top/width/height
     • JavaScript fitAllWords() measures natural text width,
       applies scaleX() to fit each line into its OCR bbox exactly
           │
           ▼
   Single self-contained .html file (no external dependencies)
```

### OCR JSON structure (Azure prebuilt-read)

```json
{
  "pages": [
    {
      "width": 8.5,        // inches
      "height": 11.0,      // inches
      "lines": [
        {
          "content": "النص العربي",
          "polygon": [x0,y0, x1,y1, x2,y2, x3,y3]   // 4 corners in inches
        }
      ],
      "words": [
        {
          "content": "النص",
          "polygon": [x0,y0, x1,y1, x2,y2, x3,y3],
          "confidence": 0.98
        }
      ]
    }
  ]
}
```

---

## Cost summary

| Operation | Azure tier | Price |
|-----------|-----------|-------|
| Searchable PDF + OCR JSON | `prebuilt-read` | **$1.50 / 1,000 pages** |
| HTML rendering | Local | **Free** |

For 63 documents (1,878 pages): **$2.82 total**.

---

## File size comparison (single page)

| Mode | Size | Notes |
|------|------|-------|
| Overlay (default) | ~377 KB | Full scan image + invisible text |
| Replace-text | ~131 KB | Text regions erased → better compression |
| Text-only | ~14 KB | No image, text only |

---

## Validation

After batch processing, validate all searchable PDFs for corruption:

```bash
python -m fixed_layout_pipeline validate \
  --input output_searchable/

# Auto-fix corrupted files (re-wrap with pikepdf)
python -m fixed_layout_pipeline validate \
  --input output_searchable/ --fix
```
