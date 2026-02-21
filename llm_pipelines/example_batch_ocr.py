#!/usr/bin/env python3
"""
Example usage of Mistral Batch OCR Pipeline.

Shows different ways to use the batch OCR API:
1. Process entire directory
2. Process specific PDFs
3. Check status of existing jobs
"""

from pathlib import Path
from .mistral_batch_ocr import MistralBatchOCR, BatchOCRConfig

# ---------------------------------------------------------------------------
# Example 1: Process entire directory with defaults
# ---------------------------------------------------------------------------
def example_simple():
    """Process all PDFs in a directory - simplest usage."""
    
    pipeline = MistralBatchOCR()
    
    result = pipeline.process_directory(
        pdf_dir=Path("./pdfs"),
        wait_for_completion=True
    )
    
    print(f"Processed {result['pdfs_saved']} PDFs")


# ---------------------------------------------------------------------------
# Example 2: Custom configuration and chunking
# ---------------------------------------------------------------------------
def example_custom_config():
    """Process with custom batch size and settings."""
    
    config = BatchOCRConfig(
        batch_size=1000,  # 1000 PDFs per batch job
        include_image_base64=True,  # Include extracted images
        max_upload_workers=16,  # More parallel uploads
        output_dir="./my_ocr_output",
        save_raw_json=True,
        save_markdown=True,
    )
    
    pipeline = MistralBatchOCR(config)
    
    result = pipeline.process_directory(
        pdf_dir=Path("./large_archive"),
        pattern="*.pdf",
        wait_for_completion=True
    )
    
    print(f"Created {result['batch_jobs_created']} batch jobs")
    print(f"Saved {result['pdfs_saved']} PDFs")


# ---------------------------------------------------------------------------
# Example 3: Submit and poll separately (async workflow)
# ---------------------------------------------------------------------------
def example_async_workflow():
    """Submit jobs without waiting, then poll later."""
    
    pipeline = MistralBatchOCR()
    
    # Step 1: Submit jobs (don't wait)
    print("Submitting batch jobs...")
    result = pipeline.process_directory(
        pdf_dir=Path("./pdfs"),
        wait_for_completion=False  # Just submit and return
    )
    
    print(f"Submitted {result['batch_jobs_created']} batch jobs")
    print(f"Job IDs: {result['batch_job_ids']}")
    print("Jobs are processing in background...")
    
    # ... do other work ...
    
    # Step 2: Later, poll for results
    print("\nChecking job status...")
    poll_result = pipeline.poll_all_jobs(timeout=3600)  # Wait up to 1 hour
    
    # Step 3: Download results
    stats = pipeline.process_all_results()
    print(f"Downloaded {stats['pdfs_saved']} PDFs")


# ---------------------------------------------------------------------------
# Example 4: Process specific PDFs (not entire directory)
# ---------------------------------------------------------------------------
def example_specific_pdfs():
    """Process a specific list of PDFs."""
    
    pipeline = MistralBatchOCR()
    
    # Select specific PDFs
    pdf_paths = [
        Path("./pdfs/doc1.pdf"),
        Path("./pdfs/doc2.pdf"),
        Path("./pdfs/important_doc.pdf"),
    ]
    
    # Upload them
    custom_ids = ["doc1", "doc2", "important_doc"]
    file_id_map = pipeline.upload_pdfs_parallel(pdf_paths, custom_ids)
    
    # Create batch job
    batch_job = pipeline.create_batch_job(
        file_id_map,
        metadata={"priority": "high", "project": "Q1_reports"}
    )
    
    print(f"Created batch job: {batch_job.job_id}")
    
    # Poll until complete
    while not pipeline.poll_batch_job(batch_job):
        print("Job still running...")
        import time
        time.sleep(60)
    
    # Download results
    results = pipeline.download_batch_results(batch_job)
    saved = pipeline.parse_and_save_results(batch_job, results)
    
    print(f"Saved {saved} PDFs")


# ---------------------------------------------------------------------------
# Example 5: Resume existing jobs (recovery)
# ---------------------------------------------------------------------------
def example_resume_jobs():
    """Resume checking existing batch jobs (e.g., after restart)."""
    
    # Pipeline automatically loads existing jobs from batch_state.json
    pipeline = MistralBatchOCR()
    
    print(f"Found {len(pipeline.batch_jobs)} existing batch jobs")
    
    # Poll them
    poll_result = pipeline.poll_all_jobs()
    
    print(f"Completed: {len(poll_result['completed'])}")
    print(f"Still running: {len(poll_result['incomplete'])}")
    
    # Download any new results
    stats = pipeline.process_all_results()
    print(f"Downloaded {stats['pdfs_saved']} new PDFs")


# ---------------------------------------------------------------------------
# Example 6: Large-scale processing with chunking
# ---------------------------------------------------------------------------
def example_large_scale():
    """Process 50,000 PDFs with optimal chunking."""
    
    config = BatchOCRConfig(
        batch_size=500,  # 500 PDFs per job = 100 jobs for 50K PDFs
        max_upload_workers=16,
        output_dir="./massive_archive_ocr",
    )
    
    pipeline = MistralBatchOCR(config)
    
    # Process huge directory
    result = pipeline.process_directory(
        pdf_dir=Path("/data/court_documents"),
        pattern="*.pdf",
        wait_for_completion=False  # Submit all, poll later
    )
    
    print(f"Submitted {result['batch_jobs_created']} batch jobs")
    print(f"Total PDFs: {result['pdfs_uploaded']}")
    print(f"Estimated cost: ${result['pdfs_uploaded'] * 30 / 1000:.2f}")  # Assume 30 pages avg
    print("Jobs are running. Use --poll-only to check progress later.")


if __name__ == "__main__":
    # Run example 1 by default
    # Uncomment others to try different patterns
    
    example_simple()
    # example_custom_config()
    # example_async_workflow()
    # example_specific_pdfs()
    # example_resume_jobs()
    # example_large_scale()
