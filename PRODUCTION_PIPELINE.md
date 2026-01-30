# Production Pipeline Guide: PDF to HTML/JSON Extraction

Complete guide for running the production PDF extraction pipeline with parallel processing at scale.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Quick Start](#quick-start)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Running the Pipeline](#running-the-pipeline)
6. [Monitoring & Management](#monitoring--management)
7. [Performance Tuning](#performance-tuning)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)
10. [Architecture](#architecture)

---

## System Overview

### What This Pipeline Does

Converts PDF documents to structured HTML and JSON using Google's Gemini AI, with:
- **Nested parallelism**: Multiple PDFs + parallel chunk processing per PDF
- **High accuracy**: Polymorphic schema with discriminated unions
- **Production features**: Retry logic, validation, monitoring, error handling
- **Scalability**: Distributed processing via Celery + Redis

### Key Features

- ✅ **Parallel Processing**
  - File-level: Multiple PDFs processed simultaneously via Celery workers
  - Chunk-level: Each PDF's pages processed in parallel via ThreadPoolExecutor
  
- ✅ **Structured Output**
  - Polymorphic content blocks (heading, paragraph, list, table, equation, image, code, quote, footnote)
  - Inline formatting via Span objects (bold, italic, underline, links)
  - Multi-column layout detection with reading order preservation
  - Bounding box coordinates for layout fidelity
  
- ✅ **Production Ready**
  - Automatic retries with exponential backoff
  - Task monitoring and status tracking
  - Error recovery and validation
  - Resource cleanup and memory management

### System Requirements

- **Python**: 3.10+
- **Redis**: 5.0+ (for task queue)
- **RAM**: ~1GB per PDF being processed
- **API**: Google Gemini API key (set in `.env`)

---

## Quick Start

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure API key
echo "GEMINI_API_KEY=your_api_key_here" > .env

# 3. Start Redis
redis-server &

# 4. Start Celery workers (in separate terminal)
# NOTE: tasks are not auto-discovered; include celery_tasks and listen on pdf_processing
python -m celery -A celery_config worker --loglevel=info --concurrency=2 --queue=pdf_processing --include=celery_tasks

# 5. Process PDFs
python submit_batch.py pdfs/*.pdf --output-dir output/ --monitor
```

---

## Installation

### Step 1: Clone and Setup Environment

```bash
cd /path/to/OCR_gem_json
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

**Core dependencies:**
- `google-genai` - Google Gemini API client
- `celery[redis]` - Distributed task processing
- `redis` - Message broker
- `pymupdf` - PDF parsing and image extraction
- `pydantic` - Schema validation

### Step 3: Configure API Access

Create a `.env` file:

```bash
# Required
GEMINI_API_KEY=your_google_api_key_here

# Optional (defaults shown)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

**Get API key:**
- Go to https://aistudio.google.com/app/apikey
- Create new API key
- Copy to `.env` file

### Step 4: Verify Installation

```bash
python test_celery_setup.py
```

Expected output:
```
✓ Celery config imported
✓ PDF processing classes imported
✓ Celery tasks imported
✓ Redis connection successful
```

---

## Configuration

### Processing Configuration

Edit `pdf_to_html.py` line 66+ to adjust defaults:

```python
class ProcessingConfig:
    output_format: str = "both"          # "html", "json", or "both"
    media_resolution: MediaResolution = MediaResolution.HIGH
    pages_per_chunk: int = 15            # Pages per parallel chunk
    max_retries: int = 3                 # Retry attempts per chunk
    retry_delay: float = 2.0             # Seconds between retries
    max_tokens: int = 8192               # Max output tokens per request
```

### Celery Configuration

Edit `celery_config.py` for worker settings:

```python
app.conf.update(
    worker_prefetch_multiplier=1,         # Tasks to fetch ahead
    task_acks_late=True,                  # Ack after completion
    worker_max_tasks_per_child=10,        # Restart after N tasks
    result_expires=3600,                  # Results expire after 1 hour
    task_default_rate_limit='10/m',       # Rate limiting
)
```

### Redis Configuration

For production, configure Redis persistence and memory limits:

```bash
# /etc/redis/redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
```

---

## Running the Pipeline

### Method 1: Single File Processing

Process one PDF directly:

```bash
source venv/bin/activate
python pdf_to_html.py input.pdf output.html -f both -j -r high
```

**Options:**
- `-f, --format`: Output format (html, json, both)
- `-j, --json`: Also output JSON structure
- `-r, --resolution`: Processing resolution (low, medium, high)
- `--pages-per-chunk`: Pages per chunk for parallel processing
- `--max-retries`: Maximum retry attempts

### Method 2: Batch Processing (Recommended)

For multiple PDFs, use distributed processing:

#### Step 1: Start Redis

```bash
# Option A: Foreground (for debugging)
redis-server

# Option B: Background (for production)
redis-server --daemonize yes

# Verify
redis-cli ping  # Should return "PONG"
```

#### Step 2: Start Celery Workers

Open separate terminals for each worker:

```bash
# Terminal 1: Worker 1
source venv/bin/activate
python -m celery -A celery_config worker \
    --loglevel=info \
    --concurrency=2 \
    --queue=pdf_processing \
    --hostname=worker1@%h \
    --include=celery_tasks

# Terminal 2: Worker 2 (optional)
source venv/bin/activate
python -m celery -A celery_config worker \
    --loglevel=info \
    --concurrency=2 \
    --queue=pdf_processing \
    --hostname=worker2@%h \
    --include=celery_tasks

# Terminal 3: Worker 3 (optional)
source venv/bin/activate
python -m celery -A celery_config worker \
    --loglevel=info \
    --concurrency=2 \
    --queue=pdf_processing \
    --hostname=worker3@%h \
    --include=celery_tasks
```

**Worker parameters:**
- `--concurrency=N`: Number of concurrent tasks per worker
- `--queue`: Task queue to subscribe to
- `--hostname`: Unique worker name (important for multiple workers)
- `--loglevel`: Logging verbosity (debug, info, warning, error)

#### Step 3: Submit PDF Batch

```bash
source venv/bin/activate

# Process all PDFs in directory
python submit_batch.py pdfs/*.pdf --output-dir output/

# With live monitoring
python submit_batch.py pdfs/*.pdf --output-dir output/ --monitor

# From file list
python submit_batch.py --file-list batch.txt --output-dir output/

# Custom settings
python submit_batch.py pdfs/*.pdf \
    --output-dir output/ \
    --resolution high \
    --format both \
    --pages-per-chunk 20 \
    --monitor
```

**Batch options:**
- `--output-dir, -o`: Output directory (required)
- `--resolution, -r`: Processing resolution (low, medium, high)
- `--format, -f`: Output format (html, json, both)
- `--pages-per-chunk`: Pages per parallel chunk
- `--monitor, -m`: Live progress monitoring
- `--file-list`: Text file with PDF paths (one per line)

### Method 3: Programmatic API

Use Python API directly:

```python
from pdf_to_html import PDFProcessor, ProcessingConfig, MediaResolution

# Configure
config = ProcessingConfig(
    output_format="both",
    media_resolution=MediaResolution.HIGH,
    pages_per_chunk=15,
    max_retries=3
)

# Process
processor = PDFProcessor(config)
try:
    result = processor.process("input.pdf", "output.html")
    
    if result["success"]:
        print(f"HTML: {result['html_path']}")
        print(f"JSON: {result['json_path']}")
        print(f"Pages: {len(result['document'].pages)}")
    else:
        print(f"Error: {result['error']}")
finally:
    processor.cleanup()
```

---

## Monitoring & Management

### Check Worker Status

```bash
# Active tasks
celery -A celery_config inspect active

# Queued tasks
celery -A celery_config inspect reserved

# Worker stats
celery -A celery_config inspect stats

# Registered tasks
celery -A celery_config inspect registered
```

### Web-based Monitoring (Flower)

```bash
# Install
pip install flower

# Start Flower
celery -A celery_config flower

# Open browser
# http://localhost:5555
```

**Flower features:**
- Real-time task monitoring
- Worker management
- Task history and statistics
- Resource usage graphs
- Task retry controls

### Check Task Results

```python
from celery.result import AsyncResult

# Get task result
result = AsyncResult('task-id-here')

print(f"State: {result.state}")
print(f"Result: {result.result}")
print(f"Info: {result.info}")
```

### Log Files

Worker logs show detailed progress:

```bash
# View live logs
tail -f celery_worker.log

# Search for errors
grep ERROR celery_worker.log

# Filter by task ID
grep "task-id-here" celery_worker.log
```

### Task Management

```bash
# Purge all pending tasks (WARNING: destructive)
celery -A celery_config purge

# Revoke specific task
celery -A celery_config control revoke task-id-here

# Shutdown workers gracefully
celery -A celery_config control shutdown

# Restart worker pool
celery -A celery_config control pool_restart
```

---

## Performance Tuning

### Optimize Worker Count

**Formula**: `Total Parallel PDFs = Workers × Concurrency`

Examples:
- **Small scale**: 2 workers × concurrency=2 = 4 PDFs in parallel
- **Medium scale**: 4 workers × concurrency=3 = 12 PDFs in parallel
- **Large scale**: 8 workers × concurrency=4 = 32 PDFs in parallel

**Resource constraints:**
- Each PDF uses ~500MB-1GB RAM during processing
- Each concurrent task makes parallel API calls
- Monitor system resources and adjust accordingly

```bash
# Monitor system resources
htop
watch -n 1 free -h
```

### Optimize Chunk Size

**Smaller chunks** (5-10 pages):
- ✅ More parallelism within each PDF
- ✅ Better for large documents
- ❌ More API calls = higher cost
- ❌ More overhead

**Larger chunks** (15-30 pages):
- ✅ Fewer API calls = lower cost
- ✅ Less overhead
- ❌ Less parallelism
- ❌ Higher memory usage per chunk

**Recommendation**: 15 pages per chunk (default)

### API Rate Limiting

Adjust in `celery_config.py`:

```python
app.conf.update(
    task_default_rate_limit='10/m',  # 10 tasks per minute
)
```

Or per-task:

```python
@app.task(rate_limit='5/m')  # 5 per minute
def process_pdf(...):
    ...
```

### Redis Optimization

For high-throughput processing:

```bash
# Increase max connections
maxclients 10000

# Use faster serialization
# In celery_config.py:
task_serializer = 'msgpack'
result_serializer = 'msgpack'
accept_content = ['msgpack']

# Install msgpack
pip install msgpack
```

---

## Troubleshooting

### Common Issues

#### 1. "Connection refused" (Redis)

**Symptom**: `Error 111 connecting to localhost:6379`

**Solution**:
```bash
# Start Redis
redis-server

# Or in background
redis-server --daemonize yes

# Verify
redis-cli ping
```

#### 2. "No module named 'celery'"

**Symptom**: Import errors when running scripts

**Solution**:
```bash
# Activate virtualenv
source venv/bin/activate

# Reinstall
pip install celery redis
```

#### 3. Tasks stuck in "PENDING"

**Symptom**: Tasks never start processing

**Solution**:
```bash
# Check if workers are running
celery -A celery_config inspect active

# Start workers if not running
python -m celery -A celery_config worker --loglevel=info --queue=pdf_processing --include=celery_tasks

# Check queue routing
celery -A celery_config inspect registered
# If registered tasks are 0, restart workers with --include=celery_tasks
```

#### 4. "Validation errors" in output

**Symptom**: Schema validation failures

**Solution**: Already fixed! Schema, prompts, and discriminators are now aligned.

Verify with:
```bash
grep "type='heading'" pdf_to_html.py
# Should show lowercase discriminators
```

#### 5. Out of memory

**Symptom**: Worker crashes or system freezes

**Solution**:
```bash
# Reduce worker concurrency
python -m celery -A celery_config worker --concurrency=1 --queue=pdf_processing --include=celery_tasks

# Reduce chunk size
python submit_batch.py ... --pages-per-chunk 10

# Add worker memory limits
python -m celery -A celery_config worker --max-memory-per-child=2000000 --queue=pdf_processing --include=celery_tasks  # 2GB
```

#### 6. API rate limit errors

**Symptom**: "429 Too Many Requests"

**Solution**:
```bash
# Reduce rate limit in celery_config.py
task_default_rate_limit = '5/m'

# Or reduce worker count
```

### Debug Mode

Enable detailed logging:

```bash
# Worker debug mode
python -m celery -A celery_config worker --loglevel=debug --queue=pdf_processing --include=celery_tasks

# Python logging
export PYTHONUNBUFFERED=1
python submit_batch.py ... 2>&1 | tee debug.log
```

### Health Checks

```bash
# Redis health
redis-cli ping
redis-cli info stats

# Worker health
celery -A celery_config inspect ping

# Task queue depth
celery -A celery_config inspect reserved | wc -l
```

---

## Best Practices

### Production Deployment

1. **Use systemd for workers**

Create `/etc/systemd/system/celery-worker@.service`:

```ini
[Unit]
Description=Celery Worker %i
After=network.target redis.target

[Service]
Type=forking
User=celery
Group=celery
WorkingDirectory=/path/to/OCR_gem_json
Environment=PATH=/path/to/venv/bin
ExecStart=/path/to/venv/bin/celery -A celery_config worker \
    --loglevel=info \
    --concurrency=2 \
    --hostname=worker%i@%%h \
    --queue=pdf_processing \
    --include=celery_tasks \
    --logfile=/var/log/celery/worker%i.log \
    --pidfile=/var/run/celery/worker%i.pid
ExecStop=/path/to/venv/bin/celery -A celery_config control shutdown
Restart=always

[Install]
WantedBy=multi-user.target
```

Start workers:
```bash
sudo systemctl start celery-worker@{1..4}
sudo systemctl enable celery-worker@{1..4}
```

2. **Use supervisor for process management**

```ini
[program:celery_worker]
command=/path/to/venv/bin/celery -A celery_config worker --loglevel=info --queue=pdf_processing --include=celery_tasks
directory=/path/to/OCR_gem_json
user=celery
numprocs=4
process_name=%(program_name)s_%(process_num)02d
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=600
```

3. **Set up log rotation**

```bash
# /etc/logrotate.d/celery
/var/log/celery/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    missingok
    copytruncate
}
```

### Error Handling

Always use try-finally for cleanup:

```python
processor = PDFProcessor(config)
try:
    result = processor.process(pdf_path, output_path)
finally:
    processor.cleanup()  # Always cleanup uploaded files
```

### Resource Management

```python
# Limit worker memory
python -m celery -A celery_config worker --max-memory-per-child=2000000 --queue=pdf_processing --include=celery_tasks

# Restart workers periodically
python -m celery -A celery_config worker --max-tasks-per-child=10 --queue=pdf_processing --include=celery_tasks

# Monitor memory usage
watch -n 1 'ps aux | grep celery'
```

### Batch Processing Strategy

For large batches (100+ PDFs):

```bash
# Split into smaller batches
find pdfs/ -name "*.pdf" | split -l 50 - batch_

# Process each batch
for batch in batch_*; do
    python submit_batch.py --file-list $batch --output-dir output/
    sleep 60  # Rate limiting between batches
done
```

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   User / CLI                            │
│              submit_batch.py                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  Celery Tasks                           │
│              celery_tasks.py                            │
│  ┌──────────────────────────────────────────────────┐   │
│  │  process_pdf(pdf_path, ...)                      │   │
│  │  process_pdf_batch([pdf_paths], ...)            │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Redis Task Queue                           │
│         (Message Broker + Result Backend)               │
└──┬──────────────┬──────────────┬──────────────┬────────┘
   │              │              │              │
   ▼              ▼              ▼              ▼
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│Worker 1│   │Worker 2│   │Worker 3│   │Worker 4│
└───┬────┘   └───┬────┘   └───┬────┘   └───┬────┘
    │            │            │            │
    ▼            ▼            ▼            ▼
┌──────────────────────────────────────────────────┐
│         PDFProcessor (pdf_to_html.py)            │
│  ┌────────────────────────────────────────────┐  │
│  │  1. Upload PDF to Gemini API              │  │
│  │  2. Extract metadata & page count         │  │
│  │  3. Split into chunks                     │  │
│  │  4. Process chunks IN PARALLEL ────────┐  │  │
│  │     (ThreadPoolExecutor)               │  │  │
│  └────────────────────────────────────────┼──┘  │
└───────────────────────────────────────────┼─────┘
                                            │
        ┌───────────────┬───────────────┬───┴─────┬────────────┐
        ▼               ▼               ▼         ▼            ▼
    ┌────────┐      ┌────────┐      ┌────────┐  ...      ┌────────┐
    │Chunk 1 │      │Chunk 2 │      │Chunk 3 │           │Chunk N │
    │Pages   │      │Pages   │      │Pages   │           │Pages   │
    │1-15    │      │16-30   │      │31-35   │           │...     │
    └───┬────┘      └───┬────┘      └───┬────┘           └───┬────┘
        │               │               │                    │
        └───────────────┴───────────────┴────────────────────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │  Gemini API          │
                    │  (Parallel Requests) │
                    └──────────────────────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │  Merge Results       │
                    │  Validate Schema     │
                    │  Render HTML         │
                    │  Export JSON         │
                    └──────────────────────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │  output.html         │
                    │  output.json         │
                    └──────────────────────┘
```

### Nested Parallelism

**Level 1 - File Parallelism (Celery Workers)**:
- Multiple workers process different PDFs simultaneously
- Each worker is independent and can run on different machines
- Task distribution via Redis queue

**Level 2 - Chunk Parallelism (ThreadPoolExecutor)**:
- Within each PDF, pages split into chunks
- All chunks of a PDF processed in parallel
- ThreadPoolExecutor manages concurrent API calls

**Example with 4 workers, concurrency=2, 15 pages/chunk**:
- Processing 100 PDFs with 35 pages each
- 8 PDFs in parallel at file level (4 workers × 2 concurrency)
- Each PDF: 3 chunks (1-15, 16-30, 31-35) processed in parallel
- Total: 8 PDFs × 3 chunks = 24 concurrent API calls

### Data Flow

```
PDF File → Upload → Metadata → Split into Chunks
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
                 Chunk 1           Chunk 2           Chunk 3
                    │                 │                 │
                    ▼                 ▼                 ▼
              Gemini API        Gemini API        Gemini API
                    │                 │                 │
                    ▼                 ▼                 ▼
            JSON Response      JSON Response      JSON Response
            (Pages 1-15)       (Pages 16-30)      (Pages 31-35)
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      ▼
                            Pydantic Validation
                         (Discriminated Unions)
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
              HTML Renderer                       JSON Export
                    │                                   │
                    ▼                                   ▼
              output.html                         output.json
```

### Schema Architecture

**Polymorphic Content Blocks** (Discriminated Union):

```python
ContentBlock = Annotated[
    Union[
        HeadingBlock,      # type="heading"
        ParagraphBlock,    # type="paragraph"
        ListBlock,         # type="list"
        TableBlock,        # type="table"
        EquationBlock,     # type="equation"
        ImageBlock,        # type="image"
        CodeBlock,         # type="code"
        QuoteBlock,        # type="quote"
        FootnoteBlock,     # type="footnote"
    ],
    Field(discriminator='type')
]
```

Each block type has:
- **Required**: `type` (discriminator), `bbox_*` (layout coordinates)
- **Type-specific**: Fields relevant only to that content type
- **Optional**: Styling metadata (font, color, alignment)

---

## Cost Estimation

### Gemini API Pricing

- **Input tokens**: ~$0.075 per 1M tokens
- **Output tokens**: ~$0.30 per 1M tokens

### Typical Costs per PDF

**Small PDF** (10 pages, mostly text):
- Input: ~50K tokens
- Output: ~20K tokens  
- Cost: ~$0.01

**Medium PDF** (35 pages, mixed content):
- Input: ~150K tokens
- Output: ~60K tokens
- Cost: ~$0.03

**Large PDF** (100 pages, complex):
- Input: ~400K tokens
- Output: ~150K tokens
- Cost: ~$0.08

### Batch Processing Example

1000 PDFs × $0.03 average = **~$30 total**

**With context caching** (90% savings after first chunk):
1000 PDFs × $0.015 average = **~$15 total**

---

## Security Considerations

1. **API Key Protection**
   - Store in `.env` file (not in code)
   - Add `.env` to `.gitignore`
   - Use environment variables in production

2. **File Access**
   - Validate PDF file paths
   - Sanitize output filenames
   - Use temporary directories for processing

3. **Redis Security**
   - Use authentication: `requirepass` in redis.conf
   - Bind to localhost only (not 0.0.0.0)
   - Use SSL/TLS for remote connections

4. **Worker Isolation**
   - Run workers as non-root user
   - Use separate virtualenvs per worker
   - Limit worker resource usage (memory, CPU)

---

## Support & Resources

### Documentation
- **This guide**: `PRODUCTION_PIPELINE.md`
- **Celery setup**: `README_CELERY.md`
- **API reference**: See docstrings in `pdf_to_html.py`

### Testing
- **Setup verification**: `python test_celery_setup.py`
- **Single file test**: `python pdf_to_html.py test.pdf -f both`

### Logs
- **Worker logs**: Check terminal where worker is running
- **Redis logs**: `/var/log/redis/redis-server.log`
- **Application logs**: `extraction.log` in output directory

### Getting Help
- Check [Troubleshooting](#troubleshooting) section
- Review worker logs for error messages
- Test with single file first before batch processing

---

## Changelog

### v2.0 - Parallel Processing
- ✅ Added Celery + Redis distributed processing
- ✅ Implemented nested parallelism (files + chunks)
- ✅ Fixed schema discriminator alignment
- ✅ Added batch submission tools

### v1.0 - Initial Release
- ✅ PDF to HTML/JSON conversion
- ✅ Polymorphic schema with Pydantic
- ✅ Multi-column layout detection
- ✅ Inline formatting support

---

**Ready to process PDFs at scale! 🚀**
