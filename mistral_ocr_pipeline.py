#!/usr/bin/env python3
"""
Production-grade Mistral OCR pipeline with two-pass architecture.

Pass 1: Mistral OCR  → rich markdown text per page
Pass 2: Mistral Large → transform into DocumentStructure schema (same as Gemini pipeline)

Outputs the SAME Pydantic models as pdf_to_html.py, so HTMLRenderer works unchanged.

Architecture:
    PDF
     └─> Mistral OCR (perception)
          └─> pages[].markdown  (raw_ocr.md saved)
               └─> Mistral Large (reasoning + structuring, JSON-only)
                    └─> Pydantic validation (DocumentStructure)
                         └─> structured.json + final.html

Usage:
    python mistral_ocr_pipeline.py <pdf_path> [--output-dir ./outputs] [--pages-per-chunk 5]
"""

import os
import sys
import json
import time
import logging
import argparse
import pathlib
from typing import Optional
from dataclasses import dataclass, field

from dotenv import load_dotenv
from mistralai import Mistral
from pydantic import ValidationError

# Reuse EXACT schemas + renderer from the Gemini pipeline
from pdf_to_html import (
    DocumentStructure,
    DocumentMetadata,
    PageContent,
    TextBlock,
    Table,
    Image,
    HTMLRenderer,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mistral model constants
# ---------------------------------------------------------------------------
OCR_MODEL = "mistral-ocr-latest"
STRUCTURING_MODEL = "mistral-large-latest"

# Mistral OCR pricing (as of early 2026)
# https://docs.mistral.ai/capabilities/document/
MISTRAL_OCR_COST_PER_1K_PAGES = 2.00  # $1 per 1,000 pages
# Mistral Large pricing
MISTRAL_LARGE_INPUT_PER_1M = 0.50   # $0.50 per 1M input tokens
MISTRAL_LARGE_OUTPUT_PER_1M = 1.50  # $1.50 per 1M output tokens


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class MistralPipelineConfig:
    """Configuration for the Mistral two-pass pipeline."""
    ocr_model: str = OCR_MODEL
    structuring_model: str = STRUCTURING_MODEL
    include_image_base64: bool = True
    pages_per_chunk: int = 5           # Pages sent to LLM per structuring call
    max_retries: int = 3
    retry_delay: float = 2.0
    temperature: float = 0.0          # Deterministic structuring
    max_output_tokens: int = 65536
    save_raw_markdown: bool = True     # Save raw OCR markdown for auditing
    save_structured_json: bool = True  # Save validated JSON
    save_html: bool = True             # Save rendered HTML
    output_dir: str = "outputs"


# ---------------------------------------------------------------------------
# Schema definition (sent to LLM as instruction)
# ---------------------------------------------------------------------------
# We derive the JSON Schema directly from our Pydantic models so the LLM
# output is guaranteed to match validation.

def _get_chunk_schema() -> dict:
    """Return JSON schema for a chunk of pages (list of PageContent)."""
    page_schema = PageContent.model_json_schema()
    return {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": page_schema,
            }
        },
        "required": ["pages"],
    }


def _get_metadata_schema() -> dict:
    """Return JSON schema for DocumentMetadata."""
    return DocumentMetadata.model_json_schema()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

METADATA_PROMPT_TEMPLATE = """\
You are a document analysis engine.

Below is the OCR text from the FIRST PAGE of a PDF document.
Analyze it and return ONLY valid JSON matching this schema:

{schema}

Rules:
- Output valid JSON only — no explanations, no markdown fences.
- "total_pages" = {total_pages}
- Detect the primary language (e.g. "Arabic", "English", "French").
- Detect document_type (article, report, form, letter, book, etc.).
- Set is_scanned = true if the text looks OCR-processed.

OCR TEXT (page 1):
\"\"\"
{first_page_text}
\"\"\"
"""

STRUCTURING_PROMPT_TEMPLATE = """\
You are an expert document structuring engine.

Transform the following OCR text (pages {start_page}–{end_page}) into JSON that \
STRICTLY follows this schema:

{schema}

Rules:
- Output valid JSON only — no explanations, no markdown fences, no extra keys.
- Preserve the EXACT reading order from the OCR text.
- For each page, populate page_number, text_blocks, tables, images.
- text_blocks must classify each element:
    • "heading" (with level 1–6)
    • "paragraph"
    • "list_item" (use list_level for nesting depth)
    • "caption"
    • "footnote"
    • "quote"
    • "code"
    • "equation" (use LaTeX in content, set is_display_math)
- Tables: extract headers and rows arrays. Provide bbox if discernible.
- Images/Figures: describe with image_type, description, caption, and bbox.
- PRESERVE numeral systems exactly (Arabic-Indic ٠١٢٣٤٥٦٧٨٩ vs Western 0123456789).
- For RTL text set text_direction="rtl" on the text block.
- For multi-column layouts set has_multi_column=true and column_count.
- Set page_direction="rtl" for Arabic/Hebrew pages.
- Convert any table markdown into structured headers/rows — do NOT use HTML in tables.
- If a field is unknown, omit it or use null.
- Ensure all JSON strings are properly escaped (quotes, backslashes).

OCR TEXT:
\"\"\"
{ocr_text}
\"\"\"
"""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _ocr_img_to_pct_bbox(ocr_img: dict) -> dict:
    """
    Convert Mistral OCR pixel coordinates to percentage-based bbox.

    Mistral OCR returns absolute pixel coords:
        top_left_x, top_left_y, bottom_right_x, bottom_right_y

    We normalise to 0-100 percentages.  Since we don't know the page
    pixel dimensions from the OCR response, we estimate from the coords
    themselves (images near edges give a reasonable page-size estimate).
    If coords are missing, return a centered default.
    """
    tlx = ocr_img.get("top_left_x")
    tly = ocr_img.get("top_left_y")
    brx = ocr_img.get("bottom_right_x")
    bry = ocr_img.get("bottom_right_y")

    if None in (tlx, tly, brx, bry):
        # No coords → centre of page, 50% wide
        return {"top": 25.0, "left": 25.0, "width": 50.0, "height": 50.0}

    # Mistral OCR coords are typically normalised 0-1 already,
    # but some versions use pixel values.  Detect by magnitude.
    if max(brx, bry) <= 1.5:
        # Normalised 0-1
        return {
            "top":    round(tly * 100, 1),
            "left":   round(tlx * 100, 1),
            "width":  round((brx - tlx) * 100, 1),
            "height": round((bry - tly) * 100, 1),
        }
    else:
        # Pixel values — estimate page size as max coord + small margin
        est_w = max(brx, 1) * 1.05
        est_h = max(bry, 1) * 1.05
        return {
            "top":    round((tly / est_h) * 100, 1),
            "left":   round((tlx / est_w) * 100, 1),
            "width":  round(((brx - tlx) / est_w) * 100, 1),
            "height": round(((bry - tly) / est_h) * 100, 1),
        }


def _bbox_overlap(
    top: float, left: float, width: float, height: float,
    ocr_img: dict,
) -> float:
    """
    Compute overlap percentage between a structured Image bbox (pct 0-100)
    and a Mistral OCR image.  Returns 0-100 (IoU-ish score) or -1 if
    the OCR image has no coords.
    """
    pct = _ocr_img_to_pct_bbox(ocr_img)

    if top is None or left is None or width is None or height is None:
        # Structured image has no bbox → return 0 so it still gets the
        # first available OCR image (better than nothing).
        return 0.0

    # Rectangle A (structured)
    ax0, ay0 = left, top
    ax1, ay1 = left + width, top + height
    # Rectangle B (OCR)
    bx0, by0 = pct["left"], pct["top"]
    bx1, by1 = pct["left"] + pct["width"], pct["top"] + pct["height"]

    # Intersection
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0

    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(width * height, 1e-6)
    area_b = max(pct["width"] * pct["height"], 1e-6)
    union = area_a + area_b - inter

    return round((inter / union) * 100, 1) if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class MistralOCRPipeline:
    """
    Two-pass Mistral pipeline:
      1. Mistral OCR  → raw markdown per page
      2. Mistral Large → structured JSON (same schema as Gemini pipeline)
    """

    def __init__(self, config: Optional[MistralPipelineConfig] = None):
        self.config = config or MistralPipelineConfig()

        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError(
                "MISTRAL_API_KEY environment variable not set. "
                "Get your key at https://console.mistral.ai/"
            )
        self.client = Mistral(api_key=api_key)

        # Cost / token tracking
        self._ocr_pages = 0
        self._structuring_input_tokens = 0
        self._structuring_output_tokens = 0

    # ------------------------------------------------------------------
    # Pass 1 — Mistral OCR
    # ------------------------------------------------------------------

    def _upload_pdf(self, pdf_path: str) -> str:
        """Upload PDF to Mistral Files API. Returns file_id."""
        pdf_path = str(pathlib.Path(pdf_path).expanduser().resolve())
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Uploading PDF: {pdf_path} (attempt {attempt + 1})")
                uploaded = self.client.files.upload(
                    file={
                        "file_name": os.path.basename(pdf_path),
                        "content": open(pdf_path, "rb"),
                    },
                    purpose="ocr",
                )
                logger.info(f"Upload OK — file_id: {uploaded.id}")
                return uploaded.id
            except Exception as e:
                logger.warning(f"Upload attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"Failed to upload after {self.config.max_retries} attempts"
                    ) from e

    def _run_ocr(self, file_id: str) -> list[dict]:
        """
        Run Mistral OCR. Returns list of dicts:
            [{"page_index": int, "markdown": str, "images": [...] }, ...]
        """
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Running Mistral OCR (attempt {attempt + 1})…")
                ocr_response = self.client.ocr.process(
                    model=self.config.ocr_model,
                    document={"file_id": file_id},
                    include_image_base64=self.config.include_image_base64,
                )

                pages = []
                for page in ocr_response.pages:
                    pages.append({
                        "page_index": page.index,
                        "markdown": page.markdown,
                        # images list may contain base64 data
                        "images": [
                            {
                                "id": getattr(img, "id", None),
                                "top_left_x": getattr(img, "top_left_x", None),
                                "top_left_y": getattr(img, "top_left_y", None),
                                "bottom_right_x": getattr(img, "bottom_right_x", None),
                                "bottom_right_y": getattr(img, "bottom_right_y", None),
                                "image_base64": getattr(img, "image_base64", None),
                            }
                            for img in (page.images or [])
                        ],
                    })

                self._ocr_pages = len(pages)
                logger.info(f"OCR complete — {len(pages)} pages extracted")
                return pages

            except Exception as e:
                logger.warning(f"OCR attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"OCR failed after {self.config.max_retries} attempts"
                    ) from e

    # ------------------------------------------------------------------
    # Pass 2 — LLM structuring
    # ------------------------------------------------------------------

    def _extract_metadata(
        self, first_page_md: str, total_pages: int
    ) -> DocumentMetadata:
        """Ask LLM to produce DocumentMetadata from the first page."""
        schema_str = json.dumps(_get_metadata_schema(), indent=2)
        prompt = METADATA_PROMPT_TEMPLATE.format(
            schema=schema_str,
            total_pages=total_pages,
            first_page_text=first_page_md[:4000],  # cap to avoid huge prompts
        )

        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Extracting metadata (attempt {attempt + 1})…")
                resp = self.client.chat.complete(
                    model=self.config.structuring_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature,
                    max_tokens=2048,
                )
                raw = resp.choices[0].message.content.strip()
                # Strip markdown fences if the model wraps them
                raw = self._strip_json_fences(raw)

                self._track_tokens(resp)

                # Inject total_pages before validation (LLM often omits it)
                raw_dict = json.loads(raw)
                raw_dict["total_pages"] = total_pages
                metadata = DocumentMetadata.model_validate(raw_dict)
                logger.info(
                    f"Metadata: title={metadata.title!r}, "
                    f"lang={metadata.language}, pages={metadata.total_pages}"
                )
                return metadata

            except (ValidationError, Exception) as e:
                logger.warning(f"Metadata attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)
                else:
                    # Fallback metadata
                    logger.error("Metadata extraction failed — using fallback")
                    return DocumentMetadata(
                        total_pages=total_pages,
                        is_scanned=True,
                    )

    def _structure_pages(
        self,
        ocr_pages: list[dict],
        start_idx: int,
        end_idx: int,
    ) -> list[PageContent]:
        """
        Ask LLM to convert a chunk of OCR markdown pages into PageContent list.
        start_idx / end_idx are 0-based indices into ocr_pages.
        """
        chunk = ocr_pages[start_idx:end_idx]
        if not chunk:
            return []

        # Build combined OCR text with page markers
        parts = []
        for pg in chunk:
            page_num = pg["page_index"] + 1  # 1-based
            parts.append(f"=== PAGE {page_num} ===\n{pg['markdown']}")
        combined_text = "\n\n".join(parts)

        start_page = chunk[0]["page_index"] + 1
        end_page = chunk[-1]["page_index"] + 1

        schema_str = json.dumps(_get_chunk_schema(), indent=2)
        prompt = STRUCTURING_PROMPT_TEMPLATE.format(
            start_page=start_page,
            end_page=end_page,
            schema=schema_str,
            ocr_text=combined_text,
        )

        for attempt in range(self.config.max_retries):
            try:
                temp = self.config.temperature + (attempt * 0.1)
                logger.info(
                    f"Structuring pages {start_page}–{end_page} "
                    f"(attempt {attempt + 1}, temp={temp})"
                )
                resp = self.client.chat.complete(
                    model=self.config.structuring_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temp,
                    max_tokens=self.config.max_output_tokens,
                )
                raw = resp.choices[0].message.content.strip()
                raw = self._strip_json_fences(raw)
                self._track_tokens(resp)

                # Parse wrapper {"pages": [...]}
                wrapper = json.loads(raw)
                pages_data = wrapper.get("pages", wrapper) if isinstance(wrapper, dict) else wrapper

                # Validate each page individually for resilience
                validated: list[PageContent] = []
                for pd_raw in pages_data:
                    try:
                        page = PageContent.model_validate(pd_raw)
                        validated.append(page)
                    except ValidationError as ve:
                        logger.warning(
                            f"Page validation issue: {ve}. "
                            f"Attempting partial recovery…"
                        )
                        # Force-create with minimal data
                        page_num = pd_raw.get("page_number", start_page)
                        validated.append(PageContent(
                            page_number=page_num,
                            text_blocks=[TextBlock(
                                block_type="paragraph",
                                content=pd_raw.get("raw_text", "[extraction error]"),
                            )],
                        ))

                logger.info(
                    f"Structured {len(validated)} pages "
                    f"({start_page}–{end_page})"
                )
                return validated

            except Exception as e:
                logger.warning(
                    f"Structuring attempt {attempt + 1} failed: {e}"
                )
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    # Return placeholder pages for this chunk
                    logger.error(
                        f"All attempts failed for pages {start_page}–{end_page}"
                    )
                    placeholders = []
                    for pg in chunk:
                        placeholders.append(PageContent(
                            page_number=pg["page_index"] + 1,
                            text_blocks=[TextBlock(
                                block_type="paragraph",
                                content=pg["markdown"][:2000],
                            )],
                            raw_text=pg["markdown"],
                        ))
                    return placeholders

    # ------------------------------------------------------------------
    # Image extraction from Mistral OCR
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_ocr_images(
        all_pages: list[PageContent],
        ocr_pages: list[dict],
    ) -> int:
        """
        Populate image_data on structured Image objects using Mistral OCR's
        base64 images.  Two strategies:

        1. **Match by bbox overlap** — if the LLM created an Image entry
           with bbox coords, find the closest OCR image on the same page
           and attach its base64 data.
        2. **Inject unmatched** — any OCR image that was NOT matched to an
           existing Image entry gets added as a new Image on that page.

        Returns the number of images populated.
        """
        populated = 0

        for page in all_pages:
            pg_idx = page.page_number - 1
            if pg_idx < 0 or pg_idx >= len(ocr_pages):
                continue

            ocr_imgs = ocr_pages[pg_idx].get("images", [])
            if not ocr_imgs:
                continue

            # Track which OCR images have been consumed
            used_ocr = set()

            # --- Strategy 1: match existing Image entries by bbox ---
            for image in page.images:
                if image.image_data:  # already populated
                    continue
                best_idx = None
                best_overlap = -1.0

                for oi, ocr_img in enumerate(ocr_imgs):
                    if oi in used_ocr:
                        continue
                    if not ocr_img.get("image_base64"):
                        continue

                    # Compute simple overlap score between bbox rects
                    overlap = _bbox_overlap(
                        image.bbox_top, image.bbox_left,
                        image.bbox_width, image.bbox_height,
                        ocr_img,
                    )
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_idx = oi

                # Accept if any positive overlap (or nearest if bbox missing)
                if best_idx is not None and best_overlap >= 0:
                    image.image_data = ocr_imgs[best_idx]["image_base64"]
                    used_ocr.add(best_idx)
                    populated += 1
                    logger.info(
                        f"Matched OCR image → page {page.page_number} "
                        f"{image.image_type} (overlap={best_overlap:.1f}%)"
                    )

            # --- Strategy 2: inject leftover OCR images ---
            for oi, ocr_img in enumerate(ocr_imgs):
                if oi in used_ocr:
                    continue
                b64 = ocr_img.get("image_base64")
                if not b64:
                    continue

                # Convert Mistral's pixel coords to percentage bbox
                bbox = _ocr_img_to_pct_bbox(ocr_img)

                new_image = Image(
                    image_type="figure",
                    description=f"Image extracted by Mistral OCR (id={ocr_img.get('id', 'unknown')})",
                    bbox_top=bbox["top"],
                    bbox_left=bbox["left"],
                    bbox_width=bbox["width"],
                    bbox_height=bbox["height"],
                    image_data=b64,
                )
                page.images.append(new_image)
                populated += 1
                logger.info(
                    f"Injected new OCR image → page {page.page_number} "
                    f"(id={ocr_img.get('id', '?')})"
                )

        return populated

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def process(self, pdf_path: str) -> DocumentStructure:
        """
        Full pipeline: Upload → OCR → Structure → Validate.

        Returns a DocumentStructure identical to what the Gemini pipeline returns.
        """
        start_time = time.time()

        # 1) Upload
        file_id = self._upload_pdf(pdf_path)

        # 2) OCR (Pass 1)
        ocr_pages = self._run_ocr(file_id)
        total_pages = len(ocr_pages)

        # Save raw markdown if configured
        stem = pathlib.Path(pdf_path).stem
        output_dir = pathlib.Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.config.save_raw_markdown:
            raw_md_path = output_dir / f"{stem}_raw_ocr.md"
            with open(raw_md_path, "w", encoding="utf-8") as f:
                for pg in ocr_pages:
                    f.write(f"\n\n---\n## PAGE {pg['page_index'] + 1}\n\n")
                    f.write(pg["markdown"])
            logger.info(f"Raw OCR saved → {raw_md_path}")

        # 3) Extract metadata (Pass 2a)
        first_md = ocr_pages[0]["markdown"] if ocr_pages else ""
        metadata = self._extract_metadata(first_md, total_pages)

        # 4) Structure pages in chunks (Pass 2b)
        all_pages: list[PageContent] = []
        chunk_size = self.config.pages_per_chunk

        for chunk_start in range(0, total_pages, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total_pages)
            progress = min(100.0, (chunk_end / total_pages) * 100)
            logger.info(
                f"Structuring chunk "
                f"[{chunk_start + 1}–{chunk_end}] of {total_pages}  "
                f"({progress:.0f}%)"
            )
            pages = self._structure_pages(ocr_pages, chunk_start, chunk_end)
            all_pages.extend(pages)

        # Ensure correct page numbering and sort
        all_pages.sort(key=lambda p: p.page_number)

        # Inject raw_text from OCR into each page (for auditing / reprocessing)
        for page in all_pages:
            pg_idx = page.page_number - 1
            if 0 <= pg_idx < len(ocr_pages):
                page.raw_text = ocr_pages[pg_idx]["markdown"]

        # 5) Inject Mistral OCR images into structured pages
        if self.config.include_image_base64:
            img_count = self._inject_ocr_images(all_pages, ocr_pages)
            logger.info(f"Image injection complete — {img_count} images populated")

        elapsed = time.time() - start_time
        cost = self._calculate_cost()

        extraction_notes = (
            f"Mistral two-pass pipeline. "
            f"OCR model: {self.config.ocr_model}. "
            f"Structuring model: {self.config.structuring_model}. "
            f"Processing time: {elapsed:.1f}s. "
            f"Estimated cost: ${cost['total_cost_usd']:.4f}. "
            f"Pages: {total_pages}."
        )

        doc = DocumentStructure(
            metadata=metadata,
            pages=all_pages,
            extraction_notes=extraction_notes,
        )

        # 5) Save outputs
        if self.config.save_structured_json:
            json_path = output_dir / f"{stem}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(doc.model_dump_json(indent=2))
            logger.info(f"Structured JSON saved → {json_path}")

        if self.config.save_html:
            html_path = output_dir / f"{stem}.html"
            html_content = HTMLRenderer.render(doc)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"HTML saved → {html_path}")

        # Summary
        logger.info(
            f"\n{'='*60}\n"
            f"  ✅ Pipeline complete\n"
            f"  PDF:    {pdf_path}\n"
            f"  Pages:  {total_pages}\n"
            f"  Time:   {elapsed:.1f}s\n"
            f"  Cost:   ${cost['total_cost_usd']:.4f}\n"
            f"  Output: {output_dir}/\n"
            f"{'='*60}"
        )

        return doc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        """Remove ```json ... ``` wrappers if present."""
        text = text.strip()
        if text.startswith("```"):
            # Remove first line (```json or ```)
            lines = text.split("\n", 1)
            text = lines[1] if len(lines) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    def _track_tokens(self, response) -> None:
        """Track token usage from a chat response."""
        usage = getattr(response, "usage", None)
        if usage:
            self._structuring_input_tokens += getattr(usage, "prompt_tokens", 0)
            self._structuring_output_tokens += getattr(usage, "completion_tokens", 0)

    def _calculate_cost(self) -> dict:
        """Calculate estimated cost for the full pipeline."""
        ocr_cost = (self._ocr_pages / 1000) * MISTRAL_OCR_COST_PER_1K_PAGES
        input_cost = (self._structuring_input_tokens / 1_000_000) * MISTRAL_LARGE_INPUT_PER_1M
        output_cost = (self._structuring_output_tokens / 1_000_000) * MISTRAL_LARGE_OUTPUT_PER_1M
        total = ocr_cost + input_cost + output_cost

        return {
            "ocr_pages": self._ocr_pages,
            "ocr_cost_usd": round(ocr_cost, 6),
            "structuring_input_tokens": self._structuring_input_tokens,
            "structuring_output_tokens": self._structuring_output_tokens,
            "structuring_input_cost_usd": round(input_cost, 6),
            "structuring_output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(total, 6),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Mistral OCR two-pass pipeline (OCR → LLM structuring → HTML)",
    )
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument(
        "--output-dir", "-o",
        default="outputs",
        help="Output directory (default: outputs/)",
    )
    parser.add_argument(
        "--pages-per-chunk", "-c",
        type=int,
        default=5,
        help="Pages per structuring LLM call (default: 5)",
    )
    parser.add_argument(
        "--structuring-model",
        default=STRUCTURING_MODEL,
        help=f"Structuring LLM model (default: {STRUCTURING_MODEL})",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip base64 image extraction from OCR",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip HTML rendering (only save JSON + markdown)",
    )
    parser.add_argument(
        "--temperature", "-t",
        type=float,
        default=0.0,
        help="LLM temperature for structuring (default: 0.0)",
    )

    args = parser.parse_args()

    config = MistralPipelineConfig(
        output_dir=args.output_dir,
        pages_per_chunk=args.pages_per_chunk,
        structuring_model=args.structuring_model,
        include_image_base64=not args.no_images,
        save_html=not args.no_html,
        temperature=args.temperature,
    )

    pipeline = MistralOCRPipeline(config)
    doc = pipeline.process(args.pdf)

    # Print quick summary to stdout
    print(f"\n✅ Done — {doc.metadata.total_pages} pages processed")
    print(f"   Title:    {doc.metadata.title or '(untitled)'}")
    print(f"   Language: {doc.metadata.language or '(unknown)'}")
    print(f"   Output:   {args.output_dir}/")


if __name__ == "__main__":
    main()
