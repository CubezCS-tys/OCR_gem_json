# Production Pipeline Setup

Complete distributed processing system for scaling PDF OCR with Celery + Redis.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start Redis

```bash
# Option 1: Docker
docker run -d -p 6379:6379 redis:latest

# Option 2: Local install (Ubuntu/Debian)
sudo apt install redis-server
sudo systemctl start redis

# Option 3: macOS with Homebrew
brew install redis
brew services start redis
```

### 3. Configure Environment

Create `.env` file:

```bash
# Gemini API
GEMINI_API_KEY=your_api_key_here

# Celery broker/result (used by celery_config.py)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Redis Configuration for cache (submit_jobs.py, optional)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
# REDIS_PASSWORD=your_password  # Uncomment if needed
```

### 4. Start Celery Workers

Workers must include the task module (tasks are not auto-discovered).

```bash
# submit_jobs.py / tasks.py (default "celery" queue)
python -m celery -A celery_config worker --loglevel=info --concurrency=2 --include=tasks

# submit_batch.py / celery_tasks.py (routed to pdf_processing queue)
python -m celery -A celery_config worker --loglevel=info --concurrency=2 --queue=pdf_processing --include=celery_tasks

# Start worker as background process (submit_jobs example)
python -m celery -A celery_config worker --detach --loglevel=info --pidfile=celery.pid --include=tasks
```

`submit_batch.py` routes tasks to `pdf_processing` via `celery_config.py`. `submit_jobs.py` uses the default `celery` queue unless you add routing.

### 5. Submit Jobs

```bash
# Batch pipeline (submit_batch.py)
python submit_batch.py pdfs/*.pdf --output-dir outputs/ --monitor

# Production pipeline (submit_jobs.py)
# Single PDF
python submit_jobs.py document.pdf

# Directory of PDFs
python submit_jobs.py --directory ./pdfs --output ./outputs

# High priority processing
python submit_jobs.py urgent_doc.pdf --priority high

# Check task status
python submit_jobs.py --status <task_id>

# Rebuild HTML from JSON
python submit_jobs.py --rebuild output.json
```

Note: `submit_jobs.py` expects `PRIORITY_*` constants in `celery_config.py`. If you hit an import error, define them there or use `submit_batch.py`.

### 6. Monitor Processing

```bash
# Real-time monitoring
python monitor.py

# Check specific task
python monitor.py --task <task_id>

# Show statistics
python monitor.py --stats

# Web-based monitoring (Flower)
celery -A celery_config flower
# Open http://localhost:5555
```

## Architecture

### Task Queue System

```
┌─────────────┐         ┌─────────┐         ┌──────────────┐
│   Client    │────────>│  Redis  │────────>│   Workers    │
│ submit_batch │        │  Broker │         │ (Celery)     │
│ submit_jobs  │        │         │         │             │
└─────────────┘         └─────────┘         └──────────────┘
                             │                      │
                             │                      │
                        Result Store          PDF Processing
                        PDF Cache            (Gemini API)
```

### Priority Levels (submit_jobs.py)

These are used by `submit_jobs.py` and require priority constants in `celery_config.py` plus broker support.

- **URGENT** (9): Time-critical processing
- **HIGH** (7): Important documents
- **NORMAL** (5): Standard processing (default)
- **LOW** (3): Batch jobs
- **BACKGROUND** (1): Maintenance tasks

### Rate Limiting

- **Default Celery rate limit**: 10 tasks/minute (set in `celery_config.py`)
- Shared across all workers
- Auto-retry with exponential backoff
- Max 3 retries per task

### Caching

- **PDF Hash**: SHA256 deduplication
- **Result Cache**: 7 days TTL
- Instant retrieval for duplicate PDFs
- Reduces API costs significantly

## Production Deployment

### Multi-Worker Setup

Deploy workers across multiple machines:

```bash
# Machine 1: High-priority workers
python -m celery -A celery_config worker -n worker1@%h --concurrency=4 --include=tasks

# Machine 2: Normal priority
python -m celery -A celery_config worker -n worker2@%h --concurrency=2 --include=tasks

# Machine 3: HTML rebuild (add routing first if you want a separate queue)
python -m celery -A celery_config worker -n worker3@%h --concurrency=4 --include=tasks
```

### Monitoring Dashboard

Start Flower for web-based monitoring:

```bash
celery -A celery_config flower --port=5555 --broker=redis://localhost:6379/0
```

Access at: http://localhost:5555

Features:
- Real-time task tracking
- Worker status and statistics
- Task history and results
- Rate limit monitoring
- Resource usage graphs

### Docker Deployment

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:latest
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  celery_worker:
    build: .
    command: celery -A celery_config worker --loglevel=info --include=tasks
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - REDIS_HOST=redis
    depends_on:
      - redis
    volumes:
      - ./pdfs:/app/pdfs
      - ./outputs:/app/outputs
    deploy:
      replicas: 3

  flower:
    build: .
    command: celery -A celery_config flower --port=5555
    ports:
      - "5555:5555"
    environment:
      - REDIS_HOST=redis
    depends_on:
      - redis

volumes:
  redis_data:
```

Run with:

```bash
docker-compose up -d --scale celery_worker=5
```

### Systemd Service

Create `/etc/systemd/system/celery-worker.service`:

```ini
[Unit]
Description=Celery Worker for PDF Processing
After=network.target redis.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/path/to/OCR_gem_json
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/celery -A celery_config worker \
    --detach \
    --pidfile=/var/run/celery/worker.pid \
    --logfile=/var/log/celery/worker.log \
    --loglevel=info \
    --include=tasks
ExecStop=/path/to/venv/bin/celery -A celery_config control shutdown
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable celery-worker
sudo systemctl start celery-worker
sudo systemctl status celery-worker
```

## Usage Examples

### Batch Processing Directory

```bash
# Process all PDFs with medium quality
python submit_jobs.py --directory ./pdfs --output ./outputs

# High priority batch
python submit_jobs.py -d ./urgent_pdfs -o ./outputs --priority high

# Skip duplicate checking (process everything)
python submit_jobs.py -d ./pdfs --no-duplicate-check

# Only JSON output
python submit_jobs.py -d ./pdfs --format json
```

### Priority Processing

```bash
# Urgent document (highest priority)
python submit_jobs.py critical.pdf --priority urgent

# High priority
python submit_jobs.py important.pdf --priority high

# Background processing
python submit_jobs.py archive.pdf --priority low
```

### Monitoring Tasks

```bash
# Watch queue in real-time
python monitor.py

# Custom update interval
python monitor.py --interval 2

# Check specific task
python monitor.py --task abc123-def456-ghi789

# View processing statistics
python monitor.py --stats

# Cancel a task
python monitor.py --revoke abc123-def456 --terminate
```

### Result Caching

```bash
# First run: processes PDF (~30s)
python submit_jobs.py document.pdf

# Second run: instant (from cache)
python submit_jobs.py document.pdf

# Disable caching (force reprocess)
python submit_jobs.py document.pdf --no-cache
```

## Performance Tuning

### Worker Concurrency

```bash
# Auto-detect CPU cores
python -m celery -A celery_config worker --autoscale=10,3 --include=tasks

# Fixed concurrency
python -m celery -A celery_config worker --concurrency=8 --include=tasks

# Single-threaded (max reliability)
python -m celery -A celery_config worker --concurrency=1 --include=tasks
```

### Rate Limiting

Edit `celery_config.py`:

```python
# Increase if you have higher quota
task_default_rate_limit = '10/m'
task_annotations = {
    # submit_jobs.py
    'tasks.process_pdf_task': {'rate_limit': '100/m'},
    # submit_batch.py
    'celery_tasks.process_pdf': {'rate_limit': '100/m'},
}
```

### Memory Management

```python
# In celery_config.py
worker_max_tasks_per_child = 50  # Restart after N tasks
worker_max_memory_per_child = 500000  # 500MB limit
```

### Task Timeout

```python
# In celery_config.py
task_time_limit = 3600  # Hard limit: 1 hour
task_soft_time_limit = 3000  # Soft limit: 50 min
```

## Troubleshooting

### Redis Connection Issues

```bash
# Test Redis connection
redis-cli ping
# Should return: PONG

# Check Redis info
redis-cli info
```

### Worker Not Picking Up Tasks

```bash
# Check worker is running
celery -A celery_config inspect active

# Check registered tasks
celery -A celery_config inspect registered

# If registered task count is 0, restart workers with --include=celery_tasks or --include=tasks
# and make sure the queue matches the submit script you used.

# Purge stuck tasks
celery -A celery_config purge
```

### Rate Limit Errors

If you see "429 Too Many Requests":

1. Reduce workers: `--concurrency=1`
2. Lower rate limit in `celery_config.py`
3. Add delays between submissions

### Memory Issues

```bash
# Monitor worker memory
watch -n 1 'ps aux | grep celery'

# Reduce max tasks per worker
python -m celery -A celery_config worker --max-tasks-per-child=10 --include=tasks
```

### Task Hangs

```bash
# Set shorter timeout in celery_config.py
task_time_limit = 600  # 10 minutes

# Force kill hung task
python monitor.py --revoke <task_id> --terminate
```

## Cost Optimization

### Caching Strategy

- **Cache Hit Rate**: Check with `python monitor.py --stats`
- **Target**: >50% cache hits for repeated processing
- **TTL**: Adjust in `tasks.py` (default 7 days)

### Batch Processing

Process multiple pages per request:

```python
# In pdf_to_html.py
config = ProcessingConfig(
    chunk_size=20,  # Increase from 15 (more pages per API call)
    use_chunked_processing=True
)
```

### Resolution Settings

```bash
# Low quality: 50% cost reduction
python submit_jobs.py doc.pdf --resolution low

# Medium: balanced (default)
python submit_jobs.py doc.pdf --resolution medium

# High: 2x cost
python submit_jobs.py doc.pdf --resolution high
```

## Security

### API Key Protection

```bash
# Never commit .env file
echo ".env" >> .gitignore

# Use environment variables in production
export GEMINI_API_KEY="your_key_here"
```

### Redis Authentication

```bash
# Set Redis password
redis-cli CONFIG SET requirepass "your_password"

# Update .env
REDIS_PASSWORD=your_password
```

### Worker Isolation

Run workers as non-privileged user:

```bash
sudo useradd -r -s /bin/false celery
sudo chown -R celery:celery /path/to/OCR_gem_json
sudo -u celery celery -A celery_config worker --include=tasks
```

## Monitoring Metrics

### Key Metrics to Track

1. **Task Success Rate**: Target >95%
2. **Average Processing Time**: ~20-40s per page
3. **Cache Hit Rate**: Target >50%
4. **Worker Utilization**: Target 70-80%
5. **Queue Length**: Should stay near 0
6. **API Cost**: ~$0.05-$0.10 per document

### Flower Dashboard

Monitor at http://localhost:5555:

- Tasks: Real-time task execution
- Workers: Worker status and performance
- Broker: Redis connection and queue status
- Monitor: Historical graphs and trends

### Custom Metrics

Export metrics to Prometheus/Grafana:

```bash
pip install prometheus-client

# Add to celery_config.py
task_send_sent_event = True
```

## Support

For issues or questions:

1. Check logs: `tail -f /var/log/celery/worker.log`
2. Monitor dashboard: http://localhost:5555
3. Test single PDF: `python pdf_to_html.py test.pdf`
4. Verify Redis: `redis-cli ping`
5. Check workers: `celery -A celery_config inspect active`

## Next Steps

1. ✅ Install dependencies
2. ✅ Configure `.env`
3. ✅ Start Redis
4. ✅ Launch workers
5. ✅ Submit test job
6. ✅ Monitor in Flower
7. 📊 Scale workers as needed
8. 💰 Track costs and optimize
