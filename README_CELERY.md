# Distributed PDF Processing with Celery + Redis

This setup gives you **nested parallelism**:
- **File-level**: Multiple Celery workers processing different PDFs in parallel
- **Chunk-level**: Each PDF's chunks processed in parallel via ThreadPoolExecutor

## Architecture

```
Multiple PDFs → Celery Queue (Redis) → Multiple Workers
                                          ↓
                              Each Worker processes 1 PDF
                                          ↓
                         ThreadPoolExecutor processes chunks in parallel
```

## Setup

### 1. Install Celery
```bash
source venv/bin/activate
pip install celery redis
```

### 2. Configure Redis (if needed)
```bash
# Check if Redis is running
redis-cli ping  # Should return "PONG"

# If not running, start it
redis-server
```

### 3. Set environment variables (optional)
```bash
# .env file
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

## Usage

### Start Celery Workers
Workers must import `celery_tasks` (tasks are not auto-discovered).

```bash
# Terminal 1: Start first worker
python -m celery -A celery_config worker --loglevel=info --concurrency=2 --queue=pdf_processing --include=celery_tasks

# Terminal 2: Start second worker (optional, for more parallelism)
python -m celery -A celery_config worker --loglevel=info --concurrency=2 --queue=pdf_processing --include=celery_tasks

# Terminal 3: Start third worker (optional)
python -m celery -A celery_config worker --loglevel=info --concurrency=2 --queue=pdf_processing --include=celery_tasks
```

**Worker settings**:
- `--concurrency=2`: Each worker handles 2 PDFs at once
- `--queue=pdf_processing`: Subscribe to PDF processing queue
- Adjust concurrency based on your machine (CPU cores, RAM)

### Submit PDF Files for Processing

```bash
# Process all PDFs in a directory
python submit_batch.py pdfs/*.pdf --output-dir output/

# Process specific files
python submit_batch.py file1.pdf file2.pdf file3.pdf --output-dir output/

# Process from file list
python submit_batch.py --file-list my_pdfs.txt --output-dir output/

# With monitoring
python submit_batch.py pdfs/*.pdf --output-dir output/ --monitor

# Custom settings
python submit_batch.py pdfs/*.pdf --output-dir output/ \
    --resolution high \
    --format both \
    --pages-per-chunk 20
```

### Monitor Tasks

```bash
# Check active tasks
celery -A celery_config inspect active

# Check queued tasks
celery -A celery_config inspect reserved

# Check worker stats
celery -A celery_config inspect stats

# Flower (web-based monitoring)
pip install flower
celery -A celery_config flower
# Open http://localhost:5555
```

## Performance Tuning

### For maximum throughput:

```bash
# 4 workers, each handling 2 PDFs = 8 PDFs processed simultaneously
# Each PDF's chunks still process in parallel

# Worker 1
python -m celery -A celery_config worker --concurrency=2 --hostname=worker1@%h --queue=pdf_processing --include=celery_tasks

# Worker 2  
python -m celery -A celery_config worker --concurrency=2 --hostname=worker2@%h --queue=pdf_processing --include=celery_tasks

# Worker 3
python -m celery -A celery_config worker --concurrency=2 --hostname=worker3@%h --queue=pdf_processing --include=celery_tasks

# Worker 4
python -m celery -A celery_config worker --concurrency=2 --hostname=worker4@%h --queue=pdf_processing --include=celery_tasks
```

### Resource limits:
- Each PDF uses ~500MB-1GB RAM during processing
- Each chunk makes API calls in parallel
- Monitor system resources and adjust workers accordingly

## Troubleshooting

### Tasks stuck in queue
```bash
# Purge all tasks (WARNING: deletes all pending tasks)
celery -A celery_config purge

# Restart workers
pkill -f "celery worker"
```

### Check Redis
```bash
# Check Redis connection
redis-cli ping

# Monitor Redis operations
redis-cli monitor

# Check Redis memory
redis-cli info memory
```

### View logs
```bash
# Worker logs show detailed progress
# Look for: "Processing chunk X in parallel"
```

## Example Workflow

```bash
# 1. Start Redis (if not running)
redis-server &

# 2. Start 2 Celery workers in background
python -m celery -A celery_config worker --concurrency=2 --loglevel=info --detach --queue=pdf_processing --include=celery_tasks
python -m celery -A celery_config worker --concurrency=2 --loglevel=info --detach --queue=pdf_processing --include=celery_tasks

# 3. Submit 100 PDFs for processing
python submit_batch.py pdfs/*.pdf --output-dir output/ --monitor

# 4. Check progress
celery -A celery_config inspect active

# 5. When done, stop workers
pkill -f "celery worker"
```

## Scaling to Multiple Machines

1. Run Redis on a central server
2. Update `CELERY_BROKER_URL` on all machines to point to central Redis
3. Start workers on each machine
4. Submit tasks from any machine

```bash
# Machine 1 (Redis server)
export CELERY_BROKER_URL=redis://192.168.1.100:6379/0

# Machine 2 (Worker)
export CELERY_BROKER_URL=redis://192.168.1.100:6379/0
python -m celery -A celery_config worker --concurrency=4 --queue=pdf_processing --include=celery_tasks

# Machine 3 (Worker)
export CELERY_BROKER_URL=redis://192.168.1.100:6379/0
python -m celery -A celery_config worker --concurrency=4 --queue=pdf_processing --include=celery_tasks

# Machine 4 (Submit tasks)
export CELERY_BROKER_URL=redis://192.168.1.100:6379/0
python submit_batch.py pdfs/*.pdf --output-dir output/
```
