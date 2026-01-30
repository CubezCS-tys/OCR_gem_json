"""
Celery tasks for distributed PDF processing.

Each task processes ONE PDF file with parallel chunk processing.
Multiple tasks can run in parallel across Celery workers.
"""

from celery_config import app
from pdf_to_html import PDFProcessor, ProcessingConfig, MediaResolution
import pathlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


@app.task(bind=True, name='celery_tasks.process_pdf', max_retries=3)
def process_pdf(
    self,
    pdf_path: str,
    output_html: Optional[str] = None,
    output_json: Optional[str] = None,
    output_format: str = 'both',
    resolution: str = 'high',
    pages_per_chunk: int = 15,
    max_retries: int = 3,
) -> dict:
    """
    Process a single PDF file with parallel chunk processing.

    Args:
        pdf_path: Path to input PDF file
        output_html: Path to output HTML file (optional)
        output_json: Path to output JSON file (optional)
        output_format: 'html', 'json', or 'both'
        resolution: 'low', 'medium', or 'high'
        pages_per_chunk: Number of pages per chunk for parallel processing
        max_retries: Maximum retry attempts per chunk

    Returns:
        dict: Processing results with paths, stats, and timing
    """
    try:
        # Update task state (use string for JSON serialization)
        self.update_state(state='PROCESSING', meta={'pdf': str(pdf_path), 'status': 'Starting extraction'})

        # Setup paths
        pdf_path = pathlib.Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Auto-generate output paths if not provided
        if output_html is None and output_format in ['html', 'both']:
            output_html = pdf_path.with_suffix('.html')
        if output_json is None and output_format in ['json', 'both']:
            output_json = pdf_path.with_suffix('.json')

        # Create processor with configuration
        config = ProcessingConfig(
            output_format=output_format,
            media_resolution=MediaResolution(resolution),
            pages_per_chunk=pages_per_chunk,
            max_retries=max_retries,
        )
        processor = PDFProcessor(config)

        # Process PDF (chunks will be processed in parallel via ThreadPoolExecutor)
        logger.info(f"[Celery Task {self.request.id}] Processing {pdf_path}")
        self.update_state(state='PROCESSING', meta={'pdf': str(pdf_path), 'status': 'Extracting content'})

        try:
            result = processor.process(str(pdf_path), str(output_html))

            # Return success result
            doc = result.get('document')
            return {
                'status': 'success',
                'pdf_path': str(pdf_path),
                'output_html': result.get('html_path'),
                'output_json': result.get('json_path'),
                'pages': len(doc.pages) if doc else 0,
                'blocks': sum(len(p.blocks) for p in doc.pages) if doc else 0,
                'processing_time': result.get('processing_time', 0),
                'task_id': self.request.id,
            }
        finally:
            processor.cleanup()

    except Exception as e:
        logger.error(f"[Celery Task {self.request.id}] Failed to process {pdf_path}: {e}")

        # Retry with exponential backoff
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            return {
                'status': 'failed',
                'pdf_path': str(pdf_path),
                'error': str(e),
                'task_id': self.request.id,
            }


@app.task(name='celery_tasks.process_pdf_batch')
def process_pdf_batch(pdf_paths: list[str], output_dir: str, **kwargs) -> dict:
    """
    Submit a batch of PDF files for parallel processing.

    This is a coordination task that submits individual PDF tasks.
    Each PDF will be processed by a separate worker with parallel chunks.

    Args:
        pdf_paths: List of PDF file paths
        output_dir: Output directory for all files
        **kwargs: Additional arguments passed to process_pdf

    Returns:
        dict: Batch job info with task IDs
    """
    from celery import group

    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create tasks for each PDF
    tasks = []
    for pdf_path in pdf_paths:
        pdf_path = pathlib.Path(pdf_path)
        output_html = output_dir / f"{pdf_path.stem}.html"
        output_json = output_dir / f"{pdf_path.stem}.json"

        task = process_pdf.s(
            pdf_path=str(pdf_path),
            output_html=str(output_html),
            output_json=str(output_json),
            **kwargs
        )
        tasks.append(task)

    # Submit all tasks in parallel
    job = group(tasks)
    result = job.apply_async()

    return {
        'status': 'submitted',
        'total_files': len(pdf_paths),
        'group_id': result.id,
        'task_ids': [str(r.id) for r in result.results] if hasattr(result, 'results') else [],
    }
