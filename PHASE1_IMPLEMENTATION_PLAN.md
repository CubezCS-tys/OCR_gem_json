# Phase 1: Schema Enhancements Implementation Plan

## Overview
This document outlines the production-grade enhancements being made to the Pydantic schemas and HTML rendering for OCR_gem_json.

## Critical Issues Found

### 1. TableCell Defined But Not Used
**Problem:** `TableCell` class exists with row_span/col_span support, but `Table.rows` is `list[list[str]]` instead of using TableCell.

**Solution:** Migrate Table to use proper TableCell structure while maintaining backward compatibility.

### 2. No Inline Markup Support
**Problem:** TextBlock.content is a plain string - cannot represent links, bold, italic within text.

**Solution:** Add optional inline_elements field for rich text support.

### 3. Limited List Support
**Problem:** Only has list_level, no distinction between ul/ol/dl.

**Solution:** Add list_type and list_style fields.

### 4. Image Accessibility Gap
**Problem:** Single `description` field used for both alt text and detailed description.

**Solution:** Split into alt_text (required, concise) and long_description (optional, detailed).

## Schema Changes

### 1. Enhanced Table Support

```python
class TableCell(BaseModel):
    """Represents a cell in a table."""
    content: str
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    # NEW: Cell alignment
    alignment: Optional[Literal["left", "right", "center", "justify"]] = None

class TableRow(BaseModel):
    """Represents a row in a table - enables proper structure."""
    cells: list[TableCell]
    is_header_row: bool = False

class Table(BaseModel):
    """Represents a table extracted from the document."""
    caption: Optional[str] = None

    # DEPRECATED (keep for backward compatibility)
    headers: list[str] = Field(default_factory=list, description="DEPRECATED: Use rows with is_header cells")
    rows: list[list[str]] = Field(default_factory=list, description="DEPRECATED: Use structured_rows")

    # NEW: Proper structure
    structured_rows: Optional[list[TableRow]] = Field(default=None, description="Structured table rows with TableCell objects")

    # Bounding box (unchanged)
    bbox_top: Optional[float] = None
    bbox_left: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None
```

**Migration Strategy:**
1. Keep old fields for backward compatibility
2. Add new `structured_rows` field (optional)
3. HTML renderer checks `structured_rows` first, falls back to old format
4. Update Gemini prompts to use new format
5. After migration period, deprecate old fields

### 2. Inline Markup for TextBlock

```python
class InlineElement(BaseModel):
    """Represents inline formatting or links within text."""
    type: Literal["text", "link", "strong", "emphasis", "code"]
    content: str
    # For links
    url: Optional[str] = None
    # For internal references
    target_id: Optional[str] = None

class TextBlock(BaseModel):
    """Represents a block of text with semantic meaning."""
    block_type: Literal[...]  # existing types
    level: Optional[int] = None
    content: str  # KEEP for backward compatibility

    # NEW: Rich text support
    inline_elements: Optional[list[InlineElement]] = Field(
        default=None,
        description="Optional rich text markup. If None, use plain content field."
    )

    # NEW: List enhancements
    list_type: Optional[Literal["unordered", "ordered", "definition"]] = None
    list_marker_style: Optional[str] = Field(
        default=None,
        description="List marker: 'disc', 'circle', 'square', 'decimal', 'lower-alpha', etc."
    )

    # ... existing fields unchanged
```

### 3. Enhanced Image Accessibility

```python
class Image(BaseModel):
    """Represents a visual element (chart, graph, diagram, figure)."""
    image_type: Literal[...]  # existing types

    # DEPRECATED (keep for backward compatibility)
    description: str = Field(description="DEPRECATED: Use alt_text instead")

    # NEW: Proper accessibility
    alt_text: Optional[str] = Field(
        default=None,
        description="Short alternative text for accessibility (recommended: 125 chars or less)"
    )
    long_description: Optional[str] = Field(
        default=None,
        description="Detailed description for complex images (charts, diagrams)"
    )

    caption: Optional[str] = None
    # ... bbox fields unchanged
```

**Migration Strategy:**
1. Keep `description` field populated for backward compatibility
2. New extractions populate both `description` (copy of alt_text) and `alt_text`/`long_description`
3. HTML renderer prefers `alt_text` if present, falls back to `description`

## HTML Rendering Updates

### 1. Enhanced Table Rendering

```python
@staticmethod
def _render_table(table: Table) -> str:
    """Render table with proper semantic HTML."""
    parts = []

    if table.caption:
        parts.append(f'<p class="table-caption">{HTMLRenderer._escape(table.caption)}</p>')

    parts.append('<table>')

    # Use structured_rows if available (new format)
    if table.structured_rows:
        # Render with proper thead/tbody/tfoot sections
        # Support rowspan/colspan
        # Apply cell alignment
        ...
    else:
        # Fallback to old format for backward compatibility
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
```

### 2. Inline Markup Rendering

```python
@staticmethod
def _render_inline_elements(elements: list[InlineElement]) -> str:
    """Render inline elements as HTML."""
    parts = []
    for elem in elements:
        if elem.type == "text":
            parts.append(HTMLRenderer._escape(elem.content))
        elif elem.type == "link":
            if elem.url:
                parts.append(f'<a href="{elem.url}">{HTMLRenderer._escape(elem.content)}</a>')
            elif elem.target_id:
                parts.append(f'<a href="#{elem.target_id}">{HTMLRenderer._escape(elem.content)}</a>')
        elif elem.type == "strong":
            parts.append(f'<strong>{HTMLRenderer._escape(elem.content)}</strong>')
        elif elem.type == "emphasis":
            parts.append(f'<em>{HTMLRenderer._escape(elem.content)}</em>')
        elif elem.type == "code":
            parts.append(f'<code>{HTMLRenderer._escape(elem.content)}</code>')
    return "".join(parts)
```

### 3. Enhanced Image Rendering

```python
@staticmethod
def _render_image(image: Image) -> str:
    """Render image with proper accessibility."""
    # Determine alt text (prefer new field)
    alt_text = image.alt_text if image.alt_text else image.description

    parts = [f'<figure class="image-block" ...>']

    if image.image_data:
        parts.append(
            f'<img src="data:image/png;base64,{image.image_data}" '
            f'alt="{HTMLRenderer._escape(alt_text)}" />'
        )

    # Add long description if present
    if image.long_description:
        parts.append(
            f'<details class="image-long-desc">'
            f'<summary>Detailed Description</summary>'
            f'<p>{HTMLRenderer._escape(image.long_description)}</p>'
            f'</details>'
        )

    if image.caption:
        parts.append(f'<figcaption>{HTMLRenderer._escape(image.caption)}</figcaption>')

    parts.append('</figure>')
    return "\n".join(parts)
```

## Gemini Prompt Updates

Update system instructions to use new schema:

```
For TABLES:
- Use structured_rows with TableCell objects
- Set row_span and col_span for merged cells
- Mark header rows with is_header_row=true
- Mark header cells with is_header=true
- Set alignment: left/right/center/justify

For TEXT WITH LINKS:
- If text contains hyperlinks, use inline_elements
- type="link" with url field
- For other text, use type="text"

For LISTS:
- Set list_type: "unordered", "ordered", or "definition"
- Set list_marker_style: "disc", "decimal", "lower-alpha", etc.

For IMAGES:
- Provide concise alt_text (≤125 chars) for accessibility
- Provide detailed long_description for complex visuals
- Description field is deprecated but still populated for compatibility
```

## Testing Strategy

1. **Backward Compatibility Tests:**
   - Load old JSON files → verify HTML still renders
   - Test with missing new fields → verify graceful fallback

2. **New Format Tests:**
   - Create tables with merged cells → verify rowspan/colspan render
   - Create text with links → verify links render correctly
   - Create images with long descriptions → verify accessibility

3. **Migration Tests:**
   - Process new PDFs → verify new schema is used
   - Compare output quality before/after

## Rollout Plan

1. **Phase 1a:** Implement schema changes with backward compatibility
2. **Phase 1b:** Update HTML renderer to use new fields
3. **Phase 1c:** Update Gemini prompts
4. **Phase 1d:** Test with sample documents
5. **Phase 1e:** Deploy and monitor

## Success Criteria

- ✅ All existing JSON files still render correctly
- ✅ New extractions use enhanced schema
- ✅ HTML output has proper accessibility attributes
- ✅ Tables with merged cells render correctly
- ✅ Links in text are clickable
- ✅ Images have proper alt text
- ✅ No breaking changes to API

## Notes

- All new fields are Optional to maintain backward compatibility
- Old fields marked as DEPRECATED but still functional
- HTML renderer checks new fields first, falls back to old
- After 6-month migration period, consider removing deprecated fields
