#!/usr/bin/env python3
"""
Quick demo / test script for the Mistral OCR two-pass pipeline.

Usage:
    python mistral.py                          # process default test PDF
    python mistral.py /path/to/file.pdf        # process specific PDF
    python mistral.py /path/to/file.pdf -o out # custom output dir
"""

import sys
try:
    from .mistral_ocr_pipeline import MistralOCRPipeline, MistralPipelineConfig
except ImportError:  # pragma: no cover - direct script execution fallback
    from mistral_ocr_pipeline import MistralOCRPipeline, MistralPipelineConfig

# ── defaults ──
DEFAULT_PDF = "/home/k22015806/Desktop/OCR_gem_json/pdfs/0005-052-002-003.pdf"
DEFAULT_OUTPUT_DIR = "outputs"

def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF
    output_dir = DEFAULT_OUTPUT_DIR

    # Simple flag parsing
    if "-o" in sys.argv:
        idx = sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    config = MistralPipelineConfig(
        output_dir=output_dir,
        pages_per_chunk=5,
        save_raw_markdown=True,
        save_structured_json=True,
        save_html=True,
    )

    pipeline = MistralOCRPipeline(config)
    doc = pipeline.process(pdf_path)

    # Quick summary
    print(f"\n{'='*50}")
    print(f"  Title:    {doc.metadata.title or '(untitled)'}")
    print(f"  Language: {doc.metadata.language or '(unknown)'}")
    print(f"  Pages:    {doc.metadata.total_pages}")
    print(f"  Blocks:   {sum(len(p.text_blocks) for p in doc.pages)}")
    print(f"  Tables:   {sum(len(p.tables) for p in doc.pages)}")
    print(f"  Images:   {sum(len(p.images) for p in doc.pages)}")
    print(f"  Output:   {output_dir}/")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
