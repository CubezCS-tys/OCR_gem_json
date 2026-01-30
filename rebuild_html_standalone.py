#!/usr/bin/env python3
"""
Standalone script to regenerate HTML from edited JSON files.
This version does NOT depend on pdf_to_html.py or google-genai.

Usage:
    python rebuild_html_standalone.py <json_path> <output_html_path>
"""

import sys
import json
from pathlib import Path
from typing import Any


def render_block(block: dict) -> str:
    """Render a single block to HTML."""
    block_type = block.get("type", "paragraph")
    content = block.get("content", "")
    level = block.get("level", 1)
    text_direction = block.get("text_direction", "auto")
    
    # Escape HTML special characters
    content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    dir_attr = f' dir="{text_direction}"' if text_direction and text_direction != "auto" else ""
    
    if block_type == "heading":
        tag = f"h{level}" if 1 <= level <= 6 else "h2"
        return f"<{tag}{dir_attr}>{content}</{tag}>\n"
    elif block_type == "paragraph":
        return f"<p{dir_attr}>{content}</p>\n"
    elif block_type == "list_item":
        return f"<li{dir_attr}>{content}</li>\n"
    elif block_type == "equation":
        return f'<div class="equation"{dir_attr}>{content}</div>\n'
    elif block_type == "quote":
        return f'<blockquote{dir_attr}>{content}</blockquote>\n'
    elif block_type == "code":
        return f'<pre><code{dir_attr}>{content}</code></pre>\n'
    elif block_type == "caption":
        return f'<p class="caption"{dir_attr}>{content}</p>\n'
    elif block_type == "footnote":
        return f'<p class="footnote"{dir_attr}>{content}</p>\n'
    else:
        return f"<p{dir_attr}>{content}</p>\n"


def render_table(table: dict) -> str:
    """Render a table to HTML."""
    html = '<table>\n'
    
    # Headers
    headers = table.get("headers", [])
    if headers:
        html += '<thead><tr>\n'
        for header in headers:
            content = header.get("content", header) if isinstance(header, dict) else str(header)
            html += f'<th>{content}</th>\n'
        html += '</tr></thead>\n'
    
    # Rows
    rows = table.get("rows", [])
    if rows:
        html += '<tbody>\n'
        for row in rows:
            html += '<tr>\n'
            for cell in row:
                content = cell.get("content", cell) if isinstance(cell, dict) else str(cell)
                html += f'<td>{content}</td>\n'
            html += '</tr>\n'
        html += '</tbody>\n'
    
    html += '</table>\n'
    return html


def render_page(page: dict, page_number: int) -> str:
    """Render a single page to HTML."""
    direction = "rtl" if page.get("is_rtl", False) else "ltr"
    header = page.get("header", "")
    footer = page.get("footer", "")
    
    html = f'<div class="page" id="page-{page_number}" dir="{direction}">\n'
    
    if header:
        html += f'<div class="page-header">{header}</div>\n'
    
    html += '<div class="page-content">\n'
    
    # Render blocks
    blocks = page.get("blocks", page.get("text_blocks", []))
    for block in blocks:
        html += render_block(block)
    
    # Render tables
    tables = page.get("tables", [])
    for table in tables:
        html += render_table(table)
    
    html += '</div>\n'
    
    if footer:
        html += f'<div class="page-footer">{footer}</div>\n'
    
    html += '</div>\n'
    return html


def get_css() -> str:
    """Return the CSS styles for the document."""
    return '''
    @import url('https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400;1,700&family=Noto+Naskh+Arabic:wght@400;500;600;700&display=swap');
    
    :root {
        --page-bg: #ffffff;
        --text-color: #1a1a1a;
        --border-color: #e0e0e0;
        --header-bg: #f5f5f5;
        --code-bg: #f8f8f8;
    }
    
    * { box-sizing: border-box; }
    
    body {
        font-family: 'Amiri', 'Scheherazade New', 'Noto Naskh Arabic', 'Traditional Arabic', 'Arabic Typesetting', 'Segoe UI', Tahoma, sans-serif;
        line-height: 1.8;
        color: var(--text-color);
        max-width: 900px;
        margin: 0 auto;
        padding: 20px;
        background: #fafafa;
    }
    
    .document-container {
        background: var(--page-bg);
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border-radius: 4px;
    }
    
    .page {
        position: relative;
        padding: 60px 50px;
        border-bottom: 2px dashed var(--border-color);
        page-break-after: always;
        min-height: 900px;
        overflow: visible;
    }
    
    .page:last-child { border-bottom: none; }
    
    .page-header {
        font-size: 0.75rem;
        color: #888;
        text-align: left;
        margin-bottom: 20px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border-color);
    }
    
    .page-footer {
        font-size: 0.75rem;
        color: #888;
        text-align: center;
        margin-top: 20px;
        padding-top: 10px;
        border-top: 1px solid var(--border-color);
    }
    
    [dir="rtl"] { text-align: right; }
    [dir="rtl"] .page-header { text-align: left; }
    
    h1 { font-size: 2rem; margin: 1.5rem 0 1rem; font-weight: 700; }
    h2 { font-size: 1.5rem; margin: 1.25rem 0 0.75rem; font-weight: 600; }
    h3 { font-size: 1.25rem; margin: 1rem 0 0.5rem; font-weight: 600; }
    h4, h5, h6 { font-size: 1.1rem; margin: 0.75rem 0 0.5rem; font-weight: 600; }
    
    p { margin: 0.75rem 0; text-align: justify; line-height: 1.8; }
    
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    
    th, td {
        border: 1px solid var(--border-color);
        padding: 8px 12px;
        text-align: left;
    }
    
    th { background: var(--header-bg); font-weight: 600; }
    
    .equation { margin: 1rem 0; text-align: center; direction: ltr; }
    
    blockquote {
        border-left: 4px solid #007acc;
        margin: 1rem 0;
        padding: 0.5rem 1rem;
        background: #f8f9fa;
        font-style: italic;
    }
    
    pre, code {
        font-family: 'Consolas', 'Monaco', monospace;
        background: var(--code-bg);
        border-radius: 3px;
        direction: ltr;
        text-align: left;
    }
    
    pre { padding: 1rem; overflow-x: auto; margin: 1rem 0; }
    code { padding: 0.2rem 0.4rem; }
    
    .caption { font-style: italic; color: #666; margin: 0.5rem 0; text-align: center; }
    .footnote { font-size: 0.85rem; color: #666; margin: 0.5rem 0; }
'''


def get_mathjax_script() -> str:
    """Return the MathJax configuration and loading script."""
    return '''
<script>
window.MathJax = {
  tex: {
    inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
    displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
    processEscapes: true,
    processEnvironments: true
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
  }
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
'''


def render_document(data: dict) -> str:
    """Render the full document to HTML."""
    metadata = data.get("metadata", {})
    title = metadata.get("title", "Document")
    language = metadata.get("language", "en")
    
    # Determine document direction
    is_rtl = language.lower() in ["arabic", "hebrew", "persian", "urdu"]
    doc_dir = "rtl" if is_rtl else "ltr"
    
    html = f'''<!DOCTYPE html>
<html lang="{language}" dir="{doc_dir}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{get_mathjax_script()}
<style>
{get_css()}
</style>
</head>
<body>
<div class="document-container">
'''
    
    # Render each page
    pages = data.get("pages", [])
    for i, page in enumerate(pages, 1):
        html += render_page(page, i)
    
    html += '''
</div>
</body>
</html>
'''
    return html


def rebuild_html(json_path: str, html_path: str) -> None:
    """Rebuild HTML from JSON document structure."""
    try:
        # Load JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Render to HTML
        html_content = render_document(data)
        
        # Write HTML
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ Successfully regenerated HTML: {html_path}")
        
    except Exception as e:
        print(f"❌ Error regenerating HTML: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python rebuild_html_standalone.py <json_path> <output_html_path>")
        sys.exit(1)
    
    json_path = sys.argv[1]
    html_path = sys.argv[2]
    
    rebuild_html(json_path, html_path)
