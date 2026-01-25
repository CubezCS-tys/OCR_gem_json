# Phase 3: Semantic Block Types & Structured Formatting

## Overview
Phase 3 expands the semantic vocabulary of the document schema to handle specialized content types commonly found in academic papers, technical documentation, and professional reports. This enables better semantic understanding, styling, and accessibility.

## Goals
- Support academic content (theorems, proofs, definitions, lemmas)
- Add specialized blocks (sidebars, callouts, warnings, notes)
- Implement structured formatting (bold, italic, underline, colors)
- Support code blocks with syntax highlighting
- Add metadata blocks (abstracts, keywords, author info)
- Enable semantic sections (appendices, acknowledgments)
- Improve mathematical content handling

## Schema Enhancements

### 1. Expanded Block Types

```python
class TextBlock(BaseModel):
    """Enhanced with expanded semantic types."""
    block_type: Literal[
        # Existing
        "heading", "paragraph", "list_item", "caption", "footnote",
        "quote", "code", "equation",

        # NEW: Academic/Technical
        "theorem", "proof", "lemma", "corollary", "proposition",
        "definition", "example", "remark", "note",

        # NEW: Document structure
        "abstract", "summary", "keywords", "author_info",
        "acknowledgments", "appendix_heading",

        # NEW: Special blocks
        "sidebar", "callout", "warning", "tip", "important",
        "question", "answer", "exercise", "solution",

        # NEW: Content types
        "verse", "poetry", "dialogue", "preformatted",
        "page_number", "running_head", "watermark",

        # NEW: Reference markers
        "reference", "citation_inline", "bibliography_entry"
    ] = Field(description="Semantic type of the text block")

    # ... existing fields ...

    # NEW: Structured formatting (replaces vague 'style' field)
    formatting: Optional['TextFormatting'] = Field(
        default=None,
        description="Structured text formatting (replaces style string)"
    )

    # NEW: Semantic metadata
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
```

### 2. Structured Text Formatting

```python
class TextFormatting(BaseModel):
    """Structured text formatting to replace vague style strings."""

    # Typography
    bold: bool = Field(default=False, description="Bold/strong text")
    italic: bool = Field(default=False, description="Italic/emphasized text")
    underline: bool = Field(default=False, description="Underlined text")
    strikethrough: bool = Field(default=False, description="Strikethrough text")

    # Position
    superscript: bool = Field(default=False, description="Superscript (x²)")
    subscript: bool = Field(default=False, description="Subscript (H₂O)")

    # Size
    font_size: Optional[Literal["xx-small", "x-small", "small", "normal", "large", "x-large", "xx-large"]] = Field(
        default=None,
        description="Relative font size"
    )

    # Alignment
    alignment: Optional[Literal["left", "right", "center", "justify"]] = Field(
        default=None,
        description="Text alignment"
    )

    # Colors
    text_color: Optional[str] = Field(
        default=None,
        description="Text color as hex code (e.g., '#ff0000') or name (e.g., 'red')"
    )
    background_color: Optional[str] = Field(
        default=None,
        description="Background/highlight color"
    )

    # Font
    font_family: Optional[str] = Field(
        default=None,
        description="Font family name (e.g., 'Arial', 'Times New Roman')"
    )
    monospace: bool = Field(
        default=False,
        description="Use monospace font (for code, technical content)"
    )

    # Indentation
    indent_level: Optional[int] = Field(
        default=None,
        ge=0,
        description="Indentation level (0=none, 1=first level, etc.)"
    )

    # Spacing
    line_height: Optional[Literal["single", "1.5", "double"]] = Field(
        default=None,
        description="Line height/spacing"
    )
```

### 3. Code Block Enhancement

```python
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

    # Bounding box
    bbox_top: Optional[float] = None
    bbox_left: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None
```

### 4. Special Block Containers

```python
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

    # Bounding box
    bbox_top: Optional[float] = None
    bbox_left: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None
```

### 5. Enhanced PageContent

```python
class PageContent(BaseModel):
    # ... existing fields ...

    # NEW: Code blocks separate from text blocks
    code_blocks: list[CodeBlock] = Field(
        default_factory=list,
        description="Code blocks on this page"
    )

    # NEW: Special content blocks
    special_blocks: list[SpecialBlock] = Field(
        default_factory=list,
        description="Sidebars, callouts, warnings, etc."
    )
```

### 6. Document Metadata Enhancement

```python
class DocumentMetadata(BaseModel):
    # ... existing fields ...

    # NEW: Enhanced academic metadata
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
```

## HTML Rendering Enhancements

### 1. Semantic Block Rendering

```python
@staticmethod
def _render_text_block(block: TextBlock) -> str:
    """Enhanced rendering with semantic HTML5 and structured formatting."""

    # Handle formatting
    if block.formatting:
        content = HTMLRenderer._apply_formatting(block.content, block.formatting)
    elif block.inline_elements:
        content = HTMLRenderer._render_inline_elements(block.inline_elements)
    else:
        content = HTMLRenderer._escape(block.content)

    # Apply text direction
    dir_attr = f' dir="{block.text_direction}"' if block.text_direction != "auto" else ""

    # Render based on semantic type
    if block.block_type == "heading":
        # ... existing heading logic ...
        pass

    elif block.block_type == "theorem":
        block_num = f' <span class="block-number">{block.block_number}</span>' if block.block_number else ""
        return (
            f'<div class="theorem" id="{block.element_id or ""}">'
            f'<strong class="theorem-label">Theorem{block_num}:</strong> '
            f'<span class="theorem-content">{content}</span>'
            f'</div>'
        )

    elif block.block_type == "proof":
        return (
            f'<div class="proof">'
            f'<em class="proof-label">Proof:</em> '
            f'{content}'
            f'<span class="qed">∎</span>'
            f'</div>'
        )

    elif block.block_type == "definition":
        block_num = f' {block.block_number}' if block.block_number else ""
        return (
            f'<div class="definition" id="{block.element_id or ""}">'
            f'<strong class="definition-label">Definition{block_num}:</strong> '
            f'{content}'
            f'</div>'
        )

    elif block.block_type == "abstract":
        return (
            f'<section class="abstract" role="doc-abstract">'
            f'<h2>Abstract</h2>'
            f'<p>{content}</p>'
            f'</section>'
        )

    elif block.block_type == "keywords":
        keywords = content.split(',') if ',' in content else content.split()
        keyword_spans = [f'<span class="keyword">{kw.strip()}</span>' for kw in keywords]
        return (
            f'<div class="keywords">'
            f'<strong>Keywords:</strong> '
            f'{", ".join(keyword_spans)}'
            f'</div>'
        )

    elif block.block_type in ["warning", "tip", "important", "note"]:
        icon_map = {
            "warning": "⚠️",
            "tip": "💡",
            "important": "❗",
            "note": "📝"
        }
        icon = icon_map.get(block.block_type, "ℹ️")
        severity_class = f"severity-{block.severity}" if block.severity else ""

        return (
            f'<div class="callout callout-{block.block_type} {severity_class}" role="note">'
            f'<div class="callout-icon">{icon}</div>'
            f'<div class="callout-content">{content}</div>'
            f'</div>'
        )

    elif block.block_type == "verse":
        # Preserve line breaks in poetry
        lines = content.split('\n')
        verse_lines = '<br>'.join([f'<span class="verse-line">{line}</span>' for line in lines])
        return f'<div class="verse">{verse_lines}</div>'

    elif block.block_type == "preformatted":
        return f'<pre class="preformatted">{content}</pre>'

    # ... handle other block types ...

    # Default: paragraph
    return f'<p{dir_attr}>{content}</p>'

@staticmethod
def _apply_formatting(text: str, formatting: TextFormatting) -> str:
    """Apply structured formatting to text."""
    content = HTMLRenderer._escape(text)

    # Apply text styling
    if formatting.bold:
        content = f'<strong>{content}</strong>'
    if formatting.italic:
        content = f'<em>{content}</em>'
    if formatting.underline:
        content = f'<u>{content}</u>'
    if formatting.strikethrough:
        content = f'<s>{content}</s>'
    if formatting.superscript:
        content = f'<sup>{content}</sup>'
    if formatting.subscript:
        content = f'<sub>{content}</sub>'

    # Build style attribute
    styles = []
    if formatting.text_color:
        styles.append(f'color: {formatting.text_color}')
    if formatting.background_color:
        styles.append(f'background-color: {formatting.background_color}')
    if formatting.font_family:
        styles.append(f'font-family: {formatting.font_family}')
    if formatting.font_size:
        size_map = {
            "xx-small": "0.6em", "x-small": "0.75em", "small": "0.875em",
            "normal": "1em", "large": "1.25em", "x-large": "1.5em", "xx-large": "2em"
        }
        styles.append(f'font-size: {size_map[formatting.font_size]}')
    if formatting.alignment:
        styles.append(f'text-align: {formatting.alignment}')

    if styles:
        style_attr = f' style="{"; ".join(styles)}"'
        content = f'<span{style_attr}>{content}</span>'

    return content
```

### 2. Code Block Rendering with Syntax Highlighting

```python
@staticmethod
def _render_code_block(code_block: CodeBlock) -> str:
    """Render code block with syntax highlighting."""
    escaped_code = HTMLRenderer._escape(code_block.code)

    # Language class for syntax highlighters (Prism.js, highlight.js)
    lang_class = f'language-{code_block.language}' if code_block.language else 'language-none'

    # Line numbers
    if code_block.line_numbers:
        lines = escaped_code.split('\n')
        numbered_lines = []
        for i, line in enumerate(lines, start=code_block.start_line):
            line_class = 'highlight-line' if code_block.highlight_lines and i in code_block.highlight_lines else ''
            numbered_lines.append(
                f'<span class="line-number">{i}</span>'
                f'<span class="line-content {line_class}">{line}</span>'
            )
        code_content = '\n'.join(numbered_lines)
        pre_class = 'line-numbers'
    else:
        code_content = escaped_code
        pre_class = ''

    # Filename header
    header = ''
    if code_block.filename:
        header = f'<div class="code-header"><span class="filename">{HTMLRenderer._escape(code_block.filename)}</span></div>'

    return (
        f'<div class="code-block-container">'
        f'{header}'
        f'<pre class="{pre_class}"><code class="{lang_class}">{code_content}</code></pre>'
        f'</div>'
    )
```

### 3. Special Block Rendering

```python
@staticmethod
def _render_special_block(block: SpecialBlock) -> str:
    """Render special content blocks (sidebars, callouts, etc.)."""

    # Render contained content
    content_html = []
    for text_block in block.content:
        content_html.append(HTMLRenderer._render_text_block(text_block))

    content_str = "\n".join(content_html)

    # Icon
    icon_html = ''
    if block.icon:
        icon_html = f'<div class="special-block-icon">{block.icon}</div>'

    # Title
    title_html = ''
    if block.title:
        title_html = f'<h3 class="special-block-title">{HTMLRenderer._escape(block.title)}</h3>'

    # CSS classes
    classes = [f'special-block', f'special-block-{block.block_type}']
    if block.severity:
        classes.append(f'severity-{block.severity}')
    if block.collapsible:
        classes.append('collapsible')

    class_str = ' '.join(classes)

    # Collapsible wrapper
    if block.collapsible:
        return (
            f'<details class="{class_str}">'
            f'<summary>{icon_html}{title_html}</summary>'
            f'<div class="special-block-content">{content_str}</div>'
            f'</details>'
        )
    else:
        return (
            f'<aside class="{class_str}" role="complementary">'
            f'{icon_html}{title_html}'
            f'<div class="special-block-content">{content_str}</div>'
            f'</aside>'
        )
```

## CSS Enhancements

```css
/* Theorem, Proof, Definition styles */
.theorem, .definition, .lemma, .corollary {
    margin: 1.5rem 0;
    padding: 1rem 1.5rem;
    background: #f0f8ff;
    border-left: 4px solid #007acc;
    border-radius: 4px;
}

.theorem-label, .definition-label {
    font-weight: 700;
    color: #007acc;
}

.block-number {
    font-weight: 600;
}

.proof {
    margin: 1rem 0 1rem 2rem;
    padding: 1rem;
    border-left: 2px solid #999;
    background: #fafafa;
}

.proof-label {
    font-weight: 600;
}

.qed {
    float: right;
    font-size: 1.2em;
    color: #007acc;
}

/* Callouts and Special Blocks */
.callout {
    display: flex;
    margin: 1.5rem 0;
    padding: 1rem;
    border-radius: 6px;
    border-left: 4px solid;
}

.callout-icon {
    font-size: 1.5em;
    margin-right: 1rem;
    flex-shrink: 0;
}

.callout-content {
    flex-grow: 1;
}

.callout-warning {
    background: #fff3cd;
    border-color: #ffc107;
    color: #856404;
}

.callout-tip {
    background: #d1ecf1;
    border-color: #17a2b8;
    color: #0c5460;
}

.callout-important {
    background: #f8d7da;
    border-color: #dc3545;
    color: #721c24;
}

.callout-note {
    background: #d4edda;
    border-color: #28a745;
    color: #155724;
}

/* Severity indicators */
.severity-info { border-color: #17a2b8; }
.severity-success { border-color: #28a745; }
.severity-warning { border-color: #ffc107; }
.severity-error { border-color: #dc3545; }

/* Code blocks with syntax highlighting */
.code-block-container {
    margin: 1.5rem 0;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #e1e4e8;
}

.code-header {
    background: #f6f8fa;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid #e1e4e8;
    font-size: 0.9em;
}

.filename {
    font-family: monospace;
    color: #24292e;
}

.code-block-container pre {
    margin: 0;
    padding: 1rem;
    background: #f6f8fa;
    overflow-x: auto;
}

.line-numbers .line-number {
    display: inline-block;
    width: 3em;
    text-align: right;
    color: #999;
    user-select: none;
    margin-right: 1em;
}

.highlight-line {
    background: #fffbdd;
    display: inline-block;
    width: 100%;
}

/* Verse/Poetry */
.verse {
    font-family: Georgia, serif;
    font-style: italic;
    margin: 1.5rem 2rem;
    line-height: 1.8;
}

.verse-line {
    display: block;
    padding: 0.25rem 0;
}

/* Abstract and Keywords */
.abstract {
    margin: 2rem 0;
    padding: 1.5rem;
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 8px;
}

.abstract h2 {
    margin-top: 0;
    font-size: 1.2em;
    color: #007acc;
}

.keywords {
    margin: 1rem 0;
    padding: 0.75rem 1rem;
    background: #e7f3ff;
    border-left: 3px solid #007acc;
}

.keyword {
    display: inline-block;
    background: #007acc;
    color: white;
    padding: 0.2em 0.6em;
    border-radius: 3px;
    font-size: 0.85em;
    margin: 0.2em;
}

/* Special blocks */
.special-block {
    margin: 2rem 0;
    padding: 1.5rem;
    border-radius: 8px;
    border: 2px solid;
}

.special-block-sidebar {
    float: right;
    width: 30%;
    margin: 0 0 1rem 2rem;
    background: #f8f9fa;
    border-color: #dee2e6;
}

.special-block-title {
    margin-top: 0;
    font-size: 1.1em;
}

.special-block.collapsible summary {
    cursor: pointer;
    font-weight: 600;
    list-style: none;
    padding: 0.5rem 0;
}

.special-block.collapsible summary::-webkit-details-marker {
    display: none;
}

.special-block.collapsible summary:before {
    content: '▶ ';
    display: inline-block;
    transition: transform 0.2s;
}

.special-block.collapsible[open] summary:before {
    transform: rotate(90deg);
}

/* Preformatted text */
.preformatted {
    white-space: pre-wrap;
    font-family: 'Courier New', monospace;
    background: #f5f5f5;
    padding: 1rem;
    border: 1px dashed #ccc;
    overflow-x: auto;
}
```

## Gemini Prompt Updates

```
SEMANTIC CONTENT TYPES:

1. ACADEMIC CONTENT:
   - Theorem: Use block_type="theorem", extract number if present
   - Proof: Use block_type="proof", mark end with QED symbol location
   - Definition: Use block_type="definition", extract number
   - Lemma, Corollary: Similar to theorem
   - Example: Use block_type="example"

2. SPECIAL BLOCKS:
   - Sidebars: Content in margins or boxes, use block_type="sidebar"
   - Callouts: "Note:", "Warning:", "Tip:" → block_type="note"/"warning"/"tip"
   - Important information boxes → block_type="important"

3. CODE BLOCKS:
   - Detect programming language from context or syntax
   - Preserve exact formatting, indentation
   - Extract filename from comments or headers
   - Note line numbers if present

4. STRUCTURED FORMATTING:
   - Instead of style="bold", use formatting.bold=true
   - Detect: bold, italic, underline, colors, font sizes
   - Extract alignment: centered, right-aligned, justified

5. DOCUMENT METADATA:
   - Extract authors with affiliations from title page
   - Extract keywords (usually after abstract)
   - Extract abstract (usually after title, before main content)
   - Look for DOI, copyright, license information

6. VERSE/POETRY:
   - Preserve line breaks exactly
   - Use block_type="verse"
   - Maintain indentation patterns
```

## Implementation Steps

### Step 1: Schema Updates (3-4 hours)
1. Add new block types to TextBlock Literal
2. Create TextFormatting class
3. Create CodeBlock class
4. Create SpecialBlock class
5. Enhance Author and DocumentMetadata
6. Update docstrings and examples

### Step 2: HTML Rendering (5-6 hours)
1. Implement semantic block rendering for each new type
2. Implement _apply_formatting() method
3. Implement _render_code_block() with syntax highlighting support
4. Implement _render_special_block()
5. Update _render_text_block() to use TextFormatting
6. Add metadata rendering (abstract, keywords, authors)

### Step 3: CSS Additions (2-3 hours)
1. Add theorem/proof/definition styles
2. Add callout styles (warning, tip, note, important)
3. Add code block styles with syntax highlighting support
4. Add verse/poetry styles
5. Add abstract and keywords styles
6. Add special block styles
7. Add responsive styles for sidebars

### Step 4: Syntax Highlighting Integration (2 hours)
1. Add Prism.js or highlight.js CDN link
2. Configure supported languages
3. Add language detection logic
4. Test with various code samples

### Step 5: Gemini Prompts (1-2 hours)
1. Update system instructions for semantic blocks
2. Add formatting detection rules
3. Add code block extraction guidelines
4. Add metadata extraction instructions

### Step 6: Testing (4-5 hours)
1. Test academic content (papers with theorems)
2. Test technical documentation (code samples)
3. Test callouts and warnings
4. Test verse/poetry formatting
5. Test structured formatting combinations
6. Test metadata extraction
7. Backward compatibility verification

### Step 7: Documentation (1-2 hours)
1. Create block type reference guide
2. Document formatting options
3. Create usage examples
4. Update migration guide

## Success Criteria

- [x] All new block types render with appropriate semantic HTML
- [x] Theorem/proof/definition rendering matches academic standards
- [x] Code blocks support syntax highlighting
- [x] Callouts visually distinct with proper severity indicators
- [x] Structured formatting replaces vague style strings
- [x] Abstract and keywords properly extracted and styled
- [x] Verse/poetry preserves line breaks and formatting
- [x] Sidebars float properly without disrupting flow
- [x] All semantic blocks accessible (WCAG 2.1 AA)
- [x] Backward compatibility maintained
- [x] Performance acceptable with complex formatting

## Backward Compatibility

- All new block types are additions, not replacements
- Old `style` field still works (falls back if no `formatting`)
- Documents with only basic types continue working
- TextFormatting is optional
- CodeBlock and SpecialBlock are new, optional structures

## Estimated Total Time
**18-24 hours** for complete implementation and testing

## Dependencies
- Phase 1 and 2 complete
- Optional: Prism.js or highlight.js for syntax highlighting
- No other external dependencies

## Risks & Mitigation

### Risk 1: Gemini may not detect all semantic types
**Mitigation**: Provide strong hints in prompts, add manual override options

### Risk 2: Syntax highlighting library adds bloat
**Mitigation**: Use CDN, make it optional, support multiple backends

### Risk 3: Complex formatting increases JSON size
**Mitigation**: Only include formatting when different from defaults

### Risk 4: Academic notation varies by field
**Mitigation**: Support customizable labels, flexible numbering

## Future Enhancements (Phase 3.5+)
- Custom block type definitions
- LaTeX macro support
- Interactive code examples (runnable)
- Diagram rendering (Mermaid, PlantUML)
- Mathematical proof validation
- Citation hover previews
- Collapsible proofs

## Notes
- Semantic blocks dramatically improve document quality
- Essential for academic papers, textbooks, technical docs
- Proper semantic HTML enables better accessibility
- Structured formatting enables precise styling control
