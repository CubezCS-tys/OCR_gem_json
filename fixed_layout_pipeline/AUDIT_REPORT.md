# Fixed-Layout Pipeline — Deep Audit Report

**Date:** 2026-02-16  
**Scope:** All 14 Python modules in `fixed_layout_pipeline/` (≈ 5,100 LOC)  
**Auditor:** Automated code audit

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Module Inventory](#3-module-inventory)
4. [Data Flow Analysis](#4-data-flow-analysis)
5. [Critical Bugs](#5-critical-bugs)
6. [Code Quality Issues](#6-code-quality-issues)
7. [Structural & Design Issues](#7-structural--design-issues)
8. [Documentation vs Reality Gaps](#8-documentation-vs-reality-gaps)
9. [Performance Concerns](#9-performance-concerns)
10. [Security Considerations](#10-security-considerations)
11. [Test Coverage](#11-test-coverage)
12. [Dependency Analysis](#12-dependency-analysis)
13. [Recommendations Summary](#13-recommendations-summary)

---

## 1. Executive Summary

The `fixed_layout_pipeline` is a well-architected OCR pipeline that converts scanned PDFs to pixel-accurate HTML using Azure Document Intelligence. The canonical JSON schema is thoughtfully designed with Pydantic models, and the dual-renderer approach (fidelity + semantic) is a strong design choice.

**Overall Assessment: 7/10 — Solid foundation, but several integration gaps prevent end-to-end usage.**

| Category | Rating | Notes |
|----------|--------|-------|
| Architecture | ★★★★☆ | Excellent separation of concerns |
| Schema design | ★★★★★ | Comprehensive Pydantic models with full geometry |
| OCR integration | ★★★★☆ | Thorough Azure DI conversion |
| HTML rendering | ★★★★☆ | Two renderers with good BiDi support |
| Integration / wiring | ★★☆☆☆ | Several modules not connected to pipeline |
| Error handling | ★★☆☆☆ | Minimal try/except in orchestration |
| Testing | ☆☆☆☆☆ | No tests exist |
| Documentation accuracy | ★★☆☆☆ | README describes features that don't exist |

---

## 2. Architecture Overview

```
PDF ─┬─► ingest.py ──► preprocess.py ──► ocr_engine.py ──► reading_order.py ──► pipeline.py (orchestrator)
     │                                                                              │
     │                                                                              ├──► html_renderer.py    (image-overlay HTML)
     │                                                                              ├──► dual_renderer.py    (fidelity + semantic + markdown)
     │                                                                              └──► figure_extractor.py (crop figures)
     │
     ├─► schema.py         (Pydantic canonical JSON models)
     ├─► config.py         (dataclass configuration)
     ├─► qa_evaluation.py  (CER/WER/TEDS/SSIM metrics)        ← NOT WIRED
     └─► llm_enrichment.py (LLM reading order repair)          ← NOT WIRED
```

**Architecture pattern:** Canonical Representation + Fixed-Layout HTML Overlay  
**Primary OCR engine:** Azure Document Intelligence (`prebuilt-layout`)  
**Languages:** Arabic (primary), English, French

---

## 3. Module Inventory

| Module | Lines | Purpose | Status |
|--------|------:|---------|--------|
| `schema.py` | 451 | Pydantic canonical JSON models | ✅ Solid |
| `config.py` | 120 | Pipeline configuration dataclasses | ⚠️ Incomplete |
| `ingest.py` | 189 | PDF → page images via PyMuPDF | ✅ Solid |
| `preprocess.py` | 329 | Deskew, denoise, dewarp, binarise | ⚠️ Dewarp is stub |
| `ocr_engine.py` | 649 | Azure DI → canonical schema | ⚠️ Dead code |
| `reading_order.py` | 244 | Heuristic column detection + RTL ordering | ✅ Solid |
| `pipeline.py` | 348 | End-to-end orchestrator | ⚠️ Incomplete wiring |
| `html_renderer.py` | 539 | Image-overlay fixed-layout HTML | ✅ Solid |
| `dual_renderer.py` | 1,242 | Fidelity + Semantic + Markdown renderers | ✅ Well designed |
| `figure_extractor.py` | 148 | Crop figure regions from pages | ✅ Clean |
| `qa_evaluation.py` | 473 | CER/WER/TEDS/SSIM metrics | ⚠️ Not wired |
| `llm_enrichment.py` | ~230 | LLM reading order repair | ❌ Broken import |
| `__main__.py` | 141 | CLI entry point | ⚠️ Missing commands |
| `__init__.py` | 32 | Package exports | ⚠️ Missing exports |
| **Total** | **~5,135** | | |

---

## 4. Data Flow Analysis

### 4.1 Happy Path (Full Pipeline)

```
1. pipeline.process(pdf_path)
2.   └─► ingest.extract_source_metadata()      → DocumentSource
3.   └─► ingest.rasterise_pdf()                → list[PageImage]
4.   └─► [optional] preprocess.preprocess_page() per page
5.   └─► ocr_engine.analyze_pdf()              → CanonicalDocument
6.       └─► Azure DI API call
7.       └─► _convert_azure_result()           → pages with blocks, lines, tokens, tables
8.       └─► _apply_azure_reading_order()
9.   └─► figure_extractor.extract_figures()    → figures cropped & saved
10.  └─► reading_order.resolve_reading_order() per page (heuristic)
11.  └─► html_renderer.render_to_file()        → HTML output
12.  └─► schema.CanonicalDocument.save()       → JSON output
```

### 4.2 QA Loop (JSON → HTML Regeneration)

```
1. pipeline.regenerate_html(canonical_json_path)
2.   └─► CanonicalDocument.load()
3.   └─► html_renderer.render_to_file()
```

### 4.3 Disconnected Modules

These modules exist but are **never called** by the pipeline or CLI:

| Module | What it does | Issue |
|--------|-------------|-------|
| `qa_evaluation.py` | CER/WER/Kendall τ/TEDS/SSIM | No CLI command, not imported in pipeline |
| `llm_enrichment.py` | LLM reading order repair | `LLMEnrichmentConfig` missing from `config.py` |
| `dual_renderer.py` | Fidelity + Semantic + Markdown | Not exported in `__init__.py`, no CLI command |

---

## 5. Critical Bugs

### 5.1 `LLMEnrichmentConfig` Missing from `config.py` — BROKEN IMPORT

**Severity:** 🔴 Critical (module cannot be imported)

`llm_enrichment.py` line 5 imports:
```python
from .config import LLMEnrichmentConfig
```

But `config.py` does not define `LLMEnrichmentConfig`. The class does not exist anywhere in the codebase. This means:
- `import fixed_layout_pipeline.llm_enrichment` will raise `ImportError`
- The `--llm-enrich` flag documented in the README cannot work

**Fix:** Add `LLMEnrichmentConfig` to `config.py`:
```python
@dataclass
class LLMEnrichmentConfig:
    enabled: bool = False
    provider: str = "gemini"       # "gemini" or "mistral"
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    gemini_model: str = "gemini-1.5-flash"
    mistral_api_key: str = field(default_factory=lambda: os.environ.get("MISTRAL_API_KEY", ""))
    mistral_model: str = "mistral-large-latest"
```

### 5.2 Pipeline Stage Numbering Inconsistency

**Severity:** 🟡 Medium (confusing logs)

The pipeline logs print inconsistent stage counts:
- Stages 1–4 show `[N/6]`
- Stage 5 (figure extraction) switches to `[5/7]`
- Stages 6–7 show `[6/7]` and `[7/7]`

The figure extraction stage was added after the original 6-stage plan, but stages 1–4 were never updated from `/6` to `/7`.

### 5.3 `text_opacity` Default is 1.0 — Contradicts Architecture

**Severity:** 🟡 Medium (renders visible text instead of invisible overlay)

In `config.py`, `RendererConfig.text_opacity` defaults to `1.0` (fully visible). The entire architecture is built around **invisible** text overlaid on scan images. The README example correctly shows `0.0`.

The `html_renderer.py` then uses `color: transparent` regardless of opacity (line ~147), but the opacity value is used elsewhere for debug toggling. This inconsistency means the field is misleading — it's not actually used as CSS opacity; the text color is always `transparent`.

### 5.4 Duplicate Token Construction in `ocr_engine.py`

**Severity:** 🟡 Medium (wasted CPU, potential data inconsistency)

In `_convert_azure_page()`:
1. Lines 259–278 build a `word_map: dict[str, Token]` by iterating all words
2. Lines 283–320 iterate all words **again** inside the lines loop, creating **new** `Token` objects

The `word_map` from step 1 is **never used**. This means:
- Every word's polygon is converted from inches to pixels **twice**
- Two different `Token` objects exist for the same word (potential inconsistency)

---

## 6. Code Quality Issues

### 6.1 No Error Handling in CLI

`__main__.py` calls `pipeline.process()` without try/except. If Azure credentials are missing, the user gets a raw Python traceback rather than a helpful error message.

### 6.2 WER Computation is Incorrect

In `qa_evaluation.py`, `compute_cer()` calculates WER by calling `compute_edit_distance()` on space-joined word strings:
```python
wer_distance, _, _, _ = compute_edit_distance(
    " ".join(ref_words), " ".join(hyp_words)
)
wer = wer_distance / len(ref_words)
```

This computes the **character-level** edit distance on joined words, then divides by word count — a mathematically meaningless metric. WER should use word-level edit distance (where each word is a unit).

### 6.3 Hardcoded Confidence Values

`ocr_engine.py` hardcodes confidence values in several places:
- Table confidence: `0.9` (line ~577)
- Per-cell confidence: `0.9` (line ~566)  
- Figure confidence: `0.85` (line ~613)
- Reading order confidence: `0.85` (line ~642)

These are not based on Azure's actual confidence signals.

### 6.4 Column Detection Uses Block Centers

`reading_order.py` `_detect_columns()` sorts blocks by their horizontal center, then looks for gaps. This can break with:
- Wide blocks (spanning columns)
- Side-by-side blocks with different widths
- Marginal annotations

### 6.5 Heuristic Reading Order Never Overrides Engine Order

The pipeline runs heuristic reading order with confidence `0.70` and only overrides if it exceeds the engine order (`0.85`). Since `0.70 < 0.85`, the heuristic **never actually replaces** the engine order. The code runs but has no effect.

### 6.6 Missing `__all__` in `__init__.py`

Only 5 symbols are exported:
```python
__all__ = ["Pipeline", "PipelineConfig", "CanonicalDocument", "FixedLayoutRenderer", "process_pdf"]
```

Missing: `FidelityRenderer`, `SemanticRenderer`, `MarkdownRenderer`, `render_all`, `QAReport`, `generate_qa_report`, `flag_low_confidence`.

---

## 7. Structural & Design Issues

### 7.1 Two Renderers, One Architecture Problem

The pipeline has **two independent HTML renderer modules**:

| Renderer | Module | Technique |
|----------|--------|-----------|
| `FixedLayoutRenderer` | `html_renderer.py` | Background image + invisible text overlay |
| `FidelityRenderer` | `dual_renderer.py` | White canvas + positioned visible text (no image) |

The pipeline (`pipeline.py`) only uses `FixedLayoutRenderer`. The `FidelityRenderer` (which also includes `SemanticRenderer` and `MarkdownRenderer`) is unreachable from the CLI or pipeline. Users would need to import it manually.

These solve different problems:
- `FixedLayoutRenderer`: Preserves visual fidelity via the scan image
- `FidelityRenderer`: Reproduces the document using only OCR text + geometry (no scan required)

The naming is confusing — "Fidelity" renderer actually has **less** visual fidelity than the image-overlay renderer.

### 7.2 `new_pipeline/` Directory is Empty

An empty `new_pipeline/` subdirectory exists with no contents. This is dead weight that creates confusion about whether a refactor is in progress.

### 7.3 Preprocessing Image Re-encoding Pipeline

In `pipeline.py` (stage 3), preprocessed images go through:
1. Decode from base64 data URI with OpenCV
2. Preprocess with OpenCV
3. Re-encode as JPEG (for Azure size limits)
4. Also re-encode as WebP (for HTML background)
5. Re-create base64 data URI

This is 5 encode/decode operations per page. A simpler approach would pass raw numpy arrays through the pipeline and encode once at the end.

### 7.4 `QAConfig` Referenced in README But Not in Code

The README shows:
```python
PipelineConfig(
    qa=QAConfig(confidence_threshold=0.80),
)
```

But `QAConfig` doesn't exist in `config.py` and `PipelineConfig` has no `qa` field.

---

## 8. Documentation vs Reality Gaps

| README Claim | Reality |
|------|---------|
| CLI command `python -m fixed_layout_pipeline qa` | ❌ `qa` subcommand does not exist in `__main__.py` |
| CLI flag `--llm-enrich` | ❌ Not implemented in argparse |
| Stage table includes `qa_evaluation.py` | ⚠️ Module exists but is not wired into pipeline |
| Stage table includes `llm_enrichment.py` | ❌ Module has broken import (`LLMEnrichmentConfig` missing) |
| Config includes `LLMEnrichmentConfig` | ❌ Class doesn't exist in `config.py` |
| Config includes `QAConfig` | ❌ Class doesn't exist in `config.py` |
| Output `text_opacity: 0.0` | ⚠️ Actual default is `1.0` |
| 6 pipeline stages listed | ⚠️ Pipeline actually has 7 stages (figure extraction added) |
| Evaluation metrics table lists 6 metrics | ⚠️ All metrics are implemented but unreachable |

---

## 9. Performance Concerns

### 9.1 Full PDF Sent to Azure DI (Good)
When no preprocessing is applied, the entire PDF is sent as one API call. This is optimal.

### 9.2 Individual Page API Calls (Expensive)
When preprocessing is enabled, each page is sent as a separate Azure DI API call (in `_ocr_preprocessed_pages`). For a 128-page document, this means 128 API calls instead of 1.

### 9.3 Base64 Image Embedding
With `embed_images=True` (default), every page image is base64-encoded into the HTML. For a 128-page document at 300 DPI, this creates multi-GB HTML files. Consider:
- Default to `embed_images=False`
- Reference external WebP files instead

### 9.4 Levenshtein Edit Distance is O(n×m)
`compute_edit_distance()` in `qa_evaluation.py` uses a standard O(n×m) dynamic programming approach. For long documents, this is memory-intensive. Consider using `rapidfuzz` or `python-Levenshtein` for performance-critical paths.

### 9.5 No Parallelism in OCR
`_ocr_preprocessed_pages` processes pages sequentially. The config has `max_workers=4` but it's never used. `concurrent.futures.ThreadPoolExecutor` would enable parallel Azure API calls.

---

## 10. Security Considerations

### 10.1 API Keys in Environment Variables
API keys are loaded from environment variables — this is acceptable for development but consider:
- Azure Key Vault integration for production
- Key rotation support

### 10.2 No Input Validation on PDF Files
`pipeline.process()` only checks if the file exists. No validation for:
- File size limits
- Malicious PDF content (PDF bombs)
- File type verification (could pass a non-PDF)

### 10.3 Base64 Data URIs in HTML
Embedding large base64 blobs creates potential XSS surface if the HTML is served on the web. HTML output should be treated as trusted-only.

---

## 11. Test Coverage

**Coverage: 0%** — No test files exist anywhere in the pipeline.

### Critical paths that need tests:

| Priority | What to test | Module |
|----------|-------------|--------|
| P0 | Schema serialization roundtrip (save → load) | `schema.py` |
| P0 | Azure result → canonical conversion | `ocr_engine.py` |
| P0 | BBox.iou() geometric calculations | `schema.py` |
| P0 | Polygon → BBox conversion | `schema.py` |
| P1 | Inch → pixel coordinate conversion | `ocr_engine.py` |
| P1 | Reading order heuristic (RTL, LTR, multi-column) | `reading_order.py` |
| P1 | Kendall Tau computation | `reading_order.py` |
| P1 | HTML rendering (spots check for structure) | `html_renderer.py` |
| P1 | Edit distance / CER / WER | `qa_evaluation.py` |
| P2 | Direction/language detection | `ocr_engine.py` |
| P2 | Table HTML generation | `schema.py` |
| P2 | Preprocessing (deskew, denoise) | `preprocess.py` |
| P2 | Figure extraction bounds clamping | `figure_extractor.py` |

---

## 12. Dependency Analysis

### 12.1 Required Dependencies

| Package | Purpose | In `requirements.txt` |
|---------|---------|:---------------------:|
| `pydantic>=2.0` | Schema models | ✅ |
| `PyMuPDF>=1.24.0` | PDF rasterisation | ✅ |
| `azure-ai-documentintelligence>=1.0.0` | OCR engine | ✅ |
| `azure-core>=1.30.0` | Azure SDK base | ✅ |
| `opencv-python-headless>=4.8.0` | Image preprocessing | ✅ |
| `numpy>=1.24.0` | Array operations | ✅ |
| `Pillow>=10.0.0` | Image format conversion | ✅ |
| `python-dotenv` | `.env` file loading | ❌ **MISSING** |

### 12.2 Missing Dependency: `python-dotenv`

`config.py` line 14 does:
```python
from dotenv import load_dotenv
```

But `python-dotenv` is not listed in `requirements.txt`. This will cause an `ImportError` on a fresh install.

### 12.3 Optional Dependencies

| Package | Purpose | Listed |
|---------|---------|:------:|
| `scikit-image` | Binarisation (Sauvola) + SSIM | ✅ |
| `pytesseract` | Orientation detection | ✅ (commented) |
| `google-generativeai` | LLM enrichment (Gemini) | ✅ |
| `mistralai` | LLM enrichment (Mistral) | ✅ (commented) |

---

## 13. Recommendations Summary

### 🔴 Must Fix (Blocking Issues)

| # | Issue | Module | Effort |
|---|-------|--------|--------|
| 1 | Add `LLMEnrichmentConfig` to `config.py` | `config.py` | 15 min |
| 2 | Add `python-dotenv` to `requirements.txt` | `requirements.txt` | 1 min |
| 3 | Fix pipeline stage numbering (`[N/6]` → `[N/7]`) | `pipeline.py` | 5 min |
| 4 | Remove dead `word_map` code in OCR engine | `ocr_engine.py` | 10 min |
| 5 | Fix `text_opacity` default to `0.0` | `config.py` | 1 min |

### 🟡 Should Fix (Functionality Gaps)

| # | Issue | Module | Effort |
|---|-------|--------|--------|
| 6 | Wire `qa_evaluation.py` into pipeline + CLI (`qa` command) | `pipeline.py`, `__main__.py` | 1 hr |
| 7 | Wire `llm_enrichment.py` into pipeline + CLI (`--llm-enrich`) | `pipeline.py`, `__main__.py` | 1 hr |
| 8 | Wire `dual_renderer.py` into CLI (render command) | `__main__.py` | 30 min |
| 9 | Fix WER calculation (word-level edit distance) | `qa_evaluation.py` | 30 min |
| 10 | Add error handling in CLI (try/except, user-friendly messages) | `__main__.py` | 30 min |
| 11 | Update README to match actual implementation | `README.md` | 1 hr |
| 12 | Export `FidelityRenderer`, `SemanticRenderer`, etc. in `__init__.py` | `__init__.py` | 5 min |

### 🟢 Nice to Have (Improvements)

| # | Issue | Module | Effort |
|---|-------|--------|--------|
| 13 | Add unit tests (P0 tests above) | new `tests/` dir | 4 hrs |
| 14 | Implement real dewarping (replace placeholder) | `preprocess.py` | 4 hrs |
| 15 | Add parallel OCR for preprocessed pages | `pipeline.py` | 1 hr |
| 16 | Default `embed_images=False` for large documents | `config.py` | 5 min |
| 17 | Remove empty `new_pipeline/` directory | filesystem | 1 min |
| 18 | Add `QAConfig` to `config.py` and `PipelineConfig` | `config.py` | 15 min |
| 19 | Use actual Azure confidence for tables/figures | `ocr_engine.py` | 30 min |
| 20 | Make heuristic reading order confidence dynamic | `reading_order.py` | 30 min |

---

*End of audit report.*
