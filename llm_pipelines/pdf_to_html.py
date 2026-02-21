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
from typing import Optional, Literal
from dataclasses import dataclass, field
from enum import Enum

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
from .image_utils import normalise_data_uri

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
    output_format: Literal["html", "json", "both"] = "html"
    max_output_tokens: int = 65536  # Maximum output tokens (default ~65k for long docs)
    pages_per_chunk: int = 10  # Pages to process per API call (for chunked processing)
    parallel_chunks: int = 20   # Max concurrent Gemini API calls when processing chunks
    use_chunked_processing: bool = True  # Enable chunked processing for large docs
    extract_images: bool = True  # Extract charts/graphs/figures as actual images
    image_dpi: int = 300  # DPI for rendering pages when extracting images (increased for better fidelity)
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

        if self.parallel_chunks < 1 or self.parallel_chunks > 200:
            raise ValueError(f"parallel_chunks must be between 1 and 200, got {self.parallel_chunks}")
        
        if self.image_dpi < 50 or self.image_dpi > 600:
            raise ValueError(f"image_dpi must be between 50 and 600, got {self.image_dpi}")
        
        if self.request_timeout < 10 or self.request_timeout > 3600:
            raise ValueError(f"request_timeout must be between 10 and 3600 seconds, got {self.request_timeout}")


# =============================================================================
# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUT
# =============================================================================

class TextSpan(BaseModel):
    """Character-level styled text span for rich inline formatting."""
    text: str = Field(description="The text content")
    bold: bool = Field(default=False, description="Bold text")
    italic: bool = Field(default=False, description="Italic text")
    underline: bool = Field(default=False, description="Underlined text")
    strikethrough: bool = Field(default=False, description="Strikethrough text")
    superscript: bool = Field(default=False, description="Superscript text")
    subscript: bool = Field(default=False, description="Subscript text")
    font_size: Optional[float] = Field(default=None, description="Font size in points")
    font_family: Optional[str] = Field(default=None, description="Font family name")
    text_color: Optional[str] = Field(default=None, description="Text color as hex (#000000)")
    background_color: Optional[str] = Field(default=None, description="Background color as hex")


class TableCell(BaseModel):
    """Represents a cell in a table with full styling."""
    content: str = Field(description="Text content of the cell")
    row_span: int = Field(default=1, description="Number of rows this cell spans")
    col_span: int = Field(default=1, description="Number of columns this cell spans")
    is_header: bool = Field(default=False, description="Whether this is a header cell")
    width_percent: Optional[float] = Field(default=None, description="Cell width as percentage (0-100)")
    text_align: Optional[Literal["left", "center", "right", "justify"]] = Field(default=None, description="Horizontal alignment")
    vertical_align: Optional[Literal["top", "middle", "bottom"]] = Field(default=None, description="Vertical alignment")
    background_color: Optional[str] = Field(default=None, description="Background color as hex")
    text_color: Optional[str] = Field(default=None, description="Text color as hex")
    border_width: Optional[float] = Field(default=None, description="Border width in points")
    border_color: Optional[str] = Field(default=None, description="Border color as hex")


class Table(BaseModel):
    """Represents a table extracted from the document."""
    caption: Optional[str] = Field(default=None, description="Table caption if present")
    headers: list[TableCell] = Field(default_factory=list, description="Column headers with styling")
    rows: list[list[TableCell]] = Field(default_factory=list, description="Table rows with styled cells")
    # Styling properties (let browser handle layout)
    border_style: Optional[Literal["none", "solid", "dashed", "dotted", "double"]] = Field(default="solid", description="Border style")
    border_color: Optional[str] = Field(default="#e0e0e0", description="Border color as hex")
    background_color: Optional[str] = Field(default=None, description="Table background color")
    # Flow-based positioning
    reading_order: Optional[int] = Field(default=None, description="Sequence number on page for proper flow")
    column_number: Optional[int] = Field(default=None, description="Which column (1, 2, 3...) in multi-column layout")
    multi_column_group_id: Optional[str] = Field(default=None, description="ID for grouping elements that form an inline multi-column section")


class TextBlock(BaseModel):
    """Represents a block of text with semantic meaning and rich formatting."""
    block_type: Literal["heading", "paragraph", "list_item", "caption", "footnote", "quote", "code", "equation", "hyperlink", "horizontal_rule"] = Field(
        description="Semantic type of the text block"
    )
    level: Optional[int] = Field(default=None, description="Heading level (1-6) if block_type is heading")
    content: str = Field(description="The text content (for equations, use LaTeX syntax)")
    # Rich text support
    spans: Optional[list[TextSpan]] = Field(default=None, description="Character-level spans for rich inline formatting")
    style: Optional[str] = Field(default=None, description="CSS style hints (e.g., 'bold', 'italic', 'centered')")
    # Font and typography
    font_size: Optional[float] = Field(default=None, description="Font size in points")
    font_family: Optional[str] = Field(default=None, description="Font family name")
    font_weight: Optional[int] = Field(default=400, description="Font weight (100-900, 400=normal, 700=bold)")
    line_height: Optional[float] = Field(default=None, description="Line height multiplier (e.g., 1.5)")
    letter_spacing: Optional[float] = Field(default=None, description="Letter spacing in ems")
    # Colors
    text_color: Optional[str] = Field(default=None, description="Text color as hex (#000000)")
    background_color: Optional[str] = Field(default=None, description="Background color as hex")
    # Spacing and indentation (in relative units)
    indent_left: Optional[float] = Field(default=None, description="Left indent in ems or rem")
    indent_right: Optional[float] = Field(default=None, description="Right indent in ems or rem")
    indent_first_line: Optional[float] = Field(default=None, description="First line indent in ems")
    spacing_before: Optional[float] = Field(default=None, description="Margin before block in ems")
    spacing_after: Optional[float] = Field(default=None, description="Margin after block in ems")
    # Math-specific
    is_display_math: Optional[bool] = Field(default=False, description="For equations: True for display mode (\\[...\\]), False for inline (\\(...\\))")
    equation_number: Optional[str] = Field(default=None, description="Equation number label if present (e.g., '(1)', '(2.3)')")
    # Hyperlink-specific fields
    url: Optional[str] = Field(default=None, description="URL for hyperlink block type")
    link_type: Optional[Literal["url", "email", "internal"]] = Field(default="url", description="Type of hyperlink: external URL, email, or internal bookmark")
    # List hierarchy
    list_level: Optional[int] = Field(default=1, description="Nesting level for list items (1=top level, 2=nested, etc.)")
    # Flow-based positioning and ordering
    text_direction: Optional[Literal["ltr", "rtl", "auto"]] = Field(default="auto", description="Text direction: ltr, rtl, or auto")
    text_align: Optional[Literal["left", "center", "right", "justify"]] = Field(default=None, description="Text alignment: left, center, right, or justify")
    reading_order: Optional[int] = Field(default=None, description="Sequence number on page for proper flow (1, 2, 3...)")
    column_number: Optional[int] = Field(default=None, description="Which column (1, 2, 3...) in multi-column layout")
    multi_column_group_id: Optional[str] = Field(default=None, description="ID for grouping elements that form an inline multi-column section (e.g., 'group1', 'group2')")


class Image(BaseModel):
    """Represents a visual element (chart, graph, diagram, figure) - NOT tables."""
    image_type: Literal["chart", "graph", "diagram", "figure", "photo", "logo", "illustration", "other"] = Field(
        description="Type of visual: chart, graph, diagram, figure, photo, logo, illustration, or other. NOT for tables."
    )
    description: str = Field(description="Description or alt text for the image")
    caption: Optional[str] = Field(default=None, description="Image caption if present")
    # Flow-based positioning
    reading_order: Optional[int] = Field(default=None, description="Sequence number on page for proper flow")
    column_number: Optional[int] = Field(default=None, description="Which column (1, 2, 3...) in multi-column layout")
    multi_column_group_id: Optional[str] = Field(default=None, description="ID for grouping elements that form an inline multi-column section")
    # Alignment within flow
    alignment: Optional[Literal["left", "center", "right", "full-width"]] = Field(default="center", description="Horizontal alignment within text flow")
    # Actual dimensions
    width_pixels: Optional[int] = Field(default=None, description="Actual width in pixels")
    height_pixels: Optional[int] = Field(default=None, description="Actual height in pixels")
    # No bbox - images flow naturally in document
    # Runtime field for extracted image data (not from Gemini)
    image_data: Optional[str] = Field(default=None, description="Base64 encoded image data (populated at runtime)")


class PageContent(BaseModel):
    """Structured content extracted from a single page with full fidelity."""
    page_number: int = Field(description="1-based page number")
    # Separate header components for robust rendering
    header: Optional[str] = Field(default=None, description="Header text from the page (e.g., chapter titles)")
    header_position: Optional[Literal["left", "center", "right"]] = Field(default="center", description="Position of header text: left, center, or right")
    footer: Optional[str] = Field(default=None, description="Footer text from the page (e.g., citations)")
    footer_position: Optional[Literal["left", "center", "right"]] = Field(default="center", description="Position of footer text: left, center, or right")
    page_number_text: Optional[str] = Field(default=None, description="Explicit page number as it appears in document (separate from header/footer)")
    page_number_position: Optional[Literal["header-left", "header-center", "header-right", "footer-left", "footer-center", "footer-right"]] = Field(
        default=None, description="Position of page number on the page"
    )
    # Page dimensions for precise rendering
    width_pts: Optional[float] = Field(default=None, description="Page width in PDF points (1/72 inch)")
    height_pts: Optional[float] = Field(default=None, description="Page height in PDF points")
    # Content
    text_blocks: list[TextBlock] = Field(default_factory=list, description="Ordered list of text blocks")
    tables: list[Table] = Field(default_factory=list, description="Tables found on this page")
    images: list[Image] = Field(default_factory=list, description="Images/figures found on this page")
    raw_text: Optional[str] = Field(default=None, description="Raw OCR text for the page")
    # Layout properties
    has_multi_column: bool = Field(default=False, description="Whether the page has multi-column layout")
    column_count: Optional[int] = Field(default=None, description="Number of columns if multi-column (2, 3, etc.)")
    column_gap: Optional[float] = Field(default=None, description="Gap between columns in points or percentage")
    reading_order_notes: Optional[str] = Field(default=None, description="Notes about reading order if complex")
    # Appearance
    background_color: Optional[str] = Field(default=None, description="Page background color as hex")
    background_image: Optional[str] = Field(default=None, description="Background image as base64 data URI")
    watermark: Optional[str] = Field(default=None, description="Watermark text if present")
    # Text direction
    page_direction: Optional[Literal["ltr", "rtl"]] = Field(default="ltr", description="Primary text direction: ltr or rtl")


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
    def render(doc: DocumentStructure, 
               include_styles: bool = True) -> str:
        """
        Render the structured document as HTML using natural flow layout.
        
        Args:
            doc: The document structure to render
            include_styles: Whether to include CSS styles
        """
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
                for block in page.text_blocks[:10]:  # Check more blocks
                    sample_text += block.content + " "
                    if len(sample_text) > 2000:  # Enough sample
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
        """Return CSS styles for flow-based document rendering."""
        # RTL-specific font stack
        if is_rtl:
            font_family = "'Amiri', 'Scheherazade New', 'Noto Naskh Arabic', 'Traditional Arabic', 'Arabic Typesetting', 'Segoe UI', Tahoma, sans-serif"
        else:
            font_family = "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
        
        # Base styles
        base_styles = f"""<style>
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
    
    /* Multi-column layout support */
    .page.multi-column {{
        column-gap: 2rem;
    }}
    .page.two-column {{ columns: 2; }}
    .page.three-column {{ columns: 3; }}
    
    /* Column breaks */
    .column-break {{
        break-after: column;
        column-break-after: always;
    }}"""
        
        # Continue with common styles
        common_styles = f"""
    
    /* Page header/footer components */
    .page-header {{
        font-size: 0.75rem;
        color: #888;
        text-align: {'left' if is_rtl else 'right'};
        margin-bottom: 20px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border-color);
        break-inside: avoid;
        column-break-inside: avoid;
        page-break-inside: avoid;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    
    .page-header-left {{
        text-align: left;
        flex: 1;
    }}
    
    .page-header-center {{
        text-align: center;
        flex: 1;
    }}
    
    .page-header-right {{
        text-align: right;
        flex: 1;
    }}

    .page-footer {{
        font-size: 0.75rem;
        color: #888;
        margin-top: 20px;
        padding-top: 10px;
        border-top: 1px solid var(--border-color);
        break-inside: avoid;
        column-break-inside: avoid;
        page-break-inside: avoid;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    
    .page-footer-left {{
        text-align: left;
        flex: 1;
    }}
    
    .page-footer-center {{
        text-align: center;
        flex: 1;
    }}
    
    .page-footer-right {{
        text-align: right;
        flex: 1;
    }}
    
    .page-number {{
        font-weight: 500;
        color: #666;
    }}"""
        
        base_styles += common_styles
        
        # Rest of the styles (RTL, text formatting, etc.)
        rest_styles = """
    
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
    .rtl {{
        direction: rtl;
        unicode-bidi: isolate;
    }}"""
        
        base_styles += rest_styles
        
        # Text styling and layout
        styling = """
    
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
    .strikethrough {{ text-decoration: line-through; }}
    .superscript {{ vertical-align: super; font-size: 0.75em; }}
    .subscript {{ vertical-align: sub; font-size: 0.75em; }}
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
    .list-wrapper.ltr-list {{
        direction: ltr;
        text-align: left;
        padding-left: 2rem;
        padding-right: 0;
    }}
    .list-wrapper.rtl-list {{
        direction: rtl;
        text-align: right;
        padding-right: 2rem;
        padding-left: 0;
    }}
    
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
    
    .table-caption, .caption {{
        font-style: italic;
        color: #666;
        margin: 0.5rem 0;
        text-align: center;
        font-weight: 500;
    }}"""
        
        base_styles += styling
        
        # Continue with remaining styles from the original method
        return base_styles + """
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
        width: 100%;  /* Fill the figure container */
        height: auto;  /* Preserve aspect ratio */
        margin: 0 auto;
        image-rendering: -webkit-optimize-contrast; /* Better rendering for crisp images */
        image-rendering: crisp-edges;
        object-fit: contain;  /* Never distort, always maintain aspect ratio */
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
    
    /* Hyperlinks */
    a {{
        color: #0066cc;
        text-decoration: none;
        border-bottom: 1px solid transparent;
        transition: border-color 0.2s;
    }}
    
    a:hover {{
        border-bottom-color: #0066cc;
    }}
    
    a.link-email {{
        color: #cc6600;
    }}
    
    a.link-internal {{
        color: #006633;
    }}
    
    /* Horizontal rules */
    hr.content-divider {{
        border: none;
        border-top: 2px solid var(--border-color);
        margin: 2rem 0;
        clear: both;
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
    
    /* Multi-column layout - fallback classes (dynamic styles preferred) */
    .has-multi-column {{
        column-count: 2;
        column-gap: 2rem;
        column-rule: 1px solid #e0e0e0;
        column-fill: balance; /* Balance content across columns */
    }}

    .has-multi-column-3 {{
        column-count: 3;
        column-gap: 2rem;
        column-rule: 1px solid #e0e0e0;
        column-fill: balance;
    }}
    
    .has-multi-column-4 {{
        column-count: 4;
        column-gap: 1.5rem;
        column-rule: 1px solid #e0e0e0;
        column-fill: balance;
    }}
    
    /* Inline multi-column sections - for embedded multi-column elements within single-column pages */
    .inline-multi-column {{
        margin: 1rem 0;
        padding: 1rem;
        column-gap: 2rem;
        column-rule: 1px solid #e0e0e0;
        column-fill: balance;
        break-inside: avoid-column;
        page-break-inside: avoid;
    }}
    
    .inline-multi-column > * {{
        break-inside: avoid-column;
        page-break-inside: avoid;
    }}
    
    /* For RTL multi-column, use column-fill and direction */
    [dir="rtl"] .has-multi-column,
    [dir="rtl"] .has-multi-column-3,
    [dir="rtl"] .has-multi-column-4 {{
        direction: rtl;
        column-fill: auto;
    }}
    
    @media print {{
        body {{ background: white; padding: 0; }}
        .document-container {{ box-shadow: none; }}
        .page {{ padding: 20px; }}
        /* Preserve columns in print */
        .has-multi-column, .has-multi-column-3, .has-multi-column-4 {{
            break-inside: avoid;
        }}
    }}
    
    @media (max-width: 900px) {{
        /* Reduce to 2 columns on tablets */
        .has-multi-column-3, .has-multi-column-4 {{ column-count: 2; }}
    }}
    
    @media (max-width: 600px) {{
        /* Single column on mobile */
        body {{ padding: 10px; }}
        .page {{ padding: 20px; }}
        .has-multi-column, .has-multi-column-3, .has-multi-column-4 {{ column-count: 1; }}
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
    def _render_page_header(page: PageContent) -> str:
        """Render robust page header with separate components for header text and page number."""
        if not page.header and not page.page_number_text:
            # Still show page number as fallback
            return f'<div class="page-header"><div class="page-header-right"><span class="page-number">Page {page.page_number}</span></div></div>'
        
        parts = ['<div class="page-header">']
        
        # Determine where page number should go
        page_num_position = page.page_number_position if hasattr(page, 'page_number_position') and page.page_number_position else None
        # Determine where header text should go
        header_pos = page.header_position if hasattr(page, 'header_position') and page.header_position else "center"
        
        # Left section
        parts.append('<div class="page-header-left">')
        if page_num_position == "header-left" and page.page_number_text:
            parts.append(f'<span class="page-number">{HTMLRenderer._escape(page.page_number_text)}</span>')
        elif page.header and header_pos == "left":
            parts.append(HTMLRenderer._escape(page.header))
        parts.append('</div>')
        
        # Center section
        parts.append('<div class="page-header-center">')
        if page_num_position == "header-center" and page.page_number_text:
            parts.append(f'<span class="page-number">{HTMLRenderer._escape(page.page_number_text)}</span>')
        elif page.header and header_pos == "center":
            parts.append(HTMLRenderer._escape(page.header))
        parts.append('</div>')
        
        # Right section
        parts.append('<div class="page-header-right">')
        if page_num_position == "header-right" and page.page_number_text:
            parts.append(f'<span class="page-number">{HTMLRenderer._escape(page.page_number_text)}</span>')
        elif page.header and header_pos == "right":
            parts.append(HTMLRenderer._escape(page.header))
        elif not page.page_number_text:
            # Default: show numeric page number on right
            parts.append(f'<span class="page-number">Page {page.page_number}</span>')
        parts.append('</div>')
        
        parts.append('</div>')
        return '\n'.join(parts)
    
    @staticmethod
    def _render_page_footer(page: PageContent) -> str:
        """Render robust page footer with separate components."""
        if not page.footer and not (hasattr(page, 'page_number_position') and page.page_number_position and 'footer' in page.page_number_position):
            return ""
        
        parts = ['<div class="page-footer">']
        
        # Determine where page number should go
        page_num_position = page.page_number_position if hasattr(page, 'page_number_position') and page.page_number_position else None
        # Determine where footer text should go
        footer_pos = page.footer_position if hasattr(page, 'footer_position') and page.footer_position else "center"
        
        # Left section
        parts.append('<div class="page-footer-left">')
        if page_num_position == "footer-left" and page.page_number_text:
            parts.append(f'<span class="page-number">{HTMLRenderer._escape(page.page_number_text)}</span>')
        elif page.footer and footer_pos == "left":
            parts.append(HTMLRenderer._escape(page.footer))
        parts.append('</div>')
        
        # Center section
        parts.append('<div class="page-footer-center">')
        if page_num_position == "footer-center" and page.page_number_text:
            parts.append(f'<span class="page-number">{HTMLRenderer._escape(page.page_number_text)}</span>')
        elif page.footer and footer_pos == "center":
            parts.append(HTMLRenderer._escape(page.footer))
        parts.append('</div>')
        
        # Right section
        parts.append('<div class="page-footer-right">')
        if page_num_position == "footer-right" and page.page_number_text:
            parts.append(f'<span class="page-number">{HTMLRenderer._escape(page.page_number_text)}</span>')
        elif page.footer and footer_pos == "right":
            parts.append(HTMLRenderer._escape(page.footer))
        parts.append('</div>')
        
        parts.append('</div>')
        return '\n'.join(parts)
    
    @staticmethod
    def _deduplicate_header_footer(page: PageContent) -> PageContent:
        """Remove header/footer text from text_blocks if they appear there."""
        if not page.text_blocks:
            return page
        
        # Build list of strings to remove (header, footer, page number text)
        to_remove = []
        if page.header:
            to_remove.append(page.header.strip())
        if page.footer:
            to_remove.append(page.footer.strip())
        if page.page_number_text:
            to_remove.append(page.page_number_text.strip())
        
        if not to_remove:
            return page
        
        # Remove text blocks that match or are contained in header/footer
        filtered_blocks = []
        for block in page.text_blocks:
            content = block.content.strip()
            should_keep = True
            
            for remove_str in to_remove:
                # Exact match
                if content == remove_str:
                    should_keep = False
                    break
                # Block content is substring of header/footer (partial match)
                elif remove_str and content in remove_str and len(content) > 10:
                    should_keep = False
                    break
                # Header/footer is substring of block content
                elif remove_str and remove_str in content and len(remove_str) > 10:
                    should_keep = False
                    break
                # Check for similarity (80%+ similar)
                elif remove_str and content and HTMLRenderer._similarity(content, remove_str) > 0.8:
                    should_keep = False
                    break
            
            if should_keep:
                filtered_blocks.append(block)
        
        page.text_blocks = filtered_blocks
        return page
    
    @staticmethod
    def _similarity(str1: str, str2: str) -> float:
        """Calculate similarity ratio between two strings (0.0 to 1.0)."""
        if not str1 or not str2:
            return 0.0
        
        # Simple character-based similarity
        set1 = set(str1.lower())
        set2 = set(str2.lower())
        
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    @staticmethod
    def _deduplicate_images(page: PageContent) -> PageContent:
        """Remove duplicate images from the page based on description similarity.
        
        Since we no longer use bbox coordinates (for OCR'd PDFs), we deduplicate
        based on description content similarity.
        """
        if not page.images or len(page.images) <= 1:
            return page
        
        unique_images = []
        seen_descriptions = set()
        
        for img in page.images:
            # Skip generic/auto-generated descriptions
            if not img.description or "extracted by Mistral OCR" in img.description:
                unique_images.append(img)
                continue
            
            # Normalize description for comparison
            normalized_desc = img.description.lower().strip()
            
            # Check if we've seen this exact description
            if normalized_desc in seen_descriptions:
                # Likely a duplicate - skip it
                continue
            
            # Not a duplicate - add it
            unique_images.append(img)
            seen_descriptions.add(normalized_desc)
        
        page.images = unique_images
        return page
    
    @staticmethod
    def _render_page(page: PageContent, is_rtl: bool = False) -> str:
        """Render a single page to HTML using natural flow layout."""
        # Remove duplicate header/footer from text_blocks
        page = HTMLRenderer._deduplicate_header_footer(page)
        
        parts = []
        page_class = "page"
        content_class = "page-content"

        # Check if entire page is English by analyzing all text content
        page_text = " ".join(block.content for block in page.text_blocks)
        is_english_page = HTMLRenderer._detect_english_content(page_text)

        # Override RTL for English pages
        page_dir = "ltr" if is_english_page else (page.page_direction if hasattr(page, 'page_direction') else ("rtl" if is_rtl else "ltr"))

        # Add multi-column class to content, not page container
        if page.has_multi_column:
            if page.column_count and page.column_count == 4:
                content_class += " has-multi-column-4"
            elif page.column_count and page.column_count == 3:
                content_class += " has-multi-column-3"
            else:
                content_class += " has-multi-column"
            
            # Add dynamic column styling
            if page.column_count and page.column_count > 1:
                column_styles = f"column-count: {page.column_count};"
                if page.column_gap:
                    column_styles += f" column-gap: {page.column_gap}pt;"
                # Store for later use in content div
                page._column_styles = column_styles
            else:
                page._column_styles = None

        # Add english-text class for English pages
        if is_english_page:
            page_class += " english-text"
        
        # Build page style with dimensions if available
        page_style = "position: relative;"
        if page.width_pts and page.height_pts:
            page_style += f" width: {page.width_pts}pt; height: {page.height_pts}pt;"
        if page.background_color:
            page_style += f" background-color: {page.background_color};"

        parts.append(f'<div class="{page_class}" id="page-{page.page_number}" style="{page_style}" dir="{page_dir}">')

        # Render robust header with page number support
        header_html = HTMLRenderer._render_page_header(page)
        if header_html:
            parts.append(header_html)

        # Wrap content in a container with multi-column class if needed
        content_style = ""
        if hasattr(page, '_column_styles') and page._column_styles:
            content_style = f' style="{page._column_styles}"'
        parts.append(f'<div class="{content_class}"{content_style}>')
        
        # Combine all elements and sort by reading_order and column_number
        elements = []
        fallback_order = 0
        
        # Add text blocks
        for block in page.text_blocks:
            elements.append({
                'type': 'text',
                'column': getattr(block, 'column_number', None) or 1,
                'order': getattr(block, 'reading_order', None) or fallback_order,
                'content': block
            })
            fallback_order += 1
        
        # Add tables
        for table in page.tables:
            elements.append({
                'type': 'table',
                'column': getattr(table, 'column_number', None) or 1,
                'order': getattr(table, 'reading_order', None) or fallback_order,
                'content': table
            })
            fallback_order += 1
        
        # Add images
        for image in page.images:
            elements.append({
                'type': 'image',
                'column': getattr(image, 'column_number', None) or 1,
                'order': getattr(image, 'reading_order', None) or fallback_order,
                'content': image
            })
            fallback_order += 1
        
        # Sort by column (respecting RTL), then reading order
        if page.has_multi_column and page.column_count and page.column_count > 1:
            # For RTL: higher column numbers come first
            if page_dir == "rtl" and not is_english_page:
                elements.sort(key=lambda e: (-e['column'], e['order']))
            else:
                # For LTR: lower column numbers come first
                elements.sort(key=lambda e: (e['column'], e['order']))
        else:
            # Single column: just use reading order
            elements.sort(key=lambda e: e['order'])
        
        # Render elements in order, handling multi-column groups and list grouping
        footnotes = []  # Collect footnotes for end of page
        i = 0
        while i < len(elements):
            element = elements[i]
            
            # Check if this element starts a multi-column group
            group_id = getattr(element['content'], 'multi_column_group_id', None)
            
            if group_id:
                # Collect all consecutive elements with the same group_id
                group_elements = [element]
                j = i + 1
                while j < len(elements):
                    next_group_id = getattr(elements[j]['content'], 'multi_column_group_id', None)
                    if next_group_id == group_id:
                        group_elements.append(elements[j])
                        j += 1
                    else:
                        break
                
                # Determine column count from the group
                max_col = max((getattr(e['content'], 'column_number', None) or 1) for e in group_elements)
                
                # Render the group with multi-column layout
                parts.append(f'<div class="inline-multi-column" style="column-count: {max_col}; column-gap: 2rem;">')
                
                for grp_elem in group_elements:
                    if grp_elem['type'] == 'text':
                        block = grp_elem['content']
                        if block.block_type == 'list_item':
                            # Handle list items within group
                            list_items = [block]
                            # Don't look ahead for more list items outside this loop
                            parts.append(HTMLRenderer._render_list(list_items))
                        elif block.block_type != 'footnote':
                            parts.append(HTMLRenderer._render_text_block(block))
                    elif grp_elem['type'] == 'table':
                        parts.append(HTMLRenderer._render_table(grp_elem['content']))
                    elif grp_elem['type'] == 'image':
                        parts.append(HTMLRenderer._render_image(grp_elem['content']))
                
                parts.append('</div>')
                i = j  # Skip past all elements we just processed
                continue
            
            if element['type'] == 'text':
                block = element['content']
                
                # Collect footnotes separately
                if block.block_type == 'footnote':
                    footnotes.append(block)
                    i += 1
                    continue
                
                # Handle list items - group consecutive ones
                if block.block_type == 'list_item':
                    list_items = [block]
                    j = i + 1
                    # Collect consecutive list items (but not those in a multi-column group)
                    while j < len(elements):
                        next_elem = elements[j]
                        # Stop if we hit a multi-column group or non-list item
                        if getattr(next_elem['content'], 'multi_column_group_id', None):
                            break
                        if next_elem['type'] == 'text' and next_elem['content'].block_type == 'list_item':
                            list_items.append(next_elem['content'])
                            j += 1
                        else:
                            break
                    
                    # Render as a proper list
                    parts.append(HTMLRenderer._render_list(list_items))
                    i = j  # Skip the items we just processed
                else:
                    parts.append(HTMLRenderer._render_text_block(block))
                    i += 1
                    
            elif element['type'] == 'table':
                parts.append(HTMLRenderer._render_table(element['content']))
                i += 1
            elif element['type'] == 'image':
                parts.append(HTMLRenderer._render_image(element['content']))
                i += 1
            else:
                i += 1
        
        # Render footnotes at the end if any
        if footnotes:
            parts.append('<div class="footnotes-section">')
            for footnote in footnotes:
                content = HTMLRenderer._escape(footnote.content)
                parts.append(f'<div class="footnote">{content}</div>')
            parts.append('</div>')
        
        parts.append('</div>')  # Close page-content
        
        # Render robust footer
        footer_html = HTMLRenderer._render_page_footer(page)
        if footer_html:
            parts.append(footer_html)
        
        parts.append("</div>")
        return "\n".join(parts)
    
    @staticmethod
    def _parse_inline_sublist(content: str) -> tuple[str, list[str]]:
        """
        Parse inline sub-bullets from list item content.
        
        E.g., "Main text : - item1 - item2 - item3" 
        Returns: ("Main text :", ["item1", "item2", "item3"])
        
        Handles parentheses: "text : - item (sub - text) - item2"
        Should split on " - " but NOT when inside parentheses.
        
        Args:
            content: The list item content
            
        Returns:
            Tuple of (main_content, sub_items) where sub_items is empty if no sub-list found
        """
        import re
        
        # Look for pattern: text ending with colon, followed by dash-prefixed items
        if ':' not in content and '：' not in content:
            return content, []
        
        # Find the colon position
        colon_idx = content.find(':')
        if colon_idx == -1:
            colon_idx = content.find('：')
        
        if colon_idx == -1:
            return content, []
        
        main_text = content[:colon_idx + 1].strip()
        remaining = content[colon_idx + 1:].strip()
        
        # Only proceed if remaining starts with a dash (indicating sub-list)
        if not remaining.startswith('-'):
            return content, []
        
        # Smart split: split on " - " but NOT when inside parentheses
        sub_items = []
        current_item = ""
        paren_depth = 0
        i = 0
        
        while i < len(remaining):
            char = remaining[i]
            
            if char == '(':
                paren_depth += 1
                current_item += char
            elif char == ')':
                paren_depth -= 1
                current_item += char
            elif char == '-' and paren_depth == 0:
                # Check if this is a list separator (preceded by space)
                if i > 0 and remaining[i-1].isspace():
                    # This is a separator - save current item and start new one
                    item = current_item.strip().strip('-').strip()
                    if item:
                        sub_items.append(item)
                    current_item = ""
                    i += 1  # Skip the dash
                    # Skip following whitespace
                    while i < len(remaining) and remaining[i].isspace():
                        i += 1
                    continue
                else:
                    # Dash is part of content
                    current_item += char
            else:
                current_item += char
            
            i += 1
        
        # Add the last item
        item = current_item.strip().strip('-').strip()
        if item:
            sub_items.append(item)
        
        # Only return sub-list if we found multiple items (at least 2)
        if len(sub_items) >= 2:
            return main_text, sub_items
        
        # No valid sub-list found
        return content, []
    
    @staticmethod
    def _render_list(list_items: list[TextBlock]) -> str:
        """Render a group of consecutive list items as a properly nested HTML list."""
        if not list_items:
            return ""
        
        # Detect overall direction
        english_count = sum(1 for item in list_items if HTMLRenderer._detect_english_content(item.content))
        arabic_count = sum(1 for item in list_items if HTMLRenderer._has_arabic(item.content))
        list_classes = ["list-wrapper"]
        dir_attr = ""
        if english_count > arabic_count and english_count > 0:
            list_classes.append("ltr-list")
            dir_attr = ' dir="ltr"'
        elif arabic_count > english_count and arabic_count > 0:
            list_classes.append("rtl-list")
            dir_attr = ' dir="rtl"'
        
        # Build nested list structure based on list_level
        parts = []
        current_level = 0
        
        for item in list_items:
            item_level = getattr(item, 'list_level', None) or 1
            
            # Check for inline sub-list in content
            main_content, sub_items = HTMLRenderer._parse_inline_sublist(item.content)
            escaped_main = HTMLRenderer._escape(main_content)
            
            # Detect item direction
            item_dir = ""
            if HTMLRenderer._detect_english_content(item.content):
                item_dir = ' dir="ltr"'
            elif HTMLRenderer._has_arabic(item.content):
                item_dir = ' dir="rtl"'
            
            # Open lists as needed to reach target level
            while current_level < item_level:
                if current_level == 0:
                    # First level gets the wrapper class
                    parts.append(f'<ul class="{" ".join(list_classes)}"{dir_attr}>')
                else:
                    # Nested levels are plain <ul>
                    parts.append('<ul>')
                current_level += 1
            
            # Close lists as needed to reach target level
            while current_level > item_level:
                parts.append('</ul>')
                current_level -= 1
            
            # Add the list item with potential sub-list
            if sub_items:
                # Item has inline sub-list - render with nested <ul>
                parts.append(f'<li{item_dir}>')
                parts.append(escaped_main)
                parts.append('<ul>')
                for sub_item in sub_items:
                    escaped_sub = HTMLRenderer._escape(sub_item)
                    parts.append(f'<li{item_dir}>{escaped_sub}</li>')
                parts.append('</ul>')
                parts.append('</li>')
            else:
                # Regular list item
                parts.append(f'<li{item_dir}>{escaped_main}</li>')
        
        # Close all remaining open lists
        while current_level > 0:
            parts.append('</ul>')
            current_level -= 1
        
        return "\n".join(parts)
    
    @staticmethod
    def _validate_color(color: Optional[str]) -> Optional[str]:
        """Validate and sanitize hex color values to prevent CSS injection.
        
        Returns:
            Valid hex color or None if invalid
        """
        if not color:
            return None
        
        # Strip whitespace
        color = color.strip()
        
        # Check if it's a valid hex color (#RGB or #RRGGBB)
        import re
        if re.match(r'^#[0-9A-Fa-f]{3}$', color) or re.match(r'^#[0-9A-Fa-f]{6}$', color):
            return color.upper()
        
        # Check for named colors (basic set)
        valid_names = {
            'black', 'white', 'red', 'green', 'blue', 'yellow', 'cyan', 'magenta',
            'gray', 'grey', 'orange', 'purple', 'pink', 'brown', 'transparent'
        }
        if color.lower() in valid_names:
            return color.lower()
        
        # Invalid color - return None
        return None
    
    @staticmethod
    def _validate_url(url: Optional[str]) -> Optional[str]:
        """Validate and sanitize URLs to prevent XSS.
        
        Returns:
            Valid URL or None if invalid
        """
        if not url:
            return None
        
        url = url.strip()
        
        # Allow http, https, mailto, and internal anchors
        import re
        if re.match(r'^(https?://|mailto:|#)', url, re.IGNORECASE):
            # Basic XSS prevention - reject javascript: and data: schemes
            if re.match(r'^(javascript|data):', url, re.IGNORECASE):
                return None
            return url
        
        return None
    
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
    def _render_text_spans(spans: list) -> str:
        """Render a list of TextSpan objects as HTML with inline formatting."""
        parts = []
        for span in spans:
            text = HTMLRenderer._escape(span.text)
            
            # Build inline styles for this span
            styles = []
            if span.font_size:
                styles.append(f"font-size: {span.font_size}pt")
            if span.font_family:
                styles.append(f"font-family: {span.font_family}, sans-serif")
            
            # Validate colors before injection
            text_color = HTMLRenderer._validate_color(span.text_color)
            if text_color:
                styles.append(f"color: {text_color}")
            bg_color = HTMLRenderer._validate_color(span.background_color)
            if bg_color:
                styles.append(f"background-color: {bg_color}")
            
            # Build classes for styling
            classes = []
            if span.bold:
                classes.append("bold")
            if span.italic:
                classes.append("italic")
            if span.underline:
                classes.append("underline")
            if span.strikethrough:
                classes.append("strikethrough")
            
            # Handle superscript/subscript
            if span.superscript:
                text = f'<sup>{text}</sup>'
            elif span.subscript:
                text = f'<sub>{text}</sub>'
            
            # Wrap in span if we have styles or classes
            if styles or classes:
                style_attr = f' style="{"; ".join(styles)}"' if styles else ""
                class_attr = f' class="{" ".join(classes)}"' if classes else ""
                text = f'<span{class_attr}{style_attr}>{text}</span>'
            
            parts.append(text)
        
        return ''.join(parts)
    
    @staticmethod
    def _render_text_block(block: TextBlock) -> str:
        """Render a text block to HTML using natural flow layout."""
        # Skip empty content blocks
        if not block.content or not block.content.strip():
            # For horizontal_rule, render despite empty content
            if block.block_type == "horizontal_rule":
                return '<hr class="content-divider" />'
            return ""  # Skip empty blocks
        
        # Handle rich text spans if present
        if hasattr(block, 'spans') and block.spans:
            content = HTMLRenderer._render_text_spans(block.spans)
        else:
            content = HTMLRenderer._escape(block.content)
        
        # Build inline style for typography
        inline_styles = []
        
        # Font and typography (add fallback fonts)
        if block.font_size:
            inline_styles.append(f"font-size: {block.font_size}pt")
        if block.font_family:
            inline_styles.append(f"font-family: {block.font_family}, sans-serif")
        if block.font_weight and block.font_weight != 400:
            inline_styles.append(f"font-weight: {block.font_weight}")
        if block.line_height:
            inline_styles.append(f"line-height: {block.line_height}")
        if block.letter_spacing:
            inline_styles.append(f"letter-spacing: {block.letter_spacing}em")
        
        # Colors (with validation)
        text_color = HTMLRenderer._validate_color(block.text_color)
        if text_color:
            inline_styles.append(f"color: {text_color}")
        bg_color = HTMLRenderer._validate_color(block.background_color)
        if bg_color:
            inline_styles.append(f"background-color: {bg_color}")
        
        # Spacing and indentation (relative units)
        if block.indent_left:
            inline_styles.append(f"margin-left: {block.indent_left}em")
        if block.indent_right:
            inline_styles.append(f"margin-right: {block.indent_right}em")
        if block.indent_first_line:
            inline_styles.append(f"text-indent: {block.indent_first_line}em")
        if block.spacing_before:
            inline_styles.append(f"margin-top: {block.spacing_before}em")
        if block.spacing_after:
            inline_styles.append(f"margin-bottom: {block.spacing_after}em")
        
        # Text alignment
        if block.text_align:
            inline_styles.append(f"text-align: {block.text_align}")
        
        style_attr = f' style="{"; ".join(inline_styles)}"' if inline_styles else ""
        
        # Build classes
        classes = []
        if block.style:
            classes.append(block.style)
        
        # Determine text direction
        dir_attr = ""
        if block.text_direction and block.text_direction != "auto":
            dir_attr = f' dir="{block.text_direction}"'
        elif HTMLRenderer._detect_english_content(block.content):
            classes.append("ltr")
            dir_attr = ' dir="ltr"'
        elif HTMLRenderer._has_arabic(block.content):
            classes.append("rtl")
            dir_attr = ' dir="rtl"'
        
        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        
        # Render based on block type
        if block.block_type == "heading":
            level = min(max(block.level or 1, 1), 6)
            return f"<h{level}{class_attr}{dir_attr}{style_attr}>{content}</h{level}>"
        
        elif block.block_type == "paragraph":
            return f"<p{class_attr}{dir_attr}{style_attr}>{content}</p>"
        
        elif block.block_type == "list_item":
            # This shouldn't be called directly anymore - lists are grouped
            # But keep for backwards compatibility
            return f"<li>{content}</li>"
        
        elif block.block_type == "caption":
            return f'<p class="caption">{content}</p>'
        
        elif block.block_type == "footnote":
            # Footnotes are now grouped at page end, but keep for fallback
            return f'<div class="footnote">{content}</div>'
        
        elif block.block_type == "quote":
            return f"<blockquote>{content}</blockquote>"
        
        elif block.block_type == "code":
            return f"<pre><code>{content}</code></pre>"
        
        elif block.block_type == "hyperlink":
            # Render hyperlink with validation
            validated_url = HTMLRenderer._validate_url(block.url)
            if validated_url:
                link_class = f'link-{block.link_type}' if block.link_type else 'link-url'
                return f'<a href="{validated_url}" class="{link_class}" target="_blank" rel="noopener noreferrer"{dir_attr}>{content}</a>'
            else:
                # Invalid URL - render as plain text
                return f"<span{class_attr}{dir_attr}{style_attr}>{content}</span>"
        
        elif block.block_type == "horizontal_rule":
            return '<hr class="content-divider" />'
        
        elif block.block_type == "equation":
            # Render LaTeX equations with MathJax
            # Don't escape the content - it's already LaTeX
            raw_content = block.content  # Use raw content, not escaped
            
            # Clean equation content (remove Arabic text captions)
            cleaned_equation, arabic_caption = HTMLRenderer._clean_equation_content(raw_content)
            
            # If no real equation content (just Arabic label), render as styled paragraph
            if not cleaned_equation or len(cleaned_equation.strip()) < 3:
                return f'<p class="equation-caption" dir="rtl">{arabic_caption}</p>'
            
            # Check if content already has delimiters
            has_display_delimiters = cleaned_equation.strip().startswith('\\[') or cleaned_equation.strip().startswith('$$')
            has_inline_delimiters = cleaned_equation.strip().startswith('\\(') or cleaned_equation.strip().startswith('$')
            
            result_parts = []
            
            if block.is_display_math:
                # Display mode: centered, on its own line
                if has_display_delimiters:
                    result_parts.append(f'<div class="equation">{cleaned_equation}</div>')
                else:
                    result_parts.append(f'<div class="equation">\\[{cleaned_equation}\\]</div>')
            else:
                # Inline mode
                if has_inline_delimiters:
                    result_parts.append(f'<span class="equation-inline">{cleaned_equation}</span>')
                else:
                    result_parts.append(f'<span class="equation-inline">\\({cleaned_equation}\\)</span>')
            
            # Add Arabic caption as separate paragraph if present
            if arabic_caption:
                result_parts.append(f'<p class="equation-caption" dir="rtl">{arabic_caption}</p>')
            
            return '\n'.join(result_parts)
        
        return f"<p>{content}</p>"
    
    @staticmethod
    def _render_table(table: Table) -> str:
        """Render a table to HTML using natural flow layout."""
        parts = []
        
        # Detect if table contains Arabic text
        is_rtl = False
        if table.caption and HTMLRenderer._has_arabic(table.caption):
            is_rtl = True
        elif table.headers:
            for header in table.headers:
                if HTMLRenderer._has_arabic(header.content):
                    is_rtl = True
                    break
        
        dir_attr = 'rtl' if is_rtl else 'ltr'
        
        if table.caption:
            parts.append(f'<p class="table-caption" dir="{dir_attr}">{HTMLRenderer._escape(table.caption)}</p>')
        
        parts.append(f'<table dir="{dir_attr}">')
        
        if table.headers:
            parts.append("<thead><tr>")
            for header in table.headers:
                parts.append(HTMLRenderer._render_table_cell(header, is_header=True))
            parts.append("</tr></thead>")
        
        parts.append("<tbody>")
        for row in table.rows:
            parts.append("<tr>")
            for cell in row:
                parts.append(HTMLRenderer._render_table_cell(cell, is_header=False))
            parts.append("</tr>")
        parts.append("</tbody>")
        parts.append("</table>")
        
        return "\n".join(parts)
    
    @staticmethod
    def _render_table_cell(cell: TableCell, is_header: bool = False) -> str:
        """Render a single table cell with simple markup."""
        style_attr = ""
        
        # Spanning attributes
        attrs = []
        if cell.row_span > 1:
            attrs.append(f'rowspan="{cell.row_span}"')
        if cell.col_span > 1:
            attrs.append(f'colspan="{cell.col_span}"')
        
        attr_str = " " + " ".join(attrs) if attrs else ""
        
        # Use th or td based on is_header or cell.is_header
        tag = "th" if (is_header or cell.is_header) else "td"
        content = HTMLRenderer._escape(cell.content)
        
        return f"<{tag}{attr_str}{style_attr}>{content}</{tag}>"
    
    @staticmethod
    def _render_image(image: Image) -> str:
        """Render an image to HTML using natural flow layout."""
        # Simple alignment based on alignment field (not bbox)
        alignment = getattr(image, 'alignment', 'center')
        
        # Build inline styles for flow layout
        styles = []
        
        # Width: let images scale naturally, but set max-width
        styles.append("max-width: 80%")
        
        # Alignment
        if alignment == 'left':
            styles.append("margin-left: 0; margin-right: auto")
        elif alignment == 'right':
            styles.append("margin-left: auto; margin-right: 0")
        elif alignment == 'full-width':
            styles.append("max-width: 100%; margin: 1rem 0")
        else:  # default to center
            styles.append("margin: 1.5rem auto")
        
        style = "; ".join(styles)
        
        parts = [f'<figure class="image-block" style="{style}">']
        
        if image.image_data:
            # We have actual image data - normalize the data URI
            src = normalise_data_uri(image.image_data)
            # Don't add width/height attributes - let CSS handle sizing to preserve aspect ratio
            parts.append(f'<img src="{src}" '
                        f'alt="{HTMLRenderer._escape(image.description)}" '
                        f'title="{HTMLRenderer._escape(image.description)}" '
                        f'style="width: 100%; height: auto;" />')
        else:
            # Fallback to placeholder
            parts.append(f'<div class="image-placeholder">[{image.image_type.title()}: {HTMLRenderer._escape(image.description)}]</div>')
        
        if image.caption:
            parts.append(f"<figcaption>{HTMLRenderer._escape(image.caption)}</figcaption>")
        parts.append("</figure>")
        return "\n".join(parts)


# =============================================================================
# IMAGE EXTRACTOR
# =============================================================================

class ImageExtractor:
    """Extracts images from PDF pages using PyMuPDF based on bounding box coordinates."""
    
    def __init__(self, pdf_path: str, dpi: int = 300):
        """Initialize the extractor with a PDF file. Default DPI increased to 300 for higher fidelity."""
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
            for image in page.images:
                try:
                    image_data = self.extract_image(
                        page_num=page.page_number,
                        bbox_top=image.bbox_top,
                        bbox_left=image.bbox_left,
                        bbox_width=image.bbox_width,
                        bbox_height=image.bbox_height
                    )
                    image.image_data = image_data
                    if image_data:
                        logger.info(f"Extracted {image.image_type} from page {page.page_number}")
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
        
        # Token usage tracking
        self._total_input_tokens = 0
        self._total_output_tokens = 0
    
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
        total_text_chars = sum(len(block.content) for block in page.text_blocks)
        total_blocks = len(page.text_blocks)
        total_tables = len(page.tables)
        total_images = len(page.images)
        
        # Calculate table cell count
        table_cells = sum(
            len(table.headers) + sum(len(row) for row in table.rows)
            for table in page.tables
        )
        
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
            "multi_column": page.has_multi_column,
        }
    
    def _extract_page_range(self, uploaded_file: types.File, start_page: int, end_page: int) -> list[PageContent]:
        """Extract content from a specific range of pages."""
        prompt = f"""Extract content from pages {start_page} to {end_page} of this PDF document.

IMPORTANT: Only process pages {start_page} through {end_page}. Skip all other pages.

For each page in this range:
1. Set the correct page_number (starting from {start_page})
2. Extract the HEADER text if present (usually at the top of the page - may contain page numbers, chapter titles, section names)
   - Set header_position=\"left\", \"center\", or \"right\" based on where header text appears horizontally
3. Extract the FOOTER text if present (usually at the bottom of the page - may contain page numbers, citations, document info)
   - Set footer_position=\"left\", \"center\", or \"right\" based on where footer text appears horizontally
4. If page number appears separately from header/footer text:
   - Extract it in page_number_text field
   - Set page_number_position to one of: \"header-left\", \"header-center\", \"header-right\", \"footer-left\", \"footer-center\", \"footer-right\"
5. CRITICAL: DO NOT duplicate header/footer text in text_blocks - if you extract header=\"Title\", do NOT include \"Title\" as a text_block
6. Extract all text blocks with semantic types (heading, paragraph, list_item, equation, etc.)
   - CRITICAL: For EVERY SINGLE text block, you MUST provide BOUNDING BOX coordinates as percentages (0-100):
     * bbox_top: distance from top of page to top of text block (REQUIRED, 0-100)
     * bbox_left: distance from left of page to left of text block (REQUIRED, 0-100)
     * bbox_width: width of the text block (REQUIRED, 0-100)
     * bbox_height: height of the text block (REQUIRED, 0-100)
   - These coordinates are MANDATORY for proper rendering, not optional
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
   - CRITICAL: Avoid duplicate images - if same image appears multiple times, extract once
   - Use bbox positions to distinguish different images
   - Provide BOUNDING BOX coordinates as percentages (0-100) of the page:
     * bbox_top: distance from top of page
     * bbox_left: distance from left of page  
     * bbox_width: width of the image
     * bbox_height: height of the image
10. For MULTI-COLUMN LAYOUTS (CRITICAL DETECTION):
   - ALWAYS distinguish between TWO types of multi-column layouts:
   
   TYPE 1: FULL-PAGE MULTI-COLUMN (entire page is multi-column)
   - Common in: academic papers, newspapers, magazines where ENTIRE page has columns
   - Look for text flowing in parallel vertical sections across the whole page
   - If detected:
     * Set has_multi_column=true
     * Set column_count (2, 3, or more)
     * Set column_gap (gap width in points, typically 20-40)
     * For ALL text_blocks, tables, images: set column_number (1, 2, 3, etc.)
     * CRITICAL: Ensure ALL pages with same layout have SAME column_count
     * Reading order MUST follow column flow (top-to-bottom within each column)
   
   TYPE 2: INLINE MULTI-COLUMN SECTION (embedded multi-column element in single-column page)
   - Common in: lists of items, contact info, reference lists embedded in otherwise single-column text
   - Example: A page with regular single-column paragraphs, but ONE section (like a list) in 2 columns
   - If detected:
     * Set has_multi_column=FALSE for the page (page is single-column overall)
     * For elements in the inline multi-column section ONLY:
       - Set multi_column_group_id="group1" (or "group2", "group3" for multiple inline sections)
       - Set column_number (1, 2, etc.) for elements within that group
     * Elements outside the group should NOT have multi_column_group_id
   
   - Ensure bbox_left positions distinguish columns clearly:
     * 2 columns: column 1 (0-48%), column 2 (52-100%)
     * 3 columns: column 1 (0-32%), column 2 (34-66%), column 3 (68-100%)
   - CRITICAL: For LTR documents, extract columns LEFT-TO-RIGHT
   - CRITICAL: For RTL documents, extract columns RIGHT-TO-LEFT
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
                
                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=ChunkExtraction.model_json_schema(),
                        system_instruction=(
                            f"You are an expert OCR and document analysis system extracting pages {start_page}-{end_page} only. "
                            "Extract page headers and footers (usually contain page numbers, titles, or citations). "
                            "OCR all text content including tables. "
                            "PRESERVE NUMERAL SYSTEMS: If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), keep them exactly - do NOT convert to Western numerals (0123456789). "
                            "TRANSCRIBE mathematical equations EXACTLY as written - do NOT solve, simplify, or manipulate them. "
                            "Extract equations as LaTeX in 'equation' blocks preserving the exact notation from the PDF. "
                            "For SUPERSCRIPTS/SUBSCRIPTS: Use ^{} and _{} in LaTeX (e.g., x^{2}, H_{2}O). "
                            "For NUMBERED EQUATIONS: Extract equation number in equation_number field. "
                            "For NESTED LISTS: Set list_level (1=top, 2=nested, etc.) to preserve hierarchy. "
                            "For MERGED TABLE CELLS: Set row_span and col_span appropriately. "
                            "For MULTI-COLUMN LAYOUTS in LTR docs: Extract left-to-right column order. For RTL docs: right-to-left. "
                            "For MIXED RTL/LTR TEXT: Set text_direction on individual text blocks. "
                            "For WATERMARKS: Ignore decorative watermarks like 'DRAFT', 'CONFIDENTIAL'. "
                            "For EVERY element (text blocks, tables, images), provide bbox coordinates (top, left, width, height) as percentages. "
                            "CRITICAL BBOX RULES: ALWAYS measure bbox_left from the PHYSICAL LEFT EDGE of the page (0% = left edge, 100% = right edge). "
                            "This applies regardless of text direction (RTL or LTR). For Arabic/Hebrew RTL text that appears on the right side of the page, bbox_left should be 70-90%, NOT 10-30%. "
                            "For charts, graphs, diagrams, and figures provide accurate bounding box coordinates as percentages. "
                            "For tables, also provide bbox coordinates for proper ordering. "
                            "CRITICAL: Ensure all JSON strings are properly escaped, especially quotes and special characters."
                        ),
                        media_resolution=self._get_media_resolution(),
                        max_output_tokens=self.config.max_output_tokens,
                        temperature=temperature,
                    ),
                )
                
                chunk = ChunkExtraction.model_validate_json(response.text)
                
                # Track token usage
                if hasattr(response, 'usage_metadata'):
                    self._total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0)
                    self._total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0)
                
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
        
        # Estimate cost and time
        cost_estimate = self._estimate_cost(total_pages)
        logger.info(f"Starting extraction of {total_pages} pages (estimated ${cost_estimate['estimated_cost_usd']} USD)")
        
        all_pages: list[PageContent] = []
        chunk_size = self.config.pages_per_chunk
        start_time = time.time()

        # Build list of (chunk_idx, start, end) tuples
        chunk_ranges = [
            (idx, s, min(s + chunk_size - 1, total_pages))
            for idx, s in enumerate(range(1, total_pages + 1, chunk_size), 1)
        ]
        total_chunks = len(chunk_ranges)
        logger.info(
            f"Processing {total_pages} pages in {total_chunks} chunks "
            f"({chunk_size} pages/chunk, {self.config.parallel_chunks} concurrent workers)"
        )

        def _fetch_chunk(chunk_idx: int, start: int, end: int):
            """Worker: extract one chunk and return (start, pages_list)."""
            try:
                pages = self._extract_page_range(uploaded_file, start, end)
                # Normalise page numbers
                for i, page in enumerate(pages):
                    expected = start + i
                    if page.page_number != expected:
                        page.page_number = expected
                logger.info(f"Chunk {chunk_idx}/{total_chunks} done: pages {start}-{end}")
                return start, pages
            except Exception as exc:
                logger.error(f"Failed to extract pages {start}-{end}: {exc}")
                placeholders = [
                    PageContent(
                        page_number=p,
                        text_blocks=[TextBlock(
                            block_type="paragraph",
                            content=f"[Page {p} extraction failed: {exc}]"
                        )]
                    )
                    for p in range(start, end + 1)
                ]
                return start, placeholders

        from concurrent.futures import ThreadPoolExecutor as _TPE
        with _TPE(max_workers=self.config.parallel_chunks) as pool:
            futures = {
                pool.submit(_fetch_chunk, idx, s, e): s
                for idx, s, e in chunk_ranges
            }
            chunk_results: dict[int, list] = {}
            for fut in futures:
                start_key, pages = fut.result()
                chunk_results[start_key] = pages

        # Reassemble in original page order
        for _, s, _ in chunk_ranges:
            all_pages.extend(chunk_results[s])

        logger.info(f"All {total_chunks} chunks collected ({len(all_pages)} pages total)")
        
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
                        text_blocks=[TextBlock(
                            block_type="paragraph",
                            content=f"[Page {page_num} could not be extracted after multiple attempts]"
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
        
        # Calculate processing time and actual cost
        elapsed_time = time.time() - start_time
        actual_cost_usd = cost_estimate["estimated_cost_usd"]
        cost_per_page = (actual_cost_usd / total_pages) if total_pages else 0.0

        logger.info(
            f"Extraction complete: {elapsed_time:.1f}s, "
            f"{total_chars:,} chars, {total_blocks} blocks, "
            f"{total_tables} tables, {total_images} images"
        )
        logger.info(
            f"💰 Cost summary: ${actual_cost_usd:.4f} total | "
            f"${cost_per_page:.5f}/page | "
            f"{total_pages} pages | "
            f"{elapsed_time / total_pages:.1f}s/page"
        )

        # Update metadata with actual extracted count
        metadata.total_pages = len(all_pages)

        extraction_notes = (
            f"Extracted in {(total_pages + chunk_size - 1) // chunk_size} chunks of {chunk_size} pages. "
            f"Processing time: {elapsed_time:.1f}s ({elapsed_time / total_pages:.2f}s/page). "
            f"Cost: ${actual_cost_usd:.4f} total (${cost_per_page:.5f}/page). "
            f"Content: {total_chars:,} chars, {total_blocks} text blocks, "
            f"{total_tables} tables, {total_images} images. "
            f"Pages with content: {pages_with_content}/{total_pages}."
        )
        
        if missing_pages:
            extraction_notes += f" Recovered {len(missing_pages) - len(still_missing)}/{len(missing_pages)} missing pages."
        
        return DocumentStructure(
            metadata=metadata,
            pages=all_pages,
            extraction_notes=extraction_notes
        )
    
    def _extract_structured(self, uploaded_file: types.File) -> DocumentStructure:
        """Extract structured document data using Gemini's structured output."""
        
        prompt = """Analyze this PDF document and extract its complete content in a structured format.

Instructions:
1. Process EVERY page from start to finish - do not skip any pages
2. For each page:
   - Set the correct page_number (1, 2, 3, etc.)
3. Extract the HEADER text if present (usually at the top of the page - may contain page numbers, chapter titles, section names)
   - Set header_position=\"left\", \"center\", or \"right\" based on where header text appears horizontally
4. Extract the FOOTER text if present (usually at the bottom of the page - may contain page numbers, citations, document info)
   - Set footer_position=\"left\", \"center\", or \"right\" based on where footer text appears horizontally
5. If page number appears separately from header/footer text:
   - Extract it in page_number_text field
   - Set page_number_position to one of: \"header-left\", \"header-center\", \"header-right\", \"footer-left\", \"footer-center\", \"footer-right\"
6. CRITICAL: DO NOT duplicate header/footer text in text_blocks - if you extract header="Title", do NOT include "Title" as a text_block
7. Extract all text blocks with semantic types (heading, paragraph, list_item, equation, etc.)
   - CRITICAL: For EVERY text block, you MUST provide bbox coordinates as percentages (0-100)
6. For MATHEMATICAL EQUATIONS:
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
7. For LISTS (numbered, bulleted, nested):
   - For NESTED LISTS: Set list_level field (1=top, 2=nested, etc.)
   - Preserve hierarchy structure
8. For TABLES: OCR all text content. Do NOT treat tables as images.
   - For MERGED CELLS: Set row_span and col_span values
   - For table captions: Extract separately
   - Provide bbox coordinates
9. For VISUAL ELEMENTS (charts, graphs, diagrams, figures, photos):
   - Identify image_type and provide description
   - CRITICAL: Avoid duplicate images - extract each unique image only once
   - Provide bbox coordinates as percentages (0-100)
10. For MULTI-COLUMN LAYOUTS (CRITICAL DETECTION):
    - Distinguish between TWO types:
    
    TYPE 1: FULL-PAGE MULTI-COLUMN (entire page is multi-column)
    - If entire page has columns: Set has_multi_column=true, column_count, column_gap
    - Set column_number for all elements
    
    TYPE 2: INLINE MULTI-COLUMN SECTION (embedded multi-column in single-column page)
    - Example: Single-column page with one 2-column list section
    - Set has_multi_column=FALSE for page
    - For elements in inline section only: set multi_column_group_id="group1" and column_number
    - Elements outside group: no multi_column_group_id
    - If detected:
      * Set has_multi_column=true, column_count (2, 3+), column_gap (20-40 points)
      * CRITICAL: Keep column_count CONSISTENT across pages with same layout
    - Ensure bbox_left positions distinguish columns clearly:
      * 2 columns: column 1 (0-48%), column 2 (52-100%)
      * 3 columns: column 1 (0-32%), column 2 (34-66%), column 3 (68-100%)
    - For LTR docs: Extract columns LEFT-TO-RIGHT
    - For RTL docs: Extract columns RIGHT-TO-LEFT
    - Reading order MUST follow column flow (top-to-bottom within each column)
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
                            "You are an expert OCR and document analysis system. "
                            "Extract complete, accurate structured data from documents. "
                            "Extract page headers and footers (usually contain page numbers, titles, or citations). "
                            "OCR all text content including tables. "
                            "PRESERVE NUMERAL SYSTEMS: If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), keep them exactly - do NOT convert to Western numerals (0123456789). "
                            "TRANSCRIBE mathematical equations EXACTLY as written - do NOT solve, simplify, or manipulate them. "
                            "Extract equations as LaTeX in 'equation' blocks preserving the exact notation from the PDF. "
                            "For SUPERSCRIPTS/SUBSCRIPTS: Use ^{} and _{} in LaTeX (e.g., x^{2}, H_{2}O). "
                            "For NUMBERED EQUATIONS: Extract equation number in equation_number field. "
                            "For NESTED LISTS: Set list_level (1=top, 2=nested, etc.) to preserve hierarchy. "
                            "For MERGED TABLE CELLS: Set row_span and col_span appropriately. "
                            "For MULTI-COLUMN LAYOUTS in LTR docs: Extract left-to-right column order. For RTL docs: right-to-left. "
                            "For MIXED RTL/LTR TEXT: Set text_direction on individual text blocks. "
                            "For WATERMARKS: Ignore decorative watermarks like 'DRAFT', 'CONFIDENTIAL'. "
                            "For ALL elements (text blocks, tables, images), provide bbox coordinates (top, left, width, height) as percentages. "
                            "CRITICAL BBOX RULES: ALWAYS measure bbox_left from the PHYSICAL LEFT EDGE of the page (0% = left edge, 100% = right edge). "
                            "This applies regardless of text direction (RTL or LTR). For Arabic/Hebrew RTL text that appears on the right side of the page, bbox_left should be 70-90%, NOT 10-30%. "
                            "Preserve all content, formatting, and semantic structure. "
                            "Be thorough - process every page completely. "
                            "CRITICAL: Ensure all JSON strings are properly escaped, especially quotes and special characters."
                        ),
                        media_resolution=self._get_media_resolution(),
                        max_output_tokens=self.config.max_output_tokens,
                        temperature=temperature,
                    ),
                )
                
                # Parse and validate the response
                doc = DocumentStructure.model_validate_json(response.text)
                logger.info(f"Successfully extracted {len(doc.pages)} pages")
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
                result["usage_metadata"] = {
                    "total_input_tokens": self._total_input_tokens,
                    "total_output_tokens": self._total_output_tokens,
                    "total_tokens": self._total_input_tokens + self._total_output_tokens
                }
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
    parser.add_argument("-f", "--format", choices=["html", "json", "both"], default="html",
                        help="Output format (default: html)")
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
