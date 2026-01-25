#!/usr/bin/env python3
"""
Simple script to regenerate HTML from edited JSON files.
Used by the frontend API to rebuild HTML after user edits.

Usage:
    python rebuild_html.py <json_path> <output_html_path>
"""

import sys
import json
import pathlib
from pdf_to_html import DocumentStructure, HTMLRenderer

def rebuild_html(json_path: str, html_path: str) -> None:
    """Rebuild HTML from JSON document structure."""
    try:
        # Load JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate and parse with Pydantic
        doc = DocumentStructure.model_validate(data)
        
        # Render to HTML
        html_content = HTMLRenderer.render(doc)
        
        # Write HTML
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ Successfully regenerated HTML: {html_path}")
        
    except Exception as e:
        print(f"❌ Error regenerating HTML: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python rebuild_html.py <json_path> <output_html_path>")
        sys.exit(1)
    
    json_path = sys.argv[1]
    html_path = sys.argv[2]
    
    rebuild_html(json_path, html_path)
