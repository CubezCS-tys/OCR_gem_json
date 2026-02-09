# JSON to HTML Rendering System - Detailed Explanation

## Overview

We manually build HTML from structured JSON responses using a **Pydantic schema** that captures document structure, then render it to HTML with custom CSS styling. This is NOT a simple markdown-to-HTML conversion - we preserve rich formatting, layout, and bidirectional text handling.

---

## The Complete Pipeline

```
PDF → Mistral OCR → Markdown
                      ↓
               Gemini API (with schema)
                      ↓
            Structured JSON (DocumentStructure)
                      ↓
               HTMLRenderer
                      ↓
            Publishable HTML
```

---

## Part 1: JSON Schema Structure (Pydantic Models)

### Root Schema: `DocumentStructure`

```python
{
  "metadata": DocumentMetadata,    # Document-level info
  "pages": [PageContent],          # Array of pages
  "extraction_notes": "string"     # Optional notes
}
```

### 1.1 DocumentMetadata

Contains document-level information:

```python
{
  "title": "Research Paper Title",
  "author": "Author Name",
  "total_pages": 25,
  "language": "ar",                  # Language code
  "document_type": "academic_paper",
  "is_scanned": false
}
```

**What we handle:**
- `language`: Used to set document direction (RTL for Arabic/Hebrew)
- `title`: Becomes HTML `<title>` tag
- Document metadata informs CSS choices (font families, text direction)

### 1.2 PageContent

Each page has:

```python
{
  "page_number": 1,
  "width_pts": 595,                     # Page dimensions in PDF points
  "height_pts": 842,
  "header": "Chapter 3: Methodology",   # Page header text
  "footer": "University Journal, 2024",
  "page_number_text": "42",            # Displayed page number
  "page_number_position": "footer-center",
  
  // Content arrays (order matters!)
  "text_blocks": [TextBlock],
  "tables": [Table],
  "images": [Image],
  
  // Layout properties
  "has_multi_column": true,
  "column_count": 2,
  "column_gap": 20,
  "page_direction": "rtl",
  
  // Appearance
  "background_color": "#ffffff",
  "watermark": "DRAFT"
}
```

**What we handle:**
- **Multi-column layout**: We use CSS `column-count` and sort elements by column number
- **Header/footer**: Rendered in separate divs with positioning
- **Page dimensions**: Set explicit width/height for accurate rendering
- **RTL/LTR direction**: Applied at page level, can be overridden per element

---

## Part 2: Content Block Types

### 2.1 TextBlock

The workhorse for text content:

```python
{
  "block_type": "heading" | "paragraph" | "list_item" | "caption" | 
                "footnote" | "quote" | "code" | "equation" | 
                "hyperlink" | "horizontal_rule",
  "level": 2,                     // For headings (1-6)
  "content": "النص العربي",        // The actual text
  
  // Rich text spans (character-level formatting)
  "spans": [
    {
      "text": "bold text",
      "bold": true,
      "italic": false,
      "font_size": 12,
      "text_color": "#ff0000"
    }
  ],
  
  // Typography
  "font_size": 14,
  "font_family": "Amiri",
  "font_weight": 700,
  "line_height": 1.8,
  "letter_spacing": 0.05,
  
  // Colors
  "text_color": "#333333",
  "background_color": "#f0f0f0",
  
  // Spacing (in ems/relative units)
  "indent_left": 2.0,
  "indent_right": 0.5,
  "indent_first_line": 1.5,
  "spacing_before": 1.0,
  "spacing_after": 0.5,
  
  // Direction and alignment
  "text_direction": "rtl",
  "text_align": "justify",
  
  // Flow control
  "reading_order": 5,
  "column_number": 1,
  
  // Type-specific fields
  "url": "https://example.com",    // For hyperlinks
  "link_type": "url",
  "is_display_math": true,         // For equations
  "equation_number": "(3.2)",
  "list_level": 1                  // For nested lists
}
```

**What we handle:**

1. **Block type rendering:**
   - `heading` → `<h1>` to `<h6>` based on level
   - `paragraph` → `<p>`
   - `list_item` → grouped into `<ul>` or `<ol>`
   - `quote` → `<blockquote>`
   - `code` → `<pre><code>`
   - `equation` → MathJax with LaTeX (e.g., `\\[x^2 + y^2 = z^2\\]`)
   - `hyperlink` → `<a href="..." target="_blank">`

2. **Rich text spans:**
   ```html
   <span class="bold" style="color: #ff0000; font-size: 12pt">bold text</span>
   ```

3. **Typography conversion:**
   - Font properties → inline `style` attribute
   - Spacing in ems → CSS margins/padding

4. **Direction detection:**
   - Auto-detect Arabic/Hebrew → add `dir="rtl"`
   - Detect English → add `dir="ltr"`
   - Override with explicit `text_direction`

5. **List grouping:**
   - Consecutive `list_item` blocks are detected
   - Grouped into single `<ul>` container
   - Nested lists handled via `list_level`

6. **Equation rendering:**
   - LaTeX content wrapped in MathJax delimiters
   - Display mode: `\\[equation\\]` → Centered
   - Inline mode: `\\(equation\\)` → In-text
   - Arabic captions separated and rendered with `dir="rtl"`

### 2.2 Table

Fully styled tables:

```python
{
  "caption": "جدول رقم 1: النتائج",
  
  // Headers array
  "headers": [
    {
      "content": "العدد",
      "is_header": true,
      "text_align": "center",
      "background_color": "#f0f0f0",
      "text_color": "#000000",
      "row_span": 1,
      "col_span": 1,
      "width_percent": 25.0
    }
  ],
  
  // Rows: array of cell arrays
  "rows": [
    [
      {
        "content": "42",
        "text_align": "right",
        "vertical_align": "middle",
        "border_width": 1,
        "border_color": "#cccccc"
      },
      // ... more cells
    ]
  ],
  
  // Table-level styling
  "border_style": "solid",
  "border_color": "#e0e0e0",
  "background_color": "#ffffff",
  
  // Flow control
  "reading_order": 10,
  "column_number": 1
}
```

**What we handle:**

1. **Table structure:**
   ```html
   <table dir="rtl">
     <thead>
       <tr>
         <th style="text-align: center; background-color: #f0f0f0">العدد</th>
       </tr>
     </thead>
     <tbody>
       <tr>
         <td style="text-align: right">42</td>
       </tr>
     </tbody>
   </table>
   ```

2. **RTL detection:**
   - Check if caption or headers contain Arabic
   - Auto-add `dir="rtl"` or `dir="ltr"` to `<table>` tag
   - Default right alignment for RTL tables

3. **Cell spanning:**
   - `row_span` → `rowspan` attribute
   - `col_span` → `colspan` attribute

4. **Cell styling:**
   - Alignment (horizontal/vertical)
   - Colors (text, background, borders)
   - Width percentages

5. **Simplified rendering:**
   - Complex styling removed in favor of CSS defaults
   - Only essential attributes preserved
   - Let browser handle table layout

### 2.3 Image

Visual elements (charts, diagrams, figures):

```python
{
  "image_type": "chart" | "graph" | "diagram" | "figure" | "photo",
  "description": "Bar chart showing growth trends",
  "caption": "Figure 3: Annual Revenue Growth",
  
  // Flow control
  "reading_order": 8,
  "column_number": 1,
  "alignment": "center",
  
  // Dimensions
  "width_pixels": 800,
  "height_pixels": 600,
  
  // Runtime-populated
  "image_data": "data:image/png;base64,iVBORw0KG..."
}
```

**What we handle:**

1. **Image rendering:**
   ```html
   <figure class="image-block">
     <img src="data:image/png;base64,..." 
          alt="Bar chart showing growth trends"
          style="max-width: 90%; height: auto;">
     <figcaption>Figure 3: Annual Revenue Growth</figcaption>
   </figure>
   ```

2. **Image extraction:**
   - PyMuPDF extracts images from PDF pages
   - Base64-encode and embed in `image_data`
   - Fallback to placeholder if extraction fails

3. **Alignment:**
   - `alignment: "center"` → Centered figure
   - `alignment: "left"` → Float left
   - Responsive sizing with max-width

---

## Part 3: HTML Rendering Process

### 3.1 HTMLRenderer.render() - Main Entry Point

```python
def render(doc: DocumentStructure, include_styles: bool = True) -> str:
    # 1. Detect document direction
    is_rtl = detect_rtl(doc.metadata.language, doc.pages)
    
    # 2. Build HTML structure
    html = [
        '<!DOCTYPE html>',
        f'<html lang="{lang}" dir="{rtl_or_ltr}">',
        '<head>',
        '<meta charset="UTF-8">',
        '<title>' + doc.metadata.title + '</title>',
        get_mathjax_config(),    # MathJax for equations
        get_styles(is_rtl),       # CSS
        '</head>',
        '<body>',
        '<div class="document-container">'
    ]
    
    # 3. Render each page
    for page in doc.pages:
        html.append(render_page(page, is_rtl))
    
    html.append('</div></body></html>')
    return '\n'.join(html)
```

### 3.2 Direction Detection Algorithm

```python
def detect_rtl(language, pages):
    # Priority 1: Explicit language metadata
    if language in ['ar', 'he', 'fa', 'ur']:
        return True
    
    # Priority 2: Text content analysis
    sample_text = ""
    for page in pages[:5]:  # Sample first 5 pages
        for block in page.text_blocks[:10]:
            sample_text += block.content
    
    # Count Arabic/Hebrew characters
    rtl_chars = count_unicode_range(sample_text, 
                                    ranges=[0x0600-0x06FF,  # Arabic
                                           0x0590-0x05FF])  # Hebrew
    ltr_chars = count_unicode_range(sample_text,
                                    ranges=[0x0041-0x007A])  # A-Z
    
    return rtl_chars / (rtl_chars + ltr_chars) > 0.5
```

### 3.3 Page Rendering

```python
def _render_page(page: PageContent, is_rtl: bool) -> str:
    # 1. Detect if entire page is English (override RTL)
    page_text = " ".join(block.content for block in page.text_blocks)
    is_english_page = detect_english(page_text)
    page_dir = "ltr" if is_english_page else page.page_direction
    
    # 2. Combine all elements (text_blocks, tables, images)
    elements = []
    elements.extend(page.text_blocks)
    elements.extend(page.tables)
    elements.extend(page.images)
    
    # 3. Sort by reading order and column
    if page.has_multi_column:
        if page_dir == "rtl":
            # RTL: Right column first (higher column number)
            elements.sort(key=lambda e: (-e.column_number, e.reading_order))
        else:
            # LTR: Left column first
            elements.sort(key=lambda e: (e.column_number, e.reading_order))
    else:
        elements.sort(key=lambda e: e.reading_order)
    
    # 4. Render each element
    html = [f'<div class="page" dir="{page_dir}">']
    
    # Header
    html.append(render_page_header(page))
    
    # Content
    for element in elements:
        if isinstance(element, TextBlock):
            html.append(render_text_block(element))
        elif isinstance(element, Table):
            html.append(render_table(element))
        elif isinstance(element, Image):
            html.append(render_image(element))
    
    # Footer
    html.append(render_page_footer(page))
    html.append('</div>')
    
    return '\n'.join(html)
```

### 3.4 Multi-Column Handling

For pages with `has_multi_column: true`:

```html
<div class="page">
  <div class="page-content" style="column-count: 2; column-gap: 20pt;">
    <!-- Elements sorted by column_number -->
    <div>Column 1 content...</div>
    <div>Column 2 content...</div>
  </div>
</div>
```

CSS automatically flows content into columns. We just need to:
1. Sort elements by `column_number`
2. Apply `column-count` style
3. Add `column-break-after` for explicit breaks

---

## Part 4: CSS Styling System

### 4.1 Global Styles

```css
body {
  font-family: 'Amiri', 'Noto Naskh Arabic', sans-serif;  /* RTL font stack */
  line-height: 1.8;
  max-width: 900px;
  margin: 0 auto;
}

.document-container {
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.page {
  padding: 60px 50px;
  min-height: 900px;
  border-bottom: 2px dashed #e0e0e0;
}
```

### 4.2 RTL-Specific Styles

```css
[dir="rtl"] {
  text-align: right;
}

[dir="rtl"] blockquote {
  border-right: 4px solid #007acc;  /* Border on right for RTL */
  border-left: none;
  padding-right: 1rem;
}

[dir="rtl"] ul, [dir="rtl"] ol {
  padding-right: 2rem;  /* Indent on right for RTL */
  padding-left: 0;
}

[dir="rtl"] table th, [dir="rtl"] table td {
  text-align: right;  /* Right-align table cells in RTL */
}
```

### 4.3 Typography Hierarchy

```css
h1 { font-size: 2rem; margin: 1.5rem 0 1rem; font-weight: 700; }
h2 { font-size: 1.5rem; margin: 1.25rem 0 0.75rem; }
h3 { font-size: 1.25rem; margin: 1rem 0 0.5rem; }

p {
  margin: 0.75rem 0;
  text-align: justify;
  line-height: 1.8;
}

.bold { font-weight: bold; }
.italic { font-style: italic; }
.centered { text-align: center !important; }
```

### 4.4 Table Styles

```css
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
}

th, td {
  border: 1px solid #e0e0e0;
  padding: 8px 12px;
}

th {
  background: #f5f5f5;
  font-weight: 600;
}

.table-caption {
  font-style: italic;
  color: #666;
  text-align: center;
  margin: 0.5rem 0;
}
```

### 4.5 MathJax Integration

```html
<script>
window.MathJax = {
  tex: {
    inlineMath: [['\\(', '\\)'], ['$', '$']],
    displayMath: [['\\[', '\\]'], ['$$', '$$']],
    processEscapes: true
  }
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
```

Equations are wrapped in LaTeX delimiters:
- **Display**: `\\[x^2 + y^2 = z^2\\]` → Centered, block-level
- **Inline**: `\\(E = mc^2\\)` → In-text

---

## Part 5: Special Handling

### 5.1 Header/Footer Deduplication

Problem: Headers/footers often appear in both dedicated fields AND text_blocks.

Solution:
```python
def deduplicate_header_footer(page):
    # Remove text_blocks that match header/footer text
    if page.header:
        page.text_blocks = [b for b in page.text_blocks 
                           if normalize(b.content) != normalize(page.header)]
    
    if page.footer:
        page.text_blocks = [b for b in page.text_blocks 
                           if normalize(b.content) != normalize(page.footer)]
    
    return page
```

### 5.2 List Grouping

Problem: LLM returns individual `list_item` blocks, not grouped lists.

Solution:
```python
def render_page(page):
    i = 0
    while i < len(elements):
        if element.block_type == 'list_item':
            # Collect consecutive list items
            list_items = [element]
            while next_element.block_type == 'list_item':
                list_items.append(next_element)
            
            # Render as single <ul>
            html.append(render_list(list_items))
        else:
            html.append(render_text_block(element))
```

### 5.3 Image Deduplication

Problem: OCR may extract same image multiple times.

Solution:
```python
def deduplicate_images(page):
    seen_descriptions = set()
    unique_images = []
    
    for img in page.images:
        normalized_desc = img.description.lower().strip()
        if normalized_desc not in seen_descriptions:
            unique_images.append(img)
            seen_descriptions.add(normalized_desc)
    
    return unique_images
```

### 5.4 Equation Arabic Caption Extraction

Problem: Arabic captions mixed with LaTeX equations.

Solution:
```python
def clean_equation_content(content):
    # Extract LaTeX math symbols
    math_pattern = r'[\\{}()=+\-*/^_0-9a-zA-Z]'
    math_content = re.findall(math_pattern, content)
    
    # Extract Arabic text
    arabic_pattern = r'[\u0600-\u06FF]+'
    arabic_text = ' '.join(re.findall(arabic_pattern, content))
    
    return ''.join(math_content), arabic_text
```

Render separately:
```html
<div class="equation">\\[x^2 + y^2 = z^2\\]</div>
<p class="equation-caption" dir="rtl">المعادلة الأولى</p>
```

### 5.5 Color Validation (Security)

Problem: Prevent CSS injection through color values.

Solution:
```python
def validate_color(color):
    # Only allow hex colors (#RGB or #RRGGBB)
    if re.match(r'^#[0-9A-Fa-f]{3}$', color):
        return color
    if re.match(r'^#[0-9A-Fa-f]{6}$', color):
        return color
    
    # Or named colors
    if color.lower() in ['black', 'white', 'red', 'blue', ...]:
        return color
    
    return None  # Invalid color
```

### 5.6 URL Validation (Security)

Problem: Prevent XSS through malicious URLs.

Solution:
```python
def validate_url(url):
    # Only allow http://, https://, mailto:, and anchors
    if re.match(r'^(https?://|mailto:|#)', url, re.IGNORECASE):
        # Reject javascript: and data: schemes
        if re.match(r'^(javascript|data):', url, re.IGNORECASE):
            return None
        return url
    return None
```

---

## Part 6: Complete Example

### Input JSON (simplified):

```json
{
  "metadata": {
    "title": "بحث أكاديمي",
    "language": "ar",
    "total_pages": 1
  },
  "pages": [
    {
      "page_number": 1,
      "page_direction": "rtl",
      "text_blocks": [
        {
          "block_type": "heading",
          "level": 1,
          "content": "المقدمة",
          "font_size": 18,
          "text_align": "center"
        },
        {
          "block_type": "paragraph",
          "content": "هذا نص تجريبي للبحث الأكاديمي.",
          "text_align": "justify"
        }
      ],
      "tables": [
        {
          "caption": "جدول النتائج",
          "headers": [
            {"content": "العدد", "text_align": "center"}
          ],
          "rows": [
            [{"content": "42", "text_align": "right"}]
          ]
        }
      ]
    }
  ]
}
```

### Generated HTML:

```html
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>بحث أكاديمي</title>
  <!-- MathJax config -->
  <script>...</script>
  <!-- CSS styles -->
  <style>
    body { font-family: 'Amiri', sans-serif; }
    [dir="rtl"] { text-align: right; }
    /* ... more styles ... */
  </style>
</head>
<body>
  <div class="document-container">
    <div class="page" id="page-1" dir="rtl">
      <div class="page-content">
        
        <!-- Heading -->
        <h1 class="rtl" dir="rtl" style="font-size: 18pt; text-align: center;">المقدمة</h1>
        
        <!-- Paragraph -->
        <p class="rtl" dir="rtl" style="text-align: justify;">هذا نص تجريبي للبحث الأكاديمي.</p>
        
        <!-- Table -->
        <p class="table-caption" dir="rtl">جدول النتائج</p>
        <table dir="rtl">
          <thead>
            <tr>
              <th>العدد</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>42</td>
            </tr>
          </tbody>
        </table>
        
      </div>
    </div>
  </div>
</body>
</html>
```

---

## Summary

### What We Handle Comprehensively:

1. **Document Structure**
   - Multi-page documents with metadata
   - Page dimensions and layout

2. **Bidirectional Text**
   - Auto-detect RTL/LTR at document, page, and element level
   - Mixed-direction content (Arabic + English)
   - Proper text flow and alignment

3. **Rich Typography**
   - Font families, sizes, weights
   - Character-level formatting (spans)
   - Colors, spacing, indentation

4. **Semantic Elements**
   - Headings (H1-H6)
   - Paragraphs, quotes, code blocks
   - Lists (nested, ordered/unordered)
   - Hyperlinks with validation
   - Equations with MathJax

5. **Tables**
   - Full styling (borders, colors, alignment)
   - Cell spanning (rowspan, colspan)
   - RTL direction detection
   - Caption rendering

6. **Images**
   - Embedded base64 data URIs
   - Captions and descriptions
   - Responsive sizing
   - Alignment control

7. **Multi-Column Layout**
   - CSS column support
   - Element sorting by column and reading order
   - RTL column reversal

8. **Security**
   - Color validation (prevent CSS injection)
   - URL validation (prevent XSS)
   - HTML escaping

9. **Quality Features**
   - Header/footer deduplication
   - List grouping
   - Image deduplication
   - Equation Arabic caption extraction
   - Footnote collection

This system provides **pixel-perfect document fidelity** while maintaining semantic HTML structure and accessibility.
