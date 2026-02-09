#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process batch OCR markdown files into structured JSON using Gemini/Mistral.

Takes the markdown output from Mistral batch OCR and transforms it into
your DocumentStructure schema using Gemini for reasoning.

Usage:
    # Process single file
    python3 batch_to_structured.py batch_markdown/0308-036-091-007.json
    
    # Process all batch results
    python3 batch_to_structured.py batch_markdown/*.json
    
    # Use Mistral Large instead of Gemini
    python3 batch_to_structured.py batch_markdown/*.json --provider mistral
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If dotenv not available, try loading .env manually
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

from google import genai
from google.genai import types
from mistralai import Mistral
from pydantic import ValidationError

# Reuse schemas and renderer from existing pipeline
from pdf_to_html import DocumentStructure, HTMLRenderer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Structuring prompt template
STRUCTURING_PROMPT = """You are an expert document structure analyst. Your task is to transform OCR markdown into a structured JSON format.

INPUT: Markdown text extracted from a document via OCR
OUTPUT: Valid JSON matching the DocumentStructure schema

# DocumentStructure Schema

{schema}

# Instructions

1. Extract metadata from the first pages (title, authors, date, language, type)
2. Identify all content blocks: text paragraphs, headings, lists, tables, images, code
3. Preserve the document structure and hierarchy
4. For tables: extract as structured data with headers and cells
5. For images: note their position and any captions
6. Maintain reading order and page associations
7. Identify hyperlinks with their URLs and display text

# Document Markdown

{markdown}

# Output

Provide ONLY valid JSON matching the DocumentStructure schema. No explanations, no markdown formatting.
"""


class BatchStructurer:
    """Transform batch OCR markdown into structured JSON."""
    
    def __init__(self, provider: str = "gemini", model: Optional[str] = None):
        """
        Initialize the structurer.
        
        Args:
            provider: "gemini" or "mistral"
            model: Model name (optional, uses defaults)
        """
        self.provider = provider.lower()
        
        if self.provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable not set")
            self.client = genai.Client(api_key=api_key)
            # Use gemini-3-flash-preview which has better JSON generation
            self.model = model or os.environ.get("MODEL_NAME", "gemini-3-flash-preview")
            logger.info(f"Using Gemini: {self.model}")
            
        elif self.provider == "mistral":
            api_key = os.environ.get("MISTRAL_API_KEY")
            if not api_key:
                raise ValueError("MISTRAL_API_KEY environment variable not set")
            self.client = Mistral(api_key=api_key)
            self.model = model or "mistral-large-latest"
            logger.info(f"Using Mistral: {self.model}")
        else:
            raise ValueError(f"Unknown provider: {provider}")
        
        self.renderer = HTMLRenderer()
    
    def _get_schema_string(self) -> str:
        """Get DocumentStructure schema as string."""
        return json.dumps(DocumentStructure.model_json_schema(), indent=2)
    
    def _merge_image_data(self, doc_structure: DocumentStructure, ocr_data: dict) -> DocumentStructure:
        """
        Merge base64 image data from original OCR JSON into structured document.
        
        Args:
            doc_structure: Structured document from LLM
            ocr_data: Original OCR JSON with image_base64 data
            
        Returns:
            Updated doc_structure with image_data populated
        """
        # Build a map of OCR images by page index
        ocr_images_by_page = {}
        for page in ocr_data.get('pages', []):
            page_idx = page.get('index', -1)
            images = page.get('images', [])
            if images and page_idx >= 0:
                ocr_images_by_page[page_idx] = [
                    img for img in images 
                    if img.get('image_base64')
                ]
        
        # Match and merge images into structured document
        for page in doc_structure.pages:
            # Map page_number (1-indexed) to page index (0-indexed)
            page_idx = page.page_number - 1
            ocr_images = ocr_images_by_page.get(page_idx, [])
            
            if not ocr_images:
                continue
            
            # Assign image data to structured images
            # Simple strategy: assign in order
            for i, struct_img in enumerate(page.images):
                if i < len(ocr_images):
                    struct_img.image_data = ocr_images[i].get('image_base64')
                    logger.debug(f"Merged image data for page {page.page_number}, image {i+1}")
        
        return doc_structure
    
    def _call_llm(self, markdown: str) -> tuple[str, dict]:
        """Call LLM to structure the markdown."""
        schema_str = self._get_schema_string()
        prompt = STRUCTURING_PROMPT.format(
            schema=schema_str,
            markdown=markdown[:50000]  # Limit input size to avoid huge responses
        )
        
        if self.provider == "gemini":
            # Use response_schema for better JSON generation
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=100000,
                        response_mime_type="application/json",
                        response_schema=DocumentStructure  # Direct Pydantic schema
                    )
                )
            except Exception as e:
                logger.warning(f"Failed with response_schema, retrying without: {e}")
                # Fallback without schema
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=100000,
                        response_mime_type="application/json"
                    )
                )
            content = response.text
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
            }
        else:  # mistral
            response = self.client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=65536,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
        
        return content, usage
    
    def process_batch_json(self, json_path: Path, output_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        Process a batch OCR JSON file.
        
        Args:
            json_path: Path to batch OCR JSON file (from parse_batch_results.py)
            output_dir: Output directory (default: same as input)
        
        Returns:
            Dict with processing stats
        """
        if output_dir is None:
            output_dir = json_path.parent
        
        base_name = json_path.stem
        logger.info(f"Processing: {base_name}")
        
        # Load batch OCR JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            ocr_data = json.load(f)
        
        # Extract markdown from all pages
        markdown_parts = []
        for page in ocr_data.get('pages', []):
            page_md = page.get('markdown', '')
            if page_md:
                page_num = page.get('index', '?') + 1
                markdown_parts.append(f"# PAGE {page_num}\n\n{page_md}")
        
        if not markdown_parts:
            logger.warning(f"No markdown content found in {json_path}")
            return {"success": False, "error": "No markdown content"}
        
        full_markdown = "\n\n---\n\n".join(markdown_parts)
        logger.info(f"Extracted {len(markdown_parts)} pages, {len(full_markdown)} chars")
        
        # Call LLM for structuring
        try:
            logger.info("Calling LLM for structuring...")
            json_response, usage = self._call_llm(full_markdown)
            
            # Save raw response for debugging
            raw_response_path = output_dir / f"{base_name}_raw_response.json"
            with open(raw_response_path, 'w', encoding='utf-8') as f:
                f.write(json_response)
            logger.debug(f"Saved raw response to {raw_response_path}")
            
            # Try to parse and validate
            try:
                structured_data = json.loads(json_response)
            except json.JSONDecodeError as e:
                # Save the problematic response for inspection
                logger.error(f"JSON parse failed at char {e.pos}: {e.msg}")
                logger.error(f"Context: ...{json_response[max(0, e.pos-100):e.pos+100]}...")
                logger.error(f"Full response saved to: {raw_response_path}")
                raise
            
            doc_structure = DocumentStructure(**structured_data)
            
            # Merge image data from original OCR JSON
            doc_structure = self._merge_image_data(doc_structure, ocr_data)
            
            logger.info(f"✅ Validation passed: {len(doc_structure.pages)} pages")
            logger.info(f"📊 Tokens: {usage['prompt_tokens']:,} in, {usage['completion_tokens']:,} out")
            
            # Save structured JSON
            structured_path = output_dir / f"{base_name}_structured.json"
            with open(structured_path, 'w', encoding='utf-8') as f:
                json.dump(doc_structure.model_dump(), f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Saved: {structured_path}")
            
            # Generate HTML
            html_content = self.renderer.render(doc_structure)
            html_path = output_dir / f"{base_name}.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"🌐 Saved: {html_path}")
            
            return {
                "success": True,
                "pages": len(doc_structure.pages),
                "tokens": usage,
                "structured_json": str(structured_path),
                "html": str(html_path)
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            return {"success": False, "error": f"JSON parse error: {e}"}
        except ValidationError as e:
            logger.error(f"Pydantic validation failed: {e}")
            return {"success": False, "error": f"Validation error: {e}"}
        except Exception as e:
            logger.error(f"Processing failed: {e}")
            return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Transform batch OCR markdown into structured JSON"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Batch OCR JSON files to process"
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "mistral"],
        default="gemini",
        help="LLM provider for structuring (default: gemini)"
    )
    parser.add_argument(
        "--model",
        help="Model name (optional)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: same as input)"
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Process files in parallel"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)"
    )
    
    args = parser.parse_args()
    
    # Initialize structurer
    structurer = BatchStructurer(provider=args.provider, model=args.model)
    
    # Collect input files
    input_files = []
    for pattern in args.files:
        if '*' in pattern:
            import glob
            input_files.extend([Path(p) for p in glob.glob(pattern)])
        else:
            input_files.append(Path(pattern))
    
    # Filter to only JSON files (not _structured.json)
    input_files = [
        f for f in input_files 
        if f.suffix == '.json' and not f.stem.endswith('_structured')
    ]
    
    if not input_files:
        logger.error("No input files found")
        return
    
    logger.info(f"Found {len(input_files)} files to process")
    print("=" * 70)
    
    # Process files
    results = []
    
    if args.parallel and len(input_files) > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(structurer.process_batch_json, f, args.output_dir): f
                for f in input_files
            }
            
            for future in as_completed(futures):
                file_path = futures[future]
                try:
                    result = future.result()
                    results.append((file_path.name, result))
                except Exception as e:
                    logger.error(f"Failed to process {file_path.name}: {e}")
                    results.append((file_path.name, {"success": False, "error": str(e)}))
    else:
        for file_path in input_files:
            result = structurer.process_batch_json(file_path, args.output_dir)
            results.append((file_path.name, result))
            print("-" * 70)
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    successful = sum(1 for _, r in results if r.get("success"))
    failed = len(results) - successful
    
    total_tokens_in = sum(r.get("tokens", {}).get("prompt_tokens", 0) for _, r in results if r.get("success"))
    total_tokens_out = sum(r.get("tokens", {}).get("completion_tokens", 0) for _, r in results if r.get("success"))
    
    print(f"✅ Successful: {successful}/{len(results)}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total tokens: {total_tokens_in:,} in, {total_tokens_out:,} out")
    
    if failed > 0:
        print("\nFailed files:")
        for name, result in results:
            if not result.get("success"):
                print(f"  - {name}: {result.get('error', 'Unknown error')}")


if __name__ == "__main__":
    main()
