"""
Canonical JSON Schema — the system-of-record for the fixed-layout pipeline.

Follows the architecture from "Recreating Scanned PDFs as High-Fidelity,
Text-Selectable HTML": store a page-accurate canonical representation
(PAGE-like JSON) with explicit coordinates, reading order, confidence,
and language/direction metadata. HTML is generated deterministically from this.

Every geometric element carries a bounding box in *page pixel coordinates*
(origin = top-left of the rasterised page image).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────

class Direction(str, Enum):
    RTL = "rtl"
    LTR = "ltr"


class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    EQUATION = "equation"
    HANDWRITING = "handwriting"
    STAMP = "stamp"
    SIGNATURE = "signature"
    BARCODE = "barcode"
    KEY_VALUE = "key_value"
    SELECTION_MARK = "selection_mark"
    UNKNOWN = "unknown"


class ReadingOrderMethod(str, Enum):
    ENGINE = "engine"       # Directly from Azure DI
    HEURISTIC = "heuristic" # Rule-based override
    MODEL = "model"         # LLM-assisted
    MANUAL = "manual"       # Human correction


# ─── Geometry Primitives ─────────────────────────────────────────────────────

class BBox(BaseModel):
    """Axis-aligned bounding box in page pixel coordinates."""
    x0: float = Field(..., description="Left edge (px)")
    y0: float = Field(..., description="Top edge (px)")
    x1: float = Field(..., description="Right edge (px)")
    y1: float = Field(..., description="Bottom edge (px)")

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def area(self) -> float:
        return self.width * self.height

    def iou(self, other: "BBox") -> float:
        """Intersection over Union."""
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def to_polygon(self) -> list[list[float]]:
        """Convert to polygon [[x,y], ...]."""
        return [
            [self.x0, self.y0],
            [self.x1, self.y0],
            [self.x1, self.y1],
            [self.x0, self.y1],
        ]


class Polygon(BaseModel):
    """Arbitrary polygon (e.g., from Azure DI's polygon output)."""
    points: list[list[float]] = Field(
        ..., description="List of [x, y] points in page pixel coordinates"
    )

    def to_bbox(self) -> BBox:
        """Compute axis-aligned bounding box from polygon."""
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return BBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))


# ─── Token / Word Level ─────────────────────────────────────────────────────

class Token(BaseModel):
    """A single word/token with geometry and confidence."""
    token_id: str = Field(default_factory=lambda: f"t_{uuid.uuid4().hex[:8]}")
    text: str
    bbox: BBox
    polygon: Optional[Polygon] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    language: Optional[str] = None  # ISO 639-1: "ar", "en", "fr"
    direction: Optional[Direction] = None
    # Style properties (from vision model)
    font_weight: Optional[str] = None  # "normal", "bold", "bolder"
    font_style: Optional[str] = None   # "normal", "italic"
    text_decoration: Optional[str] = None  # "none", "underline", "line-through"
    font_size_pt: Optional[float] = None
    text_color: Optional[str] = None  # hex color e.g. "#000000"


# ─── Line Level ──────────────────────────────────────────────────────────────

class Line(BaseModel):
    """A line of text with baseline geometry."""
    line_id: str = Field(default_factory=lambda: f"l_{uuid.uuid4().hex[:8]}")
    text: str = ""
    bbox: BBox
    polygon: Optional[Polygon] = None
    baseline: Optional[list[list[float]]] = None  # [[x,y], [x,y]]
    tokens: list[Token] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    language: Optional[str] = None
    direction: Optional[Direction] = None
    # Style properties (aggregated from tokens or detected directly)
    font_weight: Optional[str] = None
    font_style: Optional[str] = None
    text_decoration: Optional[str] = None
    background_color: Optional[str] = None  # hex color for highlighted text

    def compute_text(self) -> str:
        """Reconstruct line text from tokens."""
        if self.tokens:
            return " ".join(t.text for t in self.tokens)
        return self.text


# ─── Table Structure ─────────────────────────────────────────────────────────

class TableCell(BaseModel):
    """A single cell in a table."""
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    bbox: Optional[BBox] = None
    polygon: Optional[Polygon] = None
    text: str = ""
    tokens: list[Token] = Field(default_factory=list)
    is_header: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class Table(BaseModel):
    """A detected table with cell-level structure."""
    table_id: str = Field(default_factory=lambda: f"tb_{uuid.uuid4().hex[:8]}")
    bbox: BBox
    polygon: Optional[Polygon] = None
    row_count: int = 0
    col_count: int = 0
    cells: list[TableCell] = Field(default_factory=list)
    caption: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    def to_html_table(self) -> str:
        """Render table as semantic HTML <table>."""
        if not self.cells:
            return ""

        grid: dict[tuple[int, int], TableCell] = {}
        for cell in self.cells:
            grid[(cell.row, cell.col)] = cell

        max_row = max(c.row + c.row_span for c in self.cells) if self.cells else 0
        max_col = max(c.col + c.col_span for c in self.cells) if self.cells else 0

        html = '<table border="1" cellpadding="4" cellspacing="0">\n'

        # Track which cells are spanned over
        occupied: set[tuple[int, int]] = set()
        for cell in self.cells:
            for dr in range(cell.row_span):
                for dc in range(cell.col_span):
                    if dr == 0 and dc == 0:
                        continue
                    occupied.add((cell.row + dr, cell.col + dc))

        for r in range(max_row):
            html += "  <tr>\n"
            for c in range(max_col):
                if (r, c) in occupied:
                    continue
                cell = grid.get((r, c))
                if cell is None:
                    html += "    <td></td>\n"
                    continue
                tag = "th" if cell.is_header else "td"
                attrs = ""
                if cell.row_span > 1:
                    attrs += f' rowspan="{cell.row_span}"'
                if cell.col_span > 1:
                    attrs += f' colspan="{cell.col_span}"'
                html += f"    <{tag}{attrs}>{cell.text}</{tag}>\n"
            html += "  </tr>\n"

        html += "</table>"
        return html


# ─── Block (Region) Level ────────────────────────────────────────────────────

class Block(BaseModel):
    """
    A document region: text paragraph, table, figure, etc.
    This is the primary unit of the canonical representation.
    """
    block_id: str = Field(default_factory=lambda: f"b_{uuid.uuid4().hex[:8]}")
    block_type: BlockType = BlockType.TEXT
    bbox: BBox
    polygon: Optional[Polygon] = None
    direction: Direction = Direction.RTL  # Default RTL for Arabic-primary docs
    language: Optional[str] = None  # ISO 639-1
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    # Text content (for text blocks)
    lines: list[Line] = Field(default_factory=list)

    # Table content (for table blocks)
    table: Optional[Table] = None

    # Figure/image content
    figure_uri: Optional[str] = None  # Relative path to extracted figure
    figure_caption: Optional[str] = None

    # Equation content
    equation_latex: Optional[str] = None

    def full_text(self) -> str:
        """Reconstruct full block text from lines."""
        if self.lines:
            return "\n".join(
                line.compute_text() if line.tokens else line.text
                for line in self.lines
            )
        return ""


# ─── Reading Order ───────────────────────────────────────────────────────────

class ReadingOrderUnit(BaseModel):
    """A single unit in the reading order sequence."""
    unit_id: str
    ref_block_id: Optional[str] = None
    ref_table_id: Optional[str] = None


class ReadingOrder(BaseModel):
    """
    Explicit reading order for a page.
    The 'sequence' list defines the order in which blocks should be read.
    Provenance tracks how the order was determined.
    """
    units: list[ReadingOrderUnit] = Field(default_factory=list)
    sequence: list[str] = Field(
        default_factory=list,
        description="Ordered list of unit_ids"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    method: ReadingOrderMethod = ReadingOrderMethod.ENGINE


# ─── Page Level ──────────────────────────────────────────────────────────────

class PageImage(BaseModel):
    """Metadata for the rasterised page image."""
    uri: str = ""  # Relative path or base64 data URI
    width_px: int = 0
    height_px: int = 0
    dpi: int = 300
    format: str = "webp"


class Page(BaseModel):
    """
    A single page in the canonical representation.
    Contains all geometry, text, and structure data.
    """
    page_index: int = 0  # 0-based
    image: PageImage = Field(default_factory=PageImage)
    rotation_deg: int = 0  # Applied rotation to normalize orientation
    principal_direction: Direction = Direction.RTL

    # All detected blocks (regions) on this page
    blocks: list[Block] = Field(default_factory=list)

    # Tables extracted with structure
    tables: list[Table] = Field(default_factory=list)

    # Explicit reading order
    reading_order: ReadingOrder = Field(default_factory=ReadingOrder)

    # Raw content string in reading order (Azure-style)
    content_text: str = ""

    # Page-level confidence
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    def blocks_in_reading_order(self) -> list[Block]:
        """Return blocks sorted by reading order sequence."""
        if not self.reading_order.sequence:
            # Fallback: sort by vertical position
            return sorted(self.blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))

        block_map = {b.block_id: b for b in self.blocks}
        ordered = []
        for unit_id in self.reading_order.sequence:
            # Find the unit to get the block reference
            for unit in self.reading_order.units:
                if unit.unit_id == unit_id and unit.ref_block_id:
                    block = block_map.get(unit.ref_block_id)
                    if block:
                        ordered.append(block)
                    break
        # Append any blocks not in reading order
        ordered_ids = {b.block_id for b in ordered}
        for block in self.blocks:
            if block.block_id not in ordered_ids:
                ordered.append(block)
        return ordered


# ─── Document Level ──────────────────────────────────────────────────────────

class DocumentSource(BaseModel):
    """Source file metadata."""
    filename: str = ""
    file_hash: Optional[str] = None  # SHA-256
    page_count: int = 0
    file_size_bytes: int = 0


class ProcessingInfo(BaseModel):
    """Pipeline provenance metadata."""
    pipeline_version: str = "1.0.0"
    ocr_engine: str = "azure-document-intelligence"
    ocr_model: str = "prebuilt-layout"
    processed_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    processing_time_seconds: float = 0.0
    raster_dpi: int = 300
    preprocessing: list[str] = Field(default_factory=list)  # ["deskew", "denoise"]


class CanonicalDocument(BaseModel):
    """
    The top-level canonical representation.
    This is the system-of-record. HTML is generated from this deterministically.
    """
    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: DocumentSource = Field(default_factory=DocumentSource)
    processing: ProcessingInfo = Field(default_factory=ProcessingInfo)
    pages: list[Page] = Field(default_factory=list)

    # Document-level metadata
    title: Optional[str] = None
    languages: list[str] = Field(default_factory=lambda: ["ar", "en", "fr"])
    principal_direction: Direction = Direction.RTL

    def save(self, path: Path) -> None:
        """Save canonical document to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                self.model_dump(mode="json"),
                f,
                ensure_ascii=False,
                indent=2,
            )

    @classmethod
    def load(cls, path: Path) -> "CanonicalDocument":
        """Load canonical document from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def page_count(self) -> int:
        return len(self.pages)

    def total_blocks(self) -> int:
        return sum(len(p.blocks) for p in self.pages)

    def total_tokens(self) -> int:
        return sum(
            len(token.text)
            for page in self.pages
            for block in page.blocks
            for line in block.lines
            for token in line.tokens
        )

    def avg_confidence(self) -> float:
        """Average token-level confidence across the document."""
        confs = [
            token.confidence
            for page in self.pages
            for block in page.blocks
            for line in block.lines
            for token in line.tokens
            if token.confidence > 0
        ]
        return sum(confs) / len(confs) if confs else 0.0

    def summary(self) -> dict[str, Any]:
        """Quick summary of the canonical document."""
        return {
            "document_id": self.document_id,
            "source": self.source.filename,
            "pages": self.page_count(),
            "total_blocks": self.total_blocks(),
            "avg_confidence": round(self.avg_confidence(), 3),
            "languages": self.languages,
            "ocr_engine": self.processing.ocr_engine,
        }
