#!/usr/bin/env python3
"""
HTML renderer using bounding box coordinates from canonical JSON.
Focuses on accurate text positioning using absolute coordinates.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any


def render_html_from_canonical(canonical_path: str, output_path: str = None) -> str:
    """
    Render HTML from canonical JSON using bounding box positioning.
    
    Args:
        canonical_path: Path to the canonical JSON file
        output_path: Optional output path for HTML file
        
    Returns:
        HTML string
    """
    # Load canonical JSON
    with open(canonical_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Extract document info
    doc_id = data.get('document_id', 'unknown')
    filename = data['source']['filename']
    pages = data.get('pages', [])
    
    # Start building HTML
    html_parts = []
    html_parts.append('<!DOCTYPE html>')
    html_parts.append('<html lang="ar" dir="rtl">')
    html_parts.append('<head>')
    html_parts.append('  <meta charset="UTF-8">')
    html_parts.append('  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_parts.append(f'  <title>{filename} — BBox Renderer</title>')
    html_parts.append('  <link rel="preconnect" href="https://fonts.googleapis.com">')
    html_parts.append('  <link href="https://fonts.googleapis.com/css2?family=Amiri&family=Noto+Naskh+Arabic&family=Noto+Serif&display=swap" rel="stylesheet">')
    html_parts.append('  <style>')
    html_parts.append(get_css())
    html_parts.append('  </style>')
    html_parts.append('</head>')
    html_parts.append('<body>')
    html_parts.append(f'  <h1 style="color: white; text-align: center; font-family: Arial;">Document: {filename}</h1>')
    
    # Render each page
    for page in pages:
        page_html = render_page(page)
        html_parts.append(page_html)
    
    html_parts.append('</body>')
    html_parts.append('</html>')
    
    html_content = '\n'.join(html_parts)
    
    # Write to file if output path provided
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML written to: {output_path}")
    
    return html_content


def get_css() -> str:
    """Return CSS styles for the HTML renderer."""
    return '''
    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    body {
      background: #525659;
      padding: 20px;
      font-family: 'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', serif;
    }
    
    .page-container {
      position: relative;
      background: white;
      margin: 20px auto;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      overflow: hidden;
      page-break-after: always;
    }
    
    .text-block {
      position: absolute;
      /* Optional: uncomment to see block boundaries */
      /* border: 1px dashed rgba(0,150,255,0.2); */
    }
    
    .text-line {
      position: absolute;
      white-space: pre;
      cursor: text;
      line-height: 1;
      /* Optional: uncomment to see line boundaries */
      /* outline: 1px dotted rgba(255,0,0,0.2); */
    }
    
    .text-line::selection {
      background: rgba(0, 120, 215, 0.35);
    }
    
    .text-word {
      position: absolute;
      white-space: nowrap;
      cursor: text;
      line-height: 1;
      /* Optional: uncomment to see word boundaries */
      /* border: 1px solid rgba(0,255,0,0.1); */
    }
    
    .text-word::selection {
      background: rgba(0, 120, 215, 0.35);
    }
    
    /* RTL and LTR support */
    .rtl { direction: rtl; unicode-bidi: plaintext; }
    .ltr { direction: ltr; unicode-bidi: plaintext; }
    
    /* Block type styling */
    .block-title { font-weight: bold; font-size: 1.2em; }
    .block-section_heading { font-weight: bold; font-size: 1.1em; }
    .block-footnote { font-size: 0.9em; font-style: italic; opacity: 0.8; }
    .block-page_number { font-size: 0.85em; opacity: 0.6; }
    
    /* Debug mode - uncomment to see all bounding boxes */
    /*
    .text-block { background: rgba(255,0,0,0.05); }
    .text-line { background: rgba(0,255,0,0.05); }
    .text-word { background: rgba(0,0,255,0.05); }
    */
    '''


def render_page(page: Dict) -> str:
    """Render a single page with absolute positioning."""
    page_index = page['page_index']
    image_info = page.get('image', {})
    width = image_info.get('width', 1700)
    height = image_info.get('height', 2200)
    
    blocks = page.get('blocks', [])
    
    # Start page container
    html = f'\n  <!-- Page {page_index + 1} -->\n'
    html += f'  <div class="page-container" style="width: {width}px; height: {height}px;" data-page="{page_index}">\n'
    
    # Render each block
    for block in blocks:
        if block['block_type'] == 'text':
            block_html = render_text_block(block, width, height)
            html += block_html
        # Skip tables and figures for now as requested
    
    html += '  </div>\n'
    return html


def render_text_block(block: Dict, page_width: float, page_height: float) -> str:
    """Render a text block using line-level positioning to avoid overlaps."""
    block_id = block.get('block_id', '')
    block_type = block.get('block_type', 'text')
    bbox = block.get('bbox', {})
    direction = block.get('direction', 'rtl')
    lines = block.get('lines', [])
    
    if not lines:
        return ''
    
    html = f'    <!-- Block: {block_id} -->\n'
    
    for line in lines:
        line_id = line.get('line_id', '')
        line_text = line.get('text', '')
        line_bbox = line.get('bbox', {})
        tokens = line.get('tokens', [])
        
        # Render entire line to avoid word overlaps
        html += render_line_with_tokens(line, direction)
    
    return html


def render_line_with_tokens(line: Dict, direction: str) -> str:
    """Render a line as a container with properly spaced tokens inside."""
    line_text = line.get('text', '')
    line_bbox = line.get('bbox', {})
    tokens = line.get('tokens', [])
    
    if not line_bbox or not line_text.strip():
        return ''
    
    x0, y0 = line_bbox.get('x0', 0), line_bbox.get('y0', 0)
    x1, y1 = line_bbox.get('x1', 0), line_bbox.get('y1', 0)
    
    width = x1 - x0
    height = y1 - y0
    
    # Calculate font size from line height
    font_size = height * 0.75
    
    dir_class = 'rtl' if direction == 'rtl' else 'ltr'
    
    # Create line container
    html = f'    <div class="text-line {dir_class}" style="'
    html += f'left: {x0}px; '
    html += f'top: {y0}px; '
    html += f'width: {width}px; '
    html += f'height: {height}px; '
    html += f'font-size: {font_size}px; '
    html += f'display: flex; '
    html += f'align-items: center; '
    html += f'">'
    
    if tokens and len(tokens) > 0:
        # Render tokens with relative positioning within the line
        for i, token in enumerate(tokens):
            token_text = token.get('text', '')
            token_bbox = token.get('bbox', {})
            
            if not token_text.strip() or not token_bbox:
                continue
            
            tx0 = token_bbox.get('x0', 0)
            tx1 = token_bbox.get('x1', 0)
            ty0 = token_bbox.get('y0', 0)
            ty1 = token_bbox.get('y1', 0)
            
            # Position relative to line start
            token_left = tx0 - x0
            token_width = tx1 - tx0
            
            # Add space between words (in RTL, this is handled by flexbox)
            space_after = ''
            if i < len(tokens) - 1:
                next_token_bbox = tokens[i + 1].get('bbox', {})
                if next_token_bbox:
                    gap = abs(next_token_bbox.get('x0', tx1) - tx1)
                    if gap > 5:  # Minimum gap threshold
                        space_after = '&nbsp;'
            
            html += f'<span style="position: absolute; left: {token_left}px;">'
            html += escape_html(token_text) + space_after + '</span>'
    else:
        # No tokens, render full line text
        html += escape_html(line_text)
    
    html += '</div>\n'
    
    return html


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


def main():
    """Main entry point for CLI usage."""
    if len(sys.argv) < 2:
        print("Usage: python bbox_html_renderer.py <canonical.json> [output.html]")
        print("\nExample:")
        print("  python bbox_html_renderer.py path/to/doc_canonical.json")
        print("  python bbox_html_renderer.py path/to/doc_canonical.json output.html")
        sys.exit(1)
    
    canonical_path = sys.argv[1]
    
    # Determine output path
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        # Auto-generate output filename
        canonical_file = Path(canonical_path)
        output_path = canonical_file.parent / f"{canonical_file.stem.replace('_canonical', '')}_bbox.html"
    
    print(f"Reading: {canonical_path}")
    print(f"Output:  {output_path}")
    
    render_html_from_canonical(canonical_path, str(output_path))
    print("✓ Done!")


if __name__ == '__main__':
    main()
