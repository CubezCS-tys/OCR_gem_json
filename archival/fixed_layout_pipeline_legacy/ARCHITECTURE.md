# Architecture & Design — Why This Pipeline Works

A breakdown of every design choice, smart trick, and engineering decision
that makes this scanned-Arabic-PDF-to-HTML pipeline genuinely excellent.

---

## The Core Insight

Everyone else ships OCR as an API that returns JSON.
Nobody ships **the last mile** — turning that JSON back into a document
that looks and feels like the original.

This pipeline does that last mile perfectly:

```
Scanned PDF  →  Azure prebuilt-read  →  Searchable PDF + OCR JSON  →  HTML
  (image)         ($1.50/1K pages)         (one API call)             (local, free)
```

One command. Three outputs. $1.50 per 1,000 pages.

---

## 1. The Replace-Text Trick

The signature innovation. Instead of either:
- Showing the ugly scan with invisible text (what Adobe does), or
- Trying to perfectly reconstruct the document from scratch (impossible for Arabic)

We do **both and neither**:

1. Rasterise the scanned page (keeps borders, lines, stamps, decorations)
2. For each OCR text bounding box:
   - Sample the background colour from a 4px margin strip around the text
   - Filter out dark pixels (the actual text ink) — keep only light pixels
   - Take the median colour
   - Paint a filled rectangle over the text area with that colour
3. Lay clean, rendered text on top at the exact OCR coordinates

**Result:** The document looks like the original — same borders, same layout,
same decorations — but with crisp, consistent, selectable digital text.

```python
# The background sampling — elegantly simple
light = [p for p in all_pixels if (p[0] + p[1] + p[2]) > 450]
light.sort(key=lambda p: p[0] + p[1] + p[2])
median = light[len(light) // 2]
```

This works on white paper, cream paper, yellowed paper, lined paper —
because it samples the *actual local background*, not a global assumption.

---

## 2. Two-Pass Text Fitting

The hardest problem: making text fill its bounding box without some lines
looking skinny and others looking fat.

**Naive approach** (what everyone does): set one font-size, apply `scaleX()`.
Lines with lots of text get compressed to 0.5x. Lines with little text
get stretched to 1.5x. Text weight looks wildly inconsistent.

**Our approach** — two-pass fitting in JavaScript:

```
Pass 1:  Iterate font-size (up to 8 rounds) until natural width
         is within 1% of target width.

Pass 2:  Apply scaleX() for the final <1% correction.
```

Every line ends up with `scaleX` between 0.99 and 1.01. Text weight
looks perfectly uniform across the entire page.

```javascript
for (let i = 0; i < 8; i++) {
    const ratio = targetW / natural;
    if (ratio > 0.99 && ratio < 1.01) break;  // close enough
    fontSize = fontSize * ratio;               // proportional adjustment
}
```

---

## 3. BiDi-First Design

Every text element gets a `dir` attribute based on Unicode BiDi analysis:

```python
def _first_strong_dir(text):
    for ch in text:
        cat = unicodedata.bidirectional(ch)
        if cat in ("R", "AL"):  return "rtl"
        if cat == "L":          return "ltr"
    return "rtl"  # default for Arabic docs
```

This means:
- Pure Arabic lines get `dir="rtl"` — browser renders right-to-left
- LTR content (English, numbers) within RTL lines flows correctly
- Mixed-direction content (citations, references) just works

The browser's native BiDi algorithm handles the rest. We don't fight it.

---

## 4. One API Call, Three Outputs

Azure's `prebuilt-read` with `output=[PDF]` returns:
- The OCR analysis (JSON with bounding boxes) — **included in the call**
- A searchable PDF — **included in the call**

Most people make two calls. We make one. The JSON is free.

```python
poller = client.begin_analyze_document(
    model_id="prebuilt-read",
    body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
    output=[AnalyzeOutputOption.PDF],  # also returns JSON analysis
)
result = poller.result()        # ← OCR JSON
pdf_stream = client.get_analyze_result_pdf(...)  # ← searchable PDF
```

Cost: `$1.50 / 1,000 pages`. That's it. For 1,878 pages: **$2.82**.

---

## 5. Three-Level Skip Logic

The batch pipeline has granular resumption — you can `Ctrl+C` at any point
and re-run safely:

| State | Action |
|-------|--------|
| All 3 files exist (PDF + JSON + HTML) | Skip entirely |
| PDF + JSON exist, HTML missing | Skip API call, render HTML only |
| Nothing exists | Full pipeline |

Zero-byte files (from crashes) don't count as "existing" — they get
re-processed automatically.

```python
if (out_pdf.exists() and out_pdf.stat().st_size > 0
        and out_json.exists() and out_json.stat().st_size > 0
        and out_html.exists() and out_html.stat().st_size > 0):
    return {"status": "skipped"}
```

This means you never pay Azure twice for the same document.

---

## 6. Thread-Local Client Pooling

Azure SDK clients aren't thread-safe. Creating one per request is wasteful.
Solution: one client per thread, cached by thread ID:

```python
_thread_clients: dict[int, object] = {}

def _get_client(endpoint, api_key):
    tid = threading.get_ident()
    if tid not in _thread_clients:
        _thread_clients[tid] = DocumentIntelligenceClient(...)
    return _thread_clients[tid]
```

With 4 workers processing 63 documents: 4 clients, 63 API calls.
Not 63 clients.

---

## 7. Self-Contained HTML

Every output HTML is a single file with zero external dependencies:

- Page images: **base64 data URIs** embedded in `<img src="data:image/webp;base64,...">`
- CSS: **inline** `<style>` block
- JavaScript: **inline** `<script>` block
- Fonts: **system font stack** (no web fonts to load)

You can email the HTML, put it on a USB stick, open it offline. It works
everywhere. No CORS, no CDN, no server required.

---

## 8. Debug Toolbar Built Into Every Document

Every generated HTML includes a dark toolbar with three toggle buttons:

| Button | Effect |
|--------|--------|
| **Debug Text** | Makes invisible text red — see exactly where text is positioned |
| **Boxes** | Blue outlines on every line bounding box — verify OCR accuracy |
| **Hide Image** | Fades scan to 8% opacity — see text layer in isolation |

This isn't a developer tool bolted on — it's part of the output.
Anyone checking document quality can toggle these without touching code.

---

## 9. WebP with Graceful Fallback

Images are encoded as WebP (typically 30–50% smaller than PNG).
If Pillow isn't installed, it falls back to PNG silently:

```python
try:
    from PIL import Image as PILImage
    img.save(buf, format="WEBP", quality=85)
except ImportError:
    buf.write(pix.tobytes("png"))  # fallback
```

Lazy `loading="lazy"` on images means a 64-page document doesn't
load all images upfront — the browser only rasterises what's visible.

---

## 10. Cost Tracking as a First-Class Feature

Every batch run prints exactly how much it cost:

```
📄 Pages processed:  1878
💰 Azure cost:  $2.8170
   (prebuilt-read @ $1.50 / 1K pages)
```

Per-document timing breaks down API time vs render time:

```
☁️  API time (sum):   1775.6s
🖨  Render time (sum): 335.7s
```

No surprises. No hidden charges. No "check your Azure portal" guesswork.

---

## 11. Deferred Imports

The CLI has 10+ subcommands, but only the one you invoke loads its
dependencies:

```python
def cmd_pipeline(args):
    from .batch_pipeline import run_pipeline  # loaded only when needed
```

Running `python -m fixed_layout_pipeline pipeline --dry-run` doesn't
import PyMuPDF, Pillow, or the Azure SDK. Startup is instant.

---

## 12. The Font Stack

Arabic text rendering requires the right fonts. The CSS declares a
cascade that works across systems:

```css
font-family: 'Traditional Arabic', 'Noto Naskh Arabic', 'Amiri',
             'Noto Serif', 'Times New Roman', serif;
```

- **Traditional Arabic**: Windows default, clean for body text
- **Noto Naskh Arabic**: Google's universal Arabic font (Linux/Mac)
- **Amiri**: elegant Naskh typeface for academic documents
- **Fallbacks**: serif generics that still render Arabic correctly

---

## 13. The Complete File Structure

```
fixed_layout_pipeline/
├── __main__.py            # 10 CLI subcommands
├── batch_pipeline.py      # Unified: PDF → searchable + JSON + HTML
├── batch_searchable.py    # Batch: PDF → searchable + JSON only
├── overlay_renderer.py    # Core HTML renderer (3 modes)
├── validate_pdfs.py       # PDF corruption checker + repair
├── config.py              # Environment / settings
├── schema.py              # Canonical data model (Pydantic)
├── ocr_engine.py          # Azure OCR abstraction
├── dual_renderer.py       # Fidelity / Semantic / Markdown renderers
├── gemini_html.py         # Gemini-based classification
├── read_html_renderer.py  # Word-level fidelity from prebuilt-read
└── ...
```

---

## How to Run

### Prerequisites

```bash
# 1. Python 3.10+ with venv
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set Azure credentials in .env
cat > .env << 'EOF'
AZURE_DI_ENDPOINT=https://your-instance.cognitiveservices.azure.com/
AZURE_DI_API_KEY=your-key-here
EOF
```

### Full Pipeline (Recommended)

One command — OCR + searchable PDF + JSON + replace-text HTML:

```bash
python -m fixed_layout_pipeline pipeline \
  --input pdfs/2026/2026/scanned \
  --output output_final \
  --workers 4 \
  --dpi 200
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `pdfs/2026/2026/scanned` | Folder of input PDFs |
| `--output` | `output_final` | Output directory |
| `--workers` | `4` | Parallel Azure API calls |
| `--dpi` | `200` | Image rasterisation DPI |
| `--mode` | `replace-text` | `replace-text`, `overlay`, or `text-only` |
| `--dry-run` | — | Show what would be processed, no API calls |

**Dry run** — see what will be processed without spending money:

```bash
python -m fixed_layout_pipeline pipeline \
  --input pdfs/2026/2026/scanned \
  --output output_final \
  --dry-run
```

Safe to re-run at any time — three-level skip logic avoids duplicate
API calls and duplicate renders.

### Individual Steps

**Step 1 — OCR only** (searchable PDF + JSON, no HTML):

```bash
python -m fixed_layout_pipeline batch \
  --input pdfs/2026/2026/scanned \
  --output output_final \
  --workers 4
```

**Step 2 — Render HTML** from existing OCR results:

```bash
# Replace-text mode (default — clean text on original background)
python -m fixed_layout_pipeline render \
  --input output_final \
  --dpi 200 \
  --mode replace-text

# Overlay mode (invisible text on scan image)
python -m fixed_layout_pipeline render \
  --input output_final \
  --dpi 200 \
  --mode overlay

# Text-only mode (no images, small file size)
python -m fixed_layout_pipeline render \
  --input output_final \
  --dpi 200 \
  --mode text-only
```

**Single file** — render one document directly:

```bash
python -m fixed_layout_pipeline overlay_renderer \
  --pdf output_final/0658-050-008-001/0658-050-008-001_searchable.pdf \
  --json output_final/0658-050-008-001/0658-050-008-001_ocr.json \
  --output output_final/0658-050-008-001/0658-050-008-001_replace_text.html \
  --dpi 200
```

### Validation

Check all output documents for completeness:

```bash
# Count fully complete documents
total=0; complete=0
for d in output_final/*/; do
  total=$((total + 1))
  stem=$(basename "$d")
  if [[ -f "${d}${stem}_searchable.pdf" \
     && -f "${d}${stem}_ocr.json" \
     && -f "${d}${stem}_replace_text.html" ]]; then
    complete=$((complete + 1))
  fi
done
echo "$complete / $total documents fully complete"
```

### Output Structure

```
output_final/
├── 0005-052-002-003/
│   ├── 0005-052-002-003_searchable.pdf   ← text-embedded PDF
│   ├── 0005-052-002-003_ocr.json         ← raw OCR bounding boxes
│   └── 0005-052-002-003_replace_text.html ← pixel-perfect HTML
├── 0658-050-008-001/
│   ├── ...
└── ...
```

---

## The Numbers

| Metric | Value |
|--------|-------|
| Documents processed | 63 |
| Total pages | 1,878 |
| Azure cost | $2.82 |
| Wall time (4 workers) | 14 minutes |
| Outputs per document | 3 (PDF + JSON + HTML) |
| HTML file size (replace-text) | 50–130 KB/page |
| API calls | 63 (one per document) |
| Failures | 0 |

---

## What Makes It Production-Ready

1. **Idempotent** — re-run any time, skips what's done, never double-charges
2. **Parallel** — 4 workers by default, configurable
3. **Resilient** — one failure doesn't crash the batch
4. **Observable** — cost tracking, timing, per-doc status, debug toolbar
5. **Portable** — single HTML files, no server needed
6. **Cheap** — $1.50/1K pages, the lowest Azure DI tier
7. **Fast** — 1,878 pages in 14 minutes including rendering
8. **Correct** — BiDi-first, proper Arabic RTL, two-pass fitting
