#!/usr/bin/env python3
"""
Parse Mistral batch OCR results from JSONL file.
"""

import json
import sys
from pathlib import Path

def parse_batch_results(jsonl_file: str, output_dir: str):
    """Parse batch results JSONL file and save individual JSON/markdown files."""
    
    jsonl_path = Path(jsonl_file)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    if not jsonl_path.exists():
        print(f"Error: File not found: {jsonl_file}")
        return
    
    print(f"Parsing batch results from: {jsonl_file}")
    print(f"Output directory: {output_dir}")
    print("=" * 60)
    
    processed = 0
    errors = 0
    
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                result = json.loads(line)
                custom_id = result.get('custom_id', f'unknown_{line_num}')
                
                # Extract response body
                response = result.get('response', {})
                
                # Check for errors
                if result.get('error') is not None:
                    print(f"❌ {custom_id}: Error - {result['error']}")
                    errors += 1
                    continue
                if response.get('status_code') != 200:
                    print(f"❌ {custom_id}: HTTP {response.get('status_code')}")
                    errors += 1
                    continue
                
                body = response.get('body', {})
                
                # Save JSON file
                json_file = output_path / f"{custom_id}.json"
                with open(json_file, 'w', encoding='utf-8') as jf:
                    json.dump(body, jf, indent=2, ensure_ascii=False)
                
                # Extract and save markdown
                markdown_content = []
                for page in body.get('pages', []):
                    page_md = page.get('markdown', '')
                    if page_md:
                        markdown_content.append(f"# Page {page.get('index', '?') + 1}\n\n{page_md}\n")
                
                if markdown_content:
                    md_file = output_path / f"{custom_id}.md"
                    with open(md_file, 'w', encoding='utf-8') as mf:
                        mf.write('\n---\n\n'.join(markdown_content))
                
                print(f"✅ {custom_id}: {len(body.get('pages', []))} pages")
                processed += 1
                
            except json.JSONDecodeError as e:
                print(f"❌ Line {line_num}: JSON parse error - {e}")
                errors += 1
            except Exception as e:
                print(f"❌ Line {line_num}: {e}")
                errors += 1
    
    print("=" * 60)
    print(f"✅ Processed: {processed} PDFs")
    print(f"❌ Errors: {errors}")
    print(f"📁 Output: {output_dir}/")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m llm_pipelines.parse_batch_results <jsonl_file> [output_dir]")
        print("Example: python3 -m llm_pipelines.parse_batch_results batch_markdown/batch_*.jsonl batch_markdown/")
        sys.exit(1)
    
    jsonl_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "batch_parsed"
    
    parse_batch_results(jsonl_file, output_dir)
