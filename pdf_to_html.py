#!/usr/bin/env python3
"""
Production-grade PDF to HTML converter using Google Gemini API.

Features:
- Structured output with Pydantic schema validation
- Page-by-page extraction with detailed metadata
- Robust error handling and retry logic
- Configurable processing options
- Semantic structure preservation (headings, tables, lists, etc.)

Based on Google's document processing and structured output best practices:
- https://ai.google.dev/gemini-api/docs/document-processing
- https://ai.google.dev/gemini-api/docs/structured-output
"""

import pathlib
import os
import json
import logging
import time
import base64
import io
import re
from typing import Optional, Literal, Union, List, Annotated
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logging.warning("PyMuPDF not installed. Image extraction disabled. Install with: pip install PyMuPDF")

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

import dotenv

dotenv.load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

MODEL = "gemini-3-flash-preview"  # Supports structured outputs

# Production-grade constants for reproducibility
EXTRACTION_TEMPERATURE = 0.1  # Low temperature for deterministic, accurate transcription
MAX_CONCURRENT_CHUNKS = 5  # Limit parallel API requests to avoid rate limiting
METADATA_TEMPERATURE = 0.1  # Low temperature for metadata extraction

class MediaResolution(str, Enum):
    """Media resolution options for PDF processing."""
    LOW = "low"
    MEDIUM = "medium"  # Recommended for most PDFs
    HIGH = "high"


@dataclass
class ProcessingConfig:
    """Configuration for PDF processing."""
    model: str = MODEL
    media_resolution: MediaResolution = MediaResolution.MEDIUM
    max_retries: int = 3
    retry_delay: float = 2.0
    include_metadata: bool = True
    extract_tables: bool = True
    preserve_reading_order: bool = True
    output_format: Literal["html", "json", "both", "gemini_html"] = "html"
    max_output_tokens: int = 65536  # Maximum output tokens (default ~65k for long docs)
    pages_per_chunk: int = 10  # Pages to process per API call (for chunked processing)
    use_chunked_processing: bool = True  # Enable chunked processing for large docs
    extract_images: bool = True  # Extract charts/graphs/figures as actual images
    image_dpi: int = 150  # DPI for rendering pages when extracting images
    request_timeout: int = 300  # Timeout for API requests in seconds (5 minutes)
    experimental_gemini_html: bool = False  # Also request HTML directly from Gemini for comparison
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.max_retries < 0 or self.max_retries > 10:
            raise ValueError(f"max_retries must be between 0 and 10, got {self.max_retries}")
        
        if self.retry_delay < 0 or self.retry_delay > 60:
            raise ValueError(f"retry_delay must be between 0 and 60 seconds, got {self.retry_delay}")
        
        if self.max_output_tokens < 1024 or self.max_output_tokens > 1000000:
            raise ValueError(f"max_output_tokens must be between 1024 and 1000000, got {self.max_output_tokens}")
        
        if self.pages_per_chunk < 1 or self.pages_per_chunk > 100:
            raise ValueError(f"pages_per_chunk must be between 1 and 100, got {self.pages_per_chunk}")
        
        if self.image_dpi < 50 or self.image_dpi > 600:
            raise ValueError(f"image_dpi must be between 50 and 600, got {self.image_dpi}")
        
        if self.request_timeout < 10 or self.request_timeout > 3600:
            raise ValueError(f"request_timeout must be between 10 and 3600 seconds, got {self.request_timeout}")


# =============================================================================
# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUT - POLYMORPHIC APPROACH
# =============================================================================

# --- Sub-components ---

class Span(BaseModel):
    """Inline formatting span within a text block."""
    start: int = Field(description="Start character index (0-based)")
    end: int = Field(description="End character index (exclusive)")
    style: Literal["bold", "italic", "underline", "code", "link", "superscript", "subscript"] = Field(
        description="Style type"
    )
    url: Optional[str] = Field(default=None, description="URL for link spans")


class ColumnLayout(BaseModel):
    """Detailed column layout information for multi-column pages."""
    column_count: int = Field(ge=1, le=5, description="Number of columns (1-5)")
    column_boundaries: list[float] = Field(
        description="X-coordinates (%) of column dividers. For 2 columns: [50.0], for 3: [33.3, 66.7]"
    )
    column_gaps: list[float] = Field(
        default_factory=list,
        description="Gap widths (%) between columns. Length = column_count - 1"
    )
    reading_order: Literal["ltr", "rtl", "top-to-bottom", "zigzag"] = Field(
        default="ltr",
        description="Reading order: ltr (left-to-right), rtl (right-to-left), top-to-bottom, zigzag"
    )


class TableCell(BaseModel):
    """Represents a cell in a table."""
    content: str = Field(description="Text content of the cell")
    row_span: int = Field(default=1, description="Number of rows this cell spans (1 for standard)")
    col_span: int = Field(default=1, description="Number of columns this cell spans (1 for standard)")
    is_header: bool = Field(default=False, description="Whether this is a header cell")
    # Optional styling metadata
    alignment: Optional[Literal["left", "center", "right", "justify"]] = Field(default=None, description="Horizontal alignment")
    vertical_alignment: Optional[Literal["top", "middle", "bottom"]] = Field(default=None, description="Vertical alignment")
    background_color: Optional[str] = Field(default=None, description="Background color as hex (#RRGGBB)")
    text_color: Optional[str] = Field(default=None, description="Text color as hex (#RRGGBB)")
    font_weight: Optional[Literal["normal", "bold", "light"]] = Field(default=None, description="Font weight")


class ListItem(BaseModel):
    """An item in a list, which can contain content AND a nested list."""
    content: str = Field(description="Text content of the list item")
    # RECURSION: A list item can contain another list
    sub_list: Optional["ListBlock"] = Field(default=None, description="Nested sub-list if present")


# --- Main Block Types (Polymorphic) ---

class HeadingBlock(BaseModel):
    """A heading block (H1-H6)."""
    type: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=6, description="Heading level (1-6 for HTML H1-H6)")
    content: str = Field(description="The heading text")
    id: Optional[str] = Field(default=None, description="Slug for anchor links (auto-generated if needed)")
    text_direction: Literal["ltr", "rtl", "auto"] = Field(default="auto", description="Text direction")
    # Optional styling metadata
    font_size_pt: Optional[float] = Field(default=None, description="Font size in points")
    font_weight: Optional[Literal["normal", "bold", "light", "black"]] = Field(default=None, description="Font weight")
    font_family: Optional[str] = Field(default=None, description="Font family name")
    text_color: Optional[str] = Field(default=None, description="Text color as hex (#RRGGBB)")
    background_color: Optional[str] = Field(default=None, description="Background color as hex (#RRGGBB)")
    alignment: Optional[Literal["left", "center", "right", "justify"]] = Field(default=None, description="Text alignment")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class ParagraphBlock(BaseModel):
    """A paragraph of text."""
    type: Literal["paragraph"] = "paragraph"
    content: str = Field(description="The paragraph text")
    spans: list[Span] = Field(default_factory=list, description="Inline formatting spans (bold, italic, links, etc.)")
    text_direction: Literal["ltr", "rtl", "auto"] = Field(default="auto", description="Text direction")
    # Optional styling metadata
    font_size_pt: Optional[float] = Field(default=None, description="Font size in points")
    font_weight: Optional[Literal["normal", "bold", "light", "black"]] = Field(default=None, description="Font weight")
    font_family: Optional[str] = Field(default=None, description="Font family name")
    text_color: Optional[str] = Field(default=None, description="Text color as hex (#RRGGBB)")
    background_color: Optional[str] = Field(default=None, description="Background color as hex (#RRGGBB)")
    alignment: Optional[Literal["left", "center", "right", "justify"]] = Field(default=None, description="Text alignment")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class ListBlock(BaseModel):
    """A list (ordered or unordered) with support for nesting."""
    type: Literal["list"] = "list"
    style: Literal["unordered", "ordered"] = Field(description="List style: unordered (bullets) or ordered (numbers)")
    items: list[ListItem] = Field(description="List items, each can contain nested sub-lists")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class TableBlock(BaseModel):
    """A table with support for merged cells (rowspan/colspan)."""
    type: Literal["table"] = "table"
    caption: Optional[str] = Field(default=None, description="Table caption if present")
    headers: list[str] = Field(default_factory=list, description="Column headers")
    rows: list[list[TableCell]] = Field(description="Table rows with TableCell objects supporting rowspan/colspan")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class EquationBlock(BaseModel):
    """A mathematical equation in LaTeX format."""
    type: Literal["equation"] = "equation"
    latex: str = Field(description="LaTeX representation of the equation")
    is_display: bool = Field(default=True, description="True for display mode (\\[...\\]), False for inline (\\(...\\))")
    number: Optional[str] = Field(default=None, description="Equation number label if present (e.g., '(1)', '(2.3)')")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class ImageBlock(BaseModel):
    """A visual element (chart, graph, diagram, figure, photo)."""
    type: Literal["image"] = "image"
    image_type: Literal["chart", "graph", "diagram", "figure", "photo", "logo", "illustration", "other"] = Field(
        description="Type of visual element"
    )
    description: str = Field(description="Description or alt text for the image")
    caption: Optional[str] = Field(default=None, description="Image caption if present")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")
    # Runtime field for extracted image data (not from Gemini)
    image_data: Optional[str] = Field(default=None, description="Base64 encoded image data (populated at runtime)")


class CodeBlock(BaseModel):
    """A code block."""
    type: Literal["code"] = "code"
    content: str = Field(description="The code content")
    language: Optional[str] = Field(default=None, description="Programming language (e.g., 'python', 'javascript')")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class QuoteBlock(BaseModel):
    """A block quote."""
    type: Literal["quote"] = "quote"
    content: str = Field(description="The quoted text")
    attribution: Optional[str] = Field(default=None, description="Quote attribution/source if present")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


class FootnoteBlock(BaseModel):
    """A footnote."""
    type: Literal["footnote"] = "footnote"
    content: str = Field(description="The footnote text")
    reference_number: Optional[str] = Field(default=None, description="Footnote number/marker (e.g., '1', 'a', '*')")
    # REQUIRED bounding box
    bbox_top: float = Field(description="REQUIRED: Top edge as percentage from top of page (0-100)")
    bbox_left: float = Field(description="REQUIRED: Left edge as percentage from left of page (0-100)")
    bbox_width: float = Field(description="REQUIRED: Width as percentage of page width (0-100)")
    bbox_height: float = Field(description="REQUIRED: Height as percentage of page height (0-100)")


# --- The Union Type ---
# This forces the model to pick exactly ONE of these types per block
# Using discriminated union with 'type' field for proper Pydantic validation
ContentBlock = Annotated[
    Union[
        HeadingBlock,
        ParagraphBlock,
        ListBlock,
        TableBlock,
        EquationBlock,
        ImageBlock,
        CodeBlock,
        QuoteBlock,
        FootnoteBlock
    ],
    Field(discriminator='type')
]


class PageContent(BaseModel):
    """Structured content extracted from a single page."""
    page_number: int = Field(description="1-based page number")
    header: Optional[str] = Field(default=None, description="Header text from the page (e.g., page numbers, chapter titles)")
    footer: Optional[str] = Field(default=None, description="Footer text from the page (e.g., page numbers, citations)")
    blocks: list[ContentBlock] = Field(description="Ordered list of content blocks (polymorphic)")
    raw_text: Optional[str] = Field(default=None, description="Raw OCR text for the page")
    column_layout: Optional[ColumnLayout] = Field(default=None, description="Detailed column layout if multi-column")
    # Deprecated fields (kept for backwards compatibility)
    has_multi_column: bool = Field(default=False, description="DEPRECATED: Use column_layout instead")
    column_count: Optional[int] = Field(default=None, description="DEPRECATED: Use column_layout.column_count")
    reading_order_notes: Optional[str] = Field(default=None, description="Notes about reading order if complex")
    page_direction: Literal["ltr", "rtl"] = Field(default="ltr", description="Primary text direction: ltr or rtl")

    @property
    def is_multi_column(self) -> bool:
        """Check if page has multiple columns."""
        if self.column_layout:
            return self.column_layout.column_count > 1
        return self.has_multi_column

    @property
    def get_column_count(self) -> int:
        """Get column count (1 for single column)."""
        if self.column_layout:
            return self.column_layout.column_count
        return self.column_count or 1


class DocumentMetadata(BaseModel):
    """Metadata about the document."""
    title: Optional[str] = Field(default=None, description="Document title if detectable")
    author: Optional[str] = Field(default=None, description="Document author if detectable")
    total_pages: int = Field(description="Total number of pages in the document")
    language: Optional[str] = Field(default=None, description="Primary language of the document")
    document_type: Optional[str] = Field(default=None, description="Type: report, form, article, letter, etc.")
    is_scanned: bool = Field(default=False, description="Whether the document appears to be scanned/OCR'd")


class DocumentStructure(BaseModel):
    """Complete structured representation of a PDF document."""
    metadata: DocumentMetadata = Field(description="Document metadata")
    pages: list[PageContent] = Field(description="Content for each page")
    extraction_notes: Optional[str] = Field(default=None, description="Any notes about the extraction process")


class ChunkExtraction(BaseModel):
    """Extraction result for a chunk of pages."""
    pages: list[PageContent] = Field(description="Content for each page in this chunk")
    chunk_notes: Optional[str] = Field(default=None, description="Any notes about this chunk extraction")


# Resolve forward references for recursive structures (ListBlock -> ListItem -> ListBlock)
ListBlock.model_rebuild()
ListItem.model_rebuild()


# =============================================================================
# HTML RENDERER
# =============================================================================

class HTMLRenderer:
    """Converts structured document data to HTML."""
    
    # RTL language codes
    RTL_LANGUAGES = {
        "ar", "arabic",
        "he", "hebrew", "iw",  # iw is legacy code for Hebrew
        "fa", "persian", "farsi",
        "ur", "urdu",
        "yi", "yiddish",
        "ps", "pashto",
        "sd", "sindhi",
        "ug", "uyghur",
        "ku", "kurdish",
        "dv", "divehi",
    }
    
    @staticmethod
    def _is_rtl_language(language: Optional[str]) -> bool:
        """Check if the language is RTL."""
        if not language:
            return False
        lang_lower = language.lower().strip()
        # Check exact match or prefix (e.g., "ar-SA" -> "ar")
        return (lang_lower in HTMLRenderer.RTL_LANGUAGES or 
                lang_lower.split("-")[0] in HTMLRenderer.RTL_LANGUAGES or
                lang_lower.split("_")[0] in HTMLRenderer.RTL_LANGUAGES)
    
    @staticmethod
    def _detect_rtl_text(text: str, threshold: float = 0.3) -> bool:
        """
        Detect if text is predominantly RTL.
        
        Args:
            text: The text to analyze
            threshold: Minimum ratio of RTL chars to total directional chars (default 0.3 = 30%)
        
        Returns:
            True if RTL characters exceed the threshold
        """
        if not text or len(text) < 10:
            return False
        
        # Unicode ranges for RTL scripts
        rtl_chars = 0
        ltr_chars = 0
        for char in text:
            code = ord(char)
            # Arabic (0600-06FF, 0750-077F, 08A0-08FF, FB50-FDFF, FE70-FEFF)
            # Hebrew (0590-05FF, FB1D-FB4F)
            if (0x0600 <= code <= 0x06FF or  # Arabic
                0x0750 <= code <= 0x077F or  # Arabic Supplement
                0x08A0 <= code <= 0x08FF or  # Arabic Extended-A
                0xFB50 <= code <= 0xFDFF or  # Arabic Presentation Forms-A
                0xFE70 <= code <= 0xFEFF or  # Arabic Presentation Forms-B
                0x0590 <= code <= 0x05FF or  # Hebrew
                0xFB1D <= code <= 0xFB4F):   # Hebrew Presentation Forms
                rtl_chars += 1
            elif 0x0041 <= code <= 0x005A or 0x0061 <= code <= 0x007A:  # A-Z, a-z
                ltr_chars += 1
        
        total_directional = rtl_chars + ltr_chars
        if total_directional == 0:
            return False
        
        rtl_ratio = rtl_chars / total_directional
        return rtl_ratio >= threshold
    
    @staticmethod
    def render(doc: DocumentStructure, include_styles: bool = True) -> str:
        """Render the structured document as HTML."""
        parts = []
        
        # Determine document direction
        # Priority: 1) Explicit language metadata, 2) Text content analysis
        is_rtl = False
        
        # First check language metadata from Gemini
        if doc.metadata.language:
            is_rtl = HTMLRenderer._is_rtl_language(doc.metadata.language)
        
        # If no language metadata or it's generic, analyze text content
        if not doc.metadata.language and doc.pages:
            # Sample more content for better detection
            sample_text = ""
            for page in doc.pages[:5]:  # Check first 5 pages
                block_count = 0
                for block in page.blocks:
                    if isinstance(block, (HeadingBlock, ParagraphBlock)):
                        sample_text += block.content + " "
                        block_count += 1
                    elif isinstance(block, ListBlock):
                        for item in block.items:
                            sample_text += item.content + " "
                            block_count += 1
                    if block_count >= 10 or len(sample_text) > 2000:  # Enough sample
                        break
                if len(sample_text) > 2000:
                    break
            # Use higher threshold (50%) to be sure it's RTL
            is_rtl = HTMLRenderer._detect_rtl_text(sample_text, threshold=0.5)
        
        # DOCTYPE and HTML opening
        parts.append("<!DOCTYPE html>")
        lang = doc.metadata.language or ("ar" if is_rtl else "en")
        dir_attr = ' dir="rtl"' if is_rtl else ' dir="ltr"'
        parts.append(f'<html lang="{lang}"{dir_attr}>')
        parts.append("<head>")
        parts.append('<meta charset="UTF-8">')
        parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        
        if doc.metadata.title:
            parts.append(f"<title>{HTMLRenderer._escape(doc.metadata.title)}</title>")
        
        # Add MathJax for equation rendering
        parts.append(HTMLRenderer._get_mathjax_config())
        
        if include_styles:
            parts.append(HTMLRenderer._get_styles(is_rtl))
        
        parts.append("</head>")
        parts.append("<body>")
        parts.append('<div class="document-container">')
        
        # Render each page
        for page in doc.pages:
            parts.append(HTMLRenderer._render_page(page, is_rtl))
        
        parts.append("</div>")
        parts.append("</body>")
        parts.append("</html>")
        
        return "\n".join(parts)
    
    @staticmethod
    def _get_mathjax_config() -> str:
        """Return MathJax configuration script."""
        return r"""<script>
window.MathJax = {
  tex: {
    inlineMath: [['\\(', '\\)'], ['$', '$']],
    displayMath: [['\\[', '\\]'], ['$$', '$$']],
    processEscapes: true,
    processEnvironments: true,
    packages: {'[+]': ['noerrors']}
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'],
    ignoreHtmlClass: 'tex2jax_ignore',
    processHtmlClass: 'tex2jax_process'
  },
  loader: {load: ['[tex]/noerrors']},
  startup: {
    pageReady: () => {
      return MathJax.startup.defaultPageReady().then(() => {
        console.log('MathJax initial typesetting complete');
      });
    }
  }
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async id="MathJax-script"></script>
<script>
// Enhanced MathJax loading and error handling
document.getElementById('MathJax-script').addEventListener('load', function() {
  console.log('MathJax loaded successfully');
  
  // Force typesetting after a brief delay
  setTimeout(() => {
    if (window.MathJax && MathJax.typesetPromise) {
      console.log('Triggering MathJax typesetting...');
      MathJax.typesetPromise()
        .then(() => console.log('MathJax typesetting complete!'))
        .catch((err) => console.error('MathJax typeset error:', err));
    }
  }, 100);
});

document.getElementById('MathJax-script').addEventListener('error', function() {
  console.error('Failed to load MathJax from CDN');
});

// Additional safety: trigger on window load
window.addEventListener('load', () => {
  setTimeout(() => {
    if (window.MathJax && MathJax.typesetPromise) {
      MathJax.typesetPromise().catch((err) => console.error('MathJax error:', err));
    }
  }, 200);
});
</script>"""
    
    @staticmethod
    def _get_styles(is_rtl: bool = False) -> str:
        """Return CSS styles for the document."""
        # RTL-specific font stack
        if is_rtl:
            font_family = "'Amiri', 'Scheherazade New', 'Noto Naskh Arabic', 'Traditional Arabic', 'Arabic Typesetting', 'Segoe UI', Tahoma, sans-serif"
        else:
            font_family = "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
        
        return f"""<style>
    @import url('https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400;1,700&family=Noto+Naskh+Arabic:wght@400;500;600;700&display=swap');
    
    :root {{
        --page-bg: #ffffff;
        --text-color: #1a1a1a;
        --border-color: #e0e0e0;
        --header-bg: #f5f5f5;
        --code-bg: #f8f8f8;
    }}
    
    * {{ box-sizing: border-box; }}
    
    body {{
        font-family: {font_family};
        line-height: 1.8;
        color: var(--text-color);
        max-width: 900px;
        margin: 0 auto;
        padding: 20px;
        background: #fafafa;
    }}
    
    .document-container {{
        background: var(--page-bg);
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border-radius: 4px;
    }}
    
    .page {{
        position: relative;
        padding: 60px 50px;
        border-bottom: 2px dashed var(--border-color);
        page-break-after: always;
        min-height: 900px;
        overflow: visible;
    }}
    
    .page:last-child {{
        border-bottom: none;
    }}
    
    .page-header {{
        font-size: 0.75rem;
        color: #888;
        text-align: {'left' if is_rtl else 'right'};
        margin-bottom: 20px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border-color);
    }}
    
    .page-footer {{
        font-size: 0.75rem;
        color: #888;
        text-align: center;
        margin-top: 20px;
        padding-top: 10px;
        border-top: 1px solid var(--border-color);
    }}
    
    /* RTL Support */
    [dir="rtl"] {{
        text-align: right;
    }}
    
    [dir="rtl"] .page-header {{
        text-align: left;
    }}
    
    [dir="rtl"] blockquote {{
        border-left: none;
        border-right: 4px solid #007acc;
        padding-right: 1rem;
        padding-left: 0;
    }}
    
    [dir="rtl"] ul, [dir="rtl"] ol {{
        padding-left: 0;
        padding-right: 2rem;
    }}
    
    [dir="rtl"] th, [dir="rtl"] td {{
        text-align: right;
    }}
    
    /* Bidirectional text support - let browser handle mixed content naturally */
    .bidi-isolate {{
        unicode-bidi: isolate;
    }}
    
    /* For paragraphs with mixed content, use plaintext bidi */
    p, li, td, th, h1, h2, h3, h4, h5, h6 {{
        unicode-bidi: plaintext;  /* Let browser auto-detect direction per paragraph */
    }}
    
    /* Force LTR for specific content */
    .ltr {{
        direction: ltr;
        unicode-bidi: isolate;
    }}
    
    /* Force RTL for specific content */
    .rtl {{
        direction: rtl;
        unicode-bidi: isolate;
    }}
    
    /* English page styling */
    .english-text {{
        direction: ltr !important;
        text-align: left !important;
        font-family: Arial, Helvetica, sans-serif;
    }}
    
    .english-text p {{
        text-align: justify;
    }}
    
    h1 {{ font-size: 2rem; margin: 1.5rem 0 1rem; font-weight: 700; }}
    h2 {{ font-size: 1.5rem; margin: 1.25rem 0 0.75rem; font-weight: 600; }}
    h3 {{ font-size: 1.25rem; margin: 1rem 0 0.5rem; font-weight: 600; }}
    h4, h5, h6 {{ font-size: 1.1rem; margin: 0.75rem 0 0.5rem; font-weight: 600; }}
    
    p {{ 
        margin: 0.75rem 0; 
        text-align: justify;
        line-height: 1.8;
    }}
    
    [dir="rtl"] p {{
        text-align: justify;
    }}
    
    /* Text style classes */
    .bold {{ font-weight: bold; }}
    .italic {{ font-style: italic; }}
    .underline {{ text-decoration: underline; }}
    .centered {{ 
        text-align: center !important;
        display: block;
        width: 100%;
    }}
    .right-aligned {{ text-align: right; }}
    .small {{ font-size: 0.9em; }}
    .large {{ font-size: 1.2em; }}
    
    /* List styles */
    ul, ol {{ margin: 0.75rem 0; padding-left: 2rem; }}
    [dir="rtl"] ul, [dir="rtl"] ol {{ padding-left: 0; padding-right: 2rem; }}
    li {{ margin: 0.25rem 0; line-height: 1.6; }}
    
    /* Auto-generated list wrapper */
    .list-wrapper {{ margin: 1rem 0; }}
    
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.9rem;
    }}
    
    th, td {{
        border: 1px solid var(--border-color);
        padding: 8px 12px;
        text-align: left;
    }}
    
    th {{
        background: var(--header-bg);
        font-weight: 600;
    }}
    
    /* RTL table styling */
    table[dir="rtl"] th,
    table[dir="rtl"] td {{
        text-align: right;
    }}
    
    .table-caption, .caption {{
        font-style: italic;
        color: #666;
        margin: 0.5rem 0;
        text-align: center;
        font-weight: 500;
    }}
    
    figure {{
        margin: 1.5rem 0;
        text-align: center;
    }}
    
    figcaption {{
        font-size: 0.9rem;
        color: #666;
        font-style: italic;
        margin-top: 0.5rem;
    }}
    
    .page-content {{
        position: relative;
        z-index: 1;
    }}
    
    figure.image-block {{
        margin: 1.5em auto;
        padding: 1em;
        background: rgba(249,249,249,0.95);
        border: 1px solid var(--border-color);
        border-radius: 4px;
        max-width: 90%;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }}
    
    figure.image-block img {{
        display: block;
        width: 100%;
        height: auto;
        max-width: 100%;
        margin: 0 auto;
        image-rendering: -webkit-optimize-contrast; /* Better rendering for crisp images */
        image-rendering: crisp-edges;
    }}
    
    figure.image-block figcaption {{
        text-align: center;
        font-size: 0.9rem;
        font-style: italic;
        padding: 0.5em 0;
        color: #555;
        margin-top: 0.5em;
    }}
    
    .image-placeholder {{
        background: #f0f0f0;
        padding: 20px;
        border: 1px dashed #ccc;
        color: #666;
        font-style: italic;
    }}
    
    blockquote {{
        border-left: 4px solid #007acc;
        margin: 1rem 0;
        padding: 0.5rem 1rem;
        background: #f8f9fa;
        font-style: italic;
    }}
    
    pre, code {{
        font-family: 'Consolas', 'Monaco', monospace;
        background: var(--code-bg);
        border-radius: 3px;
        direction: ltr;
        text-align: left;
    }}
    
    pre {{
        padding: 1rem;
        overflow-x: auto;
        margin: 1rem 0;
    }}
    
    code {{ padding: 0.2rem 0.4rem; }}
    
    .equation {{
        margin: 1rem 0;
        text-align: center;
        direction: ltr; /* Force LTR for math */
        unicode-bidi: embed;
    }}
    
    .equation.inline {{
        display: inline;
        margin: 0;
        direction: ltr;
        unicode-bidi: embed;
    }}
    
    /* Equation caption for Arabic explanations */
    .equation-caption {{
        text-align: center;
        font-size: 0.9rem;
        color: #555;
        margin-top: 0.5rem;
        font-style: italic;
    }}
    
    /* Ensure MathJax renders properly */
    .MathJax, .MathJax_Display {{
        direction: ltr !important;
        text-align: center !important;
    }}
    
    /* Footnotes section */
    .footnotes-section {{
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 2px solid var(--border-color);
    }}
    
    .footnote {{
        font-size: 0.85rem;
        color: #666;
        margin: 0.5rem 0;
        padding-left: 1rem;
        text-indent: -1rem;
    }}
    
    [dir="rtl"] .footnote {{
        padding-left: 0;
        padding-right: 1rem;
        text-indent: 1rem;
    }}
    
    .reading-order-note {{
        font-size: 0.8rem;
        color: #0066cc;
        background: #f0f8ff;
        padding: 0.5rem;
        margin: 1rem 0;
        border-left: 3px solid #0066cc;
        font-style: italic;
    }}
    
    /* Multi-column layout using flexbox - respects reading order */
    .multi-column,
    .multi-column-3 {{
        display: flex;
        gap: var(--column-gap, 2rem);
        align-items: flex-start;
        direction: ltr; /* keep visual columns left->right even on RTL pages */
    }}
    
    .multi-column .column,
    .multi-column-3 .column {{
        flex: 1 1 0;
        min-width: 0;
    }}
    
    
    @media print {{
        body {{ background: white; padding: 0; }}
        .document-container {{ box-shadow: none; }}
        .page {{ padding: 20px; }}
    }}
    
    @media (max-width: 600px) {{
        body {{ padding: 10px; }}
        .page {{ padding: 20px; }}
        .multi-column, .multi-column-3 {{ flex-direction: column; }}
    }}
</style>"""
    
    @staticmethod
    def _escape(text: str) -> str:
        """Escape HTML special characters."""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))
    
    @staticmethod
    def _deduplicate_header_footer(page: PageContent) -> PageContent:
        """Remove header/footer text from blocks if they appear there."""
        if page.header or page.footer:
            filtered_blocks = []
            for block in page.blocks:
                # Get content from block (different blocks have content in different places)
                content = None
                if isinstance(block, (HeadingBlock, ParagraphBlock, CodeBlock, QuoteBlock, FootnoteBlock)):
                    content = block.content
                elif isinstance(block, EquationBlock):
                    content = block.latex

                # Skip if matches header or footer
                if content:
                    if page.header and content.strip() == page.header.strip():
                        continue
                    if page.footer and content.strip() == page.footer.strip():
                        continue

                filtered_blocks.append(block)

            page.blocks = filtered_blocks

        return page
    
    @staticmethod
    def _render_page(page: PageContent, is_rtl: bool = False) -> str:
        """Render a single page to HTML with polymorphic blocks."""
        # Remove duplicate header/footer from blocks
        page = HTMLRenderer._deduplicate_header_footer(page)

        parts = []
        page_class = "page"

        # Collect all text content for language detection
        page_text = ""
        for block in page.blocks:
            if isinstance(block, (HeadingBlock, ParagraphBlock)):
                page_text += block.content + " "
            elif isinstance(block, ListBlock):
                for item in block.items:
                    page_text += item.content + " "

        is_english_page = HTMLRenderer._detect_english_content(page_text)
        page_dir = "ltr" if is_english_page else ("rtl" if is_rtl else "ltr")

        if page.is_multi_column:
            page_class += " has-multi-column"
            if page.column_layout:
                page_class += f" columns-{page.column_layout.column_count}"

        if is_english_page:
            page_class += " english-text"

        parts.append(f'<div class="{page_class}" id="page-{page.page_number}" style="position: relative;" dir="{page_dir}">')

        # Display header
        if page.header:
            parts.append(f'<div class="page-header">{HTMLRenderer._escape(page.header)}</div>')
        else:
            parts.append(f'<div class="page-header">Page {page.page_number}</div>')

        parts.append('<div class="page-content">')

        # Sort blocks by position for correct reading flow
        elements = []
        for i, block in enumerate(page.blocks):
            elements.append({
                'y': block.bbox_top,
                'x': block.bbox_left,
                'order': i,
                'block': block
            })

        # Sort by position
        get_column = None
        col_count = 1
        reading_order = "rtl" if is_rtl else "ltr"
        if page.is_multi_column:
            col_count = max(1, page.get_column_count)

            # Use column boundaries if available, otherwise estimate
            if page.column_layout and page.column_layout.column_boundaries:
                boundaries = [0.0] + page.column_layout.column_boundaries + [100.0]

                def get_column(x_pos: float) -> int:
                    for i in range(len(boundaries) - 1):
                        if boundaries[i] <= x_pos < boundaries[i + 1]:
                            return i
                    return len(boundaries) - 2
            else:
                # Fallback to equal-width columns
                column_width = 100.0 / col_count

                def get_column(x_pos: float) -> int:
                    col = int(x_pos / column_width)
                    return min(max(col, 0), col_count - 1)

            # Determine reading order
            reading_order = page.column_layout.reading_order if page.column_layout else reading_order

            if reading_order == "rtl":
                elements.sort(key=lambda e: (-(get_column(e['x'])), e['y'], e['order']))
            else:
                elements.sort(key=lambda e: (get_column(e['x']), e['y'], e['order']))
        else:
            elements.sort(key=lambda e: (e['y'], e['x'], e['order']))

        # Render blocks in order
        footnotes = []
        if page.is_multi_column:
            gap_style = ""
            if page.column_layout and page.column_layout.column_gaps:
                avg_gap = sum(page.column_layout.column_gaps) / len(page.column_layout.column_gaps)
                gap_style = f' style="--column-gap: {avg_gap:.2f}%;"'

            column_class = f"multi-column columns-{col_count}" if col_count > 1 else "multi-column"
            parts.append(f'<div class="{column_class}"{gap_style}>')

            columns = [[] for _ in range(col_count)]
            for element in elements:
                block = element['block']

                # Collect footnotes for end of page
                if isinstance(block, FootnoteBlock):
                    footnotes.append(block)
                    continue

                col_idx = get_column(element['x']) if get_column else 0
                col_idx = min(max(col_idx, 0), col_count - 1)
                columns[col_idx].append(element)

            for column in columns:
                column.sort(key=lambda e: (e['y'], e['order']))

            column_order = list(range(col_count))
            if reading_order == "rtl":
                column_order = list(reversed(column_order))

            for col_idx in column_order:
                parts.append(f'<div class="column" style="order: {col_idx};">')
                for element in columns[col_idx]:
                    parts.append(HTMLRenderer._render_block(element['block'], page))
                parts.append('</div>')

            parts.append('</div>')
        else:
            for element in elements:
                block = element['block']

                # Collect footnotes for end of page
                if isinstance(block, FootnoteBlock):
                    footnotes.append(block)
                    continue

                # Render block based on type
                parts.append(HTMLRenderer._render_block(block, page))

        # Render footnotes at end
        if footnotes:
            parts.append('<div class="footnotes-section">')
            for footnote in footnotes:
                ref = f"[{footnote.reference_number}] " if footnote.reference_number else ""
                content = HTMLRenderer._escape(footnote.content)
                parts.append(f'<div class="footnote">{ref}{content}</div>')
            parts.append('</div>')

        parts.append('</div>')  # Close page-content

        # Display footer
        if page.footer:
            parts.append(f'<div class="page-footer">{HTMLRenderer._escape(page.footer)}</div>')

        parts.append("</div>")
        return "\n".join(parts)
    
    @staticmethod
    def _apply_spans(content: str, spans: list[Span]) -> str:
        """Apply inline formatting spans to text content."""
        if not spans:
            return HTMLRenderer._escape(content)

        # Sort spans by start position
        sorted_spans = sorted(spans, key=lambda s: s.start)

        result = []
        last_end = 0

        for span in sorted_spans:
            # Add text before this span
            if span.start > last_end:
                result.append(HTMLRenderer._escape(content[last_end:span.start]))

            # Add styled span
            span_text = HTMLRenderer._escape(content[span.start:span.end])

            if span.style == "bold":
                result.append(f"<strong>{span_text}</strong>")
            elif span.style == "italic":
                result.append(f"<em>{span_text}</em>")
            elif span.style == "underline":
                result.append(f"<u>{span_text}</u>")
            elif span.style == "code":
                result.append(f"<code>{span_text}</code>")
            elif span.style == "link" and span.url:
                result.append(f'<a href="{HTMLRenderer._escape(span.url)}">{span_text}</a>')
            elif span.style == "superscript":
                result.append(f"<sup>{span_text}</sup>")
            elif span.style == "subscript":
                result.append(f"<sub>{span_text}</sub>")
            else:
                result.append(span_text)

            last_end = span.end

        # Add remaining text after last span
        if last_end < len(content):
            result.append(HTMLRenderer._escape(content[last_end:]))

        return "".join(result)

    @staticmethod
    def _render_block(block: ContentBlock, page: Optional[PageContent] = None) -> str:
        """Render a polymorphic content block based on its type."""
        if isinstance(block, HeadingBlock):
            return HTMLRenderer._render_heading(block)
        elif isinstance(block, ParagraphBlock):
            return HTMLRenderer._render_paragraph(block)
        elif isinstance(block, ListBlock):
            return HTMLRenderer._render_list(block)
        elif isinstance(block, TableBlock):
            return HTMLRenderer._render_table(block, page)
        elif isinstance(block, EquationBlock):
            return HTMLRenderer._render_equation(block)
        elif isinstance(block, ImageBlock):
            return HTMLRenderer._render_image(block, page)
        elif isinstance(block, CodeBlock):
            return HTMLRenderer._render_code(block)
        elif isinstance(block, QuoteBlock):
            return HTMLRenderer._render_quote(block)
        else:
            return ""

    @staticmethod
    def _render_heading(heading: HeadingBlock) -> str:
        """Render a heading block with styling."""
        id_attr = f' id="{heading.id}"' if heading.id else ""
        dir_attr = f' dir="{heading.text_direction}"' if heading.text_direction != "auto" else ""

        # Build inline style
        styles = []
        if heading.font_size_pt:
            styles.append(f"font-size: {heading.font_size_pt}pt")
        if heading.font_weight:
            styles.append(f"font-weight: {heading.font_weight}")
        if heading.font_family:
            styles.append(f"font-family: '{heading.font_family}'")
        if heading.text_color:
            styles.append(f"color: {heading.text_color}")
        if heading.background_color:
            styles.append(f"background-color: {heading.background_color}")
        if heading.alignment:
            styles.append(f"text-align: {heading.alignment}")

        style_attr = f' style="{"; ".join(styles)}"' if styles else ""
        content = HTMLRenderer._escape(heading.content)
        return f'<h{heading.level}{id_attr}{dir_attr}{style_attr}>{content}</h{heading.level}>'

    @staticmethod
    def _render_paragraph(paragraph: ParagraphBlock) -> str:
        """Render a paragraph block with inline formatting spans and styling."""
        dir_attr = f' dir="{paragraph.text_direction}"' if paragraph.text_direction != "auto" else ""

        # Build inline style
        styles = []
        if paragraph.font_size_pt:
            styles.append(f"font-size: {paragraph.font_size_pt}pt")
        if paragraph.font_weight:
            styles.append(f"font-weight: {paragraph.font_weight}")
        if paragraph.font_family:
            styles.append(f"font-family: '{paragraph.font_family}'")
        if paragraph.text_color:
            styles.append(f"color: {paragraph.text_color}")
        if paragraph.background_color:
            styles.append(f"background-color: {paragraph.background_color}")
        if paragraph.alignment:
            styles.append(f"text-align: {paragraph.alignment}")

        style_attr = f' style="{"; ".join(styles)}"' if styles else ""
        content = HTMLRenderer._apply_spans(paragraph.content, paragraph.spans)
        return f'<p{dir_attr}{style_attr}>{content}</p>'

    @staticmethod
    def _render_list(list_block: ListBlock) -> str:
        """Render a list block with support for nested lists."""
        tag = "ul" if list_block.style == "unordered" else "ol"
        parts = [f'<{tag}>']

        for item in list_block.items:
            parts.append(f"<li>{HTMLRenderer._escape(item.content)}")
            # Recursively render nested sub-list
            if item.sub_list:
                parts.append(HTMLRenderer._render_list(item.sub_list))
            parts.append("</li>")

        parts.append(f'</{tag}>')
        return "\n".join(parts)

    @staticmethod
    def _render_code(code: CodeBlock) -> str:
        """Render a code block."""
        lang_class = f' class="language-{code.language}"' if code.language else ""
        content = HTMLRenderer._escape(code.content)
        return f'<pre><code{lang_class}>{content}</code></pre>'

    @staticmethod
    def _render_quote(quote: QuoteBlock) -> str:
        """Render a quote block."""
        parts = ['<blockquote>']
        parts.append(f'<p>{HTMLRenderer._escape(quote.content)}</p>')
        if quote.attribution:
            parts.append(f'<footer>— {HTMLRenderer._escape(quote.attribution)}</footer>')
        parts.append('</blockquote>')
        return "\n".join(parts)

    @staticmethod
    def _render_equation(equation: EquationBlock) -> str:
        """Render an equation block."""
        if equation.is_display:
            # Display equation
            eq_html = f'<div class="equation">\\[{equation.latex}\\]</div>'
        else:
            # Inline equation
            eq_html = f'<span class="equation-inline">\\({equation.latex}\\)</span>'

        if equation.number:
            return f'<div class="equation-container">{eq_html}<span class="equation-number">{HTMLRenderer._escape(equation.number)}</span></div>'
        else:
            return eq_html
    
    @staticmethod
    def _detect_english_content(text: str) -> bool:
        """Detect if text is predominantly English (LTR)."""
        if not text or len(text.strip()) < 2:
            return False
        
        # Count Latin alphabet characters
        latin_chars = sum(1 for c in text if 'A' <= c <= 'Z' or 'a' <= c <= 'z')
        total_alpha = sum(1 for c in text if c.isalpha())
        
        if total_alpha == 0:
            return False
        
        # If more than 70% Latin characters, it's English
        return (latin_chars / total_alpha) > 0.7
    
    @staticmethod
    def _has_arabic(text: str) -> bool:
        """Check if text contains Arabic characters."""
        return bool(re.search(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]', text))
    
    @staticmethod
    def _clean_equation_content(content: str) -> tuple[str, str]:
        """
        Clean equation content by separating pure math from Arabic text.
        
        Returns:
            tuple of (cleaned_equation, arabic_caption)
        """
        # If no Arabic text, return as-is
        if not HTMLRenderer._has_arabic(content):
            return content, ""
        
        # Try to extract pure mathematical notation
        # Remove \text{...} blocks that contain Arabic
        import re
        
        # Pattern to find \text{...} with Arabic content
        text_blocks = re.findall(r'\\text\{([^}]+)\}', content)
        
        cleaned = content
        arabic_parts = []
        
        for text_block in text_blocks:
            if HTMLRenderer._has_arabic(text_block):
                # This is likely a caption, not part of the equation
                arabic_parts.append(text_block)
                # Remove this \text{...} block
                cleaned = cleaned.replace(f'\\text{{{text_block}}}', '', 1)
        
        # Clean up any remaining spacing issues
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # If equation is now empty or very short (just Arabic caption, no real math)
        # Return empty equation and full arabic caption
        if len(cleaned.strip()) < 5:
            # This is probably just an Arabic label, not a real equation
            # Return the original content as caption
            arabic_caption = ' '.join(arabic_parts).strip() if arabic_parts else content
            # Remove \text{} wrappers from caption
            arabic_caption = re.sub(r'\\text\{([^}]+)\}', r'\1', arabic_caption)
            return "", arabic_caption
        
        arabic_caption = ' '.join(arabic_parts).strip()
        return cleaned, arabic_caption
    
    
    @staticmethod
    def _render_table(table: TableBlock, page: Optional[PageContent] = None) -> str:
        """Render a table to HTML with support for rowspan/colspan."""
        parts = []

        if table.caption:
            parts.append(f'<p class="table-caption">{HTMLRenderer._escape(table.caption)}</p>')

        # Keep the extracted column order
        headers = list(table.headers)
        rows = table.rows

        # Determine table direction from page
        table_dir = ""
        if page and page.page_direction:
            table_dir = f' dir="{page.page_direction}"'
        
        parts.append(f"<table{table_dir}>")

        if headers:
            parts.append("<thead><tr>")
            for header in headers:
                parts.append(f"<th>{HTMLRenderer._escape(header)}</th>")
            parts.append("</tr></thead>")

        parts.append("<tbody>")
        for row in rows:
            parts.append("<tr>")
            for cell in row:
                # Build attributes for rowspan/colspan
                attrs = []
                if cell.row_span > 1:
                    attrs.append(f'rowspan="{cell.row_span}"')
                if cell.col_span > 1:
                    attrs.append(f'colspan="{cell.col_span}"')

                # Build inline style for cell
                cell_styles = []
                if cell.alignment:
                    cell_styles.append(f"text-align: {cell.alignment}")
                if cell.vertical_alignment:
                    cell_styles.append(f"vertical-align: {cell.vertical_alignment}")
                if cell.background_color:
                    cell_styles.append(f"background-color: {cell.background_color}")
                if cell.text_color:
                    cell_styles.append(f"color: {cell.text_color}")
                if cell.font_weight:
                    cell_styles.append(f"font-weight: {cell.font_weight}")

                if cell_styles:
                    attrs.append(f'style="{"; ".join(cell_styles)}"')

                # Use th for header cells, td for regular cells
                tag = "th" if cell.is_header else "td"
                attr_str = " " + " ".join(attrs) if attrs else ""
                parts.append(f"<{tag}{attr_str}>{HTMLRenderer._escape(cell.content)}</{tag}>")
            parts.append("</tr>")
        parts.append("</tbody>")
        parts.append("</table>")

        return "\n".join(parts)
    
    @staticmethod
    def _render_image(image: ImageBlock, page: Optional[PageContent] = None) -> str:
        """Render an image to HTML - as normal in-flow block to prevent overlaps."""
        # Use bbox dimensions for better sizing
        # If multi-column, scale width relative to column width
        width = None
        if page and page.is_multi_column:
            col_count = max(1, page.get_column_count)
            column_width_pct = None
            if page.column_layout and page.column_layout.column_boundaries:
                boundaries = [0.0] + page.column_layout.column_boundaries + [100.0]
                col_idx = 0
                for i in range(len(boundaries) - 1):
                    if boundaries[i] <= image.bbox_left < boundaries[i + 1]:
                        col_idx = i
                        break
                column_width_pct = boundaries[col_idx + 1] - boundaries[col_idx]
            else:
                column_width_pct = 100.0 / col_count

            if column_width_pct and column_width_pct > 0:
                relative_width = (image.bbox_width / column_width_pct) * 100.0
                # Boost likely full-column figures to better match PDF visuals
                if relative_width >= 50:
                    relative_width = max(relative_width, 80)
                width = min(100, max(10, relative_width))

        # Fallback to page-based sizing
        if width is None:
            # For wide images (>70% page width), show at full bbox width
            # For smaller images, cap at reasonable size
            if image.bbox_width > 70:
                width = min(95, image.bbox_width)
            else:
                width = max(30, min(80, image.bbox_width))
        
        # Build inline style for sizing (no horizontal positioning)
        style = f"max-width: {width}%; margin: 1rem auto;"
        
        parts = [f'<figure class="image-block" style="{style}" data-bbox="{image.bbox_left},{image.bbox_top},{image.bbox_width},{image.bbox_height}">']
        
        if image.image_data:
            # We have actual image data - render as embedded image
            parts.append(f'<img src="data:image/png;base64,{image.image_data}" '
                        f'alt="{HTMLRenderer._escape(image.description)}" '
                        f'title="{HTMLRenderer._escape(image.description)}" />')
        else:
            # Fallback to placeholder
            parts.append(f'<div class="image-placeholder">[{image.image_type.title()}: {HTMLRenderer._escape(image.description)}]</div>')
        
        if image.caption:
            parts.append(f"<figcaption>{HTMLRenderer._escape(image.caption)}</figcaption>")
        parts.append("</figure>")
        return "\n".join(parts)


# =============================================================================
# DOCUMENT VALIDATOR
# =============================================================================

class DocumentValidator:
    """Validates extracted documents for quality and completeness."""

    @staticmethod
    def validate_document(doc: DocumentStructure) -> dict:
        """
        Validate an extracted document and return quality report.

        Returns:
            dict with 'is_valid': bool, 'errors': list, 'warnings': list, 'stats': dict
        """
        errors = []
        warnings = []
        stats = {
            "total_pages": len(doc.pages),
            "total_blocks": 0,
            "missing_bbox_count": 0,
            "duplicate_content_count": 0,
            "empty_blocks": 0,
        }

        # Check page continuity
        page_numbers = [p.page_number for p in doc.pages]
        expected_pages = list(range(1, len(doc.pages) + 1))

        if page_numbers != expected_pages:
            missing = set(expected_pages) - set(page_numbers)
            extra = set(page_numbers) - set(expected_pages)
            if missing:
                errors.append(f"Missing pages: {sorted(missing)}")
            if extra:
                warnings.append(f"Extra/duplicate page numbers: {sorted(extra)}")

        # Check each page
        all_content = []
        for page in doc.pages:
            stats["total_blocks"] += len(page.blocks)

            for block in page.blocks:
                # Check for missing bbox
                if not DocumentValidator._has_valid_bbox(block):
                    stats["missing_bbox_count"] += 1
                    warnings.append(f"Page {page.page_number}: Block missing complete bbox")

                # Check for empty content
                content = DocumentValidator._get_block_content(block)
                if content and not content.strip():
                    stats["empty_blocks"] += 1
                    warnings.append(f"Page {page.page_number}: Empty block found")
                elif content:
                    all_content.append(content.strip())

        # Check for duplicate content
        if all_content:
            from collections import Counter
            content_counts = Counter(all_content)
            duplicates = {content: count for content, count in content_counts.items() if count > 1}
            if duplicates:
                stats["duplicate_content_count"] = len(duplicates)
                # Only warn about excessive duplication
                if len(duplicates) > 5:
                    warnings.append(f"Found {len(duplicates)} pieces of duplicate content (possible extraction error)")

        # Check for pages with no content
        empty_pages = []
        for page in doc.pages:
            if not page.blocks or len(page.blocks) == 0:
                empty_pages.append(page.page_number)

        if empty_pages:
            warnings.append(f"Pages with no content blocks: {empty_pages}")

        # Validation summary
        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "stats": stats,
        }

    @staticmethod
    def _has_valid_bbox(block: ContentBlock) -> bool:
        """Check if block has all required bbox fields."""
        try:
            return (
                hasattr(block, 'bbox_top') and block.bbox_top is not None and
                hasattr(block, 'bbox_left') and block.bbox_left is not None and
                hasattr(block, 'bbox_width') and block.bbox_width is not None and
                hasattr(block, 'bbox_height') and block.bbox_height is not None and
                0 <= block.bbox_top <= 100 and
                0 <= block.bbox_left <= 100 and
                0 <= block.bbox_width <= 100 and
                0 <= block.bbox_height <= 100
            )
        except:
            return False

    @staticmethod
    def _get_block_content(block: ContentBlock) -> Optional[str]:
        """Extract text content from any block type."""
        if isinstance(block, (HeadingBlock, ParagraphBlock, CodeBlock, QuoteBlock, FootnoteBlock)):
            return block.content
        elif isinstance(block, ListBlock):
            return " ".join(item.content for item in block.items)
        elif isinstance(block, EquationBlock):
            return block.latex
        elif isinstance(block, ImageBlock):
            return block.description
        elif isinstance(block, TableBlock):
            # Extract text from table cells
            text_parts = []
            for row in block.rows:
                for cell in row:
                    text_parts.append(cell.content)
            return " ".join(text_parts)
        return None


# =============================================================================
# IMAGE EXTRACTOR
# =============================================================================

class ImageExtractor:
    """Extracts images from PDF pages using PyMuPDF based on bounding box coordinates."""
    
    def __init__(self, pdf_path: str, dpi: int = 150):
        """Initialize the extractor with a PDF file."""
        if not HAS_PYMUPDF:
            raise RuntimeError("PyMuPDF is required for image extraction. Install with: pip install PyMuPDF")
        
        self.pdf_path = pdf_path
        self.dpi = dpi
        self.doc = fitz.open(pdf_path)
        self._page_cache: dict[int, bytes] = {}
    
    def _render_page(self, page_num: int) -> tuple[bytes, int, int]:
        """Render a page to PNG bytes and return (image_bytes, width, height)."""
        if page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"Invalid page number: {page_num}")
        
        # fitz uses 0-based indexing
        page = self.doc[page_num - 1]
        
        # Render page at specified DPI
        zoom = self.dpi / 72  # 72 is the default PDF resolution
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        
        return pix.tobytes("png"), pix.width, pix.height
    
    def extract_image(self, page_num: int, bbox_top: float, bbox_left: float, 
                      bbox_width: float, bbox_height: float, padding_percent: float = 2.0) -> str:
        """
        Extract a region from a page and return as base64 PNG.
        
        Args:
            page_num: 1-based page number
            bbox_top: Top edge as percentage (0-100)
            bbox_left: Left edge as percentage (0-100)
            bbox_width: Width as percentage (0-100)
            bbox_height: Height as percentage (0-100)
            padding_percent: Extra padding around bbox as percentage (default 2%)
        
        Returns:
            Base64 encoded PNG image data
        """
        # Get the page
        if page_num < 1 or page_num > len(self.doc):
            logger.warning(f"Invalid page number {page_num}, skipping image extraction")
            return ""
        
        page = self.doc[page_num - 1]
        page_rect = page.rect
        
        # Convert percentage coordinates to actual coordinates with padding
        x0 = page_rect.width * ((bbox_left - padding_percent) / 100)
        y0 = page_rect.height * ((bbox_top - padding_percent) / 100)
        x1 = x0 + page_rect.width * ((bbox_width + 2 * padding_percent) / 100)
        y1 = y0 + page_rect.height * ((bbox_height + 2 * padding_percent) / 100)
        
        # Clamp to page bounds
        x0 = max(0, min(x0, page_rect.width))
        y0 = max(0, min(y0, page_rect.height))
        x1 = max(0, min(x1, page_rect.width))
        y1 = max(0, min(y1, page_rect.height))
        
        # Ensure valid rectangle
        if x1 <= x0 or y1 <= y0:
            logger.warning(f"Invalid bounding box for page {page_num}, skipping")
            return ""
        
        # Create clip rectangle
        clip_rect = fitz.Rect(x0, y0, x1, y1)
        
        # Use higher DPI for small images to maintain quality
        width_pts = x1 - x0
        height_pts = y1 - y0
        area = width_pts * height_pts
        
        # If image is small (< 10000 square points), use higher DPI
        effective_dpi = self.dpi
        if area < 10000:
            effective_dpi = min(self.dpi * 2, 300)  # Double DPI up to max 300
            logger.debug(f"Small image detected ({width_pts:.1f}x{height_pts:.1f}), using {effective_dpi} DPI")
        
        # Render the clipped region
        zoom = effective_dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, clip=clip_rect)
        
        # Convert to base64
        png_bytes = pix.tobytes("png")
        return base64.b64encode(png_bytes).decode("utf-8")
    
    def extract_images_for_document(self, doc: DocumentStructure) -> DocumentStructure:
        """
        Extract all images from the document and populate image_data fields.

        Args:
            doc: DocumentStructure with image bounding boxes from Gemini

        Returns:
            DocumentStructure with image_data populated
        """
        for page in doc.pages:
            for block in page.blocks:
                if isinstance(block, ImageBlock):
                    try:
                        image_data = self.extract_image(
                            page_num=page.page_number,
                            bbox_top=block.bbox_top,
                            bbox_left=block.bbox_left,
                            bbox_width=block.bbox_width,
                            bbox_height=block.bbox_height
                        )
                        block.image_data = image_data
                        if image_data:
                            logger.info(f"Extracted {block.image_type} from page {page.page_number}")
                    except Exception as e:
                        logger.warning(f"Failed to extract image from page {page.page_number}: {e}")
        
        return doc
    
    def close(self):
        """Close the PDF document."""
        if self.doc:
            self.doc.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# =============================================================================
# PDF PROCESSOR
# =============================================================================

class PDFProcessor:
    """Production-grade PDF to HTML processor using Gemini API."""
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        """Initialize the processor with configuration."""
        self.config = config or ProcessingConfig()

        # Validate API key exists
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not set. "
                "Please set it with your Google Gemini API key. "
                "Get your key at: https://aistudio.google.com/app/apikey"
            )

        self.client = genai.Client(api_key=api_key)
        self._uploaded_file = None
        self._cached_content = None  # For context caching
        self._file_cleaned_up = False  # Track cleanup state to prevent double-delete

        # Token usage tracking (thread-safe)
        self._token_lock = Lock()
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._cache_creation_tokens = 0
        self._cache_read_tokens = 0
    
    def _get_media_resolution(self) -> types.MediaResolution:
        """Convert config resolution to API type."""
        resolution_map = {
            MediaResolution.LOW: types.MediaResolution.MEDIA_RESOLUTION_LOW,
            MediaResolution.MEDIUM: types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            MediaResolution.HIGH: types.MediaResolution.MEDIA_RESOLUTION_HIGH,
        }
        return resolution_map.get(
            self.config.media_resolution,
            types.MediaResolution.MEDIA_RESOLUTION_MEDIUM
        )
    
    def _upload_pdf(self, pdf_path: str) -> types.File:
        """Upload PDF to Gemini Files API with retry logic."""
        pdf_path = str(pathlib.Path(pdf_path).expanduser().resolve())
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Uploading PDF: {pdf_path} (attempt {attempt + 1})")
                uploaded = self.client.files.upload(file=pdf_path)
                logger.info(f"Upload successful: {uploaded.name}")
                return uploaded
            except Exception as e:
                logger.warning(f"Upload attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise RuntimeError(f"Failed to upload PDF after {self.config.max_retries} attempts") from e

    def _create_cached_content(self, uploaded_file: types.File) -> Optional[any]:
        """
        Create cached content for the uploaded PDF to reduce costs.

        Context caching can save ~90% of input token costs for multi-chunk documents.
        Cache is valid for 1 hour by default.
        """
        if not self.config.use_chunked_processing:
            # Only use caching for chunked processing (multi-chunk documents)
            return None

        try:
            logger.info("Creating context cache for PDF (saves ~90% on input tokens for subsequent chunks)")

            # Create a cache with the uploaded PDF file
            # The cache will be reused for all subsequent API calls
            cached = self.client.caches.create(
                model=self.config.model,
                contents=[uploaded_file],
                ttl_seconds=3600,  # Cache for 1 hour
                system_instruction="You are an expert OCR and document analysis system."
            )

            logger.info(f"Context cache created: {cached.name} (valid for 1 hour)")
            return cached

        except Exception as e:
            logger.warning(f"Failed to create context cache: {e}. Continuing without caching.")
            return None

    def _get_page_count(self, uploaded_file: types.File) -> tuple[int, DocumentMetadata]:
        """Get document page count and metadata."""
        prompt = """Analyze this PDF document and provide:
1. The total number of pages
2. Document metadata (title, author, language, document type)

Do NOT extract page content, just count pages and identify metadata.

IMPORTANT:
- If unable to determine page count, return -1
- If PDF is encrypted or corrupted, set total_pages to -1 and note in document_type"""

        # Try multiple times with different temperatures if JSON parsing fails
        # Start with low temperature for accurate transcription, increase slightly if it fails
        # Temperature ceiling lowered to 0.7 (metadata should be factual, not creative)
        temperatures = [0.3, 0.5, 0.7]
        last_error = None
        
        for attempt, temperature in enumerate(temperatures, 1):
            try:
                logger.info(f"Extracting metadata (attempt {attempt}/{len(temperatures)}, temperature={temperature})")
                
                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=DocumentMetadata.model_json_schema(),
                        system_instruction="You are a document analyzer. Count pages and extract metadata only. Ensure ALL JSON strings are properly escaped.",
                        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,  # Low res for counting
                        max_output_tokens=1024,
                        temperature=temperature,
                    ),
                )
                
                metadata = DocumentMetadata.model_validate_json(response.text)
                logger.info(f"Document has {metadata.total_pages} pages")
                return metadata.total_pages, metadata
                
            except (ValueError, Exception) as e:
                error_msg = str(e)
                last_error = e
                
                # Check if it's a JSON parsing error
                if "json" in error_msg.lower() or "parsing" in error_msg.lower() or "invalid" in error_msg.lower():
                    logger.warning(f"JSON parsing error on attempt {attempt}: {error_msg[:200]}")
                    if attempt < len(temperatures):
                        logger.info(f"Retrying with lower temperature ({temperatures[attempt]})...")
                        time.sleep(1)  # Brief delay before retry
                        continue
                else:
                    # Non-parsing error, re-raise immediately
                    raise
        
        # All retries exhausted
        logger.error(f"Failed to extract valid metadata after {len(temperatures)} attempts")
        raise RuntimeError(f"Metadata extraction failed: {last_error}")
    
    def _estimate_cost(self, total_pages: int) -> dict:
        """Estimate processing cost based on page count.
        
        Returns:
            dict with cost_estimate_usd, estimated_tokens, estimated_time_seconds
        """
        # Rough estimates based on Gemini pricing and typical performance
        # These are approximations and actual costs may vary
        
        if self.config.use_chunked_processing:
            num_chunks = (total_pages + self.config.pages_per_chunk - 1) // self.config.pages_per_chunk
        else:
            num_chunks = 1
        
        # Estimate tokens per page (input + output)
        # Typical: 500-2000 input tokens per page, 200-1000 output tokens per page
        avg_input_tokens_per_page = 1000
        avg_output_tokens_per_page = 500
        
        estimated_input_tokens = total_pages * avg_input_tokens_per_page
        estimated_output_tokens = total_pages * avg_output_tokens_per_page
        
        # Gemini 3 Flash Preview pricing (as of January 2026):
        # Paid Tier per 1M tokens:
        # - Input: $0.50 (text/image/video), $1.00 (audio)
        # - Output: $3.00 (including thinking tokens)
        # - Context caching: $0.05 (text/image/video)
        # Note: Free tier available with free input/output, but usage limits apply
        input_cost = (estimated_input_tokens / 1_000_000) * 0.50
        output_cost = (estimated_output_tokens / 1_000_000) * 3.00
        total_cost = input_cost + output_cost
        
        # Time estimate: ~2-5 seconds per page with API overhead
        estimated_time = total_pages * 3 + (num_chunks * 2)  # +2s overhead per chunk
        
        estimate = {
            "total_pages": total_pages,
            "num_chunks": num_chunks,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "estimated_cost_usd": round(total_cost, 4),
            "estimated_time_seconds": estimated_time,
            "estimated_time_minutes": round(estimated_time / 60, 1),
        }
        
        logger.info(
            f"Cost estimate: ${estimate['estimated_cost_usd']} USD, "
            f"~{estimate['estimated_time_minutes']} minutes for {total_pages} pages"
        )
        
        return estimate
    
    def _calculate_page_quality(self, page: PageContent) -> dict:
        """Calculate quality metrics for a page.

        Returns:
            dict with quality metrics
        """
        total_text_chars = 0
        total_blocks = len(page.blocks)
        total_tables = 0
        total_images = 0
        table_cells = 0

        for block in page.blocks:
            if isinstance(block, (HeadingBlock, ParagraphBlock, CodeBlock, QuoteBlock, FootnoteBlock)):
                total_text_chars += len(block.content)
            elif isinstance(block, ListBlock):
                for item in block.items:
                    total_text_chars += len(item.content)
            elif isinstance(block, TableBlock):
                total_tables += 1
                table_cells += len(block.headers) + sum(len(row) for row in block.rows)
            elif isinstance(block, ImageBlock):
                total_images += 1
            elif isinstance(block, EquationBlock):
                total_text_chars += len(block.latex)

        # Quality heuristics
        has_content = total_text_chars > 0 or total_tables > 0 or total_images > 0
        is_substantial = total_text_chars > 50  # At least 50 chars

        return {
            "page_number": page.page_number,
            "text_chars": total_text_chars,
            "text_blocks": total_blocks,
            "tables": total_tables,
            "table_cells": table_cells,
            "images": total_images,
            "has_content": has_content,
            "is_substantial": is_substantial,
            "multi_column": page.is_multi_column,
            "column_count": page.get_column_count,
        }
    
    def _extract_page_range(self, uploaded_file: types.File, start_page: int, end_page: int) -> list[PageContent]:
        """Extract content from a specific range of pages."""
        prompt = f"""Extract content from pages {start_page} to {end_page} of this PDF document.

IMPORTANT: Only process pages {start_page} through {end_page}. Skip all other pages.

For each page in this range:
1. Set the correct page_number (starting from {start_page})
2. Extract the HEADER text if present (usually at the top of the page - may contain page numbers, chapter titles, section names)
3. Extract the FOOTER text if present (usually at the bottom of the page - may contain page numbers, citations, document info)
4. Extract content using STRICTLY TYPED BLOCKS with lowercase 'type' discriminators:
   - HEADINGS: type='heading' with level (1-6), content, and bbox
   - PARAGRAPHS: type='paragraph' with content, spans (for bold/italic/links), and bbox
   - LISTS: type='list' with style (ordered/unordered), items, and bbox
     * For NESTED LISTS: Set sub_list field in ListItem to create nested list
   - TABLES: type='table' with rows of TableCell objects (with row_span/col_span)
   - EQUATIONS: type='equation' with latex, is_display, number (if present), and bbox
   - IMAGES/FIGURES: type='image' with image_type, description, caption, and bbox
   - CODE: type='code' with content, language, and bbox
   - QUOTES: type='quote' with content, attribution, and bbox
   - FOOTNOTES: type='footnote' with content, reference_number, and bbox

   CRITICAL RULES:
   - EVERY block MUST have complete BOUNDING BOX coordinates (bbox_top, bbox_left, bbox_width, bbox_height) as percentages 0-100
   - bbox fields are REQUIRED, not optional - missing bbox = invalid output
   - For INLINE FORMATTING (bold, italic, underline, links): Add Span objects to the paragraph's spans field
     * Span has start/end character indices, style type, and optional URL for links
5. For MATHEMATICAL EQUATIONS:
   - CRITICAL: TRANSCRIBE equations EXACTLY as they appear - do NOT solve, simplify, or manipulate them
   - Extract the equation as it is written in the PDF, preserving all notation and structure
   - Convert to LaTeX syntax in an 'equation' block
   - For inline equations: set is_display_math=false
   - For display equations (centered, standalone): set is_display_math=true
   - For NUMBERED EQUATIONS (e.g., labeled (1), (2), (3)): Extract number in equation_number field
   - Use standard LaTeX notation: \\frac{{}}{{}}, \\sum, \\int, \\sqrt{{}}, \\text{{}}, ^{{}}, _{{}}, etc.
   - For superscripts/subscripts: Use ^{{}} and _{{}} syntax (e.g., x^{{2}}, H_{{2}}O)
   - Include bbox coordinates for equation blocks
   - Example: If PDF shows "س = د/ط" transcribe it as-is, don't simplify or solve
6. For NUMBERS AND NUMERALS:
   - CRITICAL: Preserve the EXACT numeral system from the PDF
   - If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), transcribe them EXACTLY - do NOT convert to Western numerals (0123456789)
   - If PDF uses Western numerals (0123456789), keep them as Western numerals
   - Example: "٢.٥٠" must stay "٢.٥٠", NOT "2.50"
   - Example: "١٠.٠٠" must stay "١٠.٠٠", NOT "10.00"
   - This applies to ALL content: tables, text, equations, captions, page numbers
7. For LISTS (numbered, bulleted, nested):
   - For NESTED LISTS: Set list_level field (1=top level, 2=first nesting, 3=deeper nesting, etc.)
   - Preserve hierarchy and proper indentation structure
8. For TABLES: OCR all text content and structure it with headers and rows. Do NOT treat tables as images.
   - For MERGED CELLS: Set row_span and col_span values (default is 1 for regular cells)
   - For table captions: Extract separately from table content
   - Provide BOUNDING BOX coordinates (bbox_top, bbox_left, bbox_width, bbox_height) as percentages (0-100) of the page.
9. For VISUAL ELEMENTS (charts, graphs, diagrams, figures, photos):
   - Identify the image_type (chart, graph, diagram, figure, photo, logo, illustration, other)
   - Provide a description
   - Provide BOUNDING BOX coordinates as percentages (0-100) of the page:
     * bbox_top: distance from top of page
     * bbox_left: distance from left of page  
     * bbox_width: width of the image
     * bbox_height: height of the image
10. For MULTI-COLUMN LAYOUTS:
   - Set has_multi_column=true and column_count (2 or 3)
   - CRITICAL: For LTR documents, extract columns LEFT-TO-RIGHT (complete column 1, then column 2, etc.)
   - CRITICAL: For RTL documents, extract columns RIGHT-TO-LEFT (complete rightmost column first)
   - Add reading_order_notes if the layout is complex or unusual
11. For TEXT DIRECTION:
   - Set page_direction='rtl' for Arabic/Hebrew pages, 'ltr' for English/Western
   - For mixed RTL/LTR text blocks, set text_direction='rtl' or 'ltr' on individual text blocks
12. For WATERMARKS and BACKGROUND TEXT:
   - Ignore decorative watermarks (e.g., "DRAFT", "CONFIDENTIAL")
   - Extract meaningful background text only if it's actual content
13. Preserve natural reading flow and content accuracy

REMEMBER: 
- ALL elements (text blocks, images, tables) need bbox coordinates for proper ordering
- Tables = OCR the text AND provide bounding box coordinates
- Charts/Graphs/Figures = provide bounding box for extraction
- Preserve numeral systems EXACTLY as they appear
- TRANSCRIBE equations exactly, don't solve or simplify them"""

        for attempt in range(self.config.max_retries):
            try:
                # Start with low temperature for accurate transcription (not creative writing)
                temperature = 0.3 + (attempt * 0.2)  # 0.3 -> 0.5 -> 0.7 on retries
                logger.info(f"Extracting pages {start_page}-{end_page} (attempt {attempt + 1}, temperature={temperature})")
                
                # Use cached content if available, otherwise use uploaded file
                if self._cached_content:
                    contents = [self._cached_content, prompt]
                else:
                    contents = [uploaded_file, prompt]

                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=ChunkExtraction.model_json_schema(),
                        system_instruction=(
                            f"You are an expert OCR and document analysis system extracting pages {start_page}-{end_page} only using POLYMORPHIC BLOCK TYPES. "
                            "Use STRICTLY TYPED blocks with lowercase 'type' discriminators: type='heading', 'paragraph', 'list', 'table', 'equation', 'image', 'code', 'quote', 'footnote'. "
                            "For HEADINGS: type='heading' with level 1-6. "
                            "For PARAGRAPHS: type='paragraph'. For bold/italic/links, add Span objects to spans field with start/end indices and style. "
                            "For LISTS: type='list' with ordered/unordered style. For NESTED lists, set sub_list field in ListItem to create recursive list. "
                            "For TABLES: type='table' with rows of TableCell objects. For MERGED CELLS: Set row_span and col_span in TableCell. "
                            "For EQUATIONS: type='equation' with LaTeX. TRANSCRIBE EXACTLY - do NOT solve or simplify. Use ^{} and _{} for super/subscripts. "
                            "For IMAGES/FIGURES: type='image' with image_type, description, caption. "
                            "PRESERVE NUMERAL SYSTEMS: If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), keep them exactly - do NOT convert to Western numerals. "
                            "MANDATORY BBOX: EVERY block MUST have bbox_top, bbox_left, bbox_width, bbox_height as percentages (0-100). Missing bbox = invalid. "
                            "BBOX MEASUREMENT: Always measure bbox_left from PHYSICAL LEFT EDGE (0% = left, 100% = right), regardless of text direction. "
                            "For RTL text on right side: bbox_left should be 70-90%, NOT 10-30%. "
                            "For MULTI-COLUMN: LTR docs extract left-to-right, RTL docs extract right-to-left. "
                            "For MIXED RTL/LTR: Set text_direction on individual blocks. "
                            "IGNORE decorative watermarks. "
                            "Ensure all JSON strings are properly escaped."
                        ),
                        media_resolution=self._get_media_resolution(),
                        max_output_tokens=self.config.max_output_tokens,
                        temperature=temperature,
                    ),
                )
                
                chunk = ChunkExtraction.model_validate_json(response.text)
                
                # Track token usage including cache metrics
                if hasattr(response, 'usage_metadata'):
                    self._total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0)
                    self._total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0)
                    # Track cache-specific tokens if using caching
                    if self._cached_content:
                        self._cache_creation_tokens += getattr(response.usage_metadata, 'cached_content_token_count', 0)
                        self._cache_read_tokens += getattr(response.usage_metadata, 'cache_read_input_tokens', 0)
                
                logger.info(f"Extracted {len(chunk.pages)} pages from range {start_page}-{end_page}")
                return chunk.pages
                
            except Exception as e:
                error_msg = str(e)
                is_json_error = "json" in error_msg.lower() or "parsing" in error_msg.lower() or "invalid" in error_msg.lower()
                
                if is_json_error:
                    logger.warning(f"JSON parsing error on attempt {attempt + 1}: {error_msg[:200]}")
                else:
                    logger.warning(f"Chunk extraction attempt {attempt + 1} failed: {error_msg[:200]}")
                
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (attempt + 1)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {self.config.max_retries} attempts failed for pages {start_page}-{end_page}")
                    raise
        
        return []
    
    def _extract_chunked(self, uploaded_file: types.File) -> DocumentStructure:
        """Extract document content in chunks for large documents."""
        # First, get page count and metadata
        total_pages, metadata = self._get_page_count(uploaded_file)

        # Create cached content for cost savings (if chunked processing enabled)
        self._cached_content = self._create_cached_content(uploaded_file)
        if self._cached_content:
            logger.info("✓ Context caching enabled - will save ~90% on input tokens for subsequent chunks")

        # Estimate cost and time
        cost_estimate = self._estimate_cost(total_pages)
        if self._cached_content:
            # Adjust cost estimate for caching (90% savings on input tokens for chunks after first)
            num_chunks = (total_pages + self.config.pages_per_chunk - 1) // self.config.pages_per_chunk
            if num_chunks > 1:
                savings = cost_estimate['estimated_cost_usd'] * 0.9 * (num_chunks - 1) / num_chunks
                adjusted_cost = cost_estimate['estimated_cost_usd'] - savings
                logger.info(f"Estimated cost with caching: ${adjusted_cost:.4f} USD (saves ${savings:.4f})")
            else:
                logger.info(f"Estimated cost: ${cost_estimate['estimated_cost_usd']} USD")
        else:
            logger.info(f"Starting extraction of {total_pages} pages (estimated ${cost_estimate['estimated_cost_usd']} USD)")

        all_pages: list[PageContent] = []
        chunk_size = self.config.pages_per_chunk
        start_time = time.time()

        # Calculate all chunk ranges
        chunk_ranges = []
        for chunk_idx, start in enumerate(range(1, total_pages + 1, chunk_size), 1):
            end = min(start + chunk_size - 1, total_pages)
            chunk_ranges.append((chunk_idx, start, end))

        total_chunks = len(chunk_ranges)
        logger.info(f"Processing {total_chunks} chunks in parallel")

        # Helper function to process a single chunk
        def process_chunk(chunk_info):
            chunk_idx, start, end = chunk_info
            try:
                logger.info(f"Processing chunk {chunk_idx}: pages {start}-{end} of {total_pages}")
                chunk_pages = self._extract_page_range(uploaded_file, start, end)

                # Ensure page numbers are correct
                for i, page in enumerate(chunk_pages):
                    expected_page = start + i
                    if page.page_number != expected_page:
                        page.page_number = expected_page

                logger.info(f"Chunk {chunk_idx} complete: extracted {len(chunk_pages)} pages")
                return (chunk_idx, chunk_pages, None)

            except Exception as e:
                logger.error(f"Chunk {chunk_idx} failed (pages {start}-{end}): {e}")
                # Create placeholder pages for failed chunks
                placeholder_pages = []
                for page_num in range(start, end + 1):
                    placeholder_pages.append(PageContent(
                        page_number=page_num,
                        blocks=[ParagraphBlock(
                            content=f"[Page {page_num} extraction failed: {e}]",
                            bbox_top=50.0,
                            bbox_left=10.0,
                            bbox_width=80.0,
                            bbox_height=10.0
                        )]
                    ))
                return (chunk_idx, placeholder_pages, str(e))

        # Process all chunks in parallel
        chunk_results = []
        with ThreadPoolExecutor(max_workers=total_chunks) as executor:
            # Submit all chunks
            futures = {executor.submit(process_chunk, chunk_info): chunk_info for chunk_info in chunk_ranges}

            # Collect results as they complete
            completed = 0
            for future in as_completed(futures):
                chunk_idx, pages, error = future.result()
                chunk_results.append((chunk_idx, pages, error))
                completed += 1
                progress = (completed / total_chunks) * 100
                logger.info(f"Progress: {completed}/{total_chunks} chunks complete ({progress:.1f}%)")

        # Sort results by chunk index to maintain page order
        chunk_results.sort(key=lambda x: x[0])

        # Combine all pages in order
        for chunk_idx, pages, error in chunk_results:
            all_pages.extend(pages)
        
        # Sort pages by page number (in case of any ordering issues)
        all_pages.sort(key=lambda p: p.page_number)
        
        # CRITICAL: Validate page coverage - ensure no pages are missing
        expected_pages = set(range(1, total_pages + 1))
        extracted_pages = {p.page_number for p in all_pages}
        missing_pages = expected_pages - extracted_pages
        
        if missing_pages:
            logger.warning(f"Missing {len(missing_pages)} pages after initial extraction: {sorted(missing_pages)}")
            
            # Retry missing pages individually (up to max_retries attempts per page)
            for page_num in sorted(missing_pages):
                logger.info(f"Retrying missing page {page_num}")
                retry_success = False
                
                for retry_attempt in range(self.config.max_retries):
                    try:
                        retry_pages = self._extract_page_range(uploaded_file, page_num, page_num)
                        if retry_pages and len(retry_pages) > 0:
                            retry_pages[0].page_number = page_num
                            all_pages.append(retry_pages[0])
                            logger.info(f"Successfully recovered page {page_num}")
                            retry_success = True
                            break
                    except Exception as e:
                        logger.warning(f"Retry attempt {retry_attempt + 1} for page {page_num} failed: {e}")
                        if retry_attempt < self.config.max_retries - 1:
                            time.sleep(self.config.retry_delay)
                
                # If all retries failed, create placeholder
                if not retry_success:
                    logger.error(f"Failed to extract page {page_num} after {self.config.max_retries} retries")
                    all_pages.append(PageContent(
                        page_number=page_num,
                        blocks=[ParagraphBlock(
                            content=f"[Page {page_num} could not be extracted after multiple attempts]",
                            bbox_top=50.0,
                            bbox_left=10.0,
                            bbox_width=80.0,
                            bbox_height=10.0
                        )]
                    ))
            
            # Re-sort after adding recovered pages
            all_pages.sort(key=lambda p: p.page_number)
        
        # Final validation
        final_page_numbers = {p.page_number for p in all_pages}
        still_missing = expected_pages - final_page_numbers
        
        if still_missing:
            logger.error(f"CRITICAL: Still missing {len(still_missing)} pages after retry: {sorted(still_missing)}")
        else:
            logger.info(f"✓ Page coverage verified: all {total_pages} pages extracted")
        
        # Calculate quality metrics for all pages
        quality_metrics = [self._calculate_page_quality(page) for page in all_pages]
        total_chars = sum(m["text_chars"] for m in quality_metrics)
        total_blocks = sum(m["text_blocks"] for m in quality_metrics)
        total_tables = sum(m["tables"] for m in quality_metrics)
        total_images = sum(m["images"] for m in quality_metrics)
        pages_with_content = sum(1 for m in quality_metrics if m["has_content"])
        
        # Calculate processing time
        elapsed_time = time.time() - start_time
        
        logger.info(
            f"Extraction complete: {elapsed_time:.1f}s, "
            f"{total_chars:,} chars, {total_blocks} blocks, "
            f"{total_tables} tables, {total_images} images"
        )
        
        # Update metadata with actual extracted count
        metadata.total_pages = len(all_pages)
        
        extraction_notes = (
            f"Extracted in {(total_pages + chunk_size - 1) // chunk_size} chunks of {chunk_size} pages. "
            f"Processing time: {elapsed_time:.1f}s. "
            f"Content: {total_chars:,} chars, {total_blocks} text blocks, "
            f"{total_tables} tables, {total_images} images. "
            f"Pages with content: {pages_with_content}/{total_pages}."
        )
        
        if missing_pages:
            extraction_notes += f" Recovered {len(missing_pages) - len(still_missing)}/{len(missing_pages)} missing pages."

        # Create document structure
        doc = DocumentStructure(
            metadata=metadata,
            pages=all_pages,
            extraction_notes=extraction_notes
        )

        # Validate the extracted document
        validation_result = DocumentValidator.validate_document(doc)
        logger.info(f"Document validation: {validation_result['stats']}")

        if not validation_result['is_valid']:
            logger.error(f"Document validation failed with {len(validation_result['errors'])} errors")
            for error in validation_result['errors']:
                logger.error(f"  - {error}")

        if validation_result['warnings']:
            logger.warning(f"Document validation found {len(validation_result['warnings'])} warnings")
            for warning in validation_result['warnings'][:5]:  # Show first 5 warnings
                logger.warning(f"  - {warning}")
            if len(validation_result['warnings']) > 5:
                logger.warning(f"  ... and {len(validation_result['warnings']) - 5} more warnings")

        return doc
    
    def _extract_structured(self, uploaded_file: types.File) -> DocumentStructure:
        """Extract structured document data using Gemini's structured output."""
        
        prompt = """Analyze this PDF document and extract its complete content in a structured format.

Instructions:
1. Process EVERY page from start to finish - do not skip any pages
2. Extract the HEADER text if present (usually at the top of the page - may contain page numbers, chapter titles, section names)
3. Extract the FOOTER text if present (usually at the bottom of the page - may contain page numbers, citations, document info)
4. Extract all text blocks with semantic types (heading, paragraph, list_item, equation, etc.)
   - CRITICAL: For EVERY text block, you MUST provide bbox coordinates as percentages (0-100)
5. For MATHEMATICAL EQUATIONS:
   - CRITICAL: TRANSCRIBE equations EXACTLY as they appear - do NOT solve, simplify, or manipulate them
   - Convert to LaTeX syntax in 'equation' blocks
   - For inline equations: set is_display_math=false
   - For display equations: set is_display_math=true
   - For NUMBERED EQUATIONS: Extract number in equation_number field
   - Use LaTeX notation: \\frac{{}}{{}}, \\sum, \\int, \\sqrt{{}}, ^{{}}, _{{}}, etc.
   - Example: If PDF shows "س = د/ط" transcribe it as-is, don't solve
6. For NUMBERS AND NUMERALS:
   - CRITICAL: Preserve EXACT numeral system from PDF
   - If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), keep them EXACTLY
   - Do NOT convert to Western numerals (0123456789)
7. For LISTS: type='list' with ordered/unordered style
   - For NESTED LISTS: Set sub_list field in ListItem to create nested list
   - Preserve hierarchy with recursion
8. For TABLES: type='table' with rows of TableCell objects
   - For MERGED CELLS: Set row_span and col_span in TableCell
   - For table captions: Extract in caption field
   - Provide bbox coordinates
9. For VISUAL ELEMENTS (charts, graphs, diagrams, figures, photos):
   - Identify image_type and provide description
   - Provide bbox coordinates as percentages (0-100)
10. For MULTI-COLUMN LAYOUTS:
    - Set has_multi_column=true and column_count
    - For LTR docs: Extract columns LEFT-TO-RIGHT
    - For RTL docs: Extract columns RIGHT-TO-LEFT
    - Add reading_order_notes if complex
11. For TEXT DIRECTION:
    - Set page_direction='rtl' for Arabic/Hebrew, 'ltr' for Western
    - For mixed RTL/LTR: Set text_direction on individual blocks
12. For WATERMARKS: Ignore decorative watermarks
13. OCR all scanned text accurately
14. Detect document metadata: title, author, language, document type

REMEMBER:
- Tables = OCR the text. Charts/Graphs = provide bbox for extraction
- Preserve numeral systems EXACTLY
- TRANSCRIBE equations exactly, don't solve them
- If document is too large for context, prioritize first pages and set truncated=true"""

        for attempt in range(self.config.max_retries):
            try:
                # Start with low temperature for accurate transcription (not creative writing)
                temperature = 0.3 + (attempt * 0.2)  # 0.3 -> 0.5 -> 0.7 on retries
                logger.info(f"Extracting structured content (attempt {attempt + 1}, temperature={temperature})")
                
                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=DocumentStructure.model_json_schema(),
                        system_instruction=(
                            "You are an expert OCR system using POLYMORPHIC BLOCK TYPES. "
                            "Use STRICTLY TYPED blocks with lowercase 'type' discriminators: type='heading', 'paragraph', 'list', 'table', 'equation', 'image', 'code', 'quote', 'footnote'. "
                            "For HEADINGS: type='heading' with level 1-6. "
                            "For PARAGRAPHS: type='paragraph' with Span objects for bold/italic/links. "
                            "For LISTS: type='list'. For NESTED lists, use sub_list field in ListItem for recursive list. "
                            "For TABLES: type='table' with TableCell objects. For MERGED cells, set row_span/col_span. "
                            "For EQUATIONS: type='equation' with LaTeX. TRANSCRIBE EXACTLY - do NOT solve. Use ^{}/_{} for scripts. "
                            "For IMAGES: type='image' with image_type, description, caption. "
                            "PRESERVE Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩) - do NOT convert to Western. "
                            "MANDATORY BBOX: ALL blocks MUST have bbox_top, bbox_left, bbox_width, bbox_height (0-100%). "
                            "Measure bbox_left from PHYSICAL LEFT edge, regardless of text direction. "
                            "For RTL text on right: bbox_left = 70-90%, NOT 10-30%. "
                            "MULTI-COLUMN: LTR=left-to-right, RTL=right-to-left. "
                            "IGNORE decorative watermarks. "
                            "Ensure JSON strings are escaped."
                        ),
                        media_resolution=self._get_media_resolution(),
                        max_output_tokens=self.config.max_output_tokens,
                        temperature=temperature,
                    ),
                )
                
                # Parse and validate the response
                doc = DocumentStructure.model_validate_json(response.text)
                logger.info(f"Successfully extracted {len(doc.pages)} pages")

                # Validate the extracted document
                validation_result = DocumentValidator.validate_document(doc)
                logger.info(f"Document validation: {validation_result['stats']}")

                if not validation_result['is_valid']:
                    logger.error(f"Validation failed with {len(validation_result['errors'])} errors")
                    for error in validation_result['errors']:
                        logger.error(f"  - {error}")

                if validation_result['warnings']:
                    logger.warning(f"Validation found {len(validation_result['warnings'])} warnings")
                    for warning in validation_result['warnings'][:5]:
                        logger.warning(f"  - {warning}")

                return doc
                
            except Exception as e:
                error_msg = str(e)
                is_json_error = "json" in error_msg.lower() or "parsing" in error_msg.lower() or "invalid" in error_msg.lower()
                
                if is_json_error:
                    logger.warning(f"JSON parsing error on attempt {attempt + 1}: {error_msg[:200]}")
                else:
                    logger.warning(f"Extraction attempt {attempt + 1} failed: {error_msg[:200]}")
                
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (attempt + 1)
                    logger.info(f"Retrying in {delay}s with lower temperature...")
                    time.sleep(delay)
                else:
                    raise RuntimeError(f"Failed to extract content after {self.config.max_retries} attempts") from e
    
    def _direct_html_extraction(self, uploaded_file: types.File) -> str:
        """Request HTML directly from Gemini (fallback method when structured extraction fails)."""
        logger.info("Using direct HTML extraction as fallback")
        
        prompt = """Convert this entire PDF document into a single self-contained HTML document.

Requirements:
- Process ALL pages of the document completely - do not skip any
- Output ONLY raw HTML (no Markdown fences, no explanations)
- Preserve layout: headings, paragraphs, lists, tables with proper HTML tags
- Maintain correct reading order for multi-column layouts
- For MATHEMATICAL EQUATIONS: Preserve as LaTeX wrapped in <span class="equation">LaTeX code</span>
  * Use LaTeX syntax: \\frac{}{}, \\sum, \\int, \\sqrt{}, ^{}, _{}, etc.
  * TRANSCRIBE equations EXACTLY - do NOT solve, simplify, or manipulate them
  * For display equations: wrap in <div class="equation">LaTeX</div>
- For RTL text (Arabic, Hebrew): Add dir="rtl" to containing element (<p dir="rtl">, <div dir="rtl">)
- PRESERVE NUMERAL SYSTEMS: Keep Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩) exactly - do NOT convert to Western numerals
- Include CSS in <head><style>...</style> for formatting and layout
- Use .page-break { page-break-after: always; } for page breaks
- Add <div class="page-break"></div> between pages
- Use semantic HTML5 elements: <article>, <section>, <header>, <footer>, <figure>, <table>
- OCR all scanned content accurately
- Preserve all content, do not omit any text or tables"""

        # Use retry loop with temperature progression like other methods
        for attempt in range(self.config.max_retries):
            try:
                # Start with low temperature for accurate transcription
                temperature = 0.3 + (attempt * 0.2)  # 0.3 -> 0.5 -> 0.7 on retries
                logger.info(f"Direct HTML extraction (attempt {attempt + 1}, temperature={temperature})")
                
                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="text/plain",
                        system_instruction=(
                            "You are an expert document transcription assistant. "
                            "Convert documents to clean, semantic HTML5 preserving ALL content accurately. "
                            "PRESERVE NUMERAL SYSTEMS: Keep Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩) exactly - do NOT convert to Western numerals (0123456789). "
                            "For EQUATIONS: Wrap in <span class=\"equation\">LaTeX</span> or <div class=\"equation\">LaTeX</div>. "
                            "TRANSCRIBE equations EXACTLY - do NOT solve or simplify them. "
                            "For RTL text: Use <p dir=\"rtl\">, <div dir=\"rtl\">, or <span dir=\"rtl\"> attributes. "
                            "Use semantic elements: <article>, <section>, <header>, <footer>, <figure>, <table>. "
                            "Include <style> tag in <head> with CSS for layout and formatting. "
                            "Add CSS: .page-break { page-break-after: always; } and use <div class=\"page-break\"></div> between pages. "
                            "Ensure proper HTML escaping of special characters. "
                            "Be accurate and thorough - preserve all content."
                        ),
                        media_resolution=self._get_media_resolution(),
                        max_output_tokens=self.config.max_output_tokens,
                        temperature=temperature,
                    ),
                )
                
                html_content = response.text or ""
                if not html_content.strip():
                    raise ValueError("Empty HTML response from Gemini")
                
                logger.info(f"Direct HTML extraction successful ({len(html_content)} chars)")
                return html_content
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Direct HTML attempt {attempt + 1} failed: {error_msg[:200]}")
                
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (attempt + 1)
                    logger.info(f"Retrying in {delay}s with higher temperature...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {self.config.max_retries} direct HTML attempts failed")
                    raise RuntimeError(f"Direct HTML extraction failed after {self.config.max_retries} attempts") from e
        
        return ""
    
    def _post_process_gemini_html(self, html_content: str, pdf_path: str) -> str:
        """
        Post-process Gemini-generated HTML to insert actual images from the PDF.
        
        This method:
        1. Finds image placeholders in the HTML (figures, images, etc.)
        2. Extracts actual images from PDF pages
        3. Replaces placeholders with embedded base64 images
        
        Args:
            html_content: HTML generated by Gemini
            pdf_path: Path to source PDF for image extraction
            
        Returns:
            HTML with actual embedded images
        """
        if not HAS_PYMUPDF:
            logger.warning("PyMuPDF not installed. Images will remain as placeholders.")
            return html_content
        
        import re
        
        try:
            doc = fitz.open(pdf_path)
            
            # Strategy 1: Look for figure placeholders and inject images
            # Common patterns Gemini uses for images:
            # - <figure>...<img src="placeholder">...</figure>
            # - <img alt="Figure X" src="">
            # - [Image: description]
            # - <div class="image">...</div>
            
            processed_html = html_content
            
            # Track which page we're on by looking for page markers
            page_pattern = re.compile(
                r'<div[^>]*class="[^"]*page[^"]*"[^>]*>|'  # <div class="page">
                r'<div[^>]*id="page-(\d+)"[^>]*>|'  # <div id="page-1">
                r'page-break|'  # page-break class
                r'<!--\s*page\s*(\d+)\s*-->',  # <!-- page 1 -->
                re.IGNORECASE
            )
            
            # Find all images embedded by Gemini (usually empty src or placeholders)
            img_pattern = re.compile(
                r'<img[^>]*(?:src="[^"]*placeholder[^"]*"|src=""|alt="([^"]*(?:Figure|Chart|Graph|Image|Diagram)[^"]*)")',
                re.IGNORECASE
            )
            
            # Find figure elements that might need images
            figure_pattern = re.compile(
                r'<figure[^>]*>(.*?)</figure>',
                re.DOTALL | re.IGNORECASE
            )
            
            # Extract all figures from the PDF
            # Since we don't have bbox info from Gemini HTML, we extract page-wide figures
            figures_extracted = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Get all embedded images in the page
                images = page.get_images()
                for img_idx, img in enumerate(images):
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        if base_image:
                            image_bytes = base_image["image"]
                            ext = base_image.get("ext", "png")
                            b64_data = base64.b64encode(image_bytes).decode("utf-8")
                            figures_extracted.append({
                                "page": page_num + 1,
                                "index": img_idx,
                                "data": f"data:image/{ext};base64,{b64_data}",
                            })
                    except Exception as img_err:
                        logger.debug(f"Could not extract image {img_idx} from page {page_num + 1}: {img_err}")
            
            logger.info(f"Extracted {len(figures_extracted)} images from PDF")
            
            # Replace placeholder images with extracted images
            img_index = 0
            
            def replace_img(match):
                nonlocal img_index
                if img_index < len(figures_extracted):
                    img_data = figures_extracted[img_index]["data"]
                    img_index += 1
                    # Preserve alt text if present
                    alt_match = re.search(r'alt="([^"]*)"', match.group(0))
                    alt_text = alt_match.group(1) if alt_match else "Figure"
                    return f'<img src="{img_data}" alt="{alt_text}" style="max-width: 100%; height: auto;">'
                return match.group(0)
            
            processed_html = img_pattern.sub(replace_img, processed_html)
            
            # Also handle empty src attributes
            empty_src_pattern = re.compile(r'<img([^>]*)src=""([^>]*)>')
            
            def replace_empty_src(match):
                nonlocal img_index
                if img_index < len(figures_extracted):
                    img_data = figures_extracted[img_index]["data"]
                    img_index += 1
                    return f'<img{match.group(1)}src="{img_data}"{match.group(2)}>'
                return match.group(0)
            
            processed_html = empty_src_pattern.sub(replace_empty_src, processed_html)
            
            doc.close()
            
            logger.info(f"Post-processed HTML: injected {img_index} images")
            return processed_html
            
        except Exception as e:
            logger.error(f"Error post-processing Gemini HTML: {e}")
            return html_content
    
    def process(self, pdf_path: str, output_path: Optional[str] = None) -> dict:
        """
        Process a PDF file and convert to HTML.
        
        Args:
            pdf_path: Path to the input PDF file
            output_path: Optional path for output file (auto-generated if not provided)
        
        Returns:
            dict with 'html_path', 'json_path' (if applicable), and 'document' (structured data)
        """
        pdf_path = str(pathlib.Path(pdf_path).expanduser().resolve())
        base_name = pathlib.Path(pdf_path).stem
        
        if output_path:
            output_base = str(pathlib.Path(output_path).with_suffix(""))
        else:
            output_base = base_name
        
        result = {
            "html_path": None,
            "json_path": None,
            "document": None,
            "success": False,
            "method": None,
        }
        
        uploaded_file = None
        try:
            # Upload the PDF
            uploaded_file = self._upload_pdf(pdf_path)
            self._uploaded_file = uploaded_file
            
            # Handle gemini_html mode: Get HTML directly from Gemini, then post-process to add images
            if self.config.output_format == "gemini_html":
                logger.info("Using Gemini direct HTML mode with image post-processing")
                html_content = self._direct_html_extraction(uploaded_file)
                
                # Post-process to inject actual images from PDF
                html_content = self._post_process_gemini_html(html_content, pdf_path)
                
                result["method"] = "gemini_html"
                
                # Write HTML output
                html_path = f"{output_base}.html"
                pathlib.Path(html_path).write_text(html_content, encoding="utf-8")
                result["html_path"] = html_path
                result["success"] = True
                logger.info(f"Wrote Gemini HTML: {html_path}")
                
            else:
                # Standard processing: structured extraction -> our HTML renderer
                # Try structured extraction first
                try:
                    if self.config.use_chunked_processing:
                        logger.info("Using chunked processing for large document support")
                        doc = self._extract_chunked(uploaded_file)
                        result["method"] = "chunked"
                    else:
                        doc = self._extract_structured(uploaded_file)
                        result["method"] = "structured"
                    
                    # Extract actual images from PDF using bounding boxes
                    if self.config.extract_images and HAS_PYMUPDF:
                        try:
                            with ImageExtractor(pdf_path, dpi=self.config.image_dpi) as extractor:
                                doc = extractor.extract_images_for_document(doc)
                                logger.info("Image extraction completed")
                        except Exception as e:
                            logger.warning(f"Image extraction failed: {e}. Images will be placeholders.")
                    elif self.config.extract_images and not HAS_PYMUPDF:
                        logger.warning("PyMuPDF not installed. Images will be placeholders. Install with: pip install PyMuPDF")
                    
                    result["document"] = doc
                    
                    # Render to HTML from structured data
                    html_content = HTMLRenderer.render(doc)
                    
                    # EXPERIMENTAL: Also get HTML directly from Gemini if enabled
                    if self.config.experimental_gemini_html:
                        try:
                            logger.info("[EXPERIMENTAL] Requesting HTML directly from Gemini for comparison")
                            gemini_html = self._direct_html_extraction(uploaded_file)
                            
                            # Save Gemini's HTML with _gemini suffix
                            if self.config.output_format in ("html", "both"):
                                gemini_html_path = f"{output_base}_gemini.html"
                                pathlib.Path(gemini_html_path).write_text(gemini_html, encoding="utf-8")
                                result["gemini_html_path"] = gemini_html_path
                                logger.info(f"Wrote Gemini HTML: {gemini_html_path}")
                        except Exception as gemini_err:
                            logger.warning(f"Gemini direct HTML extraction failed: {gemini_err}")
                    
                except Exception as e:
                    logger.warning(f"Structured extraction failed: {e}. Falling back to direct HTML.")
                    html_content = self._direct_html_extraction(uploaded_file)
                    result["method"] = "fallback"
            
            # Write HTML output
            if self.config.output_format in ("html", "both"):
                html_path = f"{output_base}.html"
                pathlib.Path(html_path).write_text(html_content, encoding="utf-8")
                result["html_path"] = html_path
                logger.info(f"Wrote HTML: {html_path}")
            
            # Write JSON output if requested and structured data is available
            if self.config.output_format in ("json", "both") and result["document"]:
                json_path = f"{output_base}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(result["document"].model_dump(), f, indent=2, ensure_ascii=False)
                result["json_path"] = json_path
                logger.info(f"Wrote JSON: {json_path}")
            
            result["success"] = True
            
            # Remove document object to avoid serialization issues (already written to files)
            if "document" in result:
                # Store page count before removing
                if result["document"]:
                    result["pages"] = len(result["document"].pages)
                del result["document"]
            
            # Add token usage metadata for cost tracking
            if hasattr(self, '_total_input_tokens'):
                metadata = {
                    "total_input_tokens": self._total_input_tokens,
                    "total_output_tokens": self._total_output_tokens,
                    "total_tokens": self._total_input_tokens + self._total_output_tokens
                }

                # Add cache metrics if caching was used
                if self._cached_content:
                    metadata["cache_creation_tokens"] = self._cache_creation_tokens
                    metadata["cache_read_tokens"] = self._cache_read_tokens
                    # Calculate savings (cache reads cost ~10% of regular input tokens)
                    regular_cost = self._total_input_tokens * 0.50 / 1_000_000  # $0.50 per 1M tokens
                    cache_cost = self._cache_read_tokens * 0.05 / 1_000_000  # $0.05 per 1M tokens
                    metadata["estimated_cache_savings_usd"] = round(regular_cost - cache_cost, 4)

                result["usage_metadata"] = metadata
                logger.info(
                    f"Token usage: {self._total_input_tokens:,} input, "
                    f"{self._total_output_tokens:,} output, "
                    f"{self._total_input_tokens + self._total_output_tokens:,} total"
                )
            
        except FileNotFoundError as e:
            logger.error(f"File not found: {e}")
            result["error"] = str(e)
            result["error_type"] = "file_not_found"
        
        except ValueError as e:
            # Config or API key validation errors
            logger.error(f"Configuration error: {e}")
            result["error"] = str(e)
            result["error_type"] = "configuration_error"
        
        except ConnectionError as e:
            logger.error(f"Network error: {e}")
            result["error"] = str(e)
            result["error_type"] = "network_error"
        
        except Exception as e:
            logger.error(f"Processing failed: {e}", exc_info=True)
            result["error"] = str(e)
            result["error_type"] = "processing_error"
        
        finally:
            # CRITICAL: Always cleanup uploaded file, even on error
            if uploaded_file:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                    logger.info(f"Cleaned up uploaded file: {uploaded_file.name}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup uploaded file: {cleanup_error}")
        
        return result
    
    def cleanup(self):
        """Clean up uploaded files from the API."""
        if self._uploaded_file:
            try:
                self.client.files.delete(name=self._uploaded_file.name)
                logger.info(f"Deleted uploaded file: {self._uploaded_file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete uploaded file: {e}")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def pdf_to_html(
    pdf_path: str,
    out_html: str = "out.html",
    output_json: bool = False,
    media_resolution: str = "medium",
) -> dict:
    """
    Convert a PDF to HTML using Gemini's document understanding.
    
    Args:
        pdf_path: Path to the input PDF file
        out_html: Path for the output HTML file
        output_json: Also output structured JSON data
        media_resolution: Resolution for PDF processing ('low', 'medium', 'high')
    
    Returns:
        dict with processing results
    """
    config = ProcessingConfig(
        output_format="both" if output_json else "html",
        media_resolution=MediaResolution(media_resolution),
    )
    
    processor = PDFProcessor(config)
    try:
        result = processor.process(pdf_path, out_html)
        if result["success"]:
            print(f"✓ Wrote: {result.get('html_path', 'N/A')}")
            if result.get("json_path"):
                print(f"✓ Wrote: {result['json_path']}")
            print(f"  Method: {result.get('method', 'unknown')}")
            if result.get("document"):
                print(f"  Pages: {len(result['document'].pages)}")
        else:
            print(f"✗ Error: {result.get('error', 'Unknown error')}")
        return result
    finally:
        processor.cleanup()


def extract_document_structure(pdf_path: str) -> Optional[DocumentStructure]:
    """
    Extract structured document data from a PDF without rendering HTML.
    
    Args:
        pdf_path: Path to the input PDF file
    
    Returns:
        DocumentStructure object or None if extraction fails
    """
    config = ProcessingConfig(output_format="json")
    processor = PDFProcessor(config)
    try:
        uploaded = processor._upload_pdf(pdf_path)
        return processor._extract_structured(uploaded)
    finally:
        processor.cleanup()


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Production-grade PDF to HTML converter using Gemini API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.pdf                      # Output to document.html
  %(prog)s document.pdf output.html          # Specify output filename
  %(prog)s document.pdf -j                   # Also output JSON structure
  %(prog)s document.pdf -r high              # Use high resolution processing
  %(prog)s document.pdf --format both        # Output both HTML and JSON
        """
    )
    
    parser.add_argument("input", help="Input PDF file path")
    parser.add_argument("output", nargs="?", default=None, help="Output file path (default: <input>.html)")
    parser.add_argument("-j", "--json", action="store_true", help="Also output structured JSON")
    parser.add_argument("-r", "--resolution", choices=["low", "medium", "high"], default="medium",
                        help="Media resolution for processing (default: medium)")
    parser.add_argument("-f", "--format", choices=["html", "json", "both", "gemini_html"], default="html",
                        help="Output format: html (default), json, both, or gemini_html (Gemini direct HTML with image injection)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--retries", type=int, default=3, help="Number of retries on failure")
    parser.add_argument("--max-tokens", type=int, default=65536, 
                        help="Max output tokens (increase for large docs, default: 65536)")
    parser.add_argument("--chunk-size", type=int, default=15,
                        help="Pages per chunk for large docs (default: 15)")
    parser.add_argument("--no-chunking", action="store_true",
                        help="Disable chunked processing (for small docs)")
    parser.add_argument("--no-images", action="store_true",
                        help="Disable image extraction (faster, smaller output)")
    parser.add_argument("--image-dpi", type=int, default=150,
                        help="DPI for extracted images (default: 150)")
    parser.add_argument("--experimental-gemini-html", action="store_true",
                        help="[EXPERIMENTAL] Also request HTML directly from Gemini for comparison")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine output format
    output_format = args.format
    if args.json and output_format == "html":
        output_format = "both"
    
    # Set output path
    output_path = args.output
    if not output_path:
        output_path = str(pathlib.Path(args.input).with_suffix(".html"))
    
    # Create config and process
    config = ProcessingConfig(
        media_resolution=MediaResolution(args.resolution),
        output_format=output_format,
        max_retries=args.retries,
        max_output_tokens=args.max_tokens,
        pages_per_chunk=args.chunk_size,
        use_chunked_processing=not args.no_chunking,
        extract_images=not args.no_images,
        image_dpi=args.image_dpi,
        experimental_gemini_html=args.experimental_gemini_html,
    )
    
    processor = PDFProcessor(config)
    try:
        result = processor.process(args.input, output_path)
        
        if result["success"]:
            print(f"\n✓ Processing complete!")
            print(f"  Method: {result.get('method', 'unknown')}")
            if result.get("html_path"):
                print(f"  HTML: {result['html_path']}")
            if result.get("gemini_html_path"):
                print(f"  Gemini HTML (experimental): {result['gemini_html_path']}")
            if result.get("json_path"):
                print(f"  JSON: {result['json_path']}")
            if result.get("document"):
                doc = result["document"]
                print(f"  Pages: {len(doc.pages)}")
                if doc.metadata.title:
                    print(f"  Title: {doc.metadata.title}")
        else:
            print(f"\n✗ Processing failed: {result.get('error', 'Unknown error')}")
            raise SystemExit(1)
            
    finally:
        processor.cleanup()
