"""
Submit PDFs for distributed processing with Celery.
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Optional
from tasks import process_pdf_task, rebuild_html_task, batch_process_directory, get_pdf_hash
from celery_config import PRIORITY_URGENT, PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW
from celery.result import AsyncResult


def submit_pdf(
    pdf_path: str,
    output_dir: str = ".",
    priority: int = PRIORITY_NORMAL,
    check_duplicate: bool = True,
    **kwargs
) -> dict:
    """
    Submit a single PDF for processing.
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Output directory
        priority: Task priority (0-9)
        check_duplicate: Check if PDF already processed
        **kwargs: Additional processing options
    
    Returns:
        dict with task_id and status
    """
    pdf_path = Path(pdf_path).resolve()
    
    if not pdf_path.exists():
        return {'error': f'PDF not found: {pdf_path}'}
    
    # Check for duplicates
    if check_duplicate:
        try:
            pdf_hash = get_pdf_hash(str(pdf_path))
            from tasks import get_cached_result
            cached = get_cached_result(pdf_hash)
            
            if cached:
                return {
                    'status': 'cached',
                    'pdf': pdf_path.name,
                    'pdf_hash': pdf_hash[:16],
                    'result': cached
                }
        except Exception as e:
            print(f"Warning: Could not check cache: {e}")
    
    # Submit task
    task = process_pdf_task.apply_async(
        args=[str(pdf_path)],
        kwargs={'output_dir': output_dir, **kwargs},
        priority=priority
    )
    
    return {
        'status': 'submitted',
        'task_id': task.id,
        'pdf': pdf_path.name,
        'priority': priority
    }


def submit_directory(
    pdf_directory: str,
    output_dir: str = ".",
    pattern: str = "*.pdf",
    priority: int = PRIORITY_NORMAL,
    check_duplicates: bool = True,
    **kwargs
) -> dict:
    """
    Submit all PDFs in a directory.
    
    Args:
        pdf_directory: Directory containing PDFs
        output_dir: Output directory
        pattern: Glob pattern for PDFs
        priority: Task priority
        check_duplicates: Check for duplicates
        **kwargs: Processing options
    
    Returns:
        dict with submitted tasks
    """
    pdf_dir = Path(pdf_directory).resolve()
    
    if not pdf_dir.is_dir():
        return {'error': f'Directory not found: {pdf_dir}'}
    
    pdf_files = sorted(pdf_dir.glob(pattern))
    
    if not pdf_files:
        return {'error': f'No PDFs found matching {pattern}'}
    
    print(f"Found {len(pdf_files)} PDFs in {pdf_dir}")
    
    results = []
    cached_count = 0
    submitted_count = 0
    
    for pdf_path in pdf_files:
        result = submit_pdf(
            str(pdf_path),
            output_dir=output_dir,
            priority=priority,
            check_duplicate=check_duplicates,
            **kwargs
        )
        
        if result.get('status') == 'cached':
            cached_count += 1
            print(f"✓ Cached: {pdf_path.name}")
        elif result.get('status') == 'submitted':
            submitted_count += 1
            print(f"→ Submitted: {pdf_path.name} (Task: {result['task_id'][:8]}...)")
        else:
            print(f"✗ Error: {pdf_path.name}")
        
        results.append(result)
    
    return {
        'total': len(pdf_files),
        'submitted': submitted_count,
        'cached': cached_count,
        'tasks': results
    }


def rebuild_html(
    json_path: str,
    output_path: Optional[str] = None,
    priority: int = PRIORITY_LOW
) -> dict:
    """
    Submit HTML rebuild task.
    
    Args:
        json_path: Path to JSON file
        output_path: Output HTML path
        priority: Task priority
    
    Returns:
        dict with task_id
    """
    json_path = Path(json_path).resolve()
    
    if not json_path.exists():
        return {'error': f'JSON not found: {json_path}'}
    
    task = rebuild_html_task.apply_async(
        args=[str(json_path)],
        kwargs={'output_path': output_path},
        priority=priority
    )
    
    return {
        'status': 'submitted',
        'task_id': task.id,
        'json': json_path.name
    }


def check_task_status(task_id: str) -> dict:
    """
    Check status of a submitted task.
    
    Args:
        task_id: Celery task ID
    
    Returns:
        dict with task status and result
    """
    task = AsyncResult(task_id)
    
    result = {
        'task_id': task_id,
        'state': task.state,
        'ready': task.ready(),
        'successful': task.successful(),
        'failed': task.failed()
    }
    
    if task.ready():
        if task.successful():
            result['result'] = task.result
        else:
            result['error'] = str(task.info)
    elif task.state == 'PROCESSING':
        result['info'] = task.info
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Submit PDFs for distributed processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit single PDF
  python submit_jobs.py my_document.pdf
  
  # Submit with high priority
  python submit_jobs.py important.pdf --priority high
  
  # Submit directory
  python submit_jobs.py --directory ./pdfs --output ./outputs
  
  # Check task status
  python submit_jobs.py --status 1a2b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
  
  # Rebuild HTML from JSON
  python submit_jobs.py --rebuild output.json
        """
    )
    
    parser.add_argument(
        'pdf_path',
        nargs='?',
        help='Path to PDF file'
    )
    
    parser.add_argument(
        '--directory', '-d',
        help='Process all PDFs in directory'
    )
    
    parser.add_argument(
        '--output', '-o',
        default='.',
        help='Output directory (default: current directory)'
    )
    
    parser.add_argument(
        '--pattern',
        default='*.pdf',
        help='Glob pattern for PDFs in directory (default: *.pdf)'
    )
    
    parser.add_argument(
        '--priority', '-p',
        choices=['urgent', 'high', 'normal', 'low'],
        default='normal',
        help='Task priority (default: normal)'
    )
    
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable result caching'
    )
    
    parser.add_argument(
        '--no-duplicate-check',
        action='store_true',
        help='Skip duplicate checking'
    )
    
    parser.add_argument(
        '--status', '-s',
        help='Check status of task ID'
    )
    
    parser.add_argument(
        '--rebuild', '-r',
        help='Rebuild HTML from JSON file'
    )
    
    parser.add_argument(
        '--format',
        choices=['html', 'json', 'both'],
        default='both',
        help='Output format (default: both)'
    )
    
    parser.add_argument(
        '--resolution',
        choices=['low', 'medium', 'high'],
        default='medium',
        help='Media resolution (default: medium)'
    )
    
    parser.add_argument(
        '--no-images',
        action='store_true',
        help='Skip image extraction'
    )
    
    args = parser.parse_args()
    
    # Map priority
    priority_map = {
        'urgent': PRIORITY_URGENT,
        'high': PRIORITY_HIGH,
        'normal': PRIORITY_NORMAL,
        'low': PRIORITY_LOW
    }
    priority = priority_map[args.priority]
    
    # Processing options
    proc_options = {
        'output_format': args.format,
        'media_resolution': args.resolution,
        'extract_images': not args.no_images,
        'use_cache': not args.no_cache
    }
    
    # Check status
    if args.status:
        print(f"Checking task status: {args.status}")
        status = check_task_status(args.status)
        
        print(f"\nState: {status['state']}")
        print(f"Ready: {status['ready']}")
        
        if status['ready']:
            if status['successful']:
                result = status['result']
                print(f"\n✓ Success!")
                if 'html_path' in result:
                    print(f"  HTML: {result['html_path']}")
                if 'json_path' in result:
                    print(f"  JSON: {result['json_path']}")
                if 'pages' in result:
                    print(f"  Pages: {result['pages']}")
                if 'processing_time' in result:
                    print(f"  Time: {result['processing_time']:.1f}s")
                if 'cost' in result:
                    cost = result['cost']
                    print(f"  Cost: ${cost['total_cost_usd']:.6f}")
                    print(f"    Input: {cost['input_tokens']:,} tokens (${cost['input_cost_usd']:.6f})")
                    print(f"    Output: {cost['output_tokens']:,} tokens (${cost['output_cost_usd']:.6f})")
                if result.get('cached'):
                    print(f"  (from cache - no API cost)")
            else:
                print(f"\n✗ Failed: {status.get('error', 'Unknown error')}")
        elif status['state'] == 'PROCESSING':
            print(f"  {status.get('info', {}).get('status', 'Processing...')}")
        
        return 0
    
    # Rebuild HTML
    if args.rebuild:
        print(f"Submitting HTML rebuild: {args.rebuild}")
        result = rebuild_html(args.rebuild, priority=priority)
        
        if 'error' in result:
            print(f"✗ Error: {result['error']}")
            return 1
        
        print(f"✓ Submitted: Task {result['task_id'][:16]}...")
        print(f"\nCheck status with:")
        print(f"  python submit_jobs.py --status {result['task_id']}")
        return 0
    
    # Process directory
    if args.directory:
        print(f"Processing directory: {args.directory}")
        result = submit_directory(
            args.directory,
            output_dir=args.output,
            pattern=args.pattern,
            priority=priority,
            check_duplicates=not args.no_duplicate_check,
            **proc_options
        )
        
        if 'error' in result:
            print(f"✗ Error: {result['error']}")
            return 1
        
        print(f"\n{'='*50}")
        print(f"Total PDFs: {result['total']}")
        print(f"Submitted: {result['submitted']}")
        print(f"Cached: {result['cached']}")
        print(f"{'='*50}")
        
        return 0
    
    # Process single PDF
    if args.pdf_path:
        print(f"Submitting PDF: {args.pdf_path}")
        result = submit_pdf(
            args.pdf_path,
            output_dir=args.output,
            priority=priority,
            check_duplicate=not args.no_duplicate_check,
            **proc_options
        )
        
        if 'error' in result:
            print(f"✗ Error: {result['error']}")
            return 1
        
        if result['status'] == 'cached':
            print(f"✓ Using cached result (hash: {result['pdf_hash']})")
            cached = result['result']
            if 'html_path' in cached:
                print(f"  HTML: {cached['html_path']}")
            if 'json_path' in cached:
                print(f"  JSON: {cached['json_path']}")
            return 0
        
        print(f"✓ Submitted: Task {result['task_id'][:16]}...")
        print(f"  Priority: {args.priority}")
        print(f"\nCheck status with:")
        print(f"  python submit_jobs.py --status {result['task_id']}")
        return 0
    
    # No action specified
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
