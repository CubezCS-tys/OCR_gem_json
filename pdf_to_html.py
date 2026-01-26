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
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Literal
from dataclasses import dataclass, field, fields
from enum import Enum

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logging.warning("PyMuPDF not installed. Image extraction disabled. Install with: pip install PyMuPDF")

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

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
    include_metadata: bool = False
    extract_tables: bool = True
    preserve_reading_order: bool = True
    output_format: Literal["html", "json", "both"] = "html"
    max_output_tokens: int = 65536  # Maximum output tokens (default ~65k for long docs)
    pages_per_chunk: int = 10  # Pages to process per API call (for chunked processing)
    use_chunked_processing: bool = True  # Enable chunked processing for large docs
    extract_images: bool = True  # Extract charts/graphs/figures as actual images
    image_dpi: int = 150  # DPI for rendering pages when extracting images
    request_timeout: int = 300  # Timeout for API requests in seconds (5 minutes)
    experimental_gemini_html: bool = False  # Also request HTML directly from Gemini for comparison
    enable_validation: bool = True
    validation_level: Literal["basic", "standard", "strict"] = "standard"
    auto_fix_errors: bool = False
    quality_threshold: float = 70.0
    enable_caching: bool = True
    cache_ttl_hours: int = 168
    parallel_processing: bool = False
    max_workers: int = 4
    continue_on_error: bool = True
    max_retries_per_page: int = 3
    fallback_to_text_only: bool = True
    default_theme: Literal["light"] = "light"
    include_debug_info: bool = False
    minify_html: bool = False
    include_toc: bool = False
    include_navigation: bool = False
    include_lists: bool = False
    direct_html_only: bool = False
    direct_html_pages_per_chunk: int = 10
    postprocess_gemini_html: bool = True
    tighten_columns: bool = True
    inject_mathjax: bool = True
    
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

        if self.quality_threshold < 0 or self.quality_threshold > 100:
            raise ValueError(f"quality_threshold must be between 0 and 100, got {self.quality_threshold}")

        if self.cache_ttl_hours < 1 or self.cache_ttl_hours > 8760:
            raise ValueError(f"cache_ttl_hours must be between 1 and 8760, got {self.cache_ttl_hours}")

        if self.max_workers < 1 or self.max_workers > 64:
            raise ValueError(f"max_workers must be between 1 and 64, got {self.max_workers}")

        if self.max_retries_per_page < 0 or self.max_retries_per_page > 10:
            raise ValueError(f"max_retries_per_page must be between 0 and 10, got {self.max_retries_per_page}")
        
        if self.direct_html_pages_per_chunk < 1 or self.direct_html_pages_per_chunk > 50:
            raise ValueError(
                f"direct_html_pages_per_chunk must be between 1 and 50, got {self.direct_html_pages_per_chunk}"
            )


# =============================================================================
# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUT
# =============================================================================

class InlineElement(BaseModel):
    """Represents inline formatting or links within text."""
    type: Literal["text", "link", "strong", "emphasis", "code"] = Field(
        description="Inline element type: text, link, strong, emphasis, or code"
    )
    content: str = Field(description="Text content for the inline element")
    url: Optional[str] = Field(default=None, description="URL for links (if type='link')")
    target_id: Optional[str] = Field(default=None, description="Internal target id for links (if type='link')")


class TOCEntry(BaseModel):
    """Represents an entry in the table of contents."""
    level: int = Field(ge=1, le=6, description="Heading level (1-6)")
    title: str = Field(description="Heading text")
    page_number: int = Field(description="Page where this heading appears")
    section_id: str = Field(description="Unique ID for linking (e.g., 'section-1-2')")
    parent_id: Optional[str] = Field(default=None, description="ID of parent section for nesting")
    subsections: list['TOCEntry'] = Field(default_factory=list, description="Nested subsections")


class FigureReference(BaseModel):
    """Reference to a figure for List of Figures."""
    figure_number: str = Field(description="Figure number (e.g., '3.2', 'A-1')")
    caption: str = Field(description="Figure caption")
    page_number: int = Field(description="Page number where figure appears")
    figure_id: str = Field(description="Unique ID for linking")
    image_type: str = Field(description="Type: chart, graph, diagram, etc.")


class TableReference(BaseModel):
    """Reference to a table for List of Tables."""
    table_number: str = Field(description="Table number (e.g., '2.1', 'B-3')")
    caption: str = Field(description="Table caption")
    page_number: int = Field(description="Page number where table appears")
    table_id: str = Field(description="Unique ID for linking")
    row_count: int = Field(description="Number of data rows")
    column_count: int = Field(description="Number of columns")


class EquationReference(BaseModel):
    """Reference to a numbered equation."""
    equation_number: str = Field(description="Equation number (e.g., '(1)', '(2.3)')")
    page_number: int = Field(description="Page where equation appears")
    equation_id: str = Field(description="Unique ID for linking")
    equation_preview: str = Field(description="LaTeX snippet (first 50 chars)")


class Citation(BaseModel):
    """Represents a bibliography entry or citation."""
    citation_key: str = Field(description="Citation key (e.g., 'Smith2023', '[1]')")
    citation_id: str = Field(description="Unique ID for linking")
    authors: list[str] = Field(description="List of author names")
    title: str = Field(description="Publication title")
    year: Optional[int] = Field(default=None, description="Publication year")
    journal: Optional[str] = Field(default=None, description="Journal/conference name")
    volume: Optional[str] = Field(default=None, description="Volume number")
    pages: Optional[str] = Field(default=None, description="Page range (e.g., '123-145')")
    doi: Optional[str] = Field(default=None, description="Digital Object Identifier")
    url: Optional[str] = Field(default=None, description="Online URL")
    isbn: Optional[str] = Field(default=None, description="ISBN for books")
    publisher: Optional[str] = Field(default=None, description="Publisher name")
    citation_style: Optional[Literal["APA", "MLA", "Chicago", "IEEE", "Harvard"]] = Field(
        default=None,
        description="Citation format style"
    )


class TextFormatting(BaseModel):
    """Structured text formatting to replace vague style strings."""
    bold: bool = Field(default=False, description="Bold/strong text")
    italic: bool = Field(default=False, description="Italic/emphasized text")
    underline: bool = Field(default=False, description="Underlined text")
    strikethrough: bool = Field(default=False, description="Strikethrough text")
    superscript: bool = Field(default=False, description="Superscript (x^2)")
    subscript: bool = Field(default=False, description="Subscript (H2O)")
    font_size: Optional[Literal["xx-small", "x-small", "small", "normal", "large", "x-large", "xx-large"]] = Field(
        default=None,
        description="Relative font size"
    )
    alignment: Optional[Literal["left", "right", "center", "justify"]] = Field(
        default=None,
        description="Text alignment"
    )
    text_color: Optional[str] = Field(
        default=None,
        description="Text color as hex code (e.g., '#ff0000') or name (e.g., 'red')"
    )
    background_color: Optional[str] = Field(
        default=None,
        description="Background/highlight color"
    )
    font_family: Optional[str] = Field(
        default=None,
        description="Font family name (e.g., 'Arial', 'Times New Roman')"
    )
    monospace: bool = Field(
        default=False,
        description="Use monospace font (for code, technical content)"
    )
    indent_level: Optional[int] = Field(
        default=None,
        ge=0,
        description="Indentation level (0=none, 1=first level, etc.)"
    )
    line_height: Optional[Literal["single", "1.5", "double"]] = Field(
        default=None,
        description="Line height/spacing"
    )


class TableCell(BaseModel):
    """Represents a cell in a table."""
    content: str = Field(description="Text content of the cell")
    row_span: int = Field(default=1, description="Number of rows this cell spans")
    col_span: int = Field(default=1, description="Number of columns this cell spans")
    is_header: bool = Field(default=False, description="Whether this is a header cell")
    alignment: Optional[Literal["left", "right", "center", "justify"]] = Field(
        default=None, description="Optional text alignment for the cell"
    )


class TableRow(BaseModel):
    """Represents a row in a table."""
    cells: list[TableCell] = Field(description="Cells in the row")
    is_header_row: bool = Field(default=False, description="Whether this is a header row")


class Table(BaseModel):
    """Represents a table extracted from the document."""
    caption: Optional[str] = Field(default=None, description="Table caption if present")

    # DEPRECATED: Keep for backward compatibility
    headers: list[str] = Field(default_factory=list, description="DEPRECATED: Use structured_rows with header cells")
    rows: list[list[str]] = Field(default_factory=list, description="DEPRECATED: Use structured_rows")

    # NEW: Structured table rows with proper cells
    structured_rows: Optional[list[TableRow]] = Field(
        default=None, description="Structured table rows with TableCell objects"
    )
    table_number: Optional[str] = Field(
        default=None,
        description="Table number (e.g., 'Table 2.1', 'Table B-3')"
    )
    table_id: Optional[str] = Field(
        default=None,
        description="Unique ID for cross-references (e.g., 'table-sales-data')"
    )
    summary: Optional[str] = Field(
        default=None,
        description="Accessibility summary for screen readers"
    )

    # Bounding box as percentages of page dimensions (0-100) - for proper ordering
    bbox_top: Optional[float] = Field(default=None, description="Top edge as percentage from top of page (0-100)")
    bbox_left: Optional[float] = Field(default=None, description="Left edge as percentage from left of page (0-100)")
    bbox_width: Optional[float] = Field(default=None, description="Width as percentage of page width (0-100)")
    bbox_height: Optional[float] = Field(default=None, description="Height as percentage of page height (0-100)")


class TextBlock(BaseModel):
    """Represents a block of text with semantic meaning."""
    block_type: Literal[
        "heading", "paragraph", "list_item", "caption", "footnote", "quote", "code", "equation",
        "theorem", "proof", "lemma", "corollary", "proposition", "definition", "example", "remark", "note",
        "abstract", "summary", "keywords", "author_info", "acknowledgments", "appendix_heading",
        "sidebar", "callout", "warning", "tip", "important", "question", "answer", "exercise", "solution",
        "verse", "poetry", "dialogue", "preformatted", "page_number", "running_head", "watermark",
        "reference", "citation_inline", "bibliography_entry"
    ] = Field(description="Semantic type of the text block")
    level: Optional[int] = Field(default=None, description="Heading level (1-6) if block_type is heading")
    content: str = Field(description="The text content (for equations, use LaTeX syntax)")
    inline_elements: Optional[list[InlineElement]] = Field(
        default=None,
        description="Optional rich text markup. If None, use plain content field."
    )
    formatting: Optional[TextFormatting] = Field(
        default=None,
        description="Structured text formatting (replaces style string)"
    )
    element_id: Optional[str] = Field(
        default=None,
        description="Unique ID for this element (e.g., 'section-1-2', 'para-5')"
    )
    anchor_name: Optional[str] = Field(
        default=None,
        description="Named anchor for bookmarks (e.g., 'introduction', 'methodology')"
    )
    references: Optional[list[str]] = Field(
        default_factory=list,
        description="IDs of elements this block references (for 'See Section 2.3')"
    )
    style: Optional[str] = Field(default=None, description="CSS style hints (e.g., 'bold', 'italic', 'centered')")
    block_number: Optional[str] = Field(
        default=None,
        description="Block number for theorems, definitions, etc. (e.g., 'Theorem 2.3')"
    )
    block_label: Optional[str] = Field(
        default=None,
        description="Label for referencing (e.g., 'thm:main-result')"
    )
    severity: Optional[Literal["info", "warning", "error", "success"]] = Field(
        default=None,
        description="Severity level for callouts/warnings"
    )
    language: Optional[str] = Field(
        default=None,
        description="Programming language for code blocks (e.g., 'python', 'javascript')"
    )
    is_display_math: Optional[bool] = Field(default=False, description="For equations: True for display mode (\\[...\\]), False for inline (\\(...\\))")
    # NEW: List hierarchy support
    list_level: Optional[int] = Field(default=1, description="Nesting level for list items (1=top level, 2=nested, etc.)")
    # NEW: List type and marker style
    list_type: Optional[Literal["unordered", "ordered", "definition"]] = Field(
        default=None, description="List type for list items: unordered, ordered, or definition"
    )
    list_marker_style: Optional[str] = Field(
        default=None,
        description="List marker style (e.g., 'disc', 'decimal', 'lower-alpha', 'upper-roman')"
    )
    # NEW: Equation numbering support
    equation_number: Optional[str] = Field(default=None, description="Equation number label if present (e.g., '(1)', '(2.3)')")
    # NEW: Text direction for mixed RTL/LTR content
    text_direction: Optional[Literal["ltr", "rtl", "auto"]] = Field(default="auto", description="Text direction: ltr, rtl, or auto")
    # Bounding box as percentages of page dimensions (0-100) - optional for backward compatibility
    bbox_top: Optional[float] = Field(default=None, description="Top edge as percentage from top of page (0-100)")
    bbox_left: Optional[float] = Field(default=None, description="Left edge as percentage from left of page (0-100)")
    bbox_width: Optional[float] = Field(default=None, description="Width as percentage of page width (0-100)")
    bbox_height: Optional[float] = Field(default=None, description="Height as percentage of page height (0-100)")


class Image(BaseModel):
    """Represents a visual element (chart, graph, diagram, figure) - NOT tables."""
    image_type: Literal["chart", "graph", "diagram", "figure", "photo", "logo", "illustration", "other"] = Field(
        description="Type of visual: chart, graph, diagram, figure, photo, logo, illustration, or other. NOT for tables."
    )
    description: str = Field(description="DEPRECATED: Use alt_text instead (kept for backward compatibility)")
    alt_text: Optional[str] = Field(
        default=None,
        description="Short alternative text for accessibility (recommended: 125 chars or less)"
    )
    long_description: Optional[str] = Field(
        default=None,
        description="Detailed description for complex images (charts, diagrams)"
    )
    figure_number: Optional[str] = Field(
        default=None,
        description="Figure number (e.g., 'Figure 3.2', 'Fig. A-1')"
    )
    figure_id: Optional[str] = Field(
        default=None,
        description="Unique ID for cross-references (e.g., 'fig-revenue-chart')"
    )
    is_multipart: bool = Field(
        default=False,
        description="Whether this is part of a multi-part figure"
    )
    part_label: Optional[str] = Field(
        default=None,
        description="Part label for multi-part figures (e.g., 'a', 'b', 'c')"
    )
    caption: Optional[str] = Field(default=None, description="Image caption if present")
    # Bounding box as percentages of page dimensions (0-100)
    bbox_top: float = Field(description="Top edge of image as percentage from top of page (0-100)")
    bbox_left: float = Field(description="Left edge of image as percentage from left of page (0-100)")
    bbox_width: float = Field(description="Width of image as percentage of page width (0-100)")
    bbox_height: float = Field(description="Height of image as percentage of page height (0-100)")
    # Runtime field for extracted image data (not from Gemini)
    image_data: Optional[str] = Field(default=None, description="Base64 encoded image data (populated at runtime)")


class CodeBlock(BaseModel):
    """Specialized model for code blocks with syntax highlighting."""
    code: str = Field(description="The code content")
    language: Optional[str] = Field(
        default=None,
        description="Programming language (python, javascript, java, c++, sql, etc.)"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Filename if code is from a file"
    )
    line_numbers: bool = Field(
        default=False,
        description="Whether to show line numbers"
    )
    highlight_lines: Optional[list[int]] = Field(
        default=None,
        description="Line numbers to highlight (1-indexed)"
    )
    start_line: int = Field(
        default=1,
        description="Starting line number if not 1"
    )
    bbox_top: Optional[float] = None
    bbox_left: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None


class SpecialBlock(BaseModel):
    """Container for special content blocks like sidebars, callouts."""
    block_type: Literal[
        "sidebar", "callout", "warning", "tip", "note",
        "important", "example", "exercise", "theorem", "proof"
    ]
    title: Optional[str] = Field(default=None, description="Block title/heading")
    content: list[TextBlock] = Field(description="Content blocks within this special block")
    severity: Optional[Literal["info", "success", "warning", "error"]] = Field(
        default=None,
        description="Visual severity indicator"
    )
    icon: Optional[str] = Field(
        default=None,
        description="Icon name or emoji for visual marker"
    )
    collapsible: bool = Field(
        default=False,
        description="Whether block can be collapsed/expanded"
    )
    bbox_top: Optional[float] = None
    bbox_left: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None


class PageContent(BaseModel):
    """Structured content extracted from a single page."""
    page_number: int = Field(description="1-based page number")
    header: Optional[str] = Field(default=None, description="Header text from the page (e.g., page numbers, chapter titles)")
    footer: Optional[str] = Field(default=None, description="Footer text from the page (e.g., page numbers, citations)")
    text_blocks: list[TextBlock] = Field(default_factory=list, description="Ordered list of text blocks")
    tables: list[Table] = Field(default_factory=list, description="Tables found on this page")
    images: list[Image] = Field(default_factory=list, description="Images/figures found on this page")
    code_blocks: list[CodeBlock] = Field(default_factory=list, description="Code blocks on this page")
    special_blocks: list[SpecialBlock] = Field(default_factory=list, description="Sidebars, callouts, warnings, etc.")
    raw_text: Optional[str] = Field(default=None, description="Raw OCR text for the page")
    has_multi_column: bool = Field(default=False, description="Whether the page has multi-column layout")
    column_count: Optional[int] = Field(default=None, description="Number of columns if multi-column (2, 3, etc.)")
    reading_order_notes: Optional[str] = Field(default=None, description="Notes about reading order if complex")
    # NEW: Primary text direction for the page
    page_direction: Optional[Literal["ltr", "rtl"]] = Field(default="ltr", description="Primary text direction: ltr or rtl")


class DocumentMetadata(BaseModel):
    """Metadata about the document."""
    title: Optional[str] = Field(default=None, description="Document title if detectable")
    author: Optional[str] = Field(default=None, description="Document author if detectable")
    total_pages: int = Field(description="Total number of pages in the document")
    language: Optional[str] = Field(default=None, description="Primary language of the document")
    document_type: Optional[str] = Field(default=None, description="Type: report, form, article, letter, etc.")
    is_scanned: bool = Field(default=False, description="Whether the document appears to be scanned/OCR'd")
    authors: Optional[list['Author']] = Field(
        default=None,
        description="List of authors with affiliations"
    )
    affiliations: Optional[list[str]] = Field(
        default=None,
        description="Institutional affiliations"
    )
    keywords: Optional[list[str]] = Field(
        default=None,
        description="Keywords/tags for the document"
    )
    abstract: Optional[str] = Field(
        default=None,
        description="Document abstract/summary"
    )
    doi: Optional[str] = Field(
        default=None,
        description="Digital Object Identifier"
    )
    publication_date: Optional[str] = Field(
        default=None,
        description="Publication date (ISO 8601 format)"
    )
    copyright: Optional[str] = Field(
        default=None,
        description="Copyright notice"
    )
    license: Optional[str] = Field(
        default=None,
        description="License type (e.g., 'CC BY 4.0', 'MIT')"
    )


class Author(BaseModel):
    """Author information."""
    name: str
    affiliation: Optional[str] = None
    email: Optional[str] = None
    orcid: Optional[str] = None
    corresponding: bool = False


class DocumentStructure(BaseModel):
    """Complete structured representation of a PDF document."""
    metadata: DocumentMetadata = Field(description="Document metadata")
    pages: list[PageContent] = Field(description="Content for each page")
    extraction_notes: Optional[str] = Field(default=None, description="Any notes about the extraction process")
    table_of_contents: Optional[list[TOCEntry]] = Field(
        default=None,
        description="Hierarchical table of contents generated from headings"
    )
    list_of_figures: Optional[list[FigureReference]] = Field(
        default=None,
        description="List of all figures with page numbers"
    )
    list_of_tables: Optional[list[TableReference]] = Field(
        default=None,
        description="List of all tables with page numbers"
    )
    list_of_equations: Optional[list[EquationReference]] = Field(
        default=None,
        description="List of all numbered equations with page numbers"
    )
    bibliography: Optional[list[Citation]] = Field(
        default=None,
        description="Bibliography entries if present in document"
    )
    glossary: Optional[dict[str, str]] = Field(
        default=None,
        description="Glossary terms and definitions"
    )
    footnotes: Optional[dict[str, str]] = Field(
        default=None,
        description="Document-level footnotes keyed by reference marker"
    )


class ValidationError(BaseModel):
    """Represents a validation error."""
    error_type: Literal[
        "missing_content", "invalid_bbox", "broken_reference",
        "duplicate_id", "invalid_markup", "accessibility_violation",
        "malformed_equation", "empty_block", "invalid_table", "invalid_structure"
    ]
    severity: Literal["critical", "error", "warning"]
    message: str
    location: Optional[str] = Field(default=None, description="Page/element location")
    suggestion: Optional[str] = Field(default=None, description="How to fix")


class ValidationWarning(BaseModel):
    """Represents a validation warning."""
    warning_type: str
    message: str
    location: Optional[str] = None
    auto_fixable: bool = False


class QualityMetrics(BaseModel):
    """Quality metrics for extracted content."""
    pages_with_content: int
    pages_total: int
    coverage_percent: float
    total_text_chars: int
    total_text_blocks: int
    total_tables: int
    total_images: int
    total_equations: int
    avg_chars_per_page: float
    blocks_with_bbox: int
    blocks_without_bbox: int
    images_with_alt_text: int
    images_without_alt_text: int
    tables_with_headers: int
    tables_without_headers: int
    accessibility_score: float = Field(ge=0.0, le=100.0)
    wcag_compliance: Literal["A", "AA", "AAA", "non-compliant"]
    confidence_score: float = Field(ge=0.0, le=100.0)
    ocr_errors_estimated: int


class ValidationResult(BaseModel):
    """Results from document validation."""
    is_valid: bool = Field(description="Overall validation status")
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[ValidationWarning] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=100.0, description="Overall quality score (0-100)")
    metrics: QualityMetrics = Field(description="Detailed quality metrics")


class ExportConfig(BaseModel):
    """Configuration for document export."""
    format: Literal["html", "pdf", "docx", "markdown", "latex", "epub"]
    include_toc: bool = True
    include_images: bool = True
    include_page_numbers: bool = True
    include_navigation: bool = True
    include_metadata: bool = True
    theme: Literal["light", "print"] = "light"
    font_size: Literal["small", "normal", "large", "x-large"] = "normal"
    custom_css: Optional[str] = None
    page_size: Optional[Literal["A4", "Letter", "Legal"]] = "A4"
    page_orientation: Optional[Literal["portrait", "landscape"]] = "portrait"
    template: Optional[str] = None
    preserve_formatting: bool = True
    markdown_flavor: Optional[Literal["github", "commonmark", "pandoc"]] = "github"
    minify_html: bool = False


class ChunkExtraction(BaseModel):
    """Extraction result for a chunk of pages."""
    pages: list[PageContent] = Field(description="Content for each page in this chunk")
    chunk_notes: Optional[str] = Field(default=None, description="Any notes about this chunk extraction")


# Resolve forward references for self-referential models
TOCEntry.model_rebuild()
DocumentMetadata.model_rebuild()


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
    def render(
        doc: DocumentStructure,
        include_styles: bool = True,
        theme: Optional[str] = None,
        include_metadata: bool = True,
        include_toc: bool = True,
        include_navigation: bool = True,
        include_images: bool = True,
        include_page_numbers: bool = True,
        include_lists: bool = True,
    ) -> str:
        """Render the structured document as HTML."""
        parts = []

        # Ensure headings have IDs for navigation
        HTMLRenderer._ensure_heading_ids(doc)

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
        theme_class = ""
        theme_mode = theme or "light"
        if theme_mode == "print":
            theme_class = ' class="print-mode"'

        parts.append(f'<html lang="{lang}"{dir_attr}{theme_class}>')
        parts.append("<head>")
        parts.append('<meta charset="UTF-8">')
        parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        
        if doc.metadata.title:
            parts.append(f"<title>{HTMLRenderer._escape(doc.metadata.title)}</title>")
        
        # Add MathJax for equation rendering
        parts.append(HTMLRenderer._get_mathjax_config())
        parts.append(HTMLRenderer._get_syntax_highlighting())
        
        if include_styles:
            parts.append(HTMLRenderer._get_styles(is_rtl))
        
        parts.append("</head>")
        parts.append("<body>")
        if include_navigation:
            parts.append(HTMLRenderer._get_interactive_shell())
        parts.append('<div class="document-container">')

        if include_metadata:
            metadata_html = HTMLRenderer._render_document_metadata(doc.metadata)
            if metadata_html:
                parts.append(metadata_html)

        # Navigation sections (TOC, lists)
        if include_toc:
            toc_html = HTMLRenderer._generate_toc(doc)
            if toc_html:
                parts.append(toc_html)

        if include_lists:
            if include_images:
                figures = doc.list_of_figures
                if figures is None:
                    figures = HTMLRenderer._auto_generate_figures(doc)
                if figures:
                    parts.append(HTMLRenderer._render_list_of_figures(figures))

            tables = doc.list_of_tables
            if tables is None:
                tables = HTMLRenderer._auto_generate_tables(doc)
            if tables:
                parts.append(HTMLRenderer._render_list_of_tables(tables))

            equations = doc.list_of_equations
            if equations is None:
                equations = HTMLRenderer._auto_generate_equations(doc)
            if equations:
                parts.append(HTMLRenderer._render_list_of_equations(equations))

        parts.append('<main role="main" class="document-content">')

        # Render each page
        for page in doc.pages:
            parts.append(HTMLRenderer._render_page(
                page,
                is_rtl=is_rtl,
                include_images=include_images,
                include_page_numbers=include_page_numbers
            ))

        parts.append("</main>")

        # Bibliography, glossary, footnotes (if provided)
        if doc.bibliography:
            parts.append(HTMLRenderer._render_bibliography(doc.bibliography))
        if doc.glossary:
            parts.append(HTMLRenderer._render_glossary(doc.glossary))
        if doc.footnotes:
            parts.append(HTMLRenderer._render_document_footnotes(doc.footnotes))

        parts.append("</div>")
        if include_navigation:
            parts.append(HTMLRenderer._get_interactive_script())
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
    def _get_syntax_highlighting() -> str:
        """Return syntax highlighting assets (highlight.js)."""
        return """<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', () => {
  if (window.hljs) {
    document.querySelectorAll('pre code').forEach((el) => {
      window.hljs.highlightElement(el);
    });
  }
});
</script>"""

    @staticmethod
    def _get_interactive_shell() -> str:
        """Return interactive UI shell elements (search, theme toggle)."""
        return (
            '<div class="search-box" role="search">'
            '<input type="search" class="search-input" placeholder="Search..." aria-label="Search document" />'
            '<button class="search-prev" type="button" aria-label="Previous result">Prev</button>'
            '<button class="search-next" type="button" aria-label="Next result">Next</button>'
            '<span class="search-counter">0 / 0</span>'
            '</div>'
        )

    @staticmethod
    def _get_interactive_script() -> str:
        """Return interactive features script."""
        return """<script>
class DocumentSearch {
  constructor() {
    this.results = [];
    this.currentIndex = 0;
  }

  search(query) {
    this.clearHighlights();
    const trimmed = query.trim();
    if (!trimmed) return;

    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: (node) => {
          if (!node.parentElement) return NodeFilter.FILTER_REJECT;
          const tag = node.parentElement.tagName.toLowerCase();
          if (['script', 'style', 'noscript', 'code', 'pre'].includes(tag)) {
            return NodeFilter.FILTER_REJECT;
          }
          if (node.parentElement.closest('.search-box')) {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const regex = new RegExp(escapeRegExp(trimmed), 'gi');
    const results = [];

    while (walker.nextNode()) {
      const node = walker.currentNode;
      regex.lastIndex = 0;
      if (!regex.test(node.textContent)) {
        continue;
      }
      const parent = node.parentElement;
      const span = document.createElement('span');
      span.innerHTML = node.textContent.replace(regex, '<mark class="search-highlight">$&</mark>');
      parent.replaceChild(span, node);
      results.push(...span.querySelectorAll('.search-highlight'));
    }

    this.results = results;
    this.currentIndex = 0;
    this.updateSearchUI();
    this.scrollToResult();
  }

  clearHighlights() {
    document.querySelectorAll('.search-highlight').forEach(mark => {
      const parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize();
    });
    this.results = [];
    this.currentIndex = 0;
    this.updateSearchUI();
  }

  next() {
    if (this.results.length === 0) return;
    this.currentIndex = (this.currentIndex + 1) % this.results.length;
    this.scrollToResult();
  }

  previous() {
    if (this.results.length === 0) return;
    this.currentIndex = (this.currentIndex - 1 + this.results.length) % this.results.length;
    this.scrollToResult();
  }

  scrollToResult() {
    if (!this.results.length) return;
    this.results.forEach((el, idx) => {
      el.classList.toggle('current', idx === this.currentIndex);
    });
    const current = this.results[this.currentIndex];
    if (current) {
      current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    this.updateSearchUI();
  }

  updateSearchUI() {
    const counter = document.querySelector('.search-counter');
    if (counter) {
      const total = this.results.length;
      const index = total ? this.currentIndex + 1 : 0;
      counter.textContent = `${index} / ${total}`;
    }
  }
}

class ReadingProgress {
  constructor() {
    this.progressBar = document.createElement('div');
    this.progressBar.className = 'reading-progress';
    document.body.appendChild(this.progressBar);
    window.addEventListener('scroll', () => this.updateProgress());
    this.updateProgress();
  }

  updateProgress() {
    const windowHeight = window.innerHeight;
    const documentHeight = document.documentElement.scrollHeight - windowHeight;
    const scrolled = window.scrollY;
    const progress = documentHeight > 0 ? (scrolled / documentHeight) * 100 : 0;
    this.progressBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
  }
}

function showToast(message, duration = 2500) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast('Copied to clipboard');
  }).catch(() => {
    showToast('Copy failed');
  });
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&');
}

document.addEventListener('DOMContentLoaded', () => {
  const search = new DocumentSearch();
  new ReadingProgress();

  const searchInput = document.querySelector('.search-input');
  const searchPrev = document.querySelector('.search-prev');
  const searchNext = document.querySelector('.search-next');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => search.search(e.target.value));
  }
  if (searchPrev) {
    searchPrev.addEventListener('click', () => search.previous());
  }
  if (searchNext) {
    searchNext.addEventListener('click', () => search.next());
  }

  document.addEventListener('keydown', (event) => {
    const active = document.activeElement;
    const isInput = active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable);
    if (event.key === '/' && !isInput && searchInput) {
      event.preventDefault();
      searchInput.focus();
      return;
    }
    if (event.key === 'Enter' && active === searchInput) {
      event.preventDefault();
      if (event.shiftKey) {
        search.previous();
      } else {
        search.next();
      }
      return;
    }
    if (event.key === 'Escape' && active === searchInput) {
      searchInput.value = '';
      search.clearHighlights();
      searchInput.blur();
    }
  });

  document.querySelectorAll('pre code').forEach(block => {
    const button = document.createElement('button');
    button.className = 'copy-button';
    button.type = 'button';
    button.textContent = 'Copy';
    button.addEventListener('click', () => copyToClipboard(block.textContent));
    const pre = block.parentElement;
    if (pre) {
      pre.style.position = 'relative';
      pre.insertBefore(button, block);
    }
  });

  const backToTop = document.createElement('button');
  backToTop.className = 'back-to-top';
  backToTop.type = 'button';
  backToTop.textContent = 'Up';
  backToTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  backToTop.setAttribute('aria-label', 'Back to top');
  document.body.appendChild(backToTop);

  window.addEventListener('scroll', () => {
    backToTop.classList.toggle('visible', window.scrollY > 500);
  });
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
        --link-color: #007acc;
        --callout-bg: #f8f9fa;
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

    a {{
        color: var(--link-color);
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

    .image-long-desc {{
        margin-top: 0.75rem;
        text-align: left;
    }}

    .image-long-desc summary {{
        cursor: pointer;
        font-weight: 600;
    }}

    .image-long-desc p {{
        margin: 0.5rem 0 0;
    }}

    /* Table of Contents */
    .toc {{
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 1.5rem;
        margin: 2rem 0;
    }}
    
    .toc h2 {{
        margin-top: 0;
        border-bottom: 2px solid #007acc;
        padding-bottom: 0.5rem;
    }}
    
    .toc-list {{
        list-style: none;
        padding-left: 0;
        margin: 0;
    }}
    
    .toc-list li {{
        margin: 0.5rem 0;
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 1rem;
    }}
    
    .toc-list a {{
        color: #007acc;
        text-decoration: none;
        flex-grow: 1;
    }}
    
    .toc-list a:hover {{
        text-decoration: underline;
    }}
    
    .toc-page {{
        color: #666;
        font-size: 0.9em;
        white-space: nowrap;
    }}
    
    .toc-level-1 {{ padding-left: 0; font-weight: 600; }}
    .toc-level-2 {{ padding-left: 1.5rem; }}
    .toc-level-3 {{ padding-left: 3rem; }}
    .toc-level-4 {{ padding-left: 4.5rem; font-size: 0.95em; }}
    .toc-level-5 {{ padding-left: 6rem; font-size: 0.9em; }}
    .toc-level-6 {{ padding-left: 7.5rem; font-size: 0.85em; }}
    
    /* List of Figures/Tables/Equations */
    .list-of-figures, .list-of-tables, .list-of-equations {{
        margin: 2rem 0;
        padding: 1.5rem;
        background: #f8f9fa;
        border-left: 4px solid #007acc;
    }}
    
    .figure-list, .table-list, .equation-list {{
        list-style: decimal;
        padding-left: 2rem;
        margin: 0;
    }}
    
    .figure-list li, .table-list li, .equation-list li {{
        margin: 0.75rem 0;
        display: flex;
        justify-content: space-between;
        gap: 1rem;
    }}
    
    .figure-number, .table-number, .equation-number {{
        font-weight: 600;
        color: #007acc;
    }}
    
    .figure-page, .table-page, .equation-page {{
        color: #666;
        font-size: 0.9em;
        margin-left: auto;
        padding-left: 1rem;
        white-space: nowrap;
    }}
    
    /* Bibliography */
    .bibliography {{
        margin-top: 3rem;
        padding-top: 2rem;
        border-top: 3px double #007acc;
    }}
    
    .bibliography h2 {{
        margin-bottom: 1.5rem;
    }}
    
    .bibliography-list {{
        list-style: decimal;
        padding-left: 2rem;
    }}
    
    .bibliography-list li {{
        margin: 1rem 0;
        line-height: 1.6;
    }}
    
    .glossary {{
        margin-top: 2.5rem;
    }}
    
    .glossary-list dt {{
        font-weight: 600;
        margin-top: 0.75rem;
    }}
    
    .glossary-list dd {{
        margin-left: 1rem;
    }}
    
    .document-footnotes {{
        margin-top: 2.5rem;
    }}
    
    .footnotes-list {{
        list-style: decimal;
        padding-left: 2rem;
    }}
    
    .footnote-marker {{
        font-weight: 600;
        margin-right: 0.5rem;
    }}
    
    /* Section IDs for linking */
    [id^="section-"],
    [id^="figure-"],
    [id^="table-"],
    [id^="equation-"],
    [id^="citation-"] {{
        scroll-margin-top: 2rem;
    }}
    
    :target {{
        animation: highlight 2s ease;
    }}
    
    @keyframes highlight {{
        0% {{ background-color: #fff3cd; }}
        100% {{ background-color: transparent; }}
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

    /* Theorem, Proof, Definition styles */
    .theorem, .definition, .lemma, .corollary, .proposition, .example, .remark, .note {{
        margin: 1.5rem 0;
        padding: 1rem 1.5rem;
        background: #f0f8ff;
        border-left: 4px solid #007acc;
        border-radius: 4px;
    }}
    
    .theorem-label, .definition-label, .lemma-label, .corollary-label, .proposition-label {{
        font-weight: 700;
        color: #007acc;
    }}
    
    .block-number {{
        font-weight: 600;
    }}
    
    .proof {{
        margin: 1rem 0 1rem 2rem;
        padding: 1rem;
        border-left: 2px solid #999;
        background: #fafafa;
    }}
    
    .proof-label {{
        font-weight: 600;
    }}
    
    .qed {{
        float: right;
        font-size: 1.1em;
        color: #007acc;
    }}
    
    /* Callouts and Special Blocks */
    .callout {{
        display: flex;
        margin: 1.5rem 0;
        padding: 1rem;
        border-radius: 6px;
        border-left: 4px solid;
        gap: 1rem;
    }}
    
    .callout-icon {{
        font-size: 1.4em;
        flex-shrink: 0;
        line-height: 1.2;
    }}
    
    .callout-content {{
        flex-grow: 1;
    }}
    
    .callout-warning {{
        background: #fff3cd;
        border-color: #ffc107;
        color: #856404;
    }}
    
    .callout-tip {{
        background: #d1ecf1;
        border-color: #17a2b8;
        color: #0c5460;
    }}
    
    .callout-important {{
        background: #f8d7da;
        border-color: #dc3545;
        color: #721c24;
    }}
    
    .callout-note {{
        background: #d4edda;
        border-color: #28a745;
        color: #155724;
    }}

    .callout-callout {{
        background: #f1f1f1;
        border-color: #999;
        color: #333;
    }}
    
    .callout-question {{
        background: #e7f3ff;
        border-color: #007acc;
        color: #004a80;
    }}
    
    .callout-answer {{
        background: #d4edda;
        border-color: #28a745;
        color: #155724;
    }}
    
    .callout-exercise {{
        background: #fff3cd;
        border-color: #ffc107;
        color: #856404;
    }}
    
    .callout-solution {{
        background: #e2f0d9;
        border-color: #28a745;
        color: #155724;
    }}
    
    /* Severity indicators */
    .severity-info {{ border-color: #17a2b8; }}
    .severity-success {{ border-color: #28a745; }}
    .severity-warning {{ border-color: #ffc107; }}
    .severity-error {{ border-color: #dc3545; }}
    
    /* Code blocks with syntax highlighting */
    .code-block-container {{
        margin: 1.5rem 0;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid #e1e4e8;
    }}
    
    .code-header {{
        background: #f6f8fa;
        padding: 0.5rem 1rem;
        border-bottom: 1px solid #e1e4e8;
        font-size: 0.9em;
    }}
    
    .filename {{
        font-family: monospace;
        color: #24292e;
    }}
    
    .code-block-container pre {{
        margin: 0;
        padding: 1rem;
        background: #f6f8fa;
        overflow-x: auto;
    }}
    
    .line-numbers .line-number {{
        display: inline-block;
        width: 3em;
        text-align: right;
        color: #999;
        user-select: none;
        margin-right: 1em;
    }}
    
    .highlight-line {{
        background: #fffbdd;
        display: inline-block;
        width: 100%;
    }}
    
    /* Verse/Poetry */
    .verse {{
        font-family: Georgia, serif;
        font-style: italic;
        margin: 1.5rem 2rem;
        line-height: 1.8;
    }}
    
    .verse-line {{
        display: block;
        padding: 0.25rem 0;
    }}
    
    /* Abstract and Keywords */
    .abstract {{
        margin: 2rem 0;
        padding: 1.5rem;
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
    }}
    
    .abstract h2 {{
        margin-top: 0;
        font-size: 1.2em;
        color: #007acc;
    }}
    
    .keywords {{
        margin: 1rem 0;
        padding: 0.75rem 1rem;
        background: #e7f3ff;
        border-left: 3px solid #007acc;
    }}
    
    .keyword {{
        display: inline-block;
        background: #007acc;
        color: white;
        padding: 0.2em 0.6em;
        border-radius: 3px;
        font-size: 0.85em;
        margin: 0.2em;
    }}

    .document-metadata {{
        margin: 1.5rem 0 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--border-color);
    }}
    
    .document-title {{
        margin: 0 0 0.5rem;
        font-size: 1.8rem;
    }}
    
    .document-authors {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem 1.5rem;
        margin-bottom: 0.5rem;
    }}
    
    .author {{
        display: flex;
        flex-direction: column;
        font-size: 0.95rem;
    }}
    
    .author.corresponding .author-name::after {{
        content: '*';
        margin-left: 0.25rem;
        color: #007acc;
    }}
    
    .author-affiliation {{
        color: #666;
        font-size: 0.85rem;
    }}
    
    .author-email {{
        font-size: 0.85rem;
        color: #007acc;
        text-decoration: none;
    }}
    
    .document-meta-line {{
        font-size: 0.85rem;
        color: #666;
        margin-top: 0.5rem;
    }}

    .debug-info {{
        margin: 2rem 0;
        padding: 1rem 1.25rem;
        background: #fff3cd;
        border: 1px dashed #d39e00;
        border-radius: 6px;
    }}

    .debug-info h2 {{
        margin-top: 0;
        font-size: 1.1rem;
    }}

    .debug-info pre {{
        white-space: pre-wrap;
        background: #f8f9fa;
        padding: 0.75rem;
        border-radius: 4px;
        overflow-x: auto;
    }}
    
    .sidebar {{
        float: right;
        width: 30%;
        margin: 0 0 1rem 2rem;
        padding: 1rem;
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 6px;
    }}
    
    .dialogue {{
        margin: 1rem 0;
        padding-left: 1rem;
        border-left: 3px solid #dee2e6;
    }}

    .summary {{
        margin: 1.5rem 0;
        padding: 1rem;
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 6px;
    }}
    
    .author-info {{
        margin: 1rem 0;
        font-size: 0.95rem;
    }}
    
    .appendix-heading {{
        margin-top: 2rem;
        border-top: 2px solid var(--border-color);
        padding-top: 1rem;
    }}
    
    .page_number, .running_head, .watermark {{
        font-size: 0.8rem;
        color: #999;
    }}

    /* Interactive UI */
    .reading-progress {{
        position: fixed;
        top: 0;
        left: 0;
        height: 3px;
        background: linear-gradient(90deg, #007acc, #00c6ff);
        z-index: 9999;
        transition: width 0.1s ease;
    }}
    
    .back-to-top {{
        position: fixed;
        bottom: 30px;
        right: 30px;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        background: #007acc;
        color: white;
        border: none;
        font-size: 1.1em;
        cursor: pointer;
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s;
        z-index: 1000;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    }}
    
    .back-to-top.visible {{
        opacity: 1;
        visibility: visible;
    }}
    
    .back-to-top:hover {{
        background: #0056b3;
        transform: translateY(-3px);
    }}
    
    .copy-button {{
        position: absolute;
        top: 8px;
        right: 8px;
        padding: 0.4em 0.8em;
        background: #007acc;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.85em;
        opacity: 0;
        transition: opacity 0.2s;
    }}
    
    pre:hover .copy-button {{
        opacity: 1;
    }}
    
    .copy-button:hover {{
        background: #0056b3;
    }}
    
    .search-highlight {{
        background: yellow;
        color: black;
        padding: 0.1em 0.2em;
        border-radius: 2px;
    }}
    
    .search-highlight.current {{
        background: orange;
    }}
    
    .toast {{
        position: fixed;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%) translateY(100px);
        background: #333;
        color: white;
        padding: 1em 1.5em;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        z-index: 10000;
        opacity: 0;
        transition: all 0.3s;
    }}
    
    .toast.show {{
        opacity: 1;
        transform: translateX(-50%) translateY(0);
    }}
    
    .search-box {{
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: white;
        border: 2px solid #007acc;
        border-radius: 25px;
        padding: 0.4em 0.8em;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    
    .search-box input {{
        border: none;
        outline: none;
        font-size: 1em;
        width: 260px;
        background: transparent;
        color: inherit;
    }}
    
    .search-counter {{
        color: #666;
        font-size: 0.9em;
        min-width: 60px;
        text-align: right;
    }}
    
    .search-prev, .search-next {{
        background: #007acc;
        color: white;
        border: none;
        border-radius: 12px;
        padding: 0.2em 0.6em;
        cursor: pointer;
        font-size: 0.85em;
    }}
    
    .search-prev:hover, .search-next:hover {{
        background: #0056b3;
    }}
    

    /* Special blocks */
    .special-block {{
        margin: 2rem 0;
        padding: 1.5rem;
        border-radius: 8px;
        border: 2px solid;
    }}

    .special-block-icon {{
        font-size: 1.4em;
        margin-right: 0.5rem;
        display: inline-block;
    }}

    .special-block-content {{
        margin-top: 0.5rem;
    }}
    
    .special-block-sidebar {{
        float: right;
        width: 30%;
        margin: 0 0 1rem 2rem;
        background: #f8f9fa;
        border-color: #dee2e6;
    }}
    
    .special-block-title {{
        margin-top: 0;
        font-size: 1.1em;
    }}
    
    .special-block.collapsible summary {{
        cursor: pointer;
        font-weight: 600;
        list-style: none;
        padding: 0.5rem 0;
    }}
    
    .special-block.collapsible summary::-webkit-details-marker {{
        display: none;
    }}
    
    .special-block.collapsible summary:before {{
        content: '> ';
        display: inline-block;
        transition: transform 0.2s;
    }}
    
    .special-block.collapsible[open] summary:before {{
        transform: rotate(90deg);
    }}
    
    /* Preformatted text */
    .preformatted {{
        white-space: pre-wrap;
        font-family: 'Courier New', monospace;
        background: #f5f5f5;
        padding: 1rem;
        border: 1px dashed #ccc;
        overflow-x: auto;
    }}
    
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

    .equation-inline {{
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
    .multi-column {{
        display: block;
        /* Don't use CSS column-count - it breaks our reading order sorting */
    }}
    
    .multi-column-3 {{
        display: block;
    }}
    
    /* For RTL multi-column, use column-fill and direction */
    [dir="rtl"] .multi-column {{
        direction: rtl;
    }}
    
    @media print {{
        body {{ background: white; padding: 0; }}
        .document-container {{ box-shadow: none; }}
        .page {{ padding: 20px; }}
        .toc, .list-of-figures, .list-of-tables, .list-of-equations {{
            background: none;
            border: none;
            padding: 0;
        }}
        .search-box, .theme-toggle, .back-to-top, .reading-progress, .toast, .copy-button {{
            display: none !important;
        }}
    }}
    
    @media (max-width: 600px) {{
        body {{ padding: 10px; }}
        .page {{ padding: 20px; }}
        .multi-column, .multi-column-3 {{ column-count: 1; }}
        .sidebar, .special-block-sidebar {{
            float: none;
            width: 100%;
            margin: 1rem 0;
        }}
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
        """Remove header/footer text from text_blocks if they appear there."""
        if page.header:
            # Remove any text block that exactly matches the header
            page.text_blocks = [b for b in page.text_blocks if b.content.strip() != page.header.strip()]
        
        if page.footer:
            # Remove any text block that exactly matches the footer
            page.text_blocks = [b for b in page.text_blocks if b.content.strip() != page.footer.strip()]
        
        return page
    
    @staticmethod
    def _render_page(
        page: PageContent,
        is_rtl: bool = False,
        include_images: bool = True,
        include_page_numbers: bool = True
    ) -> str:
        """Render a single page to HTML."""
        # Remove duplicate header/footer from text_blocks
        page = HTMLRenderer._deduplicate_header_footer(page)
        
        parts = []
        page_class = "page"
        
        # Check if entire page is English by analyzing all text content
        page_text = " ".join(block.content for block in page.text_blocks)
        is_english_page = HTMLRenderer._detect_english_content(page_text)
        
        # Override RTL for English pages
        page_dir = "ltr" if is_english_page else ("rtl" if is_rtl else "ltr")
        
        # Add multi-column indicator for debugging if needed
        if page.has_multi_column:
            page_class += " has-multi-column"
        
        # Add english-text class for English pages
        if is_english_page:
            page_class += " english-text"
        
        parts.append(f'<div class="{page_class}" id="page-{page.page_number}" style="position: relative;" dir="{page_dir}">')
        
        # Display actual header from PDF if available, otherwise show absolute page number
        if page.header:
            parts.append(f'<div class="page-header">{HTMLRenderer._escape(page.header)}</div>')
        elif include_page_numbers:
            parts.append(f'<div class="page-header">Page {page.page_number}</div>')
        
        # Wrap content in a container
        parts.append('<div class="page-content">')
        
        # Combine all elements with bbox positions for proper ordering
        # Sort by position to get correct reading flow
        elements = []
        insertion_order = 0
        
        # Add text blocks with their positions
        for block in page.text_blocks:
            y_pos = block.bbox_top if block.bbox_top is not None else (50 + insertion_order * 0.1)
            x_pos = block.bbox_left if block.bbox_left is not None else 0
            elements.append({
                'type': 'text',
                'y': y_pos,
                'x': x_pos,
                'order': insertion_order,
                'content': block
            })
            insertion_order += 1
        
        # Add tables with their positions
        for table in page.tables:
            y_pos = table.bbox_top if table.bbox_top is not None else (50 + insertion_order * 0.1)
            x_pos = table.bbox_left if table.bbox_left is not None else 0
            elements.append({
                'type': 'table',
                'y': y_pos,
                'x': x_pos,
                'order': insertion_order,
                'content': table
            })
            insertion_order += 1
        
        # Add images with their positions
        if include_images:
            for image in page.images:
                y_pos = image.bbox_top if image.bbox_top is not None else (50 + insertion_order * 0.1)
                x_pos = image.bbox_left if image.bbox_left is not None else 0
                elements.append({
                    'type': 'image',
                    'y': y_pos,
                    'x': x_pos,
                    'order': insertion_order,
                    'content': image
                })
                insertion_order += 1

        # Add code blocks with their positions
        for code_block in page.code_blocks:
            y_pos = code_block.bbox_top if code_block.bbox_top is not None else (50 + insertion_order * 0.1)
            x_pos = code_block.bbox_left if code_block.bbox_left is not None else 0
            elements.append({
                'type': 'code_block',
                'y': y_pos,
                'x': x_pos,
                'order': insertion_order,
                'content': code_block
            })
            insertion_order += 1

        # Add special blocks with their positions
        for special_block in page.special_blocks:
            y_pos = special_block.bbox_top if special_block.bbox_top is not None else (50 + insertion_order * 0.1)
            x_pos = special_block.bbox_left if special_block.bbox_left is not None else 0
            elements.append({
                'type': 'special_block',
                'y': y_pos,
                'x': x_pos,
                'order': insertion_order,
                'content': special_block
            })
            insertion_order += 1
        
        # Sort by position for correct reading flow
        # For multi-column: group by column (x), then sort by y within column
        # For single column: just sort by y, then x
        if page.has_multi_column and page.column_count and page.column_count > 1:
            # Multi-column: sort by column then y-position
            column_width = 100.0 / page.column_count
            
            def get_column(x_pos: float) -> int:
                """Determine column based on x position."""
                col = int(x_pos / column_width)
                return min(max(col, 0), page.column_count - 1)
            
            # For RTL (Arabic), rightmost column comes first
            if is_rtl:
                elements.sort(key=lambda e: (-(get_column(e['x'])), e['y'], e['order']))
            else:
                elements.sort(key=lambda e: (get_column(e['x']), e['y'], e['order']))
        else:
            # Single column: sort top to bottom, left to right
            elements.sort(key=lambda e: (e['y'], e['x'], e['order']))
        
        # Render elements in order, grouping consecutive list items
        footnotes = []  # Collect footnotes for end of page
        i = 0
        while i < len(elements):
            element = elements[i]
            
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
                    # Collect consecutive list items
                    while j < len(elements) and elements[j]['type'] == 'text' and elements[j]['content'].block_type == 'list_item':
                        list_items.append(elements[j]['content'])
                        j += 1
                    
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
            elif element['type'] == 'code_block':
                parts.append(HTMLRenderer._render_code_block(element['content']))
                i += 1
            elif element['type'] == 'special_block':
                parts.append(HTMLRenderer._render_special_block(element['content']))
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
        
        # Display actual footer from PDF if available
        if page.footer:
            parts.append(f'<div class="page-footer">{HTMLRenderer._escape(page.footer)}</div>')
        
        # Reading order notes removed - no longer needed for single-column flow
        
        parts.append("</div>")
        return "\n".join(parts)
    
    @staticmethod
    def _render_list(list_items: list[TextBlock]) -> str:
        """Render a group of consecutive list items as a proper HTML list."""
        if not list_items:
            return ""

        def _list_tag(list_type: Optional[str]) -> str:
            if list_type == "ordered":
                return "ol"
            if list_type == "definition":
                return "dl"
            return "ul"

        def _make_list(tag: str, marker_style: Optional[str]) -> dict:
            return {"tag": tag, "marker_style": marker_style, "items": []}

        roots: list[dict] = []
        stack: list[dict] = []

        for item in list_items:
            level = max(1, item.list_level or 1)
            if stack:
                level = min(level, len(stack) + 1)
            tag = _list_tag(item.list_type or "unordered")
            marker_style = item.list_marker_style

            # Adjust stack to current level
            while len(stack) > level:
                stack.pop()

            # Ensure a list exists at this level
            if len(stack) < level:
                while len(stack) < level:
                    new_list = _make_list(tag, marker_style)
                    if not stack:
                        roots.append(new_list)
                    else:
                        parent = stack[-1]
                        if parent["items"]:
                            parent["items"][-1]["sublists"].append(new_list)
                        else:
                            roots.append(new_list)
                    stack.append(new_list)
            else:
                current = stack[-1] if stack else None
                if current is None or current["tag"] != tag or current.get("marker_style") != marker_style:
                    new_list = _make_list(tag, marker_style)
                    if level == 1 or len(stack) < 2:
                        roots.append(new_list)
                    else:
                        parent = stack[-2]
                        if parent["items"]:
                            parent["items"][-1]["sublists"].append(new_list)
                        else:
                            roots.append(new_list)
                    stack[-1] = new_list

            current = stack[-1]
            if item.formatting:
                base_content = (
                    HTMLRenderer._render_inline_elements(item.inline_elements)
                    if item.inline_elements
                    else item.content
                )
                content, formatting_style = HTMLRenderer._apply_formatting(
                    base_content,
                    item.formatting,
                    escape=not item.inline_elements
                )
            else:
                content = (
                    HTMLRenderer._render_inline_elements(item.inline_elements)
                    if item.inline_elements
                    else HTMLRenderer._escape(item.content)
                )
                formatting_style = ""
            dir_attr = ""
            if item.text_direction and item.text_direction != "auto":
                dir_attr = f' dir="{item.text_direction}"'
            style_class = f" {item.style}" if item.style else ""
            if current["tag"] == "dl":
                term_attr = HTMLRenderer._build_block_attrs(item, item.element_id or item.anchor_name)
                class_attr = f' class="{style_class.strip()}"' if style_class else ""
                term_attr = f"{term_attr}{class_attr}{formatting_style}{dir_attr}"
                current["items"].append({"term": content, "term_attr": term_attr, "sublists": []})
            else:
                item_attr = HTMLRenderer._build_block_attrs(item, item.element_id or item.anchor_name)
                class_attr = f' class="{style_class.strip()}"' if style_class else ""
                item_attr = f"{item_attr}{class_attr}{formatting_style}{dir_attr}"
                current["items"].append({"content": content, "item_attr": item_attr, "sublists": []})

        def _render_list_node(node: dict) -> str:
            tag = node["tag"]
            style_attr = ""
            if node.get("marker_style") and tag in ("ul", "ol"):
                style_attr = f' style="list-style-type: {HTMLRenderer._escape(node["marker_style"])};"'
            parts = [f'<{tag} class="list-wrapper"{style_attr}>']
            if tag == "dl":
                for item in node["items"]:
                    parts.append(f"<dt{item['term_attr']}>{item['term']}</dt>")
                    for sublist in item["sublists"]:
                        parts.append(_render_list_node(sublist))
            else:
                for item in node["items"]:
                    parts.append(f"<li{item['item_attr']}>")
                    parts.append(item["content"])
                    for sublist in item["sublists"]:
                        parts.append(_render_list_node(sublist))
                    parts.append("</li>")
            parts.append(f"</{tag}>")
            return "\n".join(parts)

        return "\n".join(_render_list_node(node) for node in roots)

    @staticmethod
    def _render_inline_elements(elements: list[InlineElement]) -> str:
        """Render inline elements as HTML."""
        parts = []
        for elem in elements:
            content = HTMLRenderer._escape(elem.content)
            if elem.type == "text":
                parts.append(content)
            elif elem.type == "link":
                if elem.url:
                    href = HTMLRenderer._escape(elem.url)
                    parts.append(f'<a href="{href}">{content}</a>')
                elif elem.target_id:
                    target = HTMLRenderer._escape(elem.target_id)
                    parts.append(f'<a href="#{target}">{content}</a>')
                else:
                    parts.append(content)
            elif elem.type == "strong":
                parts.append(f"<strong>{content}</strong>")
            elif elem.type == "emphasis":
                parts.append(f"<em>{content}</em>")
            elif elem.type == "code":
                parts.append(f"<code>{content}</code>")
            else:
                parts.append(content)
        return "".join(parts)

    @staticmethod
    def _find_explicit_math_ranges(text: str) -> list[tuple[int, int]]:
        """Find ranges already wrapped in MathJax delimiters."""
        ranges = []
        for pattern in (r'\\\(.+?\\\)', r'\\\[.+?\\\]'):
            for match in re.finditer(pattern, text, flags=re.DOTALL):
                ranges.append((match.start(), match.end()))
        ranges.sort()
        return ranges

    @staticmethod
    def _detect_inline_math_spans(text: str) -> list[tuple[int, int]]:
        """Detect likely inline math spans containing TeX commands."""
        if not text or "$" in text:
            return []

        explicit_ranges = HTMLRenderer._find_explicit_math_ranges(text)
        command_matches = list(re.finditer(r'\\[a-zA-Z]+', text))
        if not command_matches:
            return []

        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\\{}_^=+-*/().,<> ")
        spans = []

        def in_explicit_range(idx: int) -> bool:
            for start, end in explicit_ranges:
                if start <= idx < end:
                    return True
            return False

        for match in command_matches:
            if in_explicit_range(match.start()):
                continue
            left = match.start()
            while left > 0 and text[left - 1] in allowed:
                left -= 1
            right = match.end()
            while right < len(text) and text[right] in allowed:
                right += 1
            if right - left > 80:
                continue
            spans.append((left, right))

        if not spans:
            return []

        spans.sort()
        merged = [spans[0]]
        for start, end in spans[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def _normalize_inline_math(text: str) -> str:
        """Normalize common inline math tokens (e.g., greek names)."""
        math_text = text.strip()
        greek_map = {
            "alpha": "\\alpha",
            "beta": "\\beta",
            "gamma": "\\gamma",
            "delta": "\\delta",
            "epsilon": "\\epsilon",
            "theta": "\\theta",
            "lambda": "\\lambda",
            "mu": "\\mu",
            "pi": "\\pi",
            "sigma": "\\sigma",
            "phi": "\\phi",
            "omega": "\\omega",
        }
        for word, latex in greek_map.items():
            math_text = re.sub(rf"\\b{word}\\b", latex, math_text, flags=re.IGNORECASE)
        return math_text

    @staticmethod
    def _render_text_with_inline_math(text: str) -> str:
        """Render text and wrap likely inline TeX with MathJax delimiters."""
        spans = HTMLRenderer._detect_inline_math_spans(text)
        if not spans:
            return HTMLRenderer._escape(text)

        parts = []
        cursor = 0
        for start, end in spans:
            if start > cursor:
                parts.append(HTMLRenderer._escape(text[cursor:start]))
            math_text = HTMLRenderer._normalize_inline_math(text[start:end])
            parts.append(f'<span class="equation-inline">\\({math_text}\\)</span>')
            cursor = end
        if cursor < len(text):
            parts.append(HTMLRenderer._escape(text[cursor:]))
        return "".join(parts)

    @staticmethod
    def _apply_formatting(content: str, formatting: TextFormatting, escape: bool = True) -> tuple[str, str]:
        """Apply structured formatting to text and return (content_html, style_attr)."""
        text = HTMLRenderer._escape(content) if escape else content

        if formatting.bold:
            text = f"<strong>{text}</strong>"
        if formatting.italic:
            text = f"<em>{text}</em>"
        if formatting.underline:
            text = f"<u>{text}</u>"
        if formatting.strikethrough:
            text = f"<s>{text}</s>"
        if formatting.superscript:
            text = f"<sup>{text}</sup>"
        if formatting.subscript:
            text = f"<sub>{text}</sub>"

        styles = []
        if formatting.text_color:
            styles.append(f"color: {formatting.text_color}")
        if formatting.background_color:
            styles.append(f"background-color: {formatting.background_color}")
        if formatting.font_family:
            styles.append(f"font-family: {formatting.font_family}")
        elif formatting.monospace:
            styles.append("font-family: 'Consolas', 'Monaco', monospace")
        if formatting.font_size:
            size_map = {
                "xx-small": "0.6em",
                "x-small": "0.75em",
                "small": "0.875em",
                "normal": "1em",
                "large": "1.25em",
                "x-large": "1.5em",
                "xx-large": "2em",
            }
            styles.append(f"font-size: {size_map.get(formatting.font_size, '1em')}")
        if formatting.alignment:
            styles.append(f"text-align: {formatting.alignment}")
        if formatting.line_height:
            line_height_map = {
                "single": "1",
                "1.5": "1.5",
                "double": "2",
            }
            styles.append(f"line-height: {line_height_map.get(formatting.line_height, '1.5')}")
        if formatting.indent_level is not None:
            styles.append(f"margin-left: {formatting.indent_level * 2}em")

        style_attr = f' style="{"; ".join(styles)}"' if styles else ""
        return text, style_attr

    @staticmethod
    def _normalize_id(prefix: str, raw_id: Optional[str]) -> str:
        """Ensure IDs are namespaced with a prefix."""
        if not raw_id:
            return ""
        if raw_id.startswith(f"{prefix}-"):
            return raw_id
        return f"{prefix}-{raw_id}"

    @staticmethod
    def _build_block_attrs(block: TextBlock, element_id: Optional[str] = None) -> str:
        """Build common HTML attributes for text blocks."""
        attrs = []
        if element_id:
            attrs.append(f'id="{HTMLRenderer._escape(element_id)}"')
        if block.anchor_name:
            attrs.append(f'data-anchor="{HTMLRenderer._escape(block.anchor_name)}"')
        if block.references:
            refs = " ".join(block.references)
            if refs:
                attrs.append(f'data-refs="{HTMLRenderer._escape(refs)}"')
        if block.block_label:
            attrs.append(f'data-block-label="{HTMLRenderer._escape(block.block_label)}"')
        if block.block_number:
            attrs.append(f'data-block-number="{HTMLRenderer._escape(block.block_number)}"')
        return f' {" ".join(attrs)}' if attrs else ""

    @staticmethod
    def _build_block_label(label: str, block_number: Optional[str]) -> str:
        """Build label text with optional block number without duplication."""
        if not block_number:
            return label
        number_text = block_number.strip()
        if number_text.lower().startswith(label.lower()):
            return number_text
        return f"{label} {number_text}"

    @staticmethod
    def _heading_anchor_id(block: TextBlock) -> str:
        """Return normalized anchor ID for a heading block."""
        raw_id = block.element_id or block.anchor_name
        return HTMLRenderer._normalize_id("section", raw_id)

    @staticmethod
    def _figure_anchor_id(image: Image) -> str:
        """Return normalized anchor ID for a figure."""
        raw_id = image.figure_id or f"bbox-{image.bbox_top}-{image.bbox_left}"
        return HTMLRenderer._normalize_id("figure", raw_id)

    @staticmethod
    def _table_anchor_id(table: Table) -> str:
        """Return normalized anchor ID for a table."""
        raw_id = table.table_id or f"bbox-{table.bbox_top}-{table.bbox_left}"
        return HTMLRenderer._normalize_id("table", raw_id)

    @staticmethod
    def _equation_anchor_id(block: TextBlock) -> str:
        """Return normalized anchor ID for an equation block."""
        raw_id = block.element_id or block.equation_number
        return HTMLRenderer._normalize_id("equation", raw_id)

    @staticmethod
    def _ensure_heading_ids(doc: DocumentStructure) -> None:
        """Assign fallback element IDs to headings when missing."""
        for page in doc.pages:
            heading_index = 0
            for block in page.text_blocks:
                if block.block_type in ("heading", "appendix_heading"):
                    if not block.element_id and not block.anchor_name:
                        block.element_id = f"p{page.page_number}-h{heading_index}"
                    heading_index += 1

    @staticmethod
    def _generate_toc(doc: DocumentStructure) -> str:
        """Generate table of contents from headings or explicit TOC."""
        if doc.table_of_contents:
            return HTMLRenderer._render_explicit_toc(doc.table_of_contents)
        return HTMLRenderer._render_auto_toc(doc)

    @staticmethod
    def _render_explicit_toc(toc_entries: list[TOCEntry]) -> str:
        """Render explicit table of contents with proper nesting."""
        if not toc_entries:
            return ""

        def render_entries(entries: list[TOCEntry]) -> str:
            parts = ['<ol class="toc-list">']
            for entry in entries:
                indent_class = f"toc-level-{entry.level}"
                section_id = HTMLRenderer._normalize_id("section", entry.section_id)
                parts.append(
                    f'<li class="{indent_class}">'
                    f'<a href="#{section_id}">{HTMLRenderer._escape(entry.title)}</a>'
                    f'<span class="toc-page">Page {entry.page_number}</span>'
                )
                if entry.subsections:
                    parts.append(render_entries(entry.subsections))
                parts.append("</li>")
            parts.append("</ol>")
            return "\n".join(parts)

        parts = [
            '<nav role="navigation" aria-label="Table of Contents" class="toc">',
            '<h2>Table of Contents</h2>',
            render_entries(toc_entries),
            '</nav>'
        ]
        return "\n".join(parts)

    @staticmethod
    def _render_auto_toc(doc: DocumentStructure) -> str:
        """Auto-generate TOC from headings in the document."""
        toc_entries = []

        for page in doc.pages:
            for block in page.text_blocks:
                if block.block_type in ("heading", "appendix_heading"):
                    level = block.level or (2 if block.block_type == "appendix_heading" else None)
                    if not level:
                        continue
                    section_id = HTMLRenderer._heading_anchor_id(block)
                    if not section_id:
                        continue
                    toc_entries.append({
                        "level": level,
                        "title": block.content,
                        "page_number": page.page_number,
                        "section_id": section_id
                    })

        if not toc_entries:
            return ""

        parts = [
            '<nav role="navigation" aria-label="Table of Contents" class="toc auto-generated">',
            '<h2>Table of Contents</h2>',
            '<ol class="toc-list">'
        ]

        for entry in toc_entries:
            indent_class = f"toc-level-{entry['level']}"
            parts.append(
                f'<li class="{indent_class}">'
                f'<a href="#{entry["section_id"]}">{HTMLRenderer._escape(entry["title"])}</a>'
                f'<span class="toc-page">Page {entry["page_number"]}</span></li>'
            )

        parts.extend(['</ol>', '</nav>'])
        return "\n".join(parts)

    @staticmethod
    def _render_list_of_figures(figures: list[FigureReference]) -> str:
        """Render list of figures."""
        if not figures:
            return ""

        parts = [
            '<nav role="navigation" aria-label="List of Figures" class="list-of-figures">',
            '<h2>List of Figures</h2>',
            '<ol class="figure-list">'
        ]

        for fig in figures:
            figure_id = HTMLRenderer._normalize_id("figure", fig.figure_id)
            parts.append(
                f'<li>'
                f'<a href="#{figure_id}">'
                f'<span class="figure-number">{HTMLRenderer._escape(fig.figure_number)}</span> '
                f'{HTMLRenderer._escape(fig.caption)}</a>'
                f'<span class="figure-page">Page {fig.page_number}</span>'
                f'</li>'
            )

        parts.extend(['</ol>', '</nav>'])
        return "\n".join(parts)

    @staticmethod
    def _render_list_of_tables(tables: list[TableReference]) -> str:
        """Render list of tables."""
        if not tables:
            return ""

        parts = [
            '<nav role="navigation" aria-label="List of Tables" class="list-of-tables">',
            '<h2>List of Tables</h2>',
            '<ol class="table-list">'
        ]

        for tbl in tables:
            table_id = HTMLRenderer._normalize_id("table", tbl.table_id)
            parts.append(
                f'<li>'
                f'<a href="#{table_id}">'
                f'<span class="table-number">{HTMLRenderer._escape(tbl.table_number)}</span> '
                f'{HTMLRenderer._escape(tbl.caption)}</a>'
                f'<span class="table-page">Page {tbl.page_number}</span>'
                f'</li>'
            )

        parts.extend(['</ol>', '</nav>'])
        return "\n".join(parts)

    @staticmethod
    def _render_list_of_equations(equations: list[EquationReference]) -> str:
        """Render list of equations."""
        if not equations:
            return ""

        parts = [
            '<nav role="navigation" aria-label="List of Equations" class="list-of-equations">',
            '<h2>List of Equations</h2>',
            '<ol class="equation-list">'
        ]

        for eq in equations:
            equation_id = HTMLRenderer._normalize_id("equation", eq.equation_id)
            parts.append(
                f'<li>'
                f'<a href="#{equation_id}">'
                f'<span class="equation-number">{HTMLRenderer._escape(eq.equation_number)}</span> '
                f'{HTMLRenderer._escape(eq.equation_preview)}</a>'
                f'<span class="equation-page">Page {eq.page_number}</span>'
                f'</li>'
            )

        parts.extend(['</ol>', '</nav>'])
        return "\n".join(parts)

    @staticmethod
    def _render_bibliography(citations: list[Citation]) -> str:
        """Render bibliography section."""
        if not citations:
            return ""

        parts = [
            '<section class="bibliography" role="doc-bibliography">',
            '<h2>References</h2>',
            '<ol class="bibliography-list">'
        ]

        for citation in citations:
            citation_id = HTMLRenderer._normalize_id("citation", citation.citation_id)
            parts.append(f'<li id="{HTMLRenderer._escape(citation_id)}">')

            if citation.citation_style == "APA":
                formatted = HTMLRenderer._format_apa_citation(citation)
            elif citation.citation_style == "MLA":
                formatted = HTMLRenderer._format_mla_citation(citation)
            else:
                formatted = HTMLRenderer._format_generic_citation(citation)

            parts.append(formatted)
            parts.append('</li>')

        parts.extend(['</ol>', '</section>'])
        return "\n".join(parts)

    @staticmethod
    def _format_apa_citation(citation: Citation) -> str:
        """Format citation in APA style."""
        parts = []

        if citation.authors:
            author_str = ", ".join(citation.authors)
            parts.append(f'{HTMLRenderer._escape(author_str)}.')

        if citation.year:
            parts.append(f'({citation.year}).')

        parts.append(f'<em>{HTMLRenderer._escape(citation.title)}</em>.')

        if citation.journal:
            journal_str = citation.journal
            if citation.volume:
                journal_str += f", {citation.volume}"
            if citation.pages:
                journal_str += f", {citation.pages}"
            parts.append(f'{HTMLRenderer._escape(journal_str)}.')

        if citation.doi:
            parts.append(f'https://doi.org/{HTMLRenderer._escape(citation.doi)}')
        elif citation.url:
            url = HTMLRenderer._escape(citation.url)
            parts.append(f'<a href="{url}">{url}</a>')

        return " ".join(parts)

    @staticmethod
    def _format_mla_citation(citation: Citation) -> str:
        """Format citation in MLA style."""
        parts = []

        if citation.authors:
            author_str = ", ".join(citation.authors)
            parts.append(f'{HTMLRenderer._escape(author_str)}.')

        parts.append(f'"{HTMLRenderer._escape(citation.title)}."')

        if citation.journal:
            journal_str = citation.journal
            if citation.volume:
                journal_str += f", vol. {citation.volume}"
            if citation.pages:
                journal_str += f", pp. {citation.pages}"
            if citation.year:
                journal_str += f", {citation.year}"
            parts.append(f'{HTMLRenderer._escape(journal_str)}.')
        elif citation.publisher:
            publisher_parts = [citation.publisher]
            if citation.year:
                publisher_parts.append(str(citation.year))
            parts.append(f'{HTMLRenderer._escape(", ".join(publisher_parts))}.')

        if citation.doi:
            parts.append(f'https://doi.org/{HTMLRenderer._escape(citation.doi)}')
        elif citation.url:
            url = HTMLRenderer._escape(citation.url)
            parts.append(f'<a href="{url}">{url}</a>')

        return " ".join(parts)

    @staticmethod
    def _format_generic_citation(citation: Citation) -> str:
        """Format citation in a generic style."""
        parts = []

        if citation.authors:
            parts.append(HTMLRenderer._escape(", ".join(citation.authors)))

        if citation.title:
            parts.append(f'"{HTMLRenderer._escape(citation.title)}"')

        if citation.journal:
            parts.append(HTMLRenderer._escape(citation.journal))

        if citation.year:
            parts.append(str(citation.year))

        if citation.doi:
            parts.append(f'https://doi.org/{HTMLRenderer._escape(citation.doi)}')
        elif citation.url:
            url = HTMLRenderer._escape(citation.url)
            parts.append(f'<a href="{url}">{url}</a>')

        return " ".join(parts)

    @staticmethod
    def _render_glossary(glossary: dict[str, str]) -> str:
        """Render glossary section."""
        if not glossary:
            return ""

        parts = [
            '<section class="glossary" role="doc-glossary">',
            '<h2>Glossary</h2>',
            '<dl class="glossary-list">'
        ]
        for term, definition in glossary.items():
            parts.append(f'<dt>{HTMLRenderer._escape(term)}</dt>')
            parts.append(f'<dd>{HTMLRenderer._escape(definition)}</dd>')
        parts.extend(['</dl>', '</section>'])
        return "\n".join(parts)

    @staticmethod
    def _render_document_footnotes(footnotes: dict[str, str]) -> str:
        """Render document-level footnotes."""
        if not footnotes:
            return ""

        parts = [
            '<section class="document-footnotes" role="doc-endnotes">',
            '<h2>Footnotes</h2>',
            '<ol class="footnotes-list">'
        ]
        for marker, note in footnotes.items():
            parts.append(f'<li><span class="footnote-marker">{HTMLRenderer._escape(marker)}</span> {HTMLRenderer._escape(note)}</li>')
        parts.extend(['</ol>', '</section>'])
        return "\n".join(parts)

    @staticmethod
    def _render_document_metadata(metadata: DocumentMetadata) -> str:
        """Render document-level metadata such as authors, abstract, and keywords."""
        has_metadata = any([
            metadata.title,
            metadata.author,
            metadata.authors,
            metadata.affiliations,
            metadata.keywords,
            metadata.abstract,
            metadata.doi,
            metadata.publication_date,
            metadata.copyright,
            metadata.license,
        ])
        if not has_metadata:
            return ""

        parts = ['<section class="document-metadata" role="doc-introduction">']

        if metadata.title:
            parts.append(f'<h1 class="document-title">{HTMLRenderer._escape(metadata.title)}</h1>')

        if metadata.authors:
            parts.append('<div class="document-authors">')
            for author in metadata.authors:
                classes = "author"
                if author.corresponding:
                    classes += " corresponding"
                parts.append(f'<div class="{classes}">')
                parts.append(f'<span class="author-name">{HTMLRenderer._escape(author.name)}</span>')
                if author.affiliation:
                    parts.append(f'<span class="author-affiliation">{HTMLRenderer._escape(author.affiliation)}</span>')
                if author.email:
                    email = HTMLRenderer._escape(author.email)
                    parts.append(f'<a class="author-email" href="mailto:{email}">{email}</a>')
                if author.orcid:
                    parts.append(f'<span class="author-orcid">{HTMLRenderer._escape(author.orcid)}</span>')
                parts.append('</div>')
            parts.append('</div>')
        elif metadata.author:
            parts.append(f'<div class="document-author">{HTMLRenderer._escape(metadata.author)}</div>')

        if metadata.affiliations:
            parts.append('<div class="document-affiliations">')
            for affiliation in metadata.affiliations:
                parts.append(f'<div class="affiliation">{HTMLRenderer._escape(affiliation)}</div>')
            parts.append('</div>')

        meta_line_parts = []
        if metadata.publication_date:
            meta_line_parts.append(f'Published: {HTMLRenderer._escape(metadata.publication_date)}')
        if metadata.doi:
            meta_line_parts.append(f'DOI: {HTMLRenderer._escape(metadata.doi)}')
        if metadata.license:
            meta_line_parts.append(f'License: {HTMLRenderer._escape(metadata.license)}')
        if metadata.copyright:
            meta_line_parts.append(f'Copyright: {HTMLRenderer._escape(metadata.copyright)}')
        if meta_line_parts:
            parts.append(f'<div class="document-meta-line">{" | ".join(meta_line_parts)}</div>')

        if metadata.abstract:
            parts.append(
                '<section class="abstract" role="doc-abstract">'
                '<h2>Abstract</h2>'
                f'<p>{HTMLRenderer._escape(metadata.abstract)}</p>'
                '</section>'
            )

        if metadata.keywords:
            keyword_spans = [f'<span class="keyword">{HTMLRenderer._escape(kw)}</span>' for kw in metadata.keywords]
            parts.append(
                '<div class="keywords">'
                '<strong>Keywords:</strong> '
                f'{", ".join(keyword_spans)}'
                '</div>'
            )

        parts.append('</section>')
        return "\n".join(parts)

    @staticmethod
    def _auto_generate_figures(doc: DocumentStructure) -> list[FigureReference]:
        """Auto-generate list of figures from images."""
        figures: list[FigureReference] = []
        figure_counter = 1

        for page in doc.pages:
            for image in page.images:
                if not image.caption and not image.figure_number:
                    continue
                figure_number = image.figure_number or f"Figure {figure_counter}"
                figure_counter += 1
                figure_id = image.figure_id or HTMLRenderer._figure_anchor_id(image)
                if figure_id.startswith("figure-"):
                    figure_id = figure_id[len("figure-"):]
                figures.append(FigureReference(
                    figure_number=figure_number,
                    caption=image.caption or "",
                    page_number=page.page_number,
                    figure_id=figure_id,
                    image_type=image.image_type
                ))
        return figures

    @staticmethod
    def _auto_generate_tables(doc: DocumentStructure) -> list[TableReference]:
        """Auto-generate list of tables from tables."""
        tables: list[TableReference] = []
        table_counter = 1

        for page in doc.pages:
            for table in page.tables:
                if not table.caption and not table.table_number:
                    continue
                table_number = table.table_number or f"Table {table_counter}"
                table_counter += 1
                table_id = table.table_id or HTMLRenderer._table_anchor_id(table)
                if table_id.startswith("table-"):
                    table_id = table_id[len("table-"):]
                row_count = len(table.structured_rows) if table.structured_rows else len(table.rows)
                column_count = 0
                if table.structured_rows and table.structured_rows[0].cells:
                    column_count = len(table.structured_rows[0].cells)
                elif table.rows and len(table.rows[0]) > 0:
                    column_count = len(table.rows[0])
                tables.append(TableReference(
                    table_number=table_number,
                    caption=table.caption or "",
                    page_number=page.page_number,
                    table_id=table_id,
                    row_count=row_count,
                    column_count=column_count
                ))
        return tables

    @staticmethod
    def _auto_generate_equations(doc: DocumentStructure) -> list[EquationReference]:
        """Auto-generate list of numbered equations."""
        equations: list[EquationReference] = []

        for page in doc.pages:
            for block in page.text_blocks:
                if block.block_type != "equation" or not block.equation_number:
                    continue
                equation_id = HTMLRenderer._equation_anchor_id(block)
                if equation_id.startswith("equation-"):
                    equation_id = equation_id[len("equation-"):]
                preview = block.content.strip().replace("\n", " ")
                if len(preview) > 50:
                    preview = preview[:50] + "..."
                equations.append(EquationReference(
                    equation_number=block.equation_number,
                    page_number=page.page_number,
                    equation_id=equation_id,
                    equation_preview=preview
                ))
        return equations
    
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
    def _render_text_block(block: TextBlock) -> str:
        """Render a text block to HTML."""
        content_is_html = False
        if block.formatting:
            base_content = (
                HTMLRenderer._render_inline_elements(block.inline_elements)
                if block.inline_elements
                else block.content
            )
            if block.inline_elements:
                content_is_html = True
            else:
                base_content = HTMLRenderer._render_text_with_inline_math(base_content)
                content_is_html = True
            content, formatting_style = HTMLRenderer._apply_formatting(
                base_content,
                block.formatting,
                escape=not content_is_html
            )
        else:
            content = (
                HTMLRenderer._render_inline_elements(block.inline_elements)
                if block.inline_elements
                else HTMLRenderer._render_text_with_inline_math(block.content)
            )
            formatting_style = ""
        
        # Don't use bbox positioning for single-column flow
        # Let content flow naturally without horizontal positioning
        bbox_style = ""
        bbox_class = ""
        dir_attr = ""
        if block.text_direction and block.text_direction != "auto":
            dir_attr = f' dir="{block.text_direction}"'
        style_class = f" {block.style}" if block.style else ""
        
        if block.block_type == "heading":
            level = min(max(block.level or 1, 1), 6)
            classes = []
            if block.style:
                classes.append(block.style)
            if bbox_class:
                classes.append(bbox_class.strip())
            
            # Add LTR class for English content
            if HTMLRenderer._detect_english_content(block.content):
                classes.append("ltr")
            
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            heading_id = HTMLRenderer._heading_anchor_id(block)
            attr_str = HTMLRenderer._build_block_attrs(block, heading_id)
            return f"<h{level}{class_attr}{attr_str}{formatting_style}{dir_attr}{bbox_style}>{content}</h{level}>"
        
        elif block.block_type == "paragraph":
            classes = []
            if block.style:
                classes.append(block.style)
            if bbox_class:
                classes.append(bbox_class.strip())
            
            # Add LTR class for English content
            if HTMLRenderer._detect_english_content(block.content):
                classes.append("ltr")
            
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f"<p{class_attr}{attr_str}{formatting_style}{dir_attr}{bbox_style}>{content}</p>"
        
        elif block.block_type == "list_item":
            # This shouldn't be called directly anymore - lists are grouped
            # But keep for backwards compatibility
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f"<li{attr_str}{formatting_style}{dir_attr}>{content}</li>"
        
        elif block.block_type == "caption":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<p class="caption{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</p>'
        
        elif block.block_type == "footnote":
            # Footnotes are now grouped at page end, but keep for fallback
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<div class="footnote{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</div>'
        
        elif block.block_type == "quote":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f"<blockquote class=\"{style_class.strip()}\"{attr_str}{formatting_style}{dir_attr}>{content}</blockquote>" if style_class else f"<blockquote{attr_str}{formatting_style}{dir_attr}>{content}</blockquote>"
        
        elif block.block_type == "code":
            code_content = HTMLRenderer._escape(block.content)
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            lang_class = f'language-{block.language}' if block.language else ""
            class_attr = f' class="{lang_class}"' if lang_class else ""
            pre_class_attr = f' class="{style_class.strip()}"' if style_class else ""
            return f"<pre{pre_class_attr}{attr_str}{formatting_style}{dir_attr}><code{class_attr}>{code_content}</code></pre>"
        
        elif block.block_type == "equation":
            # Render LaTeX equations with MathJax
            # Don't escape the content - it's already LaTeX
            raw_content = block.content  # Use raw content, not escaped
            
            # Clean equation content (remove Arabic text captions)
            cleaned_equation, arabic_caption = HTMLRenderer._clean_equation_content(raw_content)
            
            # If no real equation content (just Arabic label), render as styled paragraph
            if not cleaned_equation or len(cleaned_equation.strip()) < 3:
                equation_id = HTMLRenderer._equation_anchor_id(block)
                attr_str = HTMLRenderer._build_block_attrs(block, equation_id)
                return f'<p class="equation-caption" dir="rtl"{attr_str}>{arabic_caption}</p>'
            
            # Check if content already has delimiters
            has_display_delimiters = cleaned_equation.strip().startswith('\\[') or cleaned_equation.strip().startswith('$$')
            has_inline_delimiters = cleaned_equation.strip().startswith('\\(') or cleaned_equation.strip().startswith('$')
            
            result_parts = []
            
            equation_id = HTMLRenderer._equation_anchor_id(block)
            equation_attr = HTMLRenderer._build_block_attrs(block, equation_id)

            if block.is_display_math:
                # Display mode: centered, on its own line
                if has_display_delimiters:
                    result_parts.append(f'<div class="equation"{equation_attr}>{cleaned_equation}</div>')
                else:
                    result_parts.append(f'<div class="equation"{equation_attr}>\\[{cleaned_equation}\\]</div>')
            else:
                # Inline mode
                if has_inline_delimiters:
                    result_parts.append(f'<span class="equation-inline"{equation_attr}>{cleaned_equation}</span>')
                else:
                    result_parts.append(f'<span class="equation-inline"{equation_attr}>\\({cleaned_equation}\\)</span>')
            
            # Add Arabic caption as separate paragraph if present
            if arabic_caption:
                result_parts.append(f'<p class="equation-caption" dir="rtl">{arabic_caption}</p>')
            
            return '\n'.join(result_parts)

        elif block.block_type in ("theorem", "lemma", "corollary", "proposition"):
            label = HTMLRenderer._build_block_label(block.block_type.title(), block.block_number)
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<div class="{block.block_type}{style_class}"{attr_str}{formatting_style}{dir_attr}>'
                f'<strong class="{block.block_type}-label">{HTMLRenderer._escape(label)}:</strong> '
                f'<span class="{block.block_type}-content">{content}</span>'
                f'</div>'
            )

        elif block.block_type in ("definition", "example", "remark", "note"):
            label = HTMLRenderer._build_block_label(block.block_type.title(), block.block_number)
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<div class="{block.block_type}{style_class}"{attr_str}{formatting_style}{dir_attr}>'
                f'<strong class="{block.block_type}-label">{HTMLRenderer._escape(label)}:</strong> '
                f'<span class="{block.block_type}-content">{content}</span>'
                f'</div>'
            )

        elif block.block_type == "proof":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<div class="proof{style_class}"{attr_str}{formatting_style}{dir_attr}>'
                f'<em class="proof-label">Proof:</em> '
                f'{content}'
                f'<span class="qed">&#9632;</span>'
                f'</div>'
            )

        elif block.block_type == "abstract":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<section class="abstract{style_class}" role="doc-abstract"{attr_str}{formatting_style}{dir_attr}>'
                f'<h2>Abstract</h2>'
                f'<p>{content}</p>'
                f'</section>'
            )

        elif block.block_type == "summary":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<section class="summary{style_class}"{attr_str}{formatting_style}{dir_attr}>'
                f'<h2>Summary</h2>'
                f'<p>{content}</p>'
                f'</section>'
            )

        elif block.block_type == "keywords":
            raw_keywords = block.content
            keywords = raw_keywords.split(",") if "," in raw_keywords else raw_keywords.split()
            keyword_spans = [f'<span class="keyword">{HTMLRenderer._escape(kw.strip())}</span>' for kw in keywords if kw.strip()]
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<div class="keywords{style_class}"{attr_str}{formatting_style}{dir_attr}>'
                f'<strong>Keywords:</strong> '
                f'{", ".join(keyword_spans)}'
                f'</div>'
            )

        elif block.block_type == "author_info":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<div class="author-info{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</div>'

        elif block.block_type == "acknowledgments":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<section class="acknowledgments{style_class}" role="doc-acknowledgments"{attr_str}{formatting_style}{dir_attr}>'
                f'<h2>Acknowledgments</h2>'
                f'<p>{content}</p>'
                f'</section>'
            )

        elif block.block_type == "appendix_heading":
            level = min(max(block.level or 2, 1), 6)
            heading_id = HTMLRenderer._heading_anchor_id(block)
            attr_str = HTMLRenderer._build_block_attrs(block, heading_id)
            return f'<h{level} class="appendix-heading{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</h{level}>'

        elif block.block_type in ("warning", "tip", "important", "note", "callout", "question", "answer", "exercise", "solution"):
            icon_map = {
                "warning": "!",
                "tip": "*",
                "important": "!",
                "note": "*",
                "callout": "*",
                "question": "?",
                "answer": "*",
                "exercise": "!",
                "solution": "*",
            }
            icon = icon_map.get(block.block_type, "*")
            severity_class = f"severity-{block.severity}" if block.severity else ""
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return (
                f'<div class="callout callout-{block.block_type} {severity_class}{style_class}" role="note"{attr_str}{formatting_style}{dir_attr}>'
                f'<div class="callout-icon">{HTMLRenderer._escape(icon)}</div>'
                f'<div class="callout-content">{content}</div>'
                f'</div>'
            )

        elif block.block_type == "sidebar":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<aside class="sidebar{style_class}" role="complementary"{attr_str}{formatting_style}{dir_attr}>{content}</aside>'

        elif block.block_type in ("verse", "poetry"):
            lines = HTMLRenderer._escape(block.content).split("\n")
            verse_lines = "<br>".join([f'<span class="verse-line">{line}</span>' for line in lines])
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<div class="verse{style_class}"{attr_str}{formatting_style}{dir_attr}>{verse_lines}</div>'

        elif block.block_type == "dialogue":
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<div class="dialogue{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</div>'

        elif block.block_type == "preformatted":
            pre_content = HTMLRenderer._escape(block.content)
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<pre class="preformatted{style_class}"{attr_str}{formatting_style}{dir_attr}>{pre_content}</pre>'

        elif block.block_type in ("page_number", "running_head", "watermark"):
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<span class="{block.block_type}{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</span>'

        elif block.block_type in ("reference", "citation_inline", "bibliography_entry"):
            block_id = block.element_id or block.anchor_name
            attr_str = HTMLRenderer._build_block_attrs(block, block_id)
            return f'<span class="{block.block_type}{style_class}"{attr_str}{formatting_style}{dir_attr}>{content}</span>'
        
        return f"<p{formatting_style}{dir_attr}>{content}</p>"

    @staticmethod
    def _render_code_block(code_block: CodeBlock) -> str:
        """Render code block with syntax highlighting."""
        escaped_code = HTMLRenderer._escape(code_block.code)
        lang_class = f'language-{code_block.language}' if code_block.language else 'language-none'

        if code_block.line_numbers:
            lines = escaped_code.split("\n")
            numbered_lines = []
            highlight_set = set(code_block.highlight_lines or [])
            for i, line in enumerate(lines, start=code_block.start_line):
                line_class = 'highlight-line' if i in highlight_set else ''
                numbered_lines.append(
                    f'<span class="line-number">{i}</span>'
                    f'<span class="line-content {line_class}">{line}</span>'
                )
            code_content = "\n".join(numbered_lines)
            pre_class = "line-numbers"
        else:
            code_content = escaped_code
            pre_class = ""

        header = ""
        if code_block.filename:
            header = (
                '<div class="code-header">'
                f'<span class="filename">{HTMLRenderer._escape(code_block.filename)}</span>'
                '</div>'
            )

        pre_class_attr = f' class="{pre_class}"' if pre_class else ""

        return (
            '<div class="code-block-container">'
            f'{header}'
            f'<pre{pre_class_attr}><code class="{lang_class}">{code_content}</code></pre>'
            '</div>'
        )

    @staticmethod
    def _render_special_block(block: SpecialBlock) -> str:
        """Render special content blocks (sidebars, callouts, etc.)."""
        content_html = []
        for text_block in block.content:
            content_html.append(HTMLRenderer._render_text_block(text_block))
        content_str = "\n".join(content_html)

        icon_html = ''
        if block.icon:
            icon_html = f'<div class="special-block-icon">{HTMLRenderer._escape(block.icon)}</div>'

        title_html = ''
        if block.title:
            title_html = f'<h3 class="special-block-title">{HTMLRenderer._escape(block.title)}</h3>'

        classes = ['special-block', f'special-block-{block.block_type}']
        if block.severity:
            classes.append(f'severity-{block.severity}')
        if block.collapsible:
            classes.append('collapsible')

        class_str = " ".join(classes)

        if block.collapsible:
            return (
                f'<details class="{class_str}">'
                f'<summary>{icon_html}{title_html}</summary>'
                f'<div class="special-block-content">{content_str}</div>'
                '</details>'
            )

        return (
            f'<aside class="{class_str}" role="complementary">'
            f'{icon_html}{title_html}'
            f'<div class="special-block-content">{content_str}</div>'
            '</aside>'
        )
    
    @staticmethod
    def _render_table(table: Table) -> str:
        """Render a table to HTML."""
        parts = []
        
        if table.table_number or table.caption:
            caption_parts = []
            if table.table_number:
                caption_parts.append(f'<span class="table-number">{HTMLRenderer._escape(table.table_number)}</span>')
            if table.caption:
                caption_parts.append(HTMLRenderer._escape(table.caption))
            caption_text = " ".join(caption_parts)
            parts.append(f'<p class="table-caption">{caption_text}</p>')

        table_id = HTMLRenderer._table_anchor_id(table)
        summary_attr = ""
        aria_label_attr = ""
        if table.summary:
            summary_text = HTMLRenderer._escape(table.summary)
            summary_attr = f' summary="{summary_text}"'
            aria_label_attr = f' aria-label="{summary_text}"'
        id_attr = f' id="{HTMLRenderer._escape(table_id)}"' if table_id else ""
        parts.append(f'<table{id_attr} role="table"{summary_attr}{aria_label_attr}>')

        if table.structured_rows:
            header_rows = [row for row in table.structured_rows if row.is_header_row]
            body_rows = [row for row in table.structured_rows if not row.is_header_row]

            def render_row(row: TableRow) -> None:
                parts.append("<tr>")
                for cell in row.cells:
                    tag = "th" if cell.is_header else "td"
                    attrs = []
                    if cell.row_span and cell.row_span > 1:
                        attrs.append(f'rowspan="{cell.row_span}"')
                    if cell.col_span and cell.col_span > 1:
                        attrs.append(f'colspan="{cell.col_span}"')
                    if cell.alignment:
                        attrs.append(f'style="text-align: {cell.alignment};"')
                    attr_str = f" {' '.join(attrs)}" if attrs else ""
                    parts.append(f"<{tag}{attr_str}>{HTMLRenderer._escape(cell.content)}</{tag}>")
                parts.append("</tr>")

            if header_rows:
                parts.append("<thead>")
                for row in header_rows:
                    render_row(row)
                parts.append("</thead>")

            # If no explicit header rows, treat all rows as body
            rows_to_render = body_rows if header_rows else table.structured_rows
            if rows_to_render:
                parts.append("<tbody>")
                for row in rows_to_render:
                    render_row(row)
                parts.append("</tbody>")
        else:
            if table.headers:
                parts.append("<thead><tr>")
                for header in table.headers:
                    parts.append(f"<th>{HTMLRenderer._escape(header)}</th>")
                parts.append("</tr></thead>")

            parts.append("<tbody>")
            for row in table.rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{HTMLRenderer._escape(cell)}</td>")
                parts.append("</tr>")
            parts.append("</tbody>")

        parts.append("</table>")
        
        return "\n".join(parts)
    
    @staticmethod
    def _render_image(image: Image) -> str:
        """Render an image to HTML - as normal in-flow block to prevent overlaps."""
        # Use bbox dimensions for better sizing
        # For wide images (>70% page width), show at full bbox width
        # For smaller images, cap at reasonable size
        if image.bbox_width > 70:
            width = min(95, image.bbox_width)
        else:
            width = max(30, min(80, image.bbox_width))
        
        # Build inline style for sizing (no horizontal positioning)
        style = f"max-width: {width}%; margin: 1rem auto;"
        
        alt_text = image.alt_text if image.alt_text else image.description
        alt_text_safe = HTMLRenderer._escape(alt_text) if alt_text else ""

        figure_id = HTMLRenderer._figure_anchor_id(image)
        id_attr = f' id="{HTMLRenderer._escape(figure_id)}"' if figure_id else ""
        multipart_attr = ""
        if image.is_multipart:
            multipart_attr = ' data-multipart="true"'
        part_label_attr = f' data-part="{HTMLRenderer._escape(image.part_label)}"' if image.part_label else ""

        parts = [f'<figure{id_attr} class="image-block" style="{style}" data-bbox="{image.bbox_left},{image.bbox_top},{image.bbox_width},{image.bbox_height}"{multipart_attr}{part_label_attr}>']
        
        if image.image_data:
            # We have actual image data - render as embedded image
            parts.append(f'<img src="data:image/png;base64,{image.image_data}" '
                        f'alt="{alt_text_safe}" '
                        f'title="{alt_text_safe}" />')
        else:
            # Fallback to placeholder
            placeholder_text = alt_text_safe
            suffix = f": {placeholder_text}" if placeholder_text else ""
            parts.append(f'<div class="image-placeholder">[{image.image_type.title()}{suffix}]</div>')

        if image.long_description:
            parts.append(
                '<details class="image-long-desc">'
                '<summary>Detailed Description</summary>'
                f'<p>{HTMLRenderer._escape(image.long_description)}</p>'
                '</details>'
            )
        
        if image.caption or image.figure_number:
            caption_parts = []
            if image.figure_number:
                caption_parts.append(f'<span class="figure-number">{HTMLRenderer._escape(image.figure_number)}</span>')
            if image.caption:
                caption_parts.append(HTMLRenderer._escape(image.caption))
            caption_text = " ".join(caption_parts)
            parts.append(f"<figcaption>{caption_text}</figcaption>")
        parts.append("</figure>")
        return "\n".join(parts)


# =============================================================================
# VALIDATION & EXPORT UTILITIES
# =============================================================================

class DocumentValidator:
    """Validates document structure and content quality."""

    @staticmethod
    def validate(doc: DocumentStructure, level: str = "standard") -> ValidationResult:
        """Validate document and return detailed results."""
        errors = []
        warnings = []

        errors.extend(DocumentValidator._validate_structure(doc))
        errors.extend(DocumentValidator._validate_references(doc))
        errors.extend(DocumentValidator._validate_bboxes(doc))

        if level in ("standard", "strict"):
            warnings.extend(DocumentValidator._check_content_quality(doc))
            warnings.extend(DocumentValidator._check_accessibility(doc))

        if level == "strict":
            errors.extend(DocumentValidator._validate_semantics(doc))
            errors.extend(DocumentValidator._validate_html_output(doc))

        metrics = DocumentValidator._calculate_metrics(doc)
        quality_score = DocumentValidator._calculate_quality_score(metrics, errors, warnings)
        is_valid = len([e for e in errors if e.severity == "critical"]) == 0

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            quality_score=quality_score,
            metrics=metrics
        )

    @staticmethod
    def _validate_structure(doc: DocumentStructure) -> list[ValidationError]:
        errors = []

        if not doc.pages:
            errors.append(ValidationError(
                error_type="missing_content",
                severity="critical",
                message="Document has no pages",
                suggestion="Check PDF extraction process"
            ))
            return errors

        for i, page in enumerate(doc.pages, 1):
            if page.page_number != i:
                errors.append(ValidationError(
                    error_type="invalid_structure",
                    severity="error",
                    message=f"Page number mismatch: expected {i}, got {page.page_number}",
                    location=f"Page {page.page_number}"
                ))

        return errors

    @staticmethod
    def _validate_references(doc: DocumentStructure) -> list[ValidationError]:
        errors = []
        all_ids = set()
        referenced_ids = set()

        for page in doc.pages:
            for block in page.text_blocks:
                if block.element_id:
                    if block.element_id in all_ids:
                        errors.append(ValidationError(
                            error_type="duplicate_id",
                            severity="error",
                            message=f"Duplicate element ID: {block.element_id}",
                            location=f"Page {page.page_number}"
                        ))
                    all_ids.add(block.element_id)
                    if block.block_type in ("heading", "appendix_heading"):
                        all_ids.add(HTMLRenderer._normalize_id("section", block.element_id))
                    if block.block_type == "equation":
                        all_ids.add(HTMLRenderer._normalize_id("equation", block.element_id))
                elif block.block_type == "equation" and block.equation_number:
                    all_ids.add(HTMLRenderer._normalize_id("equation", block.equation_number))

                if block.references:
                    referenced_ids.update(block.references)

            for img in page.images:
                if img.figure_id and img.figure_id in all_ids:
                    errors.append(ValidationError(
                        error_type="duplicate_id",
                        severity="error",
                        message=f"Duplicate figure ID: {img.figure_id}",
                        location=f"Page {page.page_number}"
                    ))
                if img.figure_id:
                    all_ids.add(img.figure_id)
                    all_ids.add(HTMLRenderer._normalize_id("figure", img.figure_id))

            for table in page.tables:
                if table.table_id and table.table_id in all_ids:
                    errors.append(ValidationError(
                        error_type="duplicate_id",
                        severity="error",
                        message=f"Duplicate table ID: {table.table_id}",
                        location=f"Page {page.page_number}"
                    ))
                if table.table_id:
                    all_ids.add(table.table_id)
                    all_ids.add(HTMLRenderer._normalize_id("table", table.table_id))

        if doc.bibliography:
            for citation in doc.bibliography:
                if citation.citation_id:
                    all_ids.add(citation.citation_id)
                    all_ids.add(HTMLRenderer._normalize_id("citation", citation.citation_id))

        broken_refs = referenced_ids - all_ids
        for ref in broken_refs:
            errors.append(ValidationError(
                error_type="broken_reference",
                severity="warning",
                message=f"Reference to non-existent ID: {ref}",
                suggestion="Check cross-references or add missing anchor"
            ))

        return errors

    @staticmethod
    def _validate_bboxes(doc: DocumentStructure) -> list[ValidationError]:
        errors = []

        def check_bbox(value: Optional[float], name: str, page_num: int) -> None:
            if value is None:
                return
            if not (0 <= value <= 100):
                errors.append(ValidationError(
                    error_type="invalid_bbox",
                    severity="warning",
                    message=f"Invalid {name}: {value} (must be 0-100)",
                    location=f"Page {page_num}",
                    suggestion="Check bbox extraction"
                ))

        for page in doc.pages:
            for block in page.text_blocks:
                check_bbox(block.bbox_top, "bbox_top", page.page_number)
                check_bbox(block.bbox_left, "bbox_left", page.page_number)
                check_bbox(block.bbox_width, "bbox_width", page.page_number)
                check_bbox(block.bbox_height, "bbox_height", page.page_number)

            for table in page.tables:
                check_bbox(table.bbox_top, "bbox_top", page.page_number)
                check_bbox(table.bbox_left, "bbox_left", page.page_number)
                check_bbox(table.bbox_width, "bbox_width", page.page_number)
                check_bbox(table.bbox_height, "bbox_height", page.page_number)

            for image in page.images:
                check_bbox(image.bbox_top, "bbox_top", page.page_number)
                check_bbox(image.bbox_left, "bbox_left", page.page_number)
                check_bbox(image.bbox_width, "bbox_width", page.page_number)
                check_bbox(image.bbox_height, "bbox_height", page.page_number)

            for code_block in page.code_blocks:
                check_bbox(code_block.bbox_top, "bbox_top", page.page_number)
                check_bbox(code_block.bbox_left, "bbox_left", page.page_number)
                check_bbox(code_block.bbox_width, "bbox_width", page.page_number)
                check_bbox(code_block.bbox_height, "bbox_height", page.page_number)

            for special_block in page.special_blocks:
                check_bbox(special_block.bbox_top, "bbox_top", page.page_number)
                check_bbox(special_block.bbox_left, "bbox_left", page.page_number)
                check_bbox(special_block.bbox_width, "bbox_width", page.page_number)
                check_bbox(special_block.bbox_height, "bbox_height", page.page_number)

        return errors

    @staticmethod
    def _check_content_quality(doc: DocumentStructure) -> list[ValidationWarning]:
        warnings = []
        for page in doc.pages:
            if not page.text_blocks and not page.tables and not page.images and not page.code_blocks and not page.special_blocks:
                warnings.append(ValidationWarning(
                    warning_type="empty_page",
                    message=f"Page {page.page_number} has no content",
                    location=f"Page {page.page_number}",
                    auto_fixable=False
                ))
        return warnings

    @staticmethod
    def _check_accessibility(doc: DocumentStructure) -> list[ValidationWarning]:
        warnings = []

        for page in doc.pages:
            for img in page.images:
                if not img.alt_text and not img.description:
                    warnings.append(ValidationWarning(
                        warning_type="accessibility_violation",
                        message=f"Image on page {page.page_number} missing alt text",
                        location=f"Page {page.page_number}",
                        auto_fixable=False
                    ))
                if img.alt_text and len(img.alt_text) > 125:
                    warnings.append(ValidationWarning(
                        warning_type="accessibility_recommendation",
                        message=f"Alt text exceeds recommended 125 characters ({len(img.alt_text)} chars)",
                        location=f"Page {page.page_number}",
                        auto_fixable=False
                    ))

        return warnings

    @staticmethod
    def _validate_semantics(doc: DocumentStructure) -> list[ValidationError]:
        errors = []
        for page in doc.pages:
            for block in page.text_blocks:
                if block.block_type == "equation" and not block.content.strip():
                    errors.append(ValidationError(
                        error_type="malformed_equation",
                        severity="warning",
                        message=f"Empty equation block on page {page.page_number}",
                        location=f"Page {page.page_number}"
                    ))
        return errors

    @staticmethod
    def _validate_html_output(doc: DocumentStructure) -> list[ValidationError]:
        errors = []
        try:
            HTMLRenderer.render(doc, include_styles=False, include_navigation=False)
        except Exception as exc:
            errors.append(ValidationError(
                error_type="invalid_markup",
                severity="error",
                message=f"HTML rendering failed: {exc}"
            ))
        return errors

    @staticmethod
    def _calculate_metrics(doc: DocumentStructure) -> QualityMetrics:
        total_chars = 0
        total_blocks = 0
        total_tables = 0
        total_images = 0
        total_equations = 0
        blocks_with_bbox = 0
        blocks_without_bbox = 0
        images_with_alt = 0
        images_without_alt = 0
        tables_with_headers = 0
        tables_without_headers = 0
        pages_with_content = 0

        for page in doc.pages:
            has_content = bool(page.text_blocks or page.tables or page.images or page.code_blocks or page.special_blocks)
            if has_content:
                pages_with_content += 1

            for block in page.text_blocks:
                total_blocks += 1
                total_chars += len(block.content)
                if block.block_type == "equation":
                    total_equations += 1

                if block.bbox_top is not None:
                    blocks_with_bbox += 1
                else:
                    blocks_without_bbox += 1

            total_tables += len(page.tables)
            for table in page.tables:
                if table.structured_rows and any(row.is_header_row for row in table.structured_rows):
                    tables_with_headers += 1
                elif table.headers:
                    tables_with_headers += 1
                else:
                    tables_without_headers += 1

            for img in page.images:
                total_images += 1
                if img.alt_text or img.description:
                    images_with_alt += 1
                else:
                    images_without_alt += 1

        coverage = (pages_with_content / len(doc.pages) * 100) if doc.pages else 0.0
        avg_chars = total_chars / len(doc.pages) if doc.pages else 0.0

        accessibility_score = 100.0
        if total_images > 0:
            accessibility_score *= (images_with_alt / total_images)
        if blocks_without_bbox > 0:
            accessibility_score *= 0.9

        if accessibility_score >= 95:
            wcag = "AAA"
        elif accessibility_score >= 85:
            wcag = "AA"
        elif accessibility_score >= 70:
            wcag = "A"
        else:
            wcag = "non-compliant"

        return QualityMetrics(
            pages_with_content=pages_with_content,
            pages_total=len(doc.pages),
            coverage_percent=coverage,
            total_text_chars=total_chars,
            total_text_blocks=total_blocks,
            total_tables=total_tables,
            total_images=total_images,
            total_equations=total_equations,
            avg_chars_per_page=avg_chars,
            blocks_with_bbox=blocks_with_bbox,
            blocks_without_bbox=blocks_without_bbox,
            images_with_alt_text=images_with_alt,
            images_without_alt_text=images_without_alt,
            tables_with_headers=tables_with_headers,
            tables_without_headers=tables_without_headers,
            accessibility_score=accessibility_score,
            wcag_compliance=wcag,
            confidence_score=90.0,
            ocr_errors_estimated=0
        )

    @staticmethod
    def _calculate_quality_score(
        metrics: QualityMetrics,
        errors: list[ValidationError],
        warnings: list[ValidationWarning]
    ) -> float:
        score = 100.0

        critical_errors = len([e for e in errors if e.severity == "critical"])
        errors_count = len([e for e in errors if e.severity == "error"])
        warning_count = len([e for e in errors if e.severity == "warning"]) + len(warnings)

        score -= (critical_errors * 20)
        score -= (errors_count * 5)
        score -= (warning_count * 1)

        if metrics.coverage_percent > 95:
            score += 5
        if metrics.accessibility_score > 90:
            score += 5

        return max(0.0, min(100.0, score))

    @staticmethod
    def auto_fix(doc: DocumentStructure) -> DocumentStructure:
        """Apply lightweight auto-fixes for common issues."""
        HTMLRenderer._ensure_heading_ids(doc)
        for page in doc.pages:
            for block in page.text_blocks:
                if block.references:
                    block.references = list(dict.fromkeys(block.references))
            for img in page.images:
                if not img.alt_text and img.description:
                    img.alt_text = img.description[:125]
        return doc


class PerformanceOptimizer:
    """Performance optimization utilities."""

    @staticmethod
    def optimize_images(doc: DocumentStructure, max_size_kb: int = 500) -> DocumentStructure:
        """Optimize image sizes if Pillow is available."""
        try:
            import base64
            from io import BytesIO
            from PIL import Image as PILImage
        except Exception:
            return doc

        for page in doc.pages:
            for img in page.images:
                if img.image_data:
                    try:
                        img_bytes = base64.b64decode(img.image_data)
                        current_size = len(img_bytes) / 1024
                        if current_size <= max_size_kb:
                            continue
                        pil_img = PILImage.open(BytesIO(img_bytes))
                        buffer = BytesIO()
                        quality = max(40, int((max_size_kb / current_size) * 95))
                        pil_img.save(buffer, format='JPEG', quality=quality, optimize=True)
                        compressed = base64.b64encode(buffer.getvalue()).decode()
                        img.image_data = compressed
                    except Exception:
                        continue
        return doc

    @staticmethod
    def lazy_load_images(html: str) -> str:
        """Add lazy loading to images."""
        return html.replace('<img ', '<img loading="lazy" ') if '<img ' in html else html

    @staticmethod
    def minify_html(html: str) -> str:
        """Minify HTML for smaller file size."""
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        html = re.sub(r'>\s+<', '><', html)
        return html.strip()


class GeminiHtmlPostProcessor:
    """Post-process Gemini HTML to improve layout and math rendering."""

    @staticmethod
    def _inject_into_head(html: str, injection: str) -> str:
        if "</head>" in html:
            return html.replace("</head>", f"{injection}\n</head>")
        return f"{injection}\n{html}"

    @staticmethod
    def inject_mathjax(html: str) -> str:
        if "MathJax" in html:
            return html
        mathjax = HTMLRenderer._get_mathjax_config()
        return GeminiHtmlPostProcessor._inject_into_head(html, mathjax)

    @staticmethod
    def inject_column_css(html: str) -> str:
        css = """<style>
body { max-width: 980px; margin: 32px auto; }
.two-column { max-width: 980px; margin: 0 auto; gap: 24px; }
.two-column .column { flex: 1 1 0; }
</style>"""
        return GeminiHtmlPostProcessor._inject_into_head(html, css)

    @staticmethod
    def inject_math_autowrap_script(html: str) -> str:
        script = """<script>
function wrapInlineMath() {
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode: (node) => {
        if (!node.parentElement) return NodeFilter.FILTER_REJECT;
        const tag = node.parentElement.tagName.toLowerCase();
        if (['script', 'style', 'noscript', 'code', 'pre'].includes(tag)) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  const greekMap = {
    alpha: '\\\\alpha',
    beta: '\\\\beta',
    gamma: '\\\\gamma',
    delta: '\\\\delta',
    epsilon: '\\\\epsilon',
    theta: '\\\\theta',
    lambda: '\\\\lambda',
    mu: '\\\\mu',
    pi: '\\\\pi',
    sigma: '\\\\sigma',
    phi: '\\\\phi',
    omega: '\\\\omega'
  };

  const mathRegex = /\\\\[a-zA-Z]+/;
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const text = node.textContent;
    if (!text || text.includes('$')) return;
    if (!mathRegex.test(text)) return;
    const span = document.createElement('span');
    let converted = text;
    Object.keys(greekMap).forEach((key) => {
      const re = new RegExp('\\\\b' + key + '\\\\b', 'gi');
      converted = converted.replace(re, greekMap[key]);
    });
    span.innerHTML = converted.replace(
      /([^<]*?)(\\\\[a-zA-Z][^<]*?)(?=$|<)/g,
      (match) => '\\\\(' + match + '\\\\)'
    );
    node.parentElement.replaceChild(span, node);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  wrapInlineMath();
  if (window.MathJax && MathJax.typesetPromise) {
    MathJax.typesetPromise().catch(() => {});
  }
});
</script>"""
        return html.replace("</body>", f"{script}\n</body>") if "</body>" in html else f"{html}\n{script}"

    @staticmethod
    def postprocess(html: str, tighten_columns: bool = True, inject_mathjax: bool = True) -> str:
        processed = html
        if tighten_columns:
            processed = GeminiHtmlPostProcessor.inject_column_css(processed)
        if inject_mathjax:
            processed = GeminiHtmlPostProcessor.inject_mathjax(processed)
            processed = GeminiHtmlPostProcessor.inject_math_autowrap_script(processed)
        return processed


class DocumentExporter:
    """Export documents to various formats."""

    @staticmethod
    def export(doc: DocumentStructure, config: ExportConfig) -> bytes:
        if config.format == "html":
            return DocumentExporter._export_html(doc, config)
        if config.format == "pdf":
            return DocumentExporter._export_pdf(doc, config)
        if config.format == "markdown":
            return DocumentExporter._export_markdown(doc, config)
        if config.format == "docx":
            return DocumentExporter._export_docx(doc, config)
        raise ValueError(f"Unsupported export format: {config.format}")

    @staticmethod
    def _export_html(doc: DocumentStructure, config: ExportConfig) -> bytes:
        html = HTMLRenderer.render(
            doc,
            theme=config.theme,
            include_metadata=config.include_metadata,
            include_toc=config.include_toc,
            include_navigation=config.include_navigation,
            include_images=config.include_images,
            include_page_numbers=config.include_page_numbers
        )
        size_map = {
            "small": "0.9em",
            "normal": "1em",
            "large": "1.1em",
            "x-large": "1.25em",
        }
        injected_css = []
        if config.font_size and config.font_size in size_map and config.font_size != "normal":
            injected_css.append(f"body {{ font-size: {size_map[config.font_size]}; }}")
        if config.custom_css:
            injected_css.append(config.custom_css)
        if injected_css:
            html = html.replace("</style>", f"\n{os.linesep.join(injected_css)}\n</style>")
        if config.minify_html:
            html = PerformanceOptimizer.minify_html(html)
        return html.encode("utf-8")

    @staticmethod
    def _export_pdf(doc: DocumentStructure, config: ExportConfig) -> bytes:
        try:
            from weasyprint import HTML, CSS
        except Exception as exc:
            raise RuntimeError("WeasyPrint required for PDF export. Install with: pip install weasyprint") from exc
        html = HTMLRenderer.render(
            doc,
            theme="print",
            include_metadata=config.include_metadata,
            include_toc=config.include_toc,
            include_navigation=False,
            include_images=config.include_images,
            include_page_numbers=config.include_page_numbers
        )
        page_size = config.page_size or "A4"
        orientation = config.page_orientation or "portrait"
        page_css = CSS(string=f"@page {{ size: {page_size} {orientation}; margin: 1cm; }}")
        return HTML(string=html).write_pdf(stylesheets=[page_css])

    @staticmethod
    def _export_markdown(doc: DocumentStructure, config: ExportConfig) -> bytes:
        md_lines = []

        if config.include_metadata and doc.metadata:
            if doc.metadata.title:
                md_lines.append(f"# {doc.metadata.title}")
            if doc.metadata.author:
                md_lines.append(f"**Author:** {doc.metadata.author}")
            md_lines.append("")

        for page in doc.pages:
            for block in page.text_blocks:
                if block.block_type == "heading":
                    level = block.level or 1
                    md_lines.append(f"{'#' * level} {block.content}")
                elif block.block_type == "paragraph":
                    md_lines.append(block.content)
                    md_lines.append("")
                elif block.block_type == "list_item":
                    md_lines.append(f"- {block.content}")
                elif block.block_type == "code":
                    lang = block.language or ""
                    md_lines.append(f"```{lang}")
                    md_lines.append(block.content)
                    md_lines.append("```")
                elif block.block_type == "equation":
                    md_lines.append(f"$$ {block.content} $$")
                else:
                    md_lines.append(block.content)
                    md_lines.append("")

            for code_block in page.code_blocks:
                lang = code_block.language or ""
                md_lines.append(f"```{lang}")
                md_lines.append(code_block.code)
                md_lines.append("```")
                md_lines.append("")

        return "\n".join(md_lines).encode("utf-8")

    @staticmethod
    def _export_docx(doc: DocumentStructure, config: ExportConfig) -> bytes:
        try:
            import docx
        except Exception as exc:
            raise RuntimeError("python-docx required for DOCX export. Install with: pip install python-docx") from exc

        document = docx.Document(config.template) if config.template else docx.Document()
        if config.include_metadata:
            if doc.metadata.title:
                document.add_heading(doc.metadata.title, level=1)
            if doc.metadata.author:
                document.add_paragraph(f"Author: {doc.metadata.author}")

        for page in doc.pages:
            for block in page.text_blocks:
                if block.block_type == "heading":
                    level = block.level or 1
                    document.add_heading(block.content, level=min(level, 9))
                elif block.block_type == "paragraph":
                    document.add_paragraph(block.content)
                elif block.block_type == "list_item":
                    document.add_paragraph(block.content, style="List Bullet")
                elif block.block_type == "code":
                    document.add_paragraph(block.content)
                else:
                    document.add_paragraph(block.content)

        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()


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
        self._token_lock = threading.Lock()
    
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

    def _repair_json_payload(self, payload: str) -> str:
        """Attempt light repairs for malformed JSON (unescaped newlines)."""
        if not payload:
            return payload
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return payload
        trimmed = payload[start:end + 1]
        out = []
        in_string = False
        escape_next = False
        for ch in trimmed:
            if escape_next:
                out.append(ch)
                escape_next = False
                continue
            if ch == "\\":
                out.append(ch)
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                out.append(ch)
                continue
            if in_string:
                if ch == "\n":
                    out.append("\\n")
                    continue
                if ch == "\r":
                    out.append("\\r")
                    continue
                if ch == "\t":
                    out.append("\\t")
                    continue
            out.append(ch)
        return "".join(out)

    def _parse_metadata_payload(self, payload: str) -> DocumentMetadata:
        """Parse metadata JSON with light repair fallback."""
        try:
            return DocumentMetadata.model_validate_json(payload)
        except Exception:
            repaired = self._repair_json_payload(payload)
            try:
                return DocumentMetadata.model_validate_json(repaired)
            except Exception:
                data = json.loads(repaired)
                return DocumentMetadata.model_validate(data)

    def _hash_file(self, file_path: str) -> str:
        """Compute SHA256 hash for a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def _hash_config(self) -> str:
        """Compute a stable hash of processing config."""
        config_payload = {}
        for config_field in fields(ProcessingConfig):
            value = getattr(self.config, config_field.name)
            if isinstance(value, Enum):
                value = value.value
            config_payload[config_field.name] = value
        encoded = json.dumps(config_payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _get_cache_paths(self, pdf_path: str, output_base: str) -> tuple[pathlib.Path, pathlib.Path]:
        """Get cache directory and cache path for a PDF/config pair."""
        cache_dir = pathlib.Path(output_base).parent / ".ocr_cache"
        cache_key = f"{self._hash_file(pdf_path)}-{self._hash_config()}"
        cache_path = cache_dir / f"{cache_key}.json"
        return cache_dir, cache_path
    
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
    
    def _get_page_count(self, uploaded_file: types.File, pdf_path: Optional[str] = None) -> tuple[int, DocumentMetadata]:
        """Get document page count and metadata."""
        prompt = """Analyze this PDF document and provide:
1. The total number of pages
2. Document metadata (title, author, language, document type)
3. Enhanced metadata if present: authors with affiliations, keywords, abstract, DOI, publication date, copyright, license

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
                        system_instruction=(
                            "You are a document analyzer. Count pages and extract metadata only. "
                            "Extract title, author, language, document type, and enhanced metadata (authors, affiliations, keywords, abstract, DOI, publication date, copyright, license) when present. "
                            "Output valid JSON only. Do not include commentary or Markdown. "
                            "Escape newlines and quotes in strings. "
                            "If any field is too long, truncate abstract to <=500 characters. "
                            "Ensure ALL JSON strings are properly escaped."
                        ),
                        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,  # Low res for counting
                        max_output_tokens=2048,
                        temperature=temperature,
                    ),
                )
                
                metadata = self._parse_metadata_payload(response.text)
                logger.info(f"Document has {metadata.total_pages} pages")
                return metadata.total_pages, metadata
                
            except Exception as e:
                error_msg = str(e)
                last_error = e

                is_json_error = isinstance(e, (json.JSONDecodeError, ValidationError))
                if not is_json_error:
                    lowered = error_msg.lower()
                    if any(token in lowered for token in ("json", "parsing", "invalid", "unterminated string")):
                        is_json_error = True

                if is_json_error:
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
        if pdf_path:
            try:
                if HAS_PYMUPDF:
                    local_doc = fitz.open(pdf_path)
                    try:
                        total_pages = len(local_doc)
                    finally:
                        local_doc.close()
                else:
                    total_pages = -1
                metadata = DocumentMetadata(
                    total_pages=total_pages,
                    title=None,
                    author=None,
                    language=None,
                    document_type="unknown"
                )
                logger.warning("Falling back to local page count for metadata")
                return total_pages, metadata
            except Exception as fallback_err:
                logger.error(f"Local page count fallback failed: {fallback_err}")
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
        total_code_blocks = len(page.code_blocks)
        total_special_blocks = len(page.special_blocks)
        
        # Calculate table cell count (supports both old and structured formats)
        def _count_table_cells(table: Table) -> int:
            if table.structured_rows:
                return sum(len(row.cells) for row in table.structured_rows)
            return len(table.headers) + sum(len(row) for row in table.rows)

        table_cells = sum(_count_table_cells(table) for table in page.tables)
        
        # Quality heuristics
        has_content = (
            total_text_chars > 0
            or total_tables > 0
            or total_images > 0
            or total_code_blocks > 0
            or total_special_blocks > 0
        )
        is_substantial = total_text_chars > 50  # At least 50 chars
        
        return {
            "page_number": page.page_number,
            "text_chars": total_text_chars,
            "text_blocks": total_blocks,
            "tables": total_tables,
            "table_cells": table_cells,
            "images": total_images,
            "code_blocks": total_code_blocks,
            "special_blocks": total_special_blocks,
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
3. Extract the FOOTER text if present (usually at the bottom of the page - may contain page numbers, citations, document info)
4. Extract all text blocks with semantic types (heading, paragraph, list_item, equation, etc.)
   - CRITICAL: For EVERY SINGLE text block, you MUST provide BOUNDING BOX coordinates as percentages (0-100):
     * bbox_top: distance from top of page to top of text block (REQUIRED, 0-100)
     * bbox_left: distance from left of page to left of text block (REQUIRED, 0-100)
     * bbox_width: width of the text block (REQUIRED, 0-100)
     * bbox_height: height of the text block (REQUIRED, 0-100)
   - These coordinates are MANDATORY for proper rendering, not optional
   - If text contains links or inline formatting, populate inline_elements:
     * Use type="text" for plain text runs
     * Use type="link" with url or target_id for hyperlinks
     * Use type="strong", type="emphasis", or type="code" for formatting
     * Keep full plain text in content for backward compatibility
   - For HEADINGS: Assign unique element_id to each heading
   - For major sections, add anchor_name (e.g., "introduction", "methodology")
4b. SEMANTIC CONTENT TYPES:
   - Use theorem/proof/lemma/corollary/proposition/definition/example/remark/note when applicable
   - Use abstract/summary/keywords/author_info/acknowledgments/appendix_heading for document structure
   - Use warning/tip/important/callout/question/answer/exercise/solution for callouts
   - Use verse/poetry/dialogue/preformatted for special text
4c. STRUCTURED FORMATTING:
   - Use formatting.bold/italic/underline/strikethrough for typography
   - Use formatting.text_color/background_color/font_size/alignment when detected
   - Avoid using style string unless formatting is unavailable
4d. CODE BLOCKS:
   - For code snippets with preserved indentation, use code_blocks with CodeBlock objects
   - Set language, filename, line_numbers, highlight_lines when present
   - Include bbox coordinates for code blocks
4e. SPECIAL BLOCKS:
   - For sidebars/callouts/warnings/tips, use special_blocks with SpecialBlock objects
   - Provide title, severity, icon, and include content as TextBlock list
   - Include bbox coordinates for special blocks
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
   - Set list_type: "unordered", "ordered", or "definition"
   - Set list_marker_style when known (e.g., "disc", "decimal", "lower-alpha", "upper-roman")
   - Preserve hierarchy and proper indentation structure
7b. For CROSS-REFERENCES in text (e.g., "See Section 2.3", "as shown in Figure 4"):
   - Add referenced IDs to the references field
   - Use inline_elements with type="link" and target_id pointing to the element ID
   - target_id should match rendered IDs (use section-/figure-/table-/equation-/citation- prefixes)
   - target_id should match rendered IDs (use section-/figure-/table-/equation-/citation- prefixes)
8. For TABLES: OCR all text content using structured_rows with TableRow and TableCell objects. Do NOT treat tables as images.
   - Mark header rows with is_header_row=true
   - Mark header cells with is_header=true
   - For MERGED CELLS: Set row_span and col_span values (default is 1 for regular cells)
   - Set cell alignment when clear: left/right/center/justify
   - Extract table_number from caption when present (e.g., "Table 2.1")
   - Assign unique table_id for cross-references
   - Provide summary describing table purpose for accessibility
   - For table captions: Extract separately from table content
   - Provide BOUNDING BOX coordinates (bbox_top, bbox_left, bbox_width, bbox_height) as percentages (0-100) of the page.
   - NEVER return an empty table if a table is visible: OCR every cell.
9. For VISUAL ELEMENTS (charts, graphs, diagrams, figures, photos):
   - Identify the image_type (chart, graph, diagram, figure, photo, logo, illustration, other)
   - Provide alt_text (short) and long_description (detailed for complex visuals)
   - Copy alt_text into description for backward compatibility
   - Extract figure_number from caption when present (e.g., "Figure 3.2")
   - Assign unique figure_id for cross-references
   - For multi-part figures (a, b, c), set is_multipart=true and part_label
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
                
                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=ChunkExtraction.model_json_schema(),
                        system_instruction=(
                            f"You are an expert OCR and document analysis system extracting pages {start_page}-{end_page} only. "
                            "You MUST extract every page fully; do not skip content or return placeholders. "
                            "Extract page headers and footers (usually contain page numbers, titles, or citations). "
                            "OCR all text content including tables. "
                            "PRESERVE NUMERAL SYSTEMS: If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), keep them exactly - do NOT convert to Western numerals (0123456789). "
                            "TRANSCRIBE mathematical equations EXACTLY as written - do NOT solve, simplify, or manipulate them. "
                            "Extract equations as LaTeX in 'equation' blocks preserving the exact notation from the PDF. "
                            "For SUPERSCRIPTS/SUBSCRIPTS: Use ^{} and _{} in LaTeX (e.g., x^{2}, H_{2}O). "
                            "For NUMBERED EQUATIONS: Extract equation number in equation_number field. "
                            "For NESTED LISTS: Set list_level (1=top, 2=nested, etc.) to preserve hierarchy. "
                            "For LIST TYPES: Set list_type (unordered/ordered/definition) and list_marker_style when known. "
                            "For INLINE FORMATTING or LINKS: Use inline_elements with type text/link/strong/emphasis/code, and keep full plain text in content. "
                            "For HEADINGS: Assign unique element_id and anchor_name for major sections. "
                            "For CROSS-REFERENCES: Add referenced IDs to references and use inline_elements link with target_id (use section-/figure-/table-/equation-/citation- prefixes). "
                            "For SEMANTIC BLOCK TYPES: Use theorem/proof/lemma/corollary/definition/example/remark/note and abstract/summary/keywords/author_info/acknowledgments when applicable. "
                            "For STRUCTURED FORMATTING: Use formatting.bold/italic/underline/strikethrough/colors/sizes/alignment instead of style strings. "
                            "For CODE BLOCKS: Populate code_blocks with language, filename, line_numbers, highlight_lines when present. "
                            "For SPECIAL BLOCKS: Populate special_blocks for sidebars/callouts/warnings/tips with nested TextBlock content. "
                            "For MERGED TABLE CELLS: Set row_span and col_span appropriately. "
                            "For TABLES: You MUST OCR every cell; do not omit or summarize. "
                            "Use structured_rows with TableRow/TableCell objects, mark is_header_row/is_header, and set alignment when clear. "
                            "Never return empty tables if a table is visible. "
                            "For TABLE NUMBERS: Extract table_number, assign table_id, and provide summary for accessibility. "
                            "For IMAGES: Provide alt_text and long_description; copy alt_text into deprecated description. "
                            "For FIGURES: Extract figure_number, assign figure_id, and set is_multipart/part_label for multi-part figures. "
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
                    with self._token_lock:
                        self._total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0)
                        self._total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0)
                
                logger.info(f"Extracted {len(chunk.pages)} pages from range {start_page}-{end_page}")
                return chunk.pages
                
            except Exception as e:
                error_msg = str(e)
                is_json_error = isinstance(e, (json.JSONDecodeError, ValidationError))
                if not is_json_error:
                    lowered = error_msg.lower()
                    if any(token in lowered for token in ("json", "parsing", "invalid", "unterminated string")):
                        is_json_error = True
                
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
    
    def _extract_chunked(self, uploaded_file: types.File, pdf_path: Optional[str] = None) -> DocumentStructure:
        """Extract document content in chunks for large documents."""
        # First, get page count and metadata
        total_pages, metadata = self._get_page_count(uploaded_file, pdf_path)
        
        # Estimate cost and time
        cost_estimate = self._estimate_cost(total_pages)
        logger.info(f"Starting extraction of {total_pages} pages (estimated ${cost_estimate['estimated_cost_usd']} USD)")
        
        all_pages: list[PageContent] = []
        chunk_size = self.config.pages_per_chunk
        start_time = time.time()
        
        # Process in chunks
        chunk_ranges = []
        for start in range(1, total_pages + 1, chunk_size):
            end = min(start + chunk_size - 1, total_pages)
            chunk_ranges.append((start, end))

        if self.config.parallel_processing and len(chunk_ranges) > 1:
            logger.info(f"Parallel processing enabled with {self.config.max_workers} workers")
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                future_map = {
                    executor.submit(self._extract_page_range, uploaded_file, start, end): (start, end)
                    for start, end in chunk_ranges
                }
                completed = 0
                total_chunks = len(chunk_ranges)
                for future in as_completed(future_map):
                    start, end = future_map[future]
                    completed += 1
                    progress = (completed / total_chunks) * 100
                    logger.info(f"Completed chunk {completed}/{total_chunks}: pages {start}-{end} ({progress:.1f}% complete)")
                    try:
                        chunk_pages = future.result()
                        for i, page in enumerate(chunk_pages):
                            expected_page = start + i
                            if page.page_number != expected_page:
                                page.page_number = expected_page
                        all_pages.extend(chunk_pages)
                        logger.info(f"Total pages extracted so far: {len(all_pages)}")
                    except Exception as e:
                        logger.error(f"Failed to extract pages {start}-{end}: {e}")
                        if not self.config.continue_on_error:
                            raise
                        for page_num in range(start, end + 1):
                            all_pages.append(PageContent(
                                page_number=page_num,
                                text_blocks=[TextBlock(
                                    block_type="paragraph",
                                    content=f"[Page {page_num} extraction failed: {e}]"
                                )]
                            ))
        else:
            for chunk_idx, (start, end) in enumerate(chunk_ranges, 1):
                progress = (chunk_idx / len(chunk_ranges)) * 100
                logger.info(f"Processing chunk {chunk_idx}: pages {start}-{end} of {total_pages} ({progress:.1f}% complete)")
                
                try:
                    chunk_pages = self._extract_page_range(uploaded_file, start, end)
                    
                    # Ensure page numbers are correct
                    for i, page in enumerate(chunk_pages):
                        expected_page = start + i
                        if page.page_number != expected_page:
                            page.page_number = expected_page
                    
                    all_pages.extend(chunk_pages)
                    logger.info(f"Total pages extracted so far: {len(all_pages)}")
                    
                except Exception as e:
                    logger.error(f"Failed to extract pages {start}-{end}: {e}")
                    if not self.config.continue_on_error:
                        raise
                    # Create placeholder pages for failed chunks
                    for page_num in range(start, end + 1):
                        all_pages.append(PageContent(
                            page_number=page_num,
                            text_blocks=[TextBlock(
                                block_type="paragraph",
                                content=f"[Page {page_num} extraction failed: {e}]"
                            )]
                        ))
        
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
                
                for retry_attempt in range(self.config.max_retries_per_page):
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
                        if retry_attempt < self.config.max_retries_per_page - 1:
                            time.sleep(self.config.retry_delay)
                
                # If all retries failed, create placeholder
                if not retry_success:
                    logger.error(f"Failed to extract page {page_num} after {self.config.max_retries_per_page} retries")
                    if not self.config.continue_on_error:
                        raise RuntimeError(f"Page {page_num} extraction failed after retries")
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
            if not self.config.continue_on_error:
                raise RuntimeError(f"Missing pages after retry: {sorted(still_missing)}")
        else:
            logger.info(f"✓ Page coverage verified: all {total_pages} pages extracted")
        
        # Calculate quality metrics for all pages
        quality_metrics = [self._calculate_page_quality(page) for page in all_pages]
        total_chars = sum(m["text_chars"] for m in quality_metrics)
        total_blocks = sum(m["text_blocks"] for m in quality_metrics)
        total_tables = sum(m["tables"] for m in quality_metrics)
        total_images = sum(m["images"] for m in quality_metrics)
        total_code_blocks = sum(m.get("code_blocks", 0) for m in quality_metrics)
        total_special_blocks = sum(m.get("special_blocks", 0) for m in quality_metrics)
        pages_with_content = sum(1 for m in quality_metrics if m["has_content"])
        
        # Calculate processing time
        elapsed_time = time.time() - start_time
        
        logger.info(
            f"Extraction complete: {elapsed_time:.1f}s, "
            f"{total_chars:,} chars, {total_blocks} blocks, "
            f"{total_tables} tables, {total_images} images, "
            f"{total_code_blocks} code blocks, {total_special_blocks} special blocks"
        )
        
        # Update metadata with actual extracted count
        metadata.total_pages = len(all_pages)
        
        extraction_notes = (
            f"Extracted in {(total_pages + chunk_size - 1) // chunk_size} chunks of {chunk_size} pages. "
            f"Processing time: {elapsed_time:.1f}s. "
            f"Content: {total_chars:,} chars, {total_blocks} text blocks, "
            f"{total_tables} tables, {total_images} images, "
            f"{total_code_blocks} code blocks, {total_special_blocks} special blocks. "
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
2. Extract the HEADER text if present (usually at the top of the page - may contain page numbers, chapter titles, section names)
3. Extract the FOOTER text if present (usually at the bottom of the page - may contain page numbers, citations, document info)
4. Extract all text blocks with semantic types (heading, paragraph, list_item, equation, etc.)
   - CRITICAL: For EVERY text block, you MUST provide bbox coordinates as percentages (0-100)
   - If text contains links or inline formatting, populate inline_elements with text/link/strong/emphasis/code
   - Keep full plain text in content for backward compatibility
   - For HEADINGS: Assign unique element_id to each heading
   - For major sections, add anchor_name (e.g., "introduction", "methodology")
   - Use semantic block types for academic content (theorem, proof, lemma, corollary, definition, example, remark, note)
   - Use abstract/summary/keywords/author_info/acknowledgments/appendix_heading when applicable
   - Use warning/tip/important/callout/question/answer/exercise/solution for callouts
   - Use verse/poetry/dialogue/preformatted for special text
   - Use formatting fields (bold/italic/underline/colors/alignment) instead of style strings
   - For code snippets, use code_blocks with language/filename/line_numbers and bbox coordinates
   - For sidebars/callouts, use special_blocks with nested TextBlock content and bbox coordinates
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
7. For LISTS (numbered, bulleted, nested):
   - For NESTED LISTS: Set list_level field (1=top, 2=nested, etc.)
   - Set list_type: "unordered", "ordered", or "definition"
   - Set list_marker_style when known (e.g., "disc", "decimal", "lower-alpha", "upper-roman")
   - Preserve hierarchy structure
7b. For CROSS-REFERENCES in text (e.g., "See Section 2.3", "as shown in Figure 4"):
   - Add referenced IDs to the references field
   - Use inline_elements with type="link" and target_id pointing to the element ID
8. For TABLES: OCR all text content using structured_rows with TableRow and TableCell objects. Do NOT treat tables as images.
   - Mark header rows with is_header_row=true
   - Mark header cells with is_header=true
   - For MERGED CELLS: Set row_span and col_span values
   - Set cell alignment when clear: left/right/center/justify
   - Extract table_number from caption when present (e.g., "Table 2.1")
   - Assign unique table_id for cross-references
   - Provide summary describing table purpose for accessibility
   - For table captions: Extract separately
   - Provide bbox coordinates
9. For VISUAL ELEMENTS (charts, graphs, diagrams, figures, photos):
   - Identify image_type
   - Provide alt_text (short) and long_description (detailed for complex visuals)
   - Copy alt_text into description for backward compatibility
   - Extract figure_number from caption when present (e.g., "Figure 3.2")
   - Assign unique figure_id for cross-references
   - For multi-part figures (a, b, c), set is_multipart=true and part_label
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
13. TABLE OF CONTENTS:
    - If the document has an explicit TOC, extract it into table_of_contents with proper nesting
    - Otherwise, TOC will be auto-generated from headings
14. CITATIONS & BIBLIOGRAPHY:
    - Identify bibliography entries at end of document
    - Extract authors, title, year, journal, volume, pages, DOI/URL, publisher, ISBN
    - Detect citation style (APA, MLA, Chicago, IEEE, Harvard) when possible
15. DOCUMENT METADATA:
    - Extract authors with affiliations, keywords, abstract, DOI, publication date, copyright, license
16. OCR all scanned text accurately
17. Detect document metadata: title, author, language, document type

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
                            "You MUST extract every page fully; do not skip content or return placeholders. "
                            "Extract page headers and footers (usually contain page numbers, titles, or citations). "
                            "OCR all text content including tables. "
                            "PRESERVE NUMERAL SYSTEMS: If PDF uses Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩), keep them exactly - do NOT convert to Western numerals (0123456789). "
                            "TRANSCRIBE mathematical equations EXACTLY as written - do NOT solve, simplify, or manipulate them. "
                            "Extract equations as LaTeX in 'equation' blocks preserving the exact notation from the PDF. "
                            "For SUPERSCRIPTS/SUBSCRIPTS: Use ^{} and _{} in LaTeX (e.g., x^{2}, H_{2}O). "
                            "For NUMBERED EQUATIONS: Extract equation number in equation_number field. "
                            "For NESTED LISTS: Set list_level (1=top, 2=nested, etc.) to preserve hierarchy. "
                            "For MERGED TABLE CELLS: Set row_span and col_span appropriately. "
                            "For LIST TYPES: Set list_type (unordered/ordered/definition) and list_marker_style when known. "
                            "For INLINE FORMATTING or LINKS: Use inline_elements with type text/link/strong/emphasis/code, and keep full plain text in content. "
                            "For TABLES: You MUST OCR every cell; do not omit or summarize. "
                            "Use structured_rows with TableRow/TableCell objects, mark is_header_row/is_header, and set alignment when clear. "
                            "Never return empty tables if a table is visible. "
                            "For IMAGES: Provide alt_text and long_description; copy alt_text into deprecated description. "
                            "For HEADINGS: Assign unique element_id and anchor_name for major sections. "
                            "For CROSS-REFERENCES: Add referenced IDs to references and use inline_elements link with target_id (use section-/figure-/table-/equation-/citation- prefixes). "
                            "For TABLE NUMBERS: Extract table_number, assign table_id, and provide summary for accessibility. "
                            "For FIGURES: Extract figure_number, assign figure_id, and set is_multipart/part_label for multi-part figures. "
                            "For TABLE OF CONTENTS: If explicit TOC exists, extract into table_of_contents with nesting. "
                            "For CITATIONS: Extract bibliography entries with authors, title, year, journal, pages, DOI/URL and citation_style. "
                            "For SEMANTIC BLOCK TYPES: Use theorem/proof/lemma/corollary/definition/example/remark/note and abstract/summary/keywords/author_info/acknowledgments when applicable. "
                            "For STRUCTURED FORMATTING: Use formatting.bold/italic/underline/strikethrough/colors/sizes/alignment instead of style strings. "
                            "For CODE BLOCKS: Populate code_blocks with language, filename, line_numbers, highlight_lines when present. "
                            "For SPECIAL BLOCKS: Populate special_blocks for sidebars/callouts/warnings/tips with nested TextBlock content. "
                            "For DOCUMENT METADATA: Extract authors, affiliations, keywords, abstract, DOI, publication date, copyright, license. "
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
                is_json_error = isinstance(e, (json.JSONDecodeError, ValidationError))
                if not is_json_error:
                    lowered = error_msg.lower()
                    if any(token in lowered for token in ("json", "parsing", "invalid", "unterminated string")):
                        is_json_error = True
                
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

    def _direct_html_extraction_range(self, uploaded_file: types.File, start_page: int, end_page: int, body_only: bool) -> str:
        """Request HTML directly from Gemini for a page range."""
        prompt = f"""Convert pages {start_page} to {end_page} of this PDF document into HTML.

Requirements:
- Process ONLY pages {start_page} through {end_page}
- Preserve layout: headings, paragraphs, lists, tables with proper HTML tags
- Maintain correct reading order for multi-column layouts
- For MATHEMATICAL EQUATIONS: Preserve as LaTeX
  * Inline equations: wrap in <span class="equation">LaTeX</span>
  * Display equations: wrap in <div class="equation">LaTeX</div>
- For RTL text (Arabic, Hebrew): Add dir="rtl" to containing element
- PRESERVE NUMERAL SYSTEMS exactly as in the PDF
"""
        if body_only:
            prompt += """- Output ONLY the HTML content for these pages (no <html>, <head>, <style>, or <body> tags)
"""
        else:
            prompt += """- Output a full standalone HTML document with <head> and <style>
"""

        for attempt in range(self.config.max_retries):
            try:
                temperature = 0.3 + (attempt * 0.2)
                logger.info(
                    f"Direct HTML extraction for pages {start_page}-{end_page} "
                    f"(attempt {attempt + 1}, temperature={temperature}, body_only={body_only})"
                )
                response = self.client.models.generate_content(
                    model=self.config.model,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="text/plain",
                        system_instruction=(
                            "You are an expert document transcription assistant. "
                            "Convert documents to clean, semantic HTML5 preserving ALL content accurately. "
                            "PRESERVE NUMERAL SYSTEMS exactly as in the PDF. "
                            "For EQUATIONS: Wrap in <span class=\"equation\">LaTeX</span> or <div class=\"equation\">LaTeX</div>. "
                            "For RTL text: Use dir=\"rtl\" attributes on the container elements. "
                            "Use semantic elements: <article>, <section>, <header>, <footer>, <figure>, <table>. "
                            "Ensure proper HTML escaping of special characters. "
                            "Be accurate and thorough."
                        ),
                        media_resolution=self._get_media_resolution(),
                        max_output_tokens=self.config.max_output_tokens,
                        temperature=temperature,
                    ),
                )
                html_content = response.text or ""
                if not html_content.strip():
                    raise ValueError("Empty HTML response from Gemini")
                return html_content
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Direct HTML range attempt {attempt + 1} failed: {error_msg[:200]}")
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (attempt + 1)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise RuntimeError(
                        f"Direct HTML extraction failed for pages {start_page}-{end_page} after {self.config.max_retries} attempts"
                    ) from e

        return ""

    def _extract_body_inner(self, html: str) -> str:
        """Extract inner HTML of the body tag."""
        lower = html.lower()
        start = lower.find("<body")
        if start == -1:
            return html
        start = lower.find(">", start)
        end = lower.rfind("</body>")
        if start == -1 or end == -1:
            return html
        return html[start + 1:end]

    def _text_only_extraction(self, pdf_path: str) -> str:
        """Fallback: extract text with PyMuPDF and wrap as simple HTML."""
        if not HAS_PYMUPDF:
            raise RuntimeError("PyMuPDF required for text-only fallback. Install with: pip install PyMuPDF")

        doc = fitz.open(pdf_path)
        try:
            parts = [
                "<!DOCTYPE html>",
                "<html lang=\"en\">",
                "<head>",
                "<meta charset=\"UTF-8\">",
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">",
                "<title>Text-only PDF Extraction</title>",
                "<style>",
                "body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0 auto; max-width: 900px; padding: 20px; background: #fafafa; }",
                ".page { background: #fff; border: 1px solid #ddd; padding: 16px; margin: 0 0 20px; }",
                ".page-header { font-size: 0.85rem; color: #666; text-align: right; margin-bottom: 10px; }",
                ".text-only { white-space: pre-wrap; font-family: 'Courier New', monospace; }",
                "</style>",
                "</head>",
                "<body>",
            ]
            for page_index in range(len(doc)):
                page = doc[page_index]
                text = page.get_text("text") or ""
                escaped = HTMLRenderer._escape(text)
                parts.append(f'<div class="page"><div class="page-header">Page {page_index + 1}</div>')
                parts.append(f'<pre class="text-only">{escaped}</pre></div>')
            parts.append("</body></html>")
            return "\n".join(parts)
        finally:
            doc.close()
    
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
        
        start_time = time.time()
        uploaded_file = None
        doc = None
        html_content = ""
        cache_path = None
        cache_used = False
        try:
            if self.config.direct_html_only:
                # Direct HTML extraction only (no structured JSON)
                uploaded_file = self._upload_pdf(pdf_path)
                self._uploaded_file = uploaded_file
                try:
                    total_pages, _ = self._get_page_count(uploaded_file, pdf_path)
                    if total_pages and total_pages > 0:
                        chunk_size = self.config.direct_html_pages_per_chunk
                        html_content = ""
                        for idx, start in enumerate(range(1, total_pages + 1, chunk_size), 1):
                            end = min(start + chunk_size - 1, total_pages)
                            body_only = idx > 1
                            chunk_html = self._direct_html_extraction_range(uploaded_file, start, end, body_only=body_only)
                            if not html_content:
                                html_content = chunk_html
                            else:
                                chunk_body = self._extract_body_inner(chunk_html)
                                if "</body>" in html_content:
                                    html_content = html_content.replace("</body>", f"{chunk_body}\n</body>")
                                else:
                                    html_content = f"{html_content}\n{chunk_body}"
                        result["method"] = "direct_html_chunked"
                    else:
                        html_content = self._direct_html_extraction(uploaded_file)
                        result["method"] = "direct_html"
                except Exception as html_err:
                    logger.error(f"Direct HTML extraction failed: {html_err}")
                    if self.config.fallback_to_text_only:
                        html_content = self._text_only_extraction(pdf_path)
                        result["method"] = "text_only"
                    else:
                        raise
                if self.config.postprocess_gemini_html and html_content:
                    html_content = GeminiHtmlPostProcessor.postprocess(
                        html_content,
                        tighten_columns=self.config.tighten_columns,
                        inject_mathjax=self.config.inject_mathjax
                    )
                if self.config.include_debug_info and html_content:
                    debug_parts = ['<section class="debug-info" role="note">', '<h2>Debug Info</h2>']
                    debug_parts.append(f"<p>Extraction method: {result.get('method')}</p>")
                    debug_parts.append("</section>")
                    debug_html = "\n".join(debug_parts)
                    if "</body>" in html_content:
                        html_content = html_content.replace("</body>", f"{debug_html}\n</body>")
                    else:
                        html_content = f"{html_content}\n{debug_html}"
                if self.config.minify_html and html_content:
                    html_content = PerformanceOptimizer.lazy_load_images(html_content)
                    html_content = PerformanceOptimizer.minify_html(html_content)
            else:
                if self.config.enable_caching:
                    try:
                        cache_dir, cache_path = self._get_cache_paths(pdf_path, output_base)
                        if cache_path.exists():
                            cache_age = time.time() - cache_path.stat().st_mtime
                            ttl_seconds = self.config.cache_ttl_hours * 3600
                            if cache_age <= ttl_seconds:
                                cached_payload = cache_path.read_text(encoding="utf-8")
                                doc = DocumentStructure.model_validate_json(cached_payload)
                                result["document"] = doc
                                result["method"] = "cache"
                                result["cached"] = True
                                result["cache_age_seconds"] = round(cache_age, 2)
                                cache_used = True
                                logger.info(f"Cache hit: {cache_path.name}")
                            else:
                                logger.info(f"Cache expired (age {cache_age:.0f}s), reprocessing")
                    except Exception as cache_err:
                        logger.warning(f"Cache read failed: {cache_err}")

                if doc is None:
                    # Upload the PDF
                    uploaded_file = self._upload_pdf(pdf_path)
                    self._uploaded_file = uploaded_file
                    
                    # Try structured extraction first
                    try:
                        if self.config.use_chunked_processing:
                            logger.info("Using chunked processing for large document support")
                            doc = self._extract_chunked(uploaded_file, pdf_path)
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

                    except Exception as e:
                        logger.warning(f"Structured extraction failed: {e}. Falling back to direct HTML.")
                        try:
                            html_content = self._direct_html_extraction(uploaded_file)
                            result["method"] = "fallback"
                        except Exception as html_err:
                            logger.error(f"Direct HTML extraction failed: {html_err}")
                            if self.config.fallback_to_text_only:
                                html_content = self._text_only_extraction(pdf_path)
                                result["method"] = "text_only"
                            else:
                                raise

                if doc:
                    if self.config.auto_fix_errors:
                        doc = DocumentValidator.auto_fix(doc)
                        result["document"] = doc

                    # Optional validation
                    validation_result = None
                    if self.config.enable_validation:
                        try:
                            validation_result = DocumentValidator.validate(doc, level=self.config.validation_level)
                            result["validation"] = validation_result.model_dump()
                            if validation_result.quality_score < self.config.quality_threshold:
                                logger.warning(
                                    f"Quality score {validation_result.quality_score:.1f} below threshold "
                                    f"{self.config.quality_threshold:.1f}"
                                )
                                if not self.config.continue_on_error:
                                    raise RuntimeError("Quality threshold not met")
                        except Exception as validation_err:
                            logger.warning(f"Validation failed: {validation_err}")
                            if not self.config.continue_on_error:
                                raise

                    if self.config.enable_caching and cache_path and not cache_used:
                        try:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_text(doc.model_dump_json(), encoding="utf-8")
                            result["cache_saved"] = True
                            logger.info(f"Cached document: {cache_path.name}")
                        except Exception as cache_err:
                            logger.warning(f"Cache write failed: {cache_err}")

                    # Render to HTML from structured data
                    if self.config.output_format in ("html", "both"):
                        html_content = HTMLRenderer.render(
                            doc,
                            theme=self.config.default_theme,
                            include_metadata=self.config.include_metadata,
                            include_toc=self.config.include_toc,
                            include_navigation=self.config.include_navigation,
                            include_images=self.config.extract_images,
                            include_page_numbers=True,
                            include_lists=self.config.include_lists,
                        )
                    
                    # EXPERIMENTAL: Also get HTML directly from Gemini if enabled
                    if self.config.experimental_gemini_html and uploaded_file:
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

            if not doc and not html_content:
                raise RuntimeError("No HTML content produced")

            if self.config.include_debug_info and html_content:
                debug_parts = ['<section class="debug-info" role="note">', '<h2>Debug Info</h2>']
                if doc and doc.extraction_notes:
                    debug_parts.append("<h3>Extraction Notes</h3>")
                    debug_parts.append(f"<pre>{HTMLRenderer._escape(doc.extraction_notes)}</pre>")
                validation_payload = result.get("validation")
                if validation_payload:
                    error_count = len(validation_payload.get("errors", []))
                    warning_count = len(validation_payload.get("warnings", []))
                    quality_score = validation_payload.get("quality_score")
                    debug_parts.append("<h3>Validation Summary</h3>")
                    debug_parts.append(
                        f"<p>Quality score: {quality_score:.1f} | "
                        f"Errors: {error_count} | Warnings: {warning_count}</p>"
                    )
                debug_parts.append("</section>")
                debug_html = "\n".join(debug_parts)
                if "</body>" in html_content:
                    html_content = html_content.replace("</body>", f"{debug_html}\n</body>")
                else:
                    html_content = f"{html_content}\n{debug_html}"

            if self.config.minify_html and html_content:
                html_content = PerformanceOptimizer.lazy_load_images(html_content)
                html_content = PerformanceOptimizer.minify_html(html_content)
            
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
            
            elapsed = time.time() - start_time
            result["processing_time_seconds"] = round(elapsed, 2)
            result["processing_time_minutes"] = round(elapsed / 60, 2)
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
    parser.add_argument("--theme", choices=["light"], default="light",
                        help="Default HTML theme (default: light)")
    parser.add_argument("--minify-html", action="store_true",
                        help="Minify HTML output and enable lazy image loading")
    parser.add_argument("--no-validation", action="store_true",
                        help="Disable validation and quality scoring")
    parser.add_argument("--validation-level", choices=["basic", "standard", "strict"], default="standard",
                        help="Validation level (default: standard)")
    parser.add_argument("--quality-threshold", type=float, default=70.0,
                        help="Quality score threshold for warnings/errors (default: 70)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable local caching of extracted documents")
    parser.add_argument("--parallel", action="store_true",
                        help="Enable parallel chunk processing")
    parser.add_argument("--max-workers", type=int, default=4,
                        help="Max workers for parallel processing (default: 4)")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Stop on first error or failed validation")
    parser.add_argument("--no-text-fallback", action="store_true",
                        help="Disable text-only fallback when extraction fails")
    parser.add_argument("--debug-info", action="store_true",
                        help="Include debug info block in HTML output")
    parser.add_argument("--include-metadata", action="store_true",
                        help="Include extracted metadata summary in HTML output")
    parser.add_argument("--include-toc", action="store_true",
                        help="Include table of contents in HTML output")
    parser.add_argument("--include-navigation", action="store_true",
                        help="Include interactive navigation UI (search/theme)")
    parser.add_argument("--include-lists", action="store_true",
                        help="Include lists of figures/tables/equations in HTML output")
    parser.add_argument("--direct-html-only", action="store_true",
                        help="Skip structured extraction and output Gemini's HTML only")
    parser.add_argument("--direct-html-pages-per-chunk", type=int, default=10,
                        help="Pages per direct-HTML request (default: 10)")
    parser.add_argument("--no-gemini-postprocess", action="store_true",
                        help="Disable post-processing of Gemini HTML")
    parser.add_argument("--no-tight-columns", action="store_true",
                        help="Do not tighten Gemini two-column layout")
    parser.add_argument("--no-mathjax", action="store_true",
                        help="Do not inject MathJax into Gemini HTML")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine output format
    output_format = args.format
    if args.json and output_format == "html":
        output_format = "both"
    if args.direct_html_only and output_format != "html":
        print("Direct HTML only mode ignores JSON output; forcing --format html.")
        output_format = "html"
    
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
        default_theme=args.theme,
        minify_html=args.minify_html,
        enable_validation=not args.no_validation,
        validation_level=args.validation_level,
        quality_threshold=args.quality_threshold,
        enable_caching=not args.no_cache,
        parallel_processing=args.parallel,
        max_workers=args.max_workers,
        continue_on_error=not args.fail_fast,
        fallback_to_text_only=not args.no_text_fallback,
        include_debug_info=args.debug_info,
        include_metadata=args.include_metadata,
        include_toc=args.include_toc,
        include_navigation=args.include_navigation,
        include_lists=args.include_lists,
        direct_html_only=args.direct_html_only,
        direct_html_pages_per_chunk=args.direct_html_pages_per_chunk,
        postprocess_gemini_html=not args.no_gemini_postprocess,
        tighten_columns=not args.no_tight_columns,
        inject_mathjax=not args.no_mathjax,
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
