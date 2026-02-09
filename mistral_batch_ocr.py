#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mistral Batch OCR Pipeline - 50% cost savings on OCR processing.

Handles batch submission of PDFs to Mistral OCR API with automatic
chunking, polling, and result retrieval.

Usage:
    python mistral_batch_ocr.py --pdfs-dir ./pdfs --output-dir ./raw_ocr
    python mistral_batch_ocr.py --pdf-list pdfs.txt --batch-size 500
"""

import os
import sys
import json
import time
import logging
import argparse
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class BatchOCRConfig:
    """Configuration for Mistral Batch OCR pipeline."""
    model: str = "mistral-ocr-2512"
    batch_size: int = 500  # PDFs per batch job
    include_image_base64: bool = True
    max_upload_workers: int = 8  # Parallel PDF uploads
    poll_interval: int = 300  # Seconds between status checks (5 min)
    max_poll_time: int = 86400  # Max time to wait for batch (24 hours)
    output_dir: str = "batch_ocr_output"
    save_raw_json: bool = True  # Save raw batch results
    save_markdown: bool = True  # Save extracted markdown per PDF


# ---------------------------------------------------------------------------
# Batch Job Tracker
# ---------------------------------------------------------------------------
@dataclass
class BatchJob:
    """Track a single batch job."""
    job_id: str
    custom_ids: List[str]  # PDF identifiers in this batch
    file_ids: Dict[str, str]  # Map custom_id -> file_id
    status: str = "QUEUED"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    output_file_id: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Serialize to dict for persistence."""
        return {
            "job_id": self.job_id,
            "custom_ids": self.custom_ids,
            "file_ids": self.file_ids,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "output_file_id": self.output_file_id,
            "error": self.error,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BatchJob":
        """Deserialize from dict."""
        return cls(**data)


# ---------------------------------------------------------------------------
# Mistral Batch OCR Pipeline
# ---------------------------------------------------------------------------
class MistralBatchOCR:
    """
    Handles batch OCR submission to Mistral API with 50% cost savings.
    
    Workflow:
        1. Upload PDFs to Mistral Files API (parallel)
        2. Create batch jobs (chunked)
        3. Poll for completion
        4. Download and parse results
        5. Save markdown per PDF
    """
    
    def __init__(self, config: Optional[BatchOCRConfig] = None):
        self.config = config or BatchOCRConfig()
        
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError(
                "MISTRAL_API_KEY environment variable not set. "
                "Get your key at https://console.mistral.ai/"
            )
        
        self.client = Mistral(api_key=api_key)
        self.output_dir = Path(self.config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Track batch jobs
        self.batch_jobs: List[BatchJob] = []
        self._load_batch_state()
    
    # ------------------------------------------------------------------
    # Phase 1: Upload PDFs
    # ------------------------------------------------------------------
    
    def upload_pdf(self, pdf_path: Path, custom_id: str) -> Optional[str]:
        """
        Upload a single PDF to Mistral Files API.

        Args:
            pdf_path: Path to PDF file
            custom_id: Unique identifier for this PDF

        Returns:
            file_id or None if upload failed
        """
        try:
            logger.info(f"Uploading {custom_id}: {pdf_path.name}")

            with open(pdf_path, "rb") as f:
                uploaded = self.client.files.upload(
                    file={
                        "file_name": pdf_path.name,
                        "content": f,
                    },
                    purpose="ocr",  # Upload PDFs with "ocr" purpose for batch OCR
                )

            logger.info(f"✓ Uploaded {custom_id}: file_id={uploaded.id}")
            return uploaded.id

        except Exception as e:
            logger.error(f"✗ Failed to upload {custom_id}: {e}")
            return None
    
    def upload_pdfs_parallel(
        self,
        pdf_paths: List[Path],
        custom_ids: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Upload multiple PDFs in parallel.
        
        Args:
            pdf_paths: List of PDF file paths
            custom_ids: Optional custom IDs (defaults to pdf filenames)
        
        Returns:
            Dict mapping custom_id -> file_id
        """
        if custom_ids is None:
            custom_ids = [p.stem for p in pdf_paths]
        
        if len(pdf_paths) != len(custom_ids):
            raise ValueError("pdf_paths and custom_ids must have same length")
        
        file_id_map = {}
        total = len(pdf_paths)
        
        logger.info(f"Uploading {total} PDFs (parallel workers: {self.config.max_upload_workers})")
        
        with ThreadPoolExecutor(max_workers=self.config.max_upload_workers) as executor:
            futures = {
                executor.submit(self.upload_pdf, path, cid): (path, cid)
                for path, cid in zip(pdf_paths, custom_ids)
            }
            
            completed = 0
            for future in as_completed(futures):
                path, cid = futures[future]
                file_id = future.result()
                
                if file_id:
                    file_id_map[cid] = file_id
                
                completed += 1
                if completed % 10 == 0 or completed == total:
                    logger.info(f"Upload progress: {completed}/{total} ({len(file_id_map)} successful)")
        
        logger.info(f"Upload complete: {len(file_id_map)}/{total} PDFs uploaded successfully")
        return file_id_map
    
    # ------------------------------------------------------------------
    # Phase 2: Create Batch Jobs
    # ------------------------------------------------------------------
    
    def create_batch_job(
        self,
        file_id_map: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[BatchJob]:
        """
        Create a single batch job from file_id map.
        
        Args:
            file_id_map: Dict mapping custom_id -> file_id
            metadata: Optional metadata for the batch job
        
        Returns:
            BatchJob object or None if creation failed
        """
        try:
            # Build inline batch requests
            requests = []
            for custom_id, file_id in file_id_map.items():
                requests.append({
                    "custom_id": custom_id,
                    "body": {
                        "document": {"file_id": file_id},
                        "include_image_base64": self.config.include_image_base64,
                    }
                })
            
            logger.info(f"Creating batch job with {len(requests)} PDFs...")
            
            # Create batch job
            job = self.client.batch.jobs.create(
                requests=requests,
                model=self.config.model,
                endpoint="/v1/ocr",
                metadata=metadata or {}
            )
            
            batch_job = BatchJob(
                job_id=job.id,
                custom_ids=list(file_id_map.keys()),
                file_ids=file_id_map,
                status=job.status,
            )
            
            self.batch_jobs.append(batch_job)
            self._save_batch_state()
            
            logger.info(f"✓ Batch job created: {job.id} (status={job.status})")
            return batch_job
        
        except Exception as e:
            logger.error(f"✗ Failed to create batch job: {e}")
            return None
    
    def create_batch_jobs_chunked(
        self,
        file_id_map: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[BatchJob]:
        """
        Create multiple batch jobs by chunking file_id_map.
        
        Args:
            file_id_map: Dict mapping custom_id -> file_id
            metadata: Optional base metadata (will add chunk info)
        
        Returns:
            List of created BatchJob objects
        """
        items = list(file_id_map.items())
        chunk_size = self.config.batch_size
        num_chunks = (len(items) + chunk_size - 1) // chunk_size
        
        logger.info(
            f"Creating {num_chunks} batch jobs "
            f"({len(items)} PDFs, {chunk_size} per batch)"
        )
        
        created_jobs = []
        
        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = min(start_idx + chunk_size, len(items))
            chunk = dict(items[start_idx:end_idx])
            
            chunk_metadata = (metadata or {}).copy()
            chunk_metadata.update({
                "chunk_index": i,
                "total_chunks": num_chunks,
                "pdf_count": len(chunk),
            })
            
            logger.info(f"Creating batch job {i+1}/{num_chunks} ({len(chunk)} PDFs)...")
            
            batch_job = self.create_batch_job(chunk, chunk_metadata)
            if batch_job:
                created_jobs.append(batch_job)
            
            # Small delay to avoid rate limiting
            if i < num_chunks - 1:
                time.sleep(1)
        
        logger.info(f"Created {len(created_jobs)}/{num_chunks} batch jobs")
        return created_jobs
    
    # ------------------------------------------------------------------
    # Phase 3: Poll for Completion
    # ------------------------------------------------------------------
    
    def poll_batch_job(self, batch_job: BatchJob) -> bool:
        """
        Poll a single batch job for completion.
        
        Args:
            batch_job: BatchJob to poll
        
        Returns:
            True if job is complete (success or failed), False if still running
        """
        try:
            job = self.client.batch.jobs.get(job_id=batch_job.job_id)
            batch_job.status = job.status
            
            if job.status in ["SUCCESS", "FAILED", "TIMEOUT_EXCEEDED", "CANCELLED"]:
                batch_job.completed_at = time.time()
                
                if job.status == "SUCCESS":
                    batch_job.output_file_id = job.output_file
                    logger.info(f"✓ Batch job {batch_job.job_id} completed successfully")
                else:
                    batch_job.error = job.status
                    logger.error(f"✗ Batch job {batch_job.job_id} failed: {job.status}")
                
                self._save_batch_state()
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error polling batch job {batch_job.job_id}: {e}")
            return False
    
    def poll_all_jobs(self, timeout: Optional[int] = None) -> Dict[str, List[BatchJob]]:
        """
        Poll all batch jobs until completion or timeout.
        
        Args:
            timeout: Max seconds to wait (default: config.max_poll_time)
        
        Returns:
            Dict with "completed" and "incomplete" job lists
        """
        timeout = timeout or self.config.max_poll_time
        start_time = time.time()
        
        pending_jobs = [j for j in self.batch_jobs if j.status not in 
                       ["SUCCESS", "FAILED", "TIMEOUT_EXCEEDED", "CANCELLED"]]
        
        if not pending_jobs:
            logger.info("No pending batch jobs to poll")
            return {"completed": self.batch_jobs, "incomplete": []}
        
        logger.info(f"Polling {len(pending_jobs)} batch jobs (timeout={timeout}s)")
        
        while pending_jobs and (time.time() - start_time) < timeout:
            logger.info(f"Checking status of {len(pending_jobs)} jobs...")
            
            still_pending = []
            for job in pending_jobs:
                is_complete = self.poll_batch_job(job)
                if not is_complete:
                    still_pending.append(job)
            
            pending_jobs = still_pending
            
            if pending_jobs:
                logger.info(
                    f"{len(pending_jobs)} jobs still running. "
                    f"Next check in {self.config.poll_interval}s..."
                )
                time.sleep(self.config.poll_interval)
        
        completed = [j for j in self.batch_jobs if j.status in 
                    ["SUCCESS", "FAILED", "TIMEOUT_EXCEEDED", "CANCELLED"]]
        
        logger.info(
            f"Polling complete: {len(completed)} finished, "
            f"{len(pending_jobs)} still pending"
        )
        
        return {"completed": completed, "incomplete": pending_jobs}
    
    # ------------------------------------------------------------------
    # Phase 4: Download and Parse Results
    # ------------------------------------------------------------------
    
    def download_batch_results(self, batch_job: BatchJob) -> Optional[List[Dict[str, Any]]]:
        """
        Download and parse results from a completed batch job.
        
        Args:
            batch_job: Completed BatchJob
        
        Returns:
            List of result dicts, or None if download failed
        """
        if not batch_job.output_file_id:
            logger.error(f"No output file for batch job {batch_job.job_id}")
            return None
        
        try:
            logger.info(f"Downloading results for batch job {batch_job.job_id}...")
            
            output_stream = self.client.files.download(
                file_id=batch_job.output_file_id
            )
            
            results = []
            content = output_stream.read().decode('utf-8')
            
            # Parse JSONL format
            for line in content.strip().split('\n'):
                if line:
                    results.append(json.loads(line))
            
            logger.info(f"✓ Downloaded {len(results)} results")
            
            # Save raw results if configured
            if self.config.save_raw_json:
                raw_path = self.output_dir / f"batch_{batch_job.job_id}_raw.jsonl"
                with open(raw_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"Saved raw results to {raw_path}")
            
            return results
        
        except Exception as e:
            logger.error(f"Failed to download results: {e}")
            return None
    
    def parse_and_save_results(
        self,
        batch_job: BatchJob,
        results: List[Dict[str, Any]]
    ) -> int:
        """
        Parse batch results and save markdown files per PDF.

        Args:
            batch_job: BatchJob these results belong to
            results: List of result dicts from batch API

        Returns:
            Number of PDFs successfully saved
        """
        saved_count = 0
        failures = []  # Track failures for manifest

        for result in results:
            custom_id = result.get("custom_id")
            if not custom_id:
                error_msg = "Result missing custom_id"
                logger.warning(error_msg)
                failures.append({
                    "custom_id": "unknown",
                    "error": error_msg,
                    "result": result
                })
                continue

            # Check for errors (only if error is not None)
            if result.get("error") is not None:
                error_msg = str(result['error'])
                logger.error(f"Error for {custom_id}: {error_msg}")
                failures.append({
                    "custom_id": custom_id,
                    "error": error_msg,
                    "result": result
                })
                continue

            # Extract OCR response
            response = result.get("response", {})
            body = response.get("body", {})
            pages = body.get("pages", [])

            if not pages:
                error_msg = "No pages found in OCR response"
                logger.warning(f"{error_msg} for {custom_id}")
                failures.append({
                    "custom_id": custom_id,
                    "error": error_msg,
                    "result": result
                })
                continue
            
            # Combine markdown from all pages
            markdown_parts = []
            for page in pages:
                page_idx = page.get("index", 0)
                page_md = page.get("markdown", "")
                
                markdown_parts.append(f"\n\n---\n## PAGE {page_idx + 1}\n\n{page_md}")
            
            full_markdown = "".join(markdown_parts)
            
            # Save markdown
            if self.config.save_markdown:
                md_path = self.output_dir / f"{custom_id}_raw_ocr.md"
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(full_markdown)
                
                logger.info(f"✓ Saved {custom_id} ({len(pages)} pages, {len(full_markdown)} chars)")
                saved_count += 1

        # Save failures manifest if any failures occurred
        if failures:
            failures_path = self.output_dir / f"batch_{batch_job.job_id}_failures.json"
            with open(failures_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "batch_job_id": batch_job.job_id,
                    "total_failures": len(failures),
                    "failures": failures,
                    "timestamp": time.time()
                }, f, indent=2, ensure_ascii=False)
            logger.warning(f"Saved {len(failures)} failures to {failures_path}")

        return saved_count
    
    def process_all_results(self) -> Dict[str, int]:
        """
        Download and parse results from all completed batch jobs.
        
        Returns:
            Dict with statistics (jobs_processed, pdfs_saved, errors)
        """
        completed_jobs = [j for j in self.batch_jobs if j.status == "SUCCESS"]
        
        if not completed_jobs:
            logger.info("No completed jobs to process")
            return {"jobs_processed": 0, "pdfs_saved": 0, "errors": 0}
        
        logger.info(f"Processing results from {len(completed_jobs)} completed jobs...")
        
        stats = {"jobs_processed": 0, "pdfs_saved": 0, "errors": 0}
        
        for job in completed_jobs:
            results = self.download_batch_results(job)
            if results:
                saved = self.parse_and_save_results(job, results)
                stats["pdfs_saved"] += saved
                stats["jobs_processed"] += 1
            else:
                stats["errors"] += 1
        
        logger.info(
            f"Results processing complete: "
            f"{stats['jobs_processed']} jobs, "
            f"{stats['pdfs_saved']} PDFs saved"
        )
        
        return stats
    
    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------
    
    def _save_batch_state(self):
        """Save batch job state to disk for recovery (atomic write)."""
        state_file = self.output_dir / "batch_state.json"
        temp_file = self.output_dir / "batch_state.json.tmp"

        state = {
            "batch_jobs": [job.to_dict() for job in self.batch_jobs],
            "updated_at": time.time(),
        }

        # Atomic write: write to temp file, then rename
        # This prevents corruption if process is killed mid-write
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)

            # Atomic rename (POSIX guarantees atomicity)
            temp_file.replace(state_file)
        except Exception as e:
            logger.error(f"Failed to save batch state: {e}")
            # Clean up temp file if it exists
            if temp_file.exists():
                temp_file.unlink()
    
    def _load_batch_state(self):
        """Load batch job state from disk."""
        state_file = self.output_dir / "batch_state.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                self.batch_jobs = [
                    BatchJob.from_dict(job_dict)
                    for job_dict in state.get("batch_jobs", [])
                ]
                logger.info(f"Loaded {len(self.batch_jobs)} batch jobs from state file")
            except Exception as e:
                logger.warning(f"Failed to load batch state: {e}")
    
    # ------------------------------------------------------------------
    # High-Level API
    # ------------------------------------------------------------------
    
    def process_directory(
        self,
        pdf_dir: Path,
        pattern: str = "*.pdf",
        wait_for_completion: bool = True
    ) -> Dict[str, Any]:
        """
        Process all PDFs in a directory using batch OCR.
        
        Args:
            pdf_dir: Directory containing PDF files
            pattern: Glob pattern for PDF files
            wait_for_completion: If True, poll until all jobs complete
        
        Returns:
            Dict with processing statistics and job info
        """
        pdf_paths = sorted(Path(pdf_dir).glob(pattern))
        
        if not pdf_paths:
            raise ValueError(f"No PDFs found in {pdf_dir} matching {pattern}")
        
        logger.info(f"Starting batch OCR for {len(pdf_paths)} PDFs from {pdf_dir}")
        
        # Phase 1: Upload PDFs
        file_id_map = self.upload_pdfs_parallel(pdf_paths)
        
        if not file_id_map:
            raise RuntimeError("No PDFs uploaded successfully")
        
        # Phase 2: Create batch jobs
        created_jobs = self.create_batch_jobs_chunked(
            file_id_map,
            metadata={"source_dir": str(pdf_dir)}
        )
        
        if not created_jobs:
            raise RuntimeError("No batch jobs created")
        
        result = {
            "pdfs_found": len(pdf_paths),
            "pdfs_uploaded": len(file_id_map),
            "batch_jobs_created": len(created_jobs),
            "batch_job_ids": [j.job_id for j in created_jobs],
        }
        
        # Phase 3: Poll for completion (optional)
        if wait_for_completion:
            logger.info("Waiting for batch jobs to complete...")
            poll_result = self.poll_all_jobs()
            
            # Phase 4: Download results
            stats = self.process_all_results()
            
            result.update({
                "completed_jobs": len(poll_result["completed"]),
                "incomplete_jobs": len(poll_result["incomplete"]),
                "pdfs_saved": stats["pdfs_saved"],
            })
        
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Mistral Batch OCR - 50% cost savings on PDF OCR"
    )
    parser.add_argument(
        "--pdfs-dir",
        type=str,
        required=True,
        help="Directory containing PDF files"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="batch_ocr_output",
        help="Output directory for results"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of PDFs per batch job"
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="*.pdf",
        help="Glob pattern for PDF files"
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for completion (just submit)"
    )
    parser.add_argument(
        "--poll-only",
        action="store_true",
        help="Only poll existing jobs (don't submit new ones)"
    )
    
    args = parser.parse_args()
    
    config = BatchOCRConfig(
        output_dir=args.output_dir,
        batch_size=args.batch_size,
    )
    
    pipeline = MistralBatchOCR(config)
    
    if args.poll_only:
        # Just poll existing jobs
        logger.info("Polling existing batch jobs...")
        poll_result = pipeline.poll_all_jobs()
        stats = pipeline.process_all_results()
        
        print(f"\n{'='*60}")
        print(f"  Polling Results:")
        print(f"  Completed jobs: {len(poll_result['completed'])}")
        print(f"  Incomplete jobs: {len(poll_result['incomplete'])}")
        print(f"  PDFs saved: {stats['pdfs_saved']}")
        print(f"{'='*60}")
    else:
        # Submit new batch
        result = pipeline.process_directory(
            pdf_dir=Path(args.pdfs_dir),
            pattern=args.pattern,
            wait_for_completion=not args.no_wait
        )
        
        print(f"\n{'='*60}")
        print(f"  Batch OCR Complete")
        print(f"  PDFs found: {result['pdfs_found']}")
        print(f"  PDFs uploaded: {result['pdfs_uploaded']}")
        print(f"  Batch jobs created: {result['batch_jobs_created']}")
        
        if not args.no_wait:
            print(f"  Completed jobs: {result['completed_jobs']}")
            print(f"  PDFs saved: {result['pdfs_saved']}")
        else:
            print(f"  Status: Submitted (use --poll-only to check progress)")
        
        print(f"  Output: {args.output_dir}/")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
