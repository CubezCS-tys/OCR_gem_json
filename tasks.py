"""
Celery tasks for distributed PDF processing.
"""

import os
import hashlib
import json
import time
from pathlib import Path
from celery import Task
from celery.utils.log import get_task_logger
from celery_config import app, PRIORITY_NORMAL
from llm_pipelines.pdf_to_html import (
    PDFProcessor,
    ProcessingConfig,
    MediaResolution,
    DocumentStructure,
    HTMLRenderer,
)

# Gemini 2.5 Flash pricing (as of January 2026)
# https://ai.google.dev/pricing
GEMINI_INPUT_COST_PER_1M = 0.50  # $0.50 per 1M input tokens
GEMINI_OUTPUT_COST_PER_1M = 3.00  # $3.00 per 1M output tokens (includes thinking)

logger = get_task_logger(__name__)


def calculate_cost(input_tokens: int, output_tokens: int) -> dict:
    """
    Calculate actual cost from token usage.
    
    Args:
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens used
    
    Returns:
        dict with cost breakdown
    """
    input_cost = (input_tokens / 1_000_000) * GEMINI_INPUT_COST_PER_1M
    output_cost = (output_tokens / 1_000_000) * GEMINI_OUTPUT_COST_PER_1M
    total_cost = input_cost + output_cost
    
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
        'input_cost_usd': round(input_cost, 6),
        'output_cost_usd': round(output_cost, 6),
        'total_cost_usd': round(total_cost, 6)
    }


def get_pdf_hash(pdf_path: str) -> str:
    """
    Calculate SHA256 hash of PDF file for deduplication.
    
    Args:
        pdf_path: Path to PDF file
    
    Returns:
        Hex digest of file hash
    """
    sha256_hash = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        # Read in chunks for large files
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_cached_result(pdf_hash: str) -> dict:
    """
    Check if PDF has been processed before.
    
    Args:
        pdf_hash: Hash of PDF file
    
    Returns:
        Cached result dict or None
    """
    from redis import Redis
    redis_client = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        password=os.getenv('REDIS_PASSWORD'),
        decode_responses=True
    )
    
    cache_key = f"pdf_result:{pdf_hash}"
    cached = redis_client.get(cache_key)
    
    if cached:
        logger.info(f"Cache hit for PDF hash {pdf_hash[:16]}...")
        return json.loads(cached)
    
    return None


def cache_result(pdf_hash: str, result: dict, ttl: int = 3600 * 24 * 7):
    """
    Cache processing result for future requests.
    
    Args:
        pdf_hash: Hash of PDF file
        result: Processing result dict
        ttl: Time to live in seconds (default 7 days)
    """
    from redis import Redis
    redis_client = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        password=os.getenv('REDIS_PASSWORD'),
        decode_responses=True
    )
    
    cache_key = f"pdf_result:{pdf_hash}"
    redis_client.setex(cache_key, ttl, json.dumps(result))
    logger.info(f"Cached result for PDF hash {pdf_hash[:16]}...")


class CallbackTask(Task):
    """Base task with callbacks for monitoring."""
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        logger.info(f"Task {task_id} succeeded: {retval.get('html_path', 'N/A')}")
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        logger.error(f"Task {task_id} failed: {exc}")
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried."""
        logger.warning(f"Task {task_id} retrying: {exc}")


@app.task(bind=True, base=CallbackTask, name='tasks.process_pdf_task')
def process_pdf_task(
    self,
    pdf_path: str,
    output_dir: str = ".",
    output_format: str = "both",
    media_resolution: str = "medium",
    extract_images: bool = True,
    image_dpi: int = 150,
    use_cache: bool = True,
    **kwargs
):
    """
    Process a PDF file to HTML/JSON using Gemini API.
    
    Args:
        pdf_path: Path to input PDF
        output_dir: Output directory for results
        output_format: 'html', 'json', or 'both'
        media_resolution: 'low', 'medium', or 'high'
        extract_images: Whether to extract images
        image_dpi: DPI for image extraction
        use_cache: Use cached results if available
        **kwargs: Additional config options
    
    Returns:
        dict with processing results
    """
    start_time = time.time()
    pdf_path = Path(pdf_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Processing PDF: {pdf_path.name}")
    
    # Calculate PDF hash for deduplication
    try:
        pdf_hash = get_pdf_hash(str(pdf_path))
        logger.info(f"PDF hash: {pdf_hash[:16]}...")
        
        # Check cache
        if use_cache:
            cached_result = get_cached_result(pdf_hash)
            if cached_result:
                logger.info(f"Using cached result for {pdf_path.name}")
                cached_result['cached'] = True
                cached_result['cache_age_seconds'] = time.time() - cached_result.get('timestamp', start_time)
                return cached_result
    except Exception as e:
        logger.warning(f"Failed to check cache: {e}")
        pdf_hash = None
    
    # Update task state
    self.update_state(
        state='PROCESSING',
        meta={'pdf': str(pdf_path), 'status': 'Uploading to Gemini...'}
    )
    
    # Configure processor
    config = ProcessingConfig(
        media_resolution=MediaResolution(media_resolution),
        output_format=output_format,
        extract_images=extract_images,
        image_dpi=image_dpi,
        use_chunked_processing=True,
        **kwargs
    )
    
    # Process PDF
    try:
        processor = PDFProcessor(config)
        
        # Determine output path
        output_base = output_dir / pdf_path.stem
        
        result = processor.process(str(pdf_path), str(output_base))
        
        if not result['success']:
            raise RuntimeError(result.get('error', 'Processing failed'))
        
        # Calculate actual cost from token usage (if available)
        cost_info = None
        if 'usage_metadata' in result:
            usage = result['usage_metadata']
            cost_info = calculate_cost(
                usage.get('total_input_tokens', 0),
                usage.get('total_output_tokens', 0)
            )
            logger.info(f"Cost: ${cost_info['total_cost_usd']:.6f} (tokens: {cost_info['total_tokens']:,})")
        
        # Add metadata
        result['pdf_hash'] = pdf_hash
        result['pdf_name'] = pdf_path.name
        result['processing_time'] = time.time() - start_time
        result['timestamp'] = start_time
        result['worker'] = self.request.hostname
        result['cached'] = False
        if cost_info:
            result['cost'] = cost_info
        
        # Cache result
        if pdf_hash and use_cache:
            try:
                cache_result(pdf_hash, result)
            except Exception as e:
                logger.warning(f"Failed to cache result: {e}")
        
        logger.info(f"Successfully processed {pdf_path.name} in {result['processing_time']:.1f}s")
        return result
        
    except Exception as e:
        logger.error(f"Failed to process {pdf_path.name}: {e}")
        raise
    
    finally:
        # Cleanup
        if 'processor' in locals():
            processor.cleanup()


@app.task(bind=True, base=CallbackTask, name='tasks.rebuild_html_task')
def rebuild_html_task(
    self,
    json_path: str,
    output_path: str = None,
    pdf_path: str = None,
    extract_images: bool = False,
    image_dpi: int = 150
):
    """
    Rebuild HTML from JSON without API calls.
    
    Args:
        json_path: Path to JSON file
        output_path: Output HTML path
        pdf_path: Original PDF (for image extraction)
        extract_images: Re-extract images
        image_dpi: DPI for images
    
    Returns:
        dict with rebuild results
    """
    start_time = time.time()
    json_path = Path(json_path)
    
    logger.info(f"Rebuilding HTML from: {json_path.name}")
    
    self.update_state(
        state='PROCESSING',
        meta={'json': str(json_path), 'status': 'Loading JSON...'}
    )
    
    try:
        # Load JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        doc = DocumentStructure.model_validate(json_data)
        
        # Extract images if requested
        if extract_images and pdf_path:
            from llm_pipelines.pdf_to_html import ImageExtractor, HAS_PYMUPDF
            
            if HAS_PYMUPDF:
                self.update_state(
                    state='PROCESSING',
                    meta={'json': str(json_path), 'status': 'Extracting images...'}
                )
                
                with ImageExtractor(str(pdf_path), dpi=image_dpi) as extractor:
                    doc = extractor.extract_images_for_document(doc)
        
        # Render HTML
        self.update_state(
            state='PROCESSING',
            meta={'json': str(json_path), 'status': 'Rendering HTML...'}
        )
        
        html_content = HTMLRenderer.render(doc)
        
        # Write output
        if not output_path:
            output_path = json_path.with_suffix('.html')
        else:
            output_path = Path(output_path)
        
        output_path.write_text(html_content, encoding='utf-8')
        
        result = {
            'success': True,
            'html_path': str(output_path),
            'json_path': str(json_path),
            'pages': len(doc.pages),
            'processing_time': time.time() - start_time,
            'worker': self.request.hostname
        }
        
        logger.info(f"Successfully rebuilt HTML in {result['processing_time']:.1f}s")
        return result
        
    except Exception as e:
        logger.error(f"Failed to rebuild HTML from {json_path.name}: {e}")
        raise


@app.task(name='tasks.batch_process_directory')
def batch_process_directory(
    pdf_directory: str,
    output_dir: str = ".",
    pattern: str = "*.pdf",
    priority: int = PRIORITY_NORMAL,
    **kwargs
):
    """
    Submit all PDFs in a directory for processing.
    
    Args:
        pdf_directory: Directory containing PDFs
        output_dir: Output directory
        pattern: Glob pattern for PDF files
        priority: Task priority (0-9)
        **kwargs: Options passed to process_pdf_task
    
    Returns:
        dict with submitted task IDs
    """
    pdf_dir = Path(pdf_directory)
    pdf_files = list(pdf_dir.glob(pattern))
    
    logger.info(f"Found {len(pdf_files)} PDFs in {pdf_directory}")
    
    tasks = []
    for pdf_path in pdf_files:
        task = process_pdf_task.apply_async(
            args=[str(pdf_path)],
            kwargs={'output_dir': output_dir, **kwargs},
            priority=priority
        )
        tasks.append({
            'task_id': task.id,
            'pdf': pdf_path.name
        })
    
    return {
        'submitted': len(tasks),
        'tasks': tasks,
        'directory': str(pdf_dir)
    }
