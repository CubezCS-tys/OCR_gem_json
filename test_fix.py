#!/usr/bin/env python3
"""
Quick test to verify the double data-URI prefix is fixed
"""

import json
from pathlib import Path
from pdf_to_html import HTMLRenderer
from mistral_ocr_pipeline import DocumentStructure

# Load the existing mistral output JSON
json_path = Path("/home/k22015806/Desktop/OCR_gem_json/mistral_output/0005-052-002-003.json")

print(f"Loading: {json_path}")
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Parse into DocumentStructure
doc = DocumentStructure(**data)

print(f"\nDocument loaded: {len(doc.pages)} pages")

# Check first few images
image_count = 0
for page in doc.pages[:3]:  # Check first 3 pages
    for img in page.images:
        if img.image_data:
            image_count += 1
            prefix = img.image_data[:80]
            print(f"\nPage {page.page_number}, Image {image_count}:")
            print(f"  Prefix: {prefix}...")
            
            # Check for the bug
            if "base64,data:" in img.image_data:
                print(f"  ❌ DOUBLE PREFIX BUG DETECTED!")
            elif img.image_data.startswith("data:image/"):
                print(f"  ✓ Valid data URI")
            else:
                print(f"  ? Unknown format")

# Now render to HTML and check output
print("\n" + "="*60)
print("Rendering to HTML...")
html_output = HTMLRenderer.render(doc)

# Check for double prefix in HTML
if 'src="data:image/png;base64,data:image/' in html_output:
    print("❌ FAIL: Double prefix found in HTML output!")
elif 'src="data:image/' in html_output:
    print("✓ PASS: HTML contains valid data URIs")
    # Count images
    img_count = html_output.count('<img src="data:image/')
    print(f"  Found {img_count} embedded images")
else:
    print("? No embedded images found in HTML")

print("\nTest complete!")
