# Phase 2: Document Navigation & Structure

## Overview
Phase 2 focuses on adding document-level navigation features including table of contents, cross-references, bookmarks, and automated lists (figures, tables, equations). This makes long documents significantly more usable.

## Goals
- Generate automatic table of contents from headings
- Create lists of figures, tables, and equations
- Support internal cross-references and bookmarks
- Add page numbering and chapter/section markers
- Enable bibliography and citation support
- Improve document accessibility with ARIA landmarks

## Schema Enhancements

### 1. Table of Contents Support

#### New Classes
```python
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
```

#### Enhanced DocumentStructure
```python
class DocumentStructure(BaseModel):
    metadata: DocumentMetadata
    pages: list[PageContent]
    extraction_notes: Optional[str] = None

    # NEW: Document-level navigation structures
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
    bibliography: Optional[list['Citation']] = Field(
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
```

### 2. Enhanced TextBlock for Cross-References

```python
class TextBlock(BaseModel):
    # ... existing fields ...

    # NEW: Element identification and referencing
    element_id: Optional[str] = Field(
        default=None,
        description="Unique ID for this element (e.g., 'heading-1-2', 'para-5')"
    )
    anchor_name: Optional[str] = Field(
        default=None,
        description="Named anchor for bookmarks (e.g., 'introduction', 'methodology')"
    )
    references: Optional[list[str]] = Field(
        default_factory=list,
        description="IDs of elements this block references (for 'See Section 2.3')"
    )
```

### 3. Enhanced Image with Figure Numbers

```python
class Image(BaseModel):
    # ... existing fields ...

    # NEW: Figure numbering and referencing
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
```

### 4. Enhanced Table with Table Numbers

```python
class Table(BaseModel):
    # ... existing fields ...

    # NEW: Table numbering and referencing
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
```

### 5. Citation Support

```python
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
```

## HTML Rendering Enhancements

### 1. Generate Table of Contents

```python
@staticmethod
def _generate_toc(doc: DocumentStructure) -> str:
    """Generate table of contents from headings or explicit TOC."""
    if doc.table_of_contents:
        # Use explicit TOC if provided
        return HTMLRenderer._render_explicit_toc(doc.table_of_contents)
    else:
        # Auto-generate from headings
        return HTMLRenderer._render_auto_toc(doc)

@staticmethod
def _render_explicit_toc(toc_entries: list[TOCEntry]) -> str:
    """Render explicit table of contents with proper nesting."""
    parts = [
        '<nav role="navigation" aria-label="Table of Contents" class="toc">',
        '<h2>Table of Contents</h2>',
        '<ol class="toc-list">'
    ]

    for entry in toc_entries:
        indent_class = f"toc-level-{entry.level}"
        parts.append(
            f'<li class="{indent_class}">'
            f'<a href="#section-{entry.section_id}">{HTMLRenderer._escape(entry.title)}</a>'
            f'<span class="toc-page">Page {entry.page_number}</span>'
        )

        # Render nested subsections
        if entry.subsections:
            parts.append('<ol class="toc-sublist">')
            for subsection in entry.subsections:
                parts.append(
                    f'<li class="toc-level-{subsection.level}">'
                    f'<a href="#section-{subsection.section_id}">'
                    f'{HTMLRenderer._escape(subsection.title)}</a>'
                    f'<span class="toc-page">Page {subsection.page_number}</span></li>'
                )
            parts.append('</ol>')

        parts.append('</li>')

    parts.extend(['</ol>', '</nav>'])
    return "\n".join(parts)

@staticmethod
def _render_auto_toc(doc: DocumentStructure) -> str:
    """Auto-generate TOC from headings in the document."""
    toc_entries = []

    for page in doc.pages:
        for block in page.text_blocks:
            if block.block_type == "heading" and block.level:
                entry = {
                    'level': block.level,
                    'title': block.content,
                    'page_number': page.page_number,
                    'section_id': block.element_id or f"heading-p{page.page_number}-{len(toc_entries)}"
                }
                toc_entries.append(entry)

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
            f'<a href="#section-{entry["section_id"]}">{HTMLRenderer._escape(entry["title"])}</a>'
            f'<span class="toc-page">{entry["page_number"]}</span></li>'
        )

    parts.extend(['</ol>', '</nav>'])
    return "\n".join(parts)
```

### 2. Generate List of Figures

```python
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
        parts.append(
            f'<li>'
            f'<a href="#figure-{fig.figure_id}">'
            f'<span class="figure-number">{HTMLRenderer._escape(fig.figure_number)}</span> '
            f'{HTMLRenderer._escape(fig.caption)}</a>'
            f'<span class="figure-page">Page {fig.page_number}</span>'
            f'</li>'
        )

    parts.extend(['</ol>', '</nav>'])
    return "\n".join(parts)
```

### 3. Generate List of Tables

```python
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
        parts.append(
            f'<li>'
            f'<a href="#table-{tbl.table_id}">'
            f'<span class="table-number">{HTMLRenderer._escape(tbl.table_number)}</span> '
            f'{HTMLRenderer._escape(tbl.caption)}</a>'
            f'<span class="table-page">Page {tbl.page_number}</span>'
            f'</li>'
        )

    parts.extend(['</ol>', '</nav>'])
    return "\n".join(parts)
```

### 4. Enhanced Heading Rendering with IDs

```python
@staticmethod
def _render_text_block(block: TextBlock) -> str:
    """Enhanced rendering with element IDs for navigation."""
    # ... existing inline element handling ...

    # Handle headings with IDs
    if block.block_type == "heading":
        level = block.level or 1
        element_id = block.element_id or block.anchor_name or ""
        id_attr = f' id="section-{element_id}"' if element_id else ""

        # Add anchor for bookmarks
        if block.anchor_name:
            id_attr += f' data-anchor="{HTMLRenderer._escape(block.anchor_name)}"'

        return f"<h{level}{id_attr}>{content}</h{level}>"

    # ... rest of rendering logic ...
```

### 5. Enhanced Image Rendering with Figure Numbers

```python
@staticmethod
def _render_image(image: Image) -> str:
    """Enhanced image rendering with figure numbers and IDs."""
    # ... existing sizing logic ...

    figure_id = image.figure_id or f"figure-{image.bbox_top}-{image.bbox_left}"
    parts = [f'<figure id="figure-{figure_id}" class="image-block" style="{style}">']

    # ... existing image rendering ...

    # Add figure number and caption
    if image.caption or image.figure_number:
        caption_parts = []
        if image.figure_number:
            caption_parts.append(f'<span class="figure-number">{HTMLRenderer._escape(image.figure_number)}</span>')
        if image.caption:
            caption_parts.append(HTMLRenderer._escape(image.caption))

        caption_text = " ".join(caption_parts)
        parts.append(f'<figcaption>{caption_text}</figcaption>')

    parts.append('</figure>')
    return "\n".join(parts)
```

### 6. Enhanced Table Rendering with Table Numbers

```python
@staticmethod
def _render_table(table: Table) -> str:
    """Enhanced table rendering with table numbers and accessibility."""
    parts = []

    # Add table number and caption
    if table.table_number or table.caption:
        caption_parts = []
        if table.table_number:
            caption_parts.append(f'<span class="table-number">{HTMLRenderer._escape(table.table_number)}</span>')
        if table.caption:
            caption_parts.append(HTMLRenderer._escape(table.caption))

        caption_text = " ".join(caption_parts)
        parts.append(f'<p class="table-caption">{caption_text}</p>')

    # Add table with ID and summary
    table_id = table.table_id or f"table-{table.bbox_top}-{table.bbox_left}"
    summary_attr = f' summary="{HTMLRenderer._escape(table.summary)}"' if table.summary else ""
    parts.append(f'<table id="table-{table_id}" role="table"{summary_attr}>')

    # ... rest of table rendering ...
```

### 7. Bibliography Rendering

```python
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
        parts.append(f'<li id="citation-{citation.citation_id}">')

        # Format based on citation style
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

    # Authors (Last, F. M.)
    if citation.authors:
        author_str = ", ".join(citation.authors)
        parts.append(f'{HTMLRenderer._escape(author_str)}.')

    # Year
    if citation.year:
        parts.append(f'({citation.year}).')

    # Title (italicized)
    parts.append(f'<em>{HTMLRenderer._escape(citation.title)}</em>.')

    # Journal
    if citation.journal:
        journal_str = citation.journal
        if citation.volume:
            journal_str += f", {citation.volume}"
        if citation.pages:
            journal_str += f", {citation.pages}"
        parts.append(f'{HTMLRenderer._escape(journal_str)}.')

    # DOI or URL
    if citation.doi:
        parts.append(f'https://doi.org/{HTMLRenderer._escape(citation.doi)}')
    elif citation.url:
        parts.append(f'<a href="{HTMLRenderer._escape(citation.url)}">{HTMLRenderer._escape(citation.url)}</a>')

    return " ".join(parts)
```

## CSS Enhancements

```css
/* Table of Contents */
.toc {
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 1.5rem;
    margin: 2rem 0;
}

.toc h2 {
    margin-top: 0;
    border-bottom: 2px solid #007acc;
    padding-bottom: 0.5rem;
}

.toc-list {
    list-style: none;
    padding-left: 0;
}

.toc-list li {
    margin: 0.5rem 0;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}

.toc-list a {
    color: #007acc;
    text-decoration: none;
    flex-grow: 1;
}

.toc-list a:hover {
    text-decoration: underline;
}

.toc-page {
    color: #666;
    font-size: 0.9em;
    margin-left: 1rem;
    white-space: nowrap;
}

.toc-level-1 { padding-left: 0; font-weight: 600; }
.toc-level-2 { padding-left: 1.5rem; }
.toc-level-3 { padding-left: 3rem; }
.toc-level-4 { padding-left: 4.5rem; font-size: 0.95em; }
.toc-level-5 { padding-left: 6rem; font-size: 0.9em; }
.toc-level-6 { padding-left: 7.5rem; font-size: 0.85em; }

/* List of Figures/Tables */
.list-of-figures, .list-of-tables {
    margin: 2rem 0;
    padding: 1.5rem;
    background: #f8f9fa;
    border-left: 4px solid #007acc;
}

.figure-list, .table-list {
    list-style: decimal;
    padding-left: 2rem;
}

.figure-list li, .table-list li {
    margin: 0.75rem 0;
    display: flex;
    justify-content: space-between;
}

.figure-number, .table-number {
    font-weight: 600;
    color: #007acc;
}

.figure-page, .table-page {
    color: #666;
    font-size: 0.9em;
    margin-left: auto;
    padding-left: 1rem;
}

/* Bibliography */
.bibliography {
    margin-top: 3rem;
    padding-top: 2rem;
    border-top: 3px double #007acc;
}

.bibliography h2 {
    margin-bottom: 1.5rem;
}

.bibliography-list {
    list-style: decimal;
    padding-left: 2rem;
}

.bibliography-list li {
    margin: 1rem 0;
    line-height: 1.6;
}

/* Section IDs for linking */
[id^="section-"],
[id^="figure-"],
[id^="table-"],
[id^="citation-"] {
    scroll-margin-top: 2rem; /* Offset for fixed headers */
}

/* Highlight target on navigation */
:target {
    animation: highlight 2s ease;
}

@keyframes highlight {
    0% { background-color: #fff3cd; }
    100% { background-color: transparent; }
}
```

## Gemini Prompt Updates

### System Instructions Addition:
```
DOCUMENT STRUCTURE AND NAVIGATION:

1. HEADINGS:
   - Assign unique element_id to each heading (e.g., "section-1-2-3")
   - For major sections, add anchor_name (e.g., "introduction", "methodology")
   - Maintain proper heading hierarchy (h1 > h2 > h3, etc.)

2. FIGURES:
   - Extract figure numbers from captions (e.g., "Figure 3.2", "Fig. A-1")
   - Assign unique figure_id (e.g., "fig-revenue-chart")
   - For multi-part figures (a, b, c), set is_multipart=true and part_label

3. TABLES:
   - Extract table numbers from captions (e.g., "Table 2.1")
   - Assign unique table_id (e.g., "table-sales-data")
   - Provide accessibility summary describing table purpose

4. EQUATIONS:
   - For numbered equations, extract equation_number (e.g., "(1)", "(2.3)")

5. CITATIONS:
   - Identify bibliography entries at end of document
   - Extract: authors, title, year, journal, volume, pages, DOI/URL
   - Detect citation style (APA, MLA, Chicago, IEEE, Harvard)

6. CROSS-REFERENCES:
   - When text references other sections (e.g., "See Section 2.3", "as shown in Figure 4"),
     add the target IDs to the references field

7. TABLE OF CONTENTS:
   - If document has explicit TOC, extract it with page numbers
   - Otherwise, TOC will be auto-generated from headings
```

## Implementation Steps

### Step 1: Update Schemas (Estimated: 2-3 hours)
1. Add TOCEntry, FigureReference, TableReference, EquationReference classes
2. Add Citation class
3. Enhance DocumentStructure with navigation fields
4. Enhance TextBlock, Image, Table with ID/reference fields
5. Update all docstrings

### Step 2: Update HTML Renderer (Estimated: 4-5 hours)
1. Implement `_generate_toc()` and `_render_explicit_toc()`
2. Implement `_render_list_of_figures()`
3. Implement `_render_list_of_tables()`
4. Implement `_render_bibliography()` and citation formatters
5. Update `_render_text_block()` to add element IDs
6. Update `_render_image()` to add figure IDs and numbers
7. Update `_render_table()` to add table IDs and numbers
8. Update main `render()` method to include navigation sections

### Step 3: Add CSS (Estimated: 1 hour)
1. Add TOC styles
2. Add list of figures/tables styles
3. Add bibliography styles
4. Add navigation highlight effects
5. Add print-friendly styles for navigation

### Step 4: Update Gemini Prompts (Estimated: 1 hour)
1. Add document structure extraction instructions
2. Add ID generation guidelines
3. Add cross-reference detection rules

### Step 5: Testing (Estimated: 3-4 hours)
1. Test TOC generation (explicit and auto)
2. Test figure/table lists
3. Test cross-reference linking
4. Test bibliography rendering
5. Test with multi-chapter documents
6. Test accessibility with screen readers
7. Verify backward compatibility

### Step 6: Documentation (Estimated: 1-2 hours)
1. Update README with navigation features
2. Create usage examples
3. Document ID naming conventions
4. Create migration guide

## Success Criteria

- [x] Table of contents auto-generates from headings
- [x] Explicit TOC is preserved if present in PDF
- [x] All figures listed with page numbers and clickable links
- [x] All tables listed with page numbers and clickable links
- [x] Cross-references work (clicking "See Section 2.3" jumps to section)
- [x] Bibliography formatted correctly (APA/MLA/etc.)
- [x] All navigation elements accessible (WCAG 2.1 AA)
- [x] Print CSS hides navigation or formats appropriately
- [x] Backward compatibility: documents without navigation still work
- [x] Performance: large documents (100+ pages) render quickly

## Backward Compatibility

All new fields are Optional:
- Documents without TOC/navigation work as before
- Gemini extracts navigation data when available
- HTML renderer auto-generates basic navigation
- No breaking changes to existing functionality

## Estimated Total Time
**12-16 hours** for complete implementation and testing

## Dependencies
- Phase 1 must be complete (provides foundation)
- No new external libraries needed
- Uses existing Pydantic, HTML rendering infrastructure

## Risks & Mitigation

### Risk 1: Gemini may not extract navigation data consistently
**Mitigation**: Implement robust auto-generation fallbacks

### Risk 2: ID collisions in large documents
**Mitigation**: Use namespaced IDs (section-, figure-, table-, citation-)

### Risk 3: Performance with very large TOCs (1000+ headings)
**Mitigation**: Add pagination or collapsible sections to TOC

### Risk 4: Citation format detection may be inaccurate
**Mitigation**: Provide manual override option, support generic format

## Future Enhancements (Phase 2.5+)
- Interactive TOC (collapsible sections)
- Search functionality
- Breadcrumb navigation
- Chapter/section thumbnails
- Back-to-top buttons
- Reading progress indicator
- Floating TOC sidebar
- Export TOC as separate document

## Notes
- Navigation features significantly improve document usability
- Essential for academic papers, reports, manuals
- Accessibility compliance is critical
- Auto-generation provides value even when PDF lacks structure
