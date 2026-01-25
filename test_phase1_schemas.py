#!/usr/bin/env python3
"""
Test script for Phase 1 schema definitions only.
Does not require Google Gemini or PyMuPDF dependencies.
"""

import json
import sys
from pydantic import ValidationError

# Import only the schema parts by reading and executing the relevant sections
print("Testing Phase 1 Schema Enhancements...")
print("=" * 60)

# Test 1: Verify schema definitions exist
print("\nTEST 1: Verifying schema class definitions...")
try:
    exec_globals = {}
    with open('pdf_to_html.py', 'r') as f:
        content = f.read()

    # Extract only the schema section (before the HTMLRenderer class)
    schema_start = content.find('# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUT')
    schema_end = content.find('# HTML RENDERER')

    if schema_start == -1 or schema_end == -1:
        print("✗ Could not find schema section")
        sys.exit(1)

    schema_code = content[schema_start:schema_end]

    # Add necessary imports for schemas
    imports = """
from pydantic import BaseModel, Field
from typing import Optional, Literal
"""

    full_code = imports + schema_code

    exec(full_code, exec_globals)

    # Verify key classes exist
    required_classes = [
        'InlineElement',
        'TableCell',
        'TableRow',
        'Table',
        'TextBlock',
        'Image',
        'PageContent',
        'DocumentMetadata',
        'DocumentStructure'
    ]

    for cls_name in required_classes:
        if cls_name not in exec_globals:
            print(f"✗ Missing class: {cls_name}")
            sys.exit(1)

    print("✓ All schema classes defined correctly")

    # Test 2: Create instances with new fields
    print("\nTEST 2: Creating instances with Phase 1 enhancements...")

    InlineElement = exec_globals['InlineElement']
    TableCell = exec_globals['TableCell']
    TableRow = exec_globals['TableRow']
    Table = exec_globals['Table']
    TextBlock = exec_globals['TextBlock']
    Image = exec_globals['Image']

    # Test InlineElement
    link_elem = InlineElement(
        type="link",
        content="Click here",
        url="https://example.com"
    )
    assert link_elem.type == "link"
    assert link_elem.url == "https://example.com"
    print("✓ InlineElement works")

    # Test TableCell with alignment
    cell = TableCell(
        content="Test",
        row_span=2,
        col_span=1,
        is_header=True,
        alignment="center"
    )
    assert cell.alignment == "center"
    assert cell.row_span == 2
    print("✓ TableCell with alignment works")

    # Test TableRow
    row = TableRow(
        cells=[cell],
        is_header_row=True
    )
    assert row.is_header_row == True
    assert len(row.cells) == 1
    print("✓ TableRow works")

    # Test Table with structured_rows
    table = Table(
        caption="Test Table",
        structured_rows=[row],
        headers=[],  # Old field (deprecated but present)
        rows=[]      # Old field (deprecated but present)
    )
    assert table.structured_rows is not None
    assert len(table.structured_rows) == 1
    print("✓ Table with structured_rows works")

    # Test TextBlock with inline_elements
    text = TextBlock(
        block_type="paragraph",
        content="Plain text",
        inline_elements=[link_elem],
        list_type="ordered",
        list_marker_style="decimal"
    )
    assert text.inline_elements is not None
    assert text.list_type == "ordered"
    print("✓ TextBlock with inline_elements and list enhancements works")

    # Test Image with alt_text and long_description
    img = Image(
        image_type="chart",
        description="",  # Deprecated
        alt_text="Short alt text",
        long_description="Detailed description of the chart",
        bbox_top=10.0,
        bbox_left=5.0,
        bbox_width=80.0,
        bbox_height=40.0
    )
    assert img.alt_text == "Short alt text"
    assert img.long_description is not None
    print("✓ Image with alt_text and long_description works")

    # Test 3: JSON Serialization
    print("\nTEST 3: JSON serialization of enhanced schemas...")

    table_dict = table.model_dump()
    table_json = json.dumps(table_dict, indent=2)
    table_restored = Table.model_validate_json(table_json)
    assert table_restored.structured_rows is not None
    print("✓ Table serialization works")

    text_dict = text.model_dump()
    text_json = json.dumps(text_dict, indent=2)
    text_restored = TextBlock.model_validate_json(text_json)
    assert text_restored.inline_elements is not None
    print("✓ TextBlock serialization works")

    img_dict = img.model_dump()
    img_json = json.dumps(img_dict, indent=2)
    img_restored = Image.model_validate_json(img_json)
    assert img_restored.alt_text == "Short alt text"
    print("✓ Image serialization works")

    # Test 4: Backward Compatibility
    print("\nTEST 4: Backward compatibility with old format...")

    # Old-style table (no structured_rows)
    old_table = Table(
        caption="Old Table",
        headers=["Col1", "Col2"],
        rows=[["A", "B"], ["C", "D"]]
    )
    assert len(old_table.headers) == 2
    assert len(old_table.rows) == 2
    assert old_table.structured_rows is None
    print("✓ Old table format still works")

    # Old-style image (only description)
    old_img = Image(
        image_type="photo",
        description="Old style description",
        bbox_top=0.0,
        bbox_left=0.0,
        bbox_width=100.0,
        bbox_height=100.0
    )
    assert old_img.description == "Old style description"
    assert old_img.alt_text is None  # New field not required
    print("✓ Old image format still works")

    # Old-style text (no inline_elements)
    old_text = TextBlock(
        block_type="paragraph",
        content="Plain old text"
    )
    assert old_text.content == "Plain old text"
    assert old_text.inline_elements is None
    print("✓ Old text format still works")

    # Test 5: Optional fields
    print("\nTEST 5: Optional fields defaults...")

    minimal_table = Table()
    assert minimal_table.caption is None
    assert minimal_table.structured_rows is None
    assert len(minimal_table.headers) == 0
    assert len(minimal_table.rows) == 0
    print("✓ Table optional fields work")

    minimal_cell = TableCell(content="Test")
    assert minimal_cell.row_span == 1
    assert minimal_cell.col_span == 1
    assert minimal_cell.is_header == False
    assert minimal_cell.alignment is None
    print("✓ TableCell defaults work")

    print("\n" + "=" * 60)
    print("ALL SCHEMA TESTS PASSED ✓")
    print("=" * 60)
    print("\nPhase 1 schema enhancements verified:")
    print("✓ InlineElement - links and formatting")
    print("✓ TableCell - alignment support")
    print("✓ TableRow - proper row structure")
    print("✓ Table - structured_rows with backward compatibility")
    print("✓ TextBlock - inline_elements and enhanced list support")
    print("✓ Image - alt_text and long_description")
    print("✓ JSON serialization maintained")
    print("✓ Backward compatibility preserved")

except Exception as e:
    print(f"\n✗ TEST FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
