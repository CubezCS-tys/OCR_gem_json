#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
    python mistral_ocr_pipeline.py <pdf_path> --parallel --workers 8 --pages-per-chunk 2
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from mistralai import Mistral
from pydantic import ValidationError
from google import genai
from google.genai import types

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
from image_utils import normalise_data_uri

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
    structuring_provider: str = "mistral"  # "mistral" or "gemini"
    include_image_base64: bool = True
    pages_per_chunk: int = 5           # Pages sent to LLM per structuring call
    parallel: bool = False             # Enable parallel chunk processing
    workers: int = 4                   # Number of parallel workers
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
You are an expert document structuring engine focused on semantic understanding and natural flow.

Transform the following OCR text (pages {start_page}–{end_page}) into JSON that \
STRICTLY follows this schema:

{schema}

CRITICAL JSON FORMATTING RULES:
- Output ONLY valid RFC 8259 JSON — no explanations, no markdown fences, no extra keys
- Use DOUBLE QUOTES for all property names and string values (never single quotes)
- NO trailing commas after the last property in objects or arrays
- Escape all special characters in strings: \" \\ \n \r \t
- All property names MUST be from the schema above — no custom fields

CRITICAL EXTRACTION RULES:
- Preserve the EXACT reading order from the OCR text
- Focus on semantic structure and content flow, NOT pixel-perfect positioning

PAGE-LEVEL EXTRACTION:
- For each page, populate page_number, text_blocks, tables, images
- Extract separate header, footer, and page_number_text if present
- CRITICAL: If you extract header/footer, DO NOT include that same text in text_blocks
- Headers/footers are typically page numbers, titles, citations at top/bottom of page
- Set page_number_position: "header-left|center|right" or "footer-left|center|right"
- Set page dimensions: width_pts, height_pts (in PDF points if detectable)
- Set page_direction="rtl" for Arabic/Hebrew pages, "ltr" otherwise
- Set background_color if the page has a colored background

MULTI-COLUMN LAYOUT DETECTION (CRITICAL):
- ALWAYS check if the page has multiple columns (2-column, 3-column layouts)
- Look for text flowing in parallel vertical sections
- Common in: academic papers, newspapers, magazines, technical reports
- If multi-column detected:
    • Set has_multi_column=true
    • Set column_count (2, 3, or more)
    • Set column_gap (gap width in points, typically 20-40)
    • CRITICAL: Ensure ALL pages have SAME column_count if they share the same layout style
    • Column detection must be CONSISTENT - don't flip between 2 and 3 columns on similar pages
- For ALL text_blocks, tables, and images: set column_number (1, 2, 3, etc.)
- Reading order MUST follow column flow (top-to-bottom within each column, left-to-right across columns for LTR)

READING ORDER & FLOW (CRITICAL):
- Set reading_order field for EVERY text_block, table, and image
- reading_order is a sequence number (1, 2, 3...) indicating document flow
- For multi-column: elements in column 1 should have lower reading_order than column 2
- Within same column: top elements have lower reading_order than bottom elements
- This controls how content flows in the rendered HTML

TEXT BLOCKS - SEMANTIC CLASSIFICATION:
- Classify each element as:
    • "heading" (with level 1–6)
    • "paragraph"
    • "list_item" (use list_level for nesting depth: 1=top, 2=nested, etc.)
    • "caption"
    • "footnote"
    • "quote"
    • "code"
    • "equation" (use LaTeX in content, set is_display_math, extract equation_number if present)
    • "hyperlink" (for clickable links - extract url and set link_type: "url", "email", or "internal")
    • "horizontal_rule" (for dividing lines/separators between sections)

TEXT BLOCKS - TYPOGRAPHY & STYLING (for fidelity):
- font_size: Extract font size in points if detectable from formatting
- font_family: Extract font name if discernible (e.g., "Arial", "Times New Roman", "Amiri")
- font_weight: Set weight (400=normal, 700=bold, or specific values 100-900)
- line_height: Line spacing multiplier or points
- letter_spacing: Character spacing in ems if abnormal
- text_color: Text color as hex (e.g., "#000000" for black)
- background_color: Background color as hex if highlighted
- text_direction: "rtl", "ltr", or "auto" for mixed content
- text_align: "left", "center", "right", or "justify" based on visual layout
- alignment: "left", "center", "right" for alignment within flow

TEXT BLOCKS - SPACING & INDENTATION (relative units):
- indent_left, indent_right: Left/right margins in ems
- indent_first_line: First line indent in ems
- spacing_before, spacing_after: Vertical spacing in ems

TEXT BLOCKS - HYPERLINKS:
- For hyperlink block_type: MUST set url field with the target URL
- Set link_type: "url" (http/https), "email" (mailto), or "internal" (bookmark/anchor)
- Content field contains the visible link text

TEXT BLOCKS - RICH TEXT (CHARACTER-LEVEL STYLING):
- spans: Array of TextSpan objects for mixed inline formatting within a block
- Each span has: text, bold, italic, underline, strikethrough, superscript, subscript
- Each span can have: font_size, font_family, text_color, background_color

TABLES - ENHANCED FIDELITY:
- headers: Array of TableCell objects (NOT plain strings)
- rows: Array of arrays of TableCell objects
- Each TableCell has: content, row_span, col_span, is_header
- TableCell styling: width_percent, text_align, vertical_align, background_color, text_color, border_width, border_color
- Table-level: border_style, border_color, background_color
- Set reading_order and column_number for table positioning

IMAGES/FIGURES - FLOW-BASED PROPERTIES:
- image_type: "chart", "graph", "diagram", "figure", "photo", "logo", "illustration", "other"
- description: Detailed alt text
- caption: Figure caption if present
- alignment: "left", "center", "right", or "full-width" within text flow
- Set reading_order and column_number for image positioning
- width_pixels, height_pixels: Actual pixel dimensions if detectable
- CRITICAL: Avoid duplicate images - same description usually means duplicate

SPECIAL CONTENT RULES:
- PRESERVE numeral systems exactly (Arabic-Indic ٠١٢٣٤٥٦٧٨٩ vs Western 0123456789)
- EQUATIONS: Use LaTeX syntax, set is_display_math, extract equation_number
- HYPERLINKS: Extract URLs, mailto links, internal references - use hyperlink block_type
- HORIZONTAL RULES: Visual dividers between sections should be horizontal_rule block_type (content can be empty)
- Convert any table markdown into structured TableCell objects — do NOT use HTML or plain strings
- If a field is unknown or not detectable, omit it or use null
- Ensure all JSON strings are properly escaped (quotes, backslashes)
- Ensure hex colors are valid format: #RGB or #RRGGBB

FIDELITY PRIORITY:
Maximize extraction of semantic structure, reading order, and styling details for high-quality HTML output.
Focus on natural document flow rather than absolute positioning.

OCR TEXT:
\"\"\"
{ocr_text}
\"\"\"
"""


# ---------------------------------------------------------------------------
# Image helpers (DEPRECATED - no longer using bbox coordinates)
# ---------------------------------------------------------------------------

def _ocr_img_to_pct_bbox(ocr_img: dict) -> dict:
    """
    DEPRECATED: Convert Mistral OCR pixel coordinates to percentage-based bbox.
    
    This function is no longer used since we removed bbox coordinates from the
    Image schema (flow-based positioning for OCR'd PDFs).

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
    DEPRECATED: Compute overlap percentage between structured Image bbox and OCR image.
    
    This function is no longer used since we removed bbox coordinates from the
    Image schema (flow-based positioning for OCR'd PDFs).
    """
    pct = _ocr_img_to_pct_bbox(ocr_img)

    if top is None or left is None or width is None or height is None:
        # Structured image has no bbox → return -1 to indicate "unmatchable"
        # Caller should handle this case separately (e.g., match by document order)
        return -1.0

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

        # Initialize Gemini client if using Gemini for structuring
        self.gemini_client = None
        if self.config.structuring_provider == "gemini":
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if not gemini_key:
                raise ValueError(
                    "GEMINI_API_KEY environment variable not set. "
                    "Get your key at https://aistudio.google.com/apikey"
                )
            self.gemini_client = genai.Client(api_key=gemini_key)
            logger.info(f"Using Gemini {self.config.structuring_model} for structuring")

        # Store PDF path for Gemini vision mode
        self.current_pdf_path = None

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
                logger.info(
                    f"Running Mistral OCR (attempt {attempt + 1})… "
                    f"[include_image_base64={self.config.include_image_base64}]"
                )
                ocr_response = self.client.ocr.process(
                    model=self.config.ocr_model,
                    document={"file_id": file_id},
                    include_image_base64=self.config.include_image_base64,
                )

                pages = []
                total_images_found = 0
                for page in ocr_response.pages:
                    page_images = []
                    if hasattr(page, 'images') and page.images:
                        for img in page.images:
                            img_data = {
                                "id": getattr(img, "id", None),
                                "top_left_x": getattr(img, "top_left_x", None),
                                "top_left_y": getattr(img, "top_left_y", None),
                                "bottom_right_x": getattr(img, "bottom_right_x", None),
                                "bottom_right_y": getattr(img, "bottom_right_y", None),
                                "image_base64": getattr(img, "image_base64", None),
                            }
                            page_images.append(img_data)
                            
                            # Debug logging
                            has_base64 = bool(img_data["image_base64"])
                            total_images_found += 1
                            if not has_base64:
                                logger.warning(
                                    f"⚠️  Page {page.index + 1} image '{img_data['id']}' has NO base64 data"
                                )
                            else:
                                # Log prefix sample to detect format issues
                                b64 = img_data["image_base64"]
                                prefix_sample = b64[:60] if b64 else ""
                                logger.info(f"Image base64 prefix sample: {prefix_sample}")
                    
                    pages.append({
                        "page_index": page.index,
                        "markdown": page.markdown,
                        "images": page_images,
                    })
                
                if total_images_found > 0:
                    logger.info(f"📸 Found {total_images_found} images across all pages")

                self._ocr_pages = len(pages)
                logger.info(f"OCR complete — {len(pages)} pages extracted")
                
                # Validate OCR output quality
                empty_pages = []
                for pg in pages:
                    if not pg["markdown"] or len(pg["markdown"].strip()) < 10:
                        empty_pages.append(pg["page_index"] + 1)
                        logger.warning(
                            f"⚠️  Page {pg['page_index'] + 1} has suspiciously short OCR output "
                            f"({len(pg.get('markdown', ''))} chars)"
                        )
                
                if empty_pages:
                    logger.warning(
                        f"⚠️  QUALITY WARNING: {len(empty_pages)} page(s) with minimal content: {empty_pages}"
                    )
                
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

    def _call_structuring_llm(self, prompt: str, max_tokens: int = 2048, page_range: tuple = None) -> tuple[str, dict]:
        """
        Call the configured structuring LLM (Mistral or Gemini).
        For Gemini: includes the PDF file for visual context.
        Returns: (response_text, usage_dict)
        """
        if self.config.structuring_provider == "gemini":
            # Gemini can see the PDF + markdown for richer context
            contents = []
            
            # Add PDF file if available
            if self.current_pdf_path:
                try:
                    with open(self.current_pdf_path, 'rb') as f:
                        pdf_data = f.read()
                    contents.append(types.Part.from_bytes(data=pdf_data, mime_type="application/pdf"))
                    logger.debug(f"Added PDF file to Gemini context ({len(pdf_data)} bytes)")
                except Exception as e:
                    logger.warning(f"Could not read PDF for Gemini: {e}")
            
            # Add the text prompt
            contents.append(prompt)
            
            response = self.gemini_client.models.generate_content(
                model=self.config.structuring_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=self.config.temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                )
            )
            content = response.text
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
            }
            return content, usage
        else:
            # Mistral with JSON schema enforcement
            response = self.client.chat.complete(
                model=self.config.structuring_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_object"
                }
            )
            content = response.choices[0].message.content
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
            return content, usage

    def _extract_metadata(
        self, first_page_md: str, total_pages: int
    ) -> DocumentMetadata:
        """Ask LLM to produce DocumentMetadata from the first page. Always uses Gemini for reliability."""
        schema_str = json.dumps(_get_metadata_schema(), indent=2)
        # Use full first page content - no truncation for fidelity
        prompt = METADATA_PROMPT_TEMPLATE.format(
            schema=schema_str,
            total_pages=total_pages,
            first_page_text=first_page_md,
        )

        # Ensure Gemini client is initialized
        if not self.gemini_client:
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if not gemini_key:
                logger.warning("GEMINI_API_KEY not set, falling back to Mistral for metadata")
                use_gemini = False
            else:
                self.gemini_client = genai.Client(api_key=gemini_key)
                use_gemini = True
        else:
            use_gemini = True

        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Extracting metadata with {'Gemini' if use_gemini else 'Mistral'} (attempt {attempt + 1})…")
                
                if use_gemini:
                    # Use Gemini for metadata extraction (more reliable for Arabic)
                    gemini_model = os.environ.get("MODEL_NAME", "gemini-2.0-flash-exp")
                    response = self.gemini_client.models.generate_content(
                        model=gemini_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            max_output_tokens=2048,
                            response_mime_type="application/json",
                        )
                    )
                    raw = response.text
                    usage = {
                        "prompt_tokens": response.usage_metadata.prompt_token_count,
                        "completion_tokens": response.usage_metadata.candidates_token_count,
                    }
                else:
                    # Fallback to Mistral with JSON mode
                    response = self.client.chat.complete(
                        model=self.config.structuring_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        max_tokens=2048,
                        response_format={
                            "type": "json_object"
                        }
                    )
                    raw = response.choices[0].message.content
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                    }
                
                # Strip markdown fences if the model wraps them
                raw = self._strip_json_fences(raw)

                self._structuring_input_tokens += usage["prompt_tokens"]
                self._structuring_output_tokens += usage["completion_tokens"]

                # Log the raw response for debugging
                logger.debug(f"Raw metadata response: {raw[:500]}...")

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
                logger.debug(f"Failed raw response: {raw[:500] if 'raw' in locals() else 'N/A'}")
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
                # Keep temperature at 0.0 for maximum fidelity - never increase on retry
                # Higher temp = more hallucinations, less faithful extraction
                logger.info(
                    f"Structuring pages {start_page}–{end_page} "
                    f"(attempt {attempt + 1})"
                )
                raw, usage = self._call_structuring_llm(
                    prompt, 
                    max_tokens=self.config.max_output_tokens,
                    page_range=(start_page, end_page)
                )
                raw = self._strip_json_fences(raw)
                
                self._structuring_input_tokens += usage["prompt_tokens"]
                self._structuring_output_tokens += usage["completion_tokens"]

                # Parse wrapper {"pages": [...]} with validation
                try:
                    wrapper = json.loads(raw)
                except json.JSONDecodeError as je:
                    # Show context around the error position for debugging
                    error_pos = je.pos
                    context_start = max(0, error_pos - 100)
                    context_end = min(len(raw), error_pos + 100)
                    context = raw[context_start:context_end]
                    
                    # Mark the error position
                    marker_pos = error_pos - context_start
                    context_with_marker = (
                        context[:marker_pos] + 
                        " <<<ERROR HERE>>> " + 
                        context[marker_pos:]
                    )
                    
                    logger.error(
                        f"JSON parse error at line {je.lineno}, col {je.colno}: {je.msg}\n"
                        f"Error position (char {error_pos}):\n"
                        f"{context_with_marker}\n"
                        f"Full output length: {len(raw)} chars"
                    )
                    
                    # On last retry, save the bad JSON for debugging
                    if attempt == self.config.max_retries - 1:
                        debug_file = f"debug_bad_json_pages_{start_page}-{end_page}.json"
                        with open(debug_file, 'w', encoding='utf-8') as f:
                            f.write(raw)
                        logger.error(f"Saved malformed JSON to {debug_file} for debugging")
                    
                    raise
                
                pages_data = wrapper.get("pages", wrapper) if isinstance(wrapper, dict) else wrapper
                
                if not pages_data:
                    logger.error(f"No pages data in response. Wrapper keys: {list(wrapper.keys()) if isinstance(wrapper, dict) else 'not a dict'}")
                    raise ValueError("Empty pages data in LLM response")

                # Validate each page individually for resilience
                validated: list[PageContent] = []
                for pd_raw in pages_data:
                    try:
                        page = PageContent.model_validate(pd_raw)
                        validated.append(page)
                    except ValidationError as ve:
                        page_num = pd_raw.get("page_number", start_page)
                        logger.error(
                            f"⚠️  QUALITY DEGRADED - Page {page_num} validation failed\n"
                            f"Validation errors: {ve.error_count()} issues\n"
                            f"First error: {ve.errors()[0] if ve.errors() else 'unknown'}\n"
                            f"Falling back to raw text extraction"
                        )
                        
                        # Attempt to recover text content from various possible fields
                        fallback_content = None
                        for field in ["raw_text", "content", "text"]:
                            if field in pd_raw and pd_raw[field]:
                                fallback_content = pd_raw[field]
                                break
                        
                        if not fallback_content:
                            # Try to extract from text_blocks if partially formed
                            if "text_blocks" in pd_raw and isinstance(pd_raw["text_blocks"], list):
                                fallback_content = "\n\n".join(
                                    str(block.get("content", "")) 
                                    for block in pd_raw["text_blocks"]
                                    if isinstance(block, dict)
                                )
                        
                        validated.append(PageContent(
                            page_number=page_num,
                            text_blocks=[TextBlock(
                                block_type="paragraph",
                                content=fallback_content or "[EXTRACTION ERROR - No recoverable content]",
                            )],
                            raw_text=fallback_content,
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
                    # Return full raw content pages for this chunk - NO TRUNCATION
                    logger.error(
                        f"❌ QUALITY SEVERELY DEGRADED - All structuring attempts failed for pages {start_page}–{end_page}\n"
                        f"Returning raw OCR markdown without structure extraction"
                    )
                    placeholders = []
                    for pg in chunk:
                        page_num = pg["page_index"] + 1
                        full_markdown = pg["markdown"]
                        placeholders.append(PageContent(
                            page_number=page_num,
                            text_blocks=[TextBlock(
                                block_type="paragraph",
                                content=full_markdown,  # Full content - no truncation
                            )],
                            raw_text=full_markdown,
                        ))
                    return placeholders

    # ------------------------------------------------------------------
    # Image extraction from Mistral OCR
    # ------------------------------------------------------------------

    def _inject_ocr_images(
        self,
        all_pages: list[PageContent],
        ocr_pages: list[dict],
    ) -> int:
        """
        Populate image_data on structured Image objects using Mistral OCR's
        base64 images.  Two strategies:

        1. **Match by reading order** — structured Image entries are matched
           to OCR images sequentially based on reading_order or document order.
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

            # --- Strategy 1: match existing Image entries by document order ---
            # Since we removed bbox coordinates (for OCR'd PDFs), we match by sequence
            structured_images = [img for img in page.images if not img.image_data]
            available_ocr = [
                (idx, ocr_img) for idx, ocr_img in enumerate(ocr_imgs)
                if ocr_img.get("image_base64")
            ]
            
            # Sort structured images by reading_order if available
            structured_images.sort(key=lambda img: getattr(img, 'reading_order', 999))
            
            # Match sequentially
            for image, (oi, ocr_img) in zip(structured_images, available_ocr):
                image.image_data = normalise_data_uri(ocr_img["image_base64"])
                used_ocr.add(oi)
                populated += 1
                logger.info(
                    f"Matched OCR image → page {page.page_number} "
                    f"{image.image_type} (sequential match by reading order)"
                )

            # --- Strategy 2: inject leftover OCR images ---
            for oi, ocr_img in enumerate(ocr_imgs):
                if oi in used_ocr:
                    continue
                b64 = ocr_img.get("image_base64")
                if not b64:
                    continue

                # Create image without bbox (flow-based positioning)
                new_image = Image(
                    image_type="figure",
                    description=f"Image extracted by Mistral OCR (id={ocr_img.get('id', 'unknown')})",
                    alignment="center",
                    image_data=normalise_data_uri(b64),
                )
                page.images.append(new_image)
                populated += 1
                logger.info(
                    f"Injected new OCR image → page {page.page_number} "
                    f"(id={ocr_img.get('id', '?')})"
                )

        return populated

    def _structure_pages_parallel(
        self, ocr_pages: list[dict], total_pages: int, chunk_size: int
    ) -> list[PageContent]:
        """
        Structure pages in parallel using ThreadPoolExecutor.
        
        Returns a list of PageContent objects in page order.
        """
        # Build list of chunk ranges
        chunks = []
        for chunk_start in range(0, total_pages, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total_pages)
            chunks.append((chunk_start, chunk_end))
        
        all_pages: list[PageContent] = []
        
        # Process chunks in parallel
        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            # Submit all tasks
            future_to_chunk = {
                executor.submit(self._structure_pages, ocr_pages, start, end): (start, end)
                for start, end in chunks
            }
            
            # Collect results as they complete
            completed = 0
            for future in as_completed(future_to_chunk):
                chunk_start, chunk_end = future_to_chunk[future]
                try:
                    pages = future.result()
                    all_pages.extend(pages)
                    completed += 1
                    progress = (completed / len(chunks)) * 100
                    logger.info(
                        f"✓ Chunk [{chunk_start + 1}–{chunk_end}] complete "
                        f"({completed}/{len(chunks)}, {progress:.0f}%)"
                    )
                except Exception as e:
                    logger.error(f"✗ Chunk [{chunk_start + 1}–{chunk_end}] failed: {e}")
                    raise
        
        return all_pages

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def process(self, pdf_path: str) -> DocumentStructure:
        """
        Full pipeline: Upload → OCR → Structure → Validate.

        Returns a DocumentStructure identical to what the Gemini pipeline returns.
        """
        start_time = time.time()
        
        # Store PDF path for Gemini vision mode
        self.current_pdf_path = str(pathlib.Path(pdf_path).expanduser().resolve())

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

        if self.config.parallel:
            # Parallel processing with workers
            logger.info(f"🚀 Using {self.config.workers} parallel workers for structuring")
            all_pages = self._structure_pages_parallel(ocr_pages, total_pages, chunk_size)
        else:
            # Sequential processing
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
        """Remove ```json ... ``` wrappers and fix common JSON errors."""
        import re
        
        text = text.strip()
        
        # Remove markdown code fences
        if text.startswith("```"):
            lines = text.split("\n", 1)
            text = lines[1] if len(lines) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
        
        text = text.strip()
        
        # Fix common JSON errors that LLMs produce:
        
        # 1. Remove trailing commas before closing braces/brackets
        # Match: , followed by optional whitespace and then } or ]
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        # 2. Replace single quotes with double quotes (but be careful with apostrophes in text)
        # This is risky but necessary if the LLM uses single quotes for property names
        # Only do this for property names (single quote at start of line or after {, [, or comma)
        text = re.sub(r"([{\[,]\s*)'([a-zA-Z_][a-zA-Z0-9_]*)'(\s*:)", r'\1"\2"\3', text)
        
        return text

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
        "--structuring-provider",
        choices=["mistral", "gemini"],
        default="mistral",
        help="LLM provider for structuring (default: mistral). Use 'gemini' for Gemini Flash with vision",
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
    parser.add_argument(
        "--parallel", "-p",
        action="store_true",
        help="Enable parallel processing of chunks",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )

    args = parser.parse_args()

    # Auto-set model if using Gemini
    if args.structuring_provider == "gemini" and args.structuring_model == STRUCTURING_MODEL:
        args.structuring_model = os.environ.get("MODEL_NAME", "gemini-2.0-flash-exp")

    config = MistralPipelineConfig(
        output_dir=args.output_dir,
        pages_per_chunk=args.pages_per_chunk,
        structuring_model=args.structuring_model,
        structuring_provider=args.structuring_provider,
        include_image_base64=not args.no_images,
        save_html=not args.no_html,
        temperature=args.temperature,
        parallel=args.parallel,
        workers=args.workers,
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
