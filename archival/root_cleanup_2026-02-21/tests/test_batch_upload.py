#!/usr/bin/env python3
"""
Quick test: Upload PDFs and submit batch OCR job.
Only tests the upload + submission phase (doesn't wait for completion).
"""

from pathlib import Path
from mistral_batch_ocr import MistralBatchOCR, BatchOCRConfig

def test_batch_upload():
    """Test uploading PDFs and creating batch job."""
    
    # Configure
    config = BatchOCRConfig(
        batch_size=100,  # All PDFs in one batch for testing
        max_upload_workers=4,  # Conservative for testing
        output_dir="batch_markdown",
        save_markdown=True,
    )
    
    pipeline = MistralBatchOCR(config)
    
    print("="*60)
    print("Testing Mistral Batch OCR - Upload & Submit Phase")
    print("="*60)
    
    # Process PDFs (submit only, don't wait)
    result = pipeline.process_directory(
        pdf_dir=Path("./pdfs"),
        pattern="*.pdf",
        wait_for_completion=False  # Just submit, don't wait
    )
    
    print("\n" + "="*60)
    print("BATCH SUBMISSION COMPLETE")
    print("="*60)
    print(f"PDFs found:        {result['pdfs_found']}")
    print(f"PDFs uploaded:     {result['pdfs_uploaded']}")
    print(f"Batch jobs created: {result['batch_jobs_created']}")
    print(f"\nBatch Job IDs:")
    for job_id in result['batch_job_ids']:
        print(f"  - {job_id}")
    print(f"\nOutput directory:  {config.output_dir}/")
    print(f"State file:        {config.output_dir}/batch_state.json")
    print("="*60)
    print("\nNext steps:")
    print("  1. Wait for batch jobs to complete (check Mistral console)")
    print("  2. Poll for results:")
    print("     python mistral_batch_ocr.py --pdfs-dir ./pdfs --output-dir batch_markdown --poll-only")
    print("="*60)

if __name__ == "__main__":
    test_batch_upload()
