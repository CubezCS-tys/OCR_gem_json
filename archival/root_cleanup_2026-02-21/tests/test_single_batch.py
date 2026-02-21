#!/usr/bin/env python3
"""
Minimal test: Upload 1 PDF and create smallest batch job.
"""

from pathlib import Path
from mistral_batch_ocr import MistralBatchOCR, BatchOCRConfig

def test_single_pdf():
    """Test with just one PDF."""
    
    config = BatchOCRConfig(
        batch_size=1,
        output_dir="batch_markdown",
    )
    
    pipeline = MistralBatchOCR(config)
    
    print("Testing with 1 PDF only...")
    
    # Upload just one PDF
    pdf_path = Path("./pdfs/0005-052-002-003.pdf")
    file_id_map = pipeline.upload_pdfs_parallel([pdf_path], ["test_doc"])
    
    print(f"Uploaded: {file_id_map}")
    
    # Try to create batch job
    batch_job = pipeline.create_batch_job(file_id_map, {"test": "single"})
    
    if batch_job:
        print(f"✓ Batch job created: {batch_job.job_id}")
        print(f"  Status: {batch_job.status}")
    else:
        print("✗ Failed to create batch job")

if __name__ == "__main__":
    test_single_pdf()
