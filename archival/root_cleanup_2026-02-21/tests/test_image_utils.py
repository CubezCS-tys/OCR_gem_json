#!/usr/bin/env python3
"""
Test script for normalise_data_uri function
"""

from image_utils import normalise_data_uri

# Test cases
test_cases = [
    # Double prefix (the bug)
    "data:image/png;base64,data:image/jpeg;base64,/9j/4AAQSkZJRg...",
    
    # Already correct data URI
    "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
    
    # Raw base64 JPEG
    "/9j/4AAQSkZJRg...",
    
    # Raw base64 PNG
    "iVBORw0KGgoAAAANSUhEUg...",
    
    # Missing "data:" prefix but has MIME
    "image/jpeg;base64,/9j/4AAQSkZJRg...",
    
    # Empty string
    "",
    
    # With whitespace
    " /9j/4AAQSkZJRg... ",
]

print("Testing normalise_data_uri function:\n")

for i, test in enumerate(test_cases, 1):
    print(f"Test {i}:")
    print(f"  Input:  {test[:80]}...")
    result = normalise_data_uri(test)
    print(f"  Output: {result[:80]}...")
    
    # Verify no double prefix
    if "base64,data:" in result:
        print(f"  ❌ FAIL: Still has double prefix!")
    elif result and result.startswith("data:image/"):
        print(f"  ✓ PASS: Valid data URI")
    elif not test:
        print(f"  ✓ PASS: Empty input handled")
    else:
        print(f"  ? Check manually")
    print()
