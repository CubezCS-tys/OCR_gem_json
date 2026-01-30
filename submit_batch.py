#!/usr/bin/env python3
"""
Submit multiple PDF files for parallel processing via Celery.

Usage:
    python submit_batch.py pdfs/*.pdf --output-dir output/
    python submit_batch.py --file-list files.txt --output-dir output/
    python submit_batch.py pdfs/*.pdf --output-dir output/ --monitor
"""

import argparse
import pathlib
import sys
from celery_tasks import process_pdf, process_pdf_batch
from celery.result import AsyncResult, GroupResult
import time


def monitor_tasks(task_ids: list[str], refresh_interval: int = 5):
    """Monitor Celery tasks and display progress."""
    print(f"\nMonitoring {len(task_ids)} tasks...")
    print("=" * 80)

    completed = set()
    failed = set()

    while True:
        pending = []
        processing = []

        for task_id in task_ids:
            if task_id in completed or task_id in failed:
                continue

            result = AsyncResult(task_id)

            if result.state == 'SUCCESS':
                completed.add(task_id)
                info = result.result
                print(f"✓ {info.get('pdf_path', 'Unknown')}: {info.get('pages', 0)} pages, {info.get('blocks', 0)} blocks")

            elif result.state == 'FAILURE':
                failed.add(task_id)
                print(f"✗ Task {task_id} failed: {result.result}")

            elif result.state == 'PROCESSING':
                processing.append(task_id)
                meta = result.info if isinstance(result.info, dict) else {}
                pdf = meta.get('pdf', task_id[:8])
                status = meta.get('status', 'processing')
                print(f"⧗ {pdf}: {status}")

            else:
                pending.append(task_id)

        # Print summary
        total = len(task_ids)
        print(f"\n[{len(completed)}/{total} complete, {len(processing)} processing, {len(pending)} pending, {len(failed)} failed]")

        # Exit if all done
        if len(completed) + len(failed) == total:
            print("\n" + "=" * 80)
            print(f"✓ Batch complete: {len(completed)} succeeded, {len(failed)} failed")
            break

        # Wait before next check
        time.sleep(refresh_interval)
        print("\n" + "-" * 80)


def main():
    parser = argparse.ArgumentParser(description='Submit PDF batch for parallel processing')
    parser.add_argument('files', nargs='*', help='PDF files to process')
    parser.add_argument('--file-list', help='Text file with one PDF path per line')
    parser.add_argument('--output-dir', '-o', required=True, help='Output directory')
    parser.add_argument('--resolution', '-r', choices=['low', 'medium', 'high'], default='high')
    parser.add_argument('--format', '-f', choices=['html', 'json', 'both'], default='both')
    parser.add_argument('--pages-per-chunk', type=int, default=15, help='Pages per chunk')
    parser.add_argument('--monitor', '-m', action='store_true', help='Monitor task progress')
    parser.add_argument('--use-batch-task', action='store_true', help='Use batch coordination task')

    args = parser.parse_args()

    # Collect PDF paths
    pdf_paths = list(args.files) if args.files else []

    if args.file_list:
        with open(args.file_list) as f:
            pdf_paths.extend([line.strip() for line in f if line.strip()])

    if not pdf_paths:
        parser.error("No PDF files specified")

    # Verify files exist
    valid_paths = []
    for pdf in pdf_paths:
        path = pathlib.Path(pdf)
        if path.exists():
            valid_paths.append(str(path.absolute()))
        else:
            print(f"Warning: File not found: {pdf}", file=sys.stderr)

    if not valid_paths:
        print("Error: No valid PDF files found", file=sys.stderr)
        sys.exit(1)

    print(f"Submitting {len(valid_paths)} PDF files for processing...")
    print(f"Output directory: {args.output_dir}")
    print(f"Resolution: {args.resolution}")
    print(f"Format: {args.format}")
    print()

    # Submit tasks
    if args.use_batch_task:
        # Use batch coordination task
        result = process_pdf_batch.delay(
            pdf_paths=valid_paths,
            output_dir=args.output_dir,
            resolution=args.resolution,
            output_format=args.format,
            pages_per_chunk=args.pages_per_chunk,
        )
        print(f"Batch job submitted: {result.id}")
        task_ids = []  # Group tasks don't give us individual IDs easily

    else:
        # Submit individual tasks
        output_dir = pathlib.Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        task_ids = []
        for pdf_path in valid_paths:
            pdf = pathlib.Path(pdf_path)
            output_html = output_dir / f"{pdf.stem}.html"
            output_json = output_dir / f"{pdf.stem}.json"

            result = process_pdf.delay(
                pdf_path=str(pdf),
                output_html=str(output_html),
                output_json=str(output_json),
                output_format=args.format,
                resolution=args.resolution,
                pages_per_chunk=args.pages_per_chunk,
            )

            task_ids.append(result.id)
            print(f"✓ Submitted: {pdf.name} → Task {result.id}")

    print(f"\n✓ All {len(valid_paths)} tasks submitted!")
    print("\nTo check status:")
    print("  celery -A celery_config inspect active")
    print("  celery -A celery_config inspect reserved")

    # Monitor if requested
    if args.monitor and task_ids:
        monitor_tasks(task_ids)


if __name__ == '__main__':
    main()
