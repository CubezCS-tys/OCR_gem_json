#!/usr/bin/env python3
"""
Quick status check for batch job.
"""

from pathlib import Path
import json
from .mistral_batch_ocr import MistralBatchOCR, BatchOCRConfig

config = BatchOCRConfig(output_dir="batch_markdown")
pipeline = MistralBatchOCR(config)

print("="*60)
print("Batch Job Status Check")
print("="*60)

if not pipeline.batch_jobs:
    print("No batch jobs found!")
else:
    for i, job in enumerate(pipeline.batch_jobs, 1):
        print(f"\nJob {i}:")
        print(f"  ID:     {job.job_id}")
        print(f"  Status: {job.status}")
        print(f"  PDFs:   {len(job.custom_ids)}")
        
        # Calculate elapsed time
        import time
        elapsed = time.time() - job.created_at
        print(f"  Age:    {elapsed/60:.1f} minutes")
        
        # Try to update status
        print("\n  Checking latest status...")
        is_complete = pipeline.poll_batch_job(job)
        
        print(f"  Current: {job.status}")
        
        if is_complete:
            print(f"  ✓ COMPLETE!")
            if job.status == "SUCCESS":
                # Download results
                results = pipeline.download_batch_results(job)
                if results:
                    saved = pipeline.parse_and_save_results(job, results)
                    print(f"  ✓ Saved {saved} PDFs to batch_markdown/")
        else:
            print(f"  ⏳ Still processing... check again in 5-10 minutes")

print("="*60)
