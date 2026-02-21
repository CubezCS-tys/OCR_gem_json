"""
FastAPI backend for OCR Pipeline Control Panel.
Provides REST API for managing workers, submitting jobs, and monitoring tasks.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import subprocess
import os
import json
import signal
from pathlib import Path
from datetime import datetime
import redis
import uuid
from celery import Celery
from celery.result import AsyncResult
import psutil

from tasks import process_pdf_task, get_pdf_hash, get_cached_result
from celery_config import app as celery_app, PRIORITY_URGENT, PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW

app = FastAPI(title="OCR Pipeline Control Panel API", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis client
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=int(os.getenv('REDIS_DB', 0)),
    password=os.getenv('REDIS_PASSWORD'),
    decode_responses=True
)

# Models
class JobSubmission(BaseModel):
    pdf_path: str
    output_dir: str = "./outputs"
    priority: str = "normal"
    format: str = "both"
    extract_images: bool = True

class BatchJobSubmission(BaseModel):
    directory: str
    output_dir: str = "./outputs"
    priority: str = "normal"
    pattern: str = "*.pdf"

class WorkerControl(BaseModel):
    action: str  # start, stop, restart
    num_workers: int = 1
    concurrency: int = 4
    queues: Optional[List[str]] = None

class TaskQuery(BaseModel):
    task_id: str


# Helper functions
def get_priority_value(priority: str) -> int:
    """Convert priority string to numeric value."""
    priorities = {
        'urgent': PRIORITY_URGENT,
        'high': PRIORITY_HIGH,
        'normal': PRIORITY_NORMAL,
        'low': PRIORITY_LOW
    }
    return priorities.get(priority.lower(), PRIORITY_NORMAL)


def store_job_history(job_id: str, job_data: dict):
    """Store job execution history in Redis."""
    try:
        # Store job data with job_id as key
        redis_client.hset(f'job_history:{job_id}', mapping={
            'data': json.dumps(job_data)
        })
        # Add to sorted set for chronological ordering
        redis_client.zadd('job_history_index', {job_id: job_data['submitted_at']})
        # Set expiration to 30 days
        redis_client.expire(f'job_history:{job_id}', 30 * 24 * 60 * 60)
    except Exception as e:
        print(f"Failed to store job history: {e}")


def store_batch_history(batch_id: str, batch_data: dict):
    """Store batch execution history in Redis."""
    try:
        # Store batch data
        redis_client.hset(f'batch_history:{batch_id}', mapping={
            'data': json.dumps(batch_data)
        })
        # Add to sorted set
        redis_client.zadd('batch_history_index', {batch_id: batch_data['submitted_at']})
        # Set expiration to 30 days
        redis_client.expire(f'batch_history:{batch_id}', 30 * 24 * 60 * 60)
    except Exception as e:
        print(f"Failed to store batch history: {e}")


def update_job_status(job_id: str, status: str, result: dict = None):
    """Update job status in history."""
    try:
        job_key = f'job_history:{job_id}'
        if redis_client.exists(job_key):
            data_str = redis_client.hget(job_key, 'data')
            if data_str:
                job_data = json.loads(data_str)
                job_data['status'] = status
                job_data['updated_at'] = datetime.now().timestamp()
                if result:
                    job_data['result'] = result
                redis_client.hset(job_key, 'data', json.dumps(job_data))
    except Exception as e:
        print(f"Failed to update job status: {e}")


def update_job_metrics(task_id: str, metrics: dict):
    """Update job with execution metrics from task result."""
    try:
        # Find job by task_id
        job_ids = redis_client.zrevrange('job_history_index', 0, -1)
        for job_id in job_ids:
            job_key = f'job_history:{job_id}'
            if redis_client.exists(job_key):
                data_str = redis_client.hget(job_key, 'data')
                if data_str:
                    job_data = json.loads(data_str)
                    if job_data.get('task_id') == task_id:
                        # Update with metrics
                        job_data['completed_at'] = datetime.now().timestamp()
                        job_data['completed_at_iso'] = datetime.now().isoformat()
                        
                        # Calculate duration
                        if 'submitted_at' in job_data:
                            duration = job_data['completed_at'] - job_data['submitted_at']
                            job_data['duration_seconds'] = round(duration, 2)
                        
                        # Add task metrics
                        if 'processing_time' in metrics:
                            job_data['processing_time'] = metrics['processing_time']
                        if 'cost' in metrics:
                            job_data['cost'] = metrics['cost']
                        if 'cached' in metrics:
                            job_data['cached'] = metrics['cached']
                        if 'usage_metadata' in metrics:
                            job_data['usage_metadata'] = metrics['usage_metadata']
                        if 'error' in metrics:
                            job_data['error'] = metrics['error']
                        
                        # Update status based on result
                        if metrics.get('success'):
                            job_data['status'] = 'completed'
                        elif 'error' in metrics:
                            job_data['status'] = 'failed'
                        
                        redis_client.hset(job_key, 'data', json.dumps(job_data))
                        break
    except Exception as e:
        print(f"Failed to update job metrics: {e}")


def get_celery_workers():
    """Get list of active Celery workers."""
    try:
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()
        registered = inspect.registered()
        
        if not stats:
            return []
        
        workers = []
        for worker_name, worker_stats in stats.items():
            workers.append({
                'name': worker_name,
                'status': 'online',
                'pool': worker_stats.get('pool', {}),
                'active_tasks': len(active.get(worker_name, [])) if active else 0,
                'registered_tasks': len(registered.get(worker_name, [])) if registered else 0,
            })
        
        return workers
    except Exception as e:
        return []


def get_queue_stats():
    """Get statistics for all queues."""
    try:
        inspect = celery_app.control.inspect()
        active = inspect.active()
        reserved = inspect.reserved()
        
        queues = {}
        
        # Get tasks from all workers
        if active:
            for worker_name, tasks in active.items():
                for task in tasks:
                    queue = task.get('delivery_info', {}).get('routing_key', 'celery')
                    if queue not in queues:
                        queues[queue] = {'active': 0, 'reserved': 0}
                    queues[queue]['active'] += 1
        
        if reserved:
            for worker_name, tasks in reserved.items():
                for task in tasks:
                    queue = task.get('delivery_info', {}).get('routing_key', 'celery')
                    if queue not in queues:
                        queues[queue] = {'active': 0, 'reserved': 0}
                    queues[queue]['reserved'] += 1
        
        # Add default queues if not present
        for queue in ['celery', 'pdf_processing', 'html_rebuild']:
            if queue not in queues:
                queues[queue] = {'active': 0, 'reserved': 0}
        
        return queues
    except Exception as e:
        return {}


def get_system_metrics():
    """Get system resource metrics."""
    return {
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': psutil.disk_usage('/').percent,
    }


def get_celery_processes():
    """Get PIDs of running Celery worker processes."""
    pids = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and 'celery' in ' '.join(cmdline) and 'worker' in ' '.join(cmdline):
                pids.append({
                    'pid': proc.info['pid'],
                    'cmdline': ' '.join(cmdline[:5])  # First 5 args
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return pids


# API Endpoints

@app.get("/")
def read_root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "OCR Pipeline Control Panel API",
        "version": "1.0.0"
    }


@app.get("/api/system/status")
def get_system_status():
    """Get overall system status."""
    workers = get_celery_workers()
    queue_stats = get_queue_stats()
    
    # Check Redis
    redis_status = "offline"
    try:
        redis_client.ping()
        redis_status = "online"
    except:
        pass
    
    return {
        "timestamp": datetime.now().isoformat(),
        "redis": redis_status,
        "workers": {
            "count": len(workers),
            "status": "online" if workers else "offline"
        },
        "queues": queue_stats,
        "metrics": get_system_metrics()
    }


@app.get("/api/workers")
def list_workers():
    """Get list of all Celery workers."""
    workers = get_celery_workers()
    processes = get_celery_processes()
    
    return {
        "workers": workers,
        "processes": processes,
        "total": len(workers)
    }


@app.post("/api/workers/start")
def start_workers(control: WorkerControl):
    """Start Celery workers."""
    try:
        num_workers = control.num_workers
        concurrency = control.concurrency
        queues = ','.join(control.queues) if control.queues else 'celery,pdf_processing,html_rebuild'
        
        # Start multiple worker processes
        for i in range(num_workers):
            worker_name = f"worker{i+1}"
            cmd = [
                'celery', '-A', 'celery_config', 'worker',
                '--concurrency', str(concurrency),
                '--queues', queues,
                '--loglevel', 'info',
                '--detach',
                '--pidfile', f'celery_{worker_name}.pid',
                '--logfile', f'celery_{worker_name}.log',
                '-n', f'{worker_name}@%h'
            ]
            
            result = subprocess.run(
                cmd,
                cwd='/home/yassine/OCR_gem_json',
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"Failed to start {worker_name}: {result.stderr}")
        
        total_capacity = num_workers * concurrency
        return {
            "status": "success",
            "message": f"Started {num_workers} worker(s) with {concurrency} concurrency each (total capacity: {total_capacity})"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workers/stop")
def stop_workers():
    """Stop all Celery workers."""
    try:
        # Graceful shutdown
        subprocess.run(['pkill', '-TERM', '-f', 'celery -A celery_config worker'])
        
        return {
            "status": "success",
            "message": "Workers stopped"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workers/restart")
def restart_workers(control: WorkerControl):
    """Restart Celery workers."""
    try:
        # Stop existing workers
        subprocess.run(['pkill', '-TERM', '-f', 'celery -A celery_config worker'])
        
        # Wait a moment
        import time
        time.sleep(2)
        
        # Start new workers
        return start_workers(control)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/queues")
def list_queues():
    """Get statistics for all queues."""
    queue_stats = get_queue_stats()
    
    return {
        "queues": [
            {
                "name": name,
                "active": stats['active'],
                "reserved": stats['reserved'],
                "total": stats['active'] + stats['reserved']
            }
            for name, stats in queue_stats.items()
        ]
    }


@app.post("/api/jobs/submit")
def submit_job(job: JobSubmission):
    """Submit a single PDF for processing."""
    try:
        pdf_path = Path(job.pdf_path).resolve()
        
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_path}")
        
        # Check for duplicates
        pdf_hash = get_pdf_hash(str(pdf_path))
        cached = get_cached_result(pdf_hash)
        
        if cached:
            return {
                "status": "cached",
                "pdf": pdf_path.name,
                "pdf_hash": pdf_hash[:16],
                "message": "Result already cached"
            }
        
        # Submit task
        priority = get_priority_value(job.priority)
        task = process_pdf_task.apply_async(
            args=[str(pdf_path)],
            kwargs={
                'output_dir': job.output_dir,
                'output_format': job.format,
                'extract_images': job.extract_images
            },
            priority=priority
        )
        
        # Store job history
        job_id = str(uuid.uuid4())
        job_history = {
            'job_id': job_id,
            'task_id': task.id,
            'type': 'single',
            'pdf_name': pdf_path.name,
            'pdf_path': str(pdf_path),
            'output_dir': job.output_dir,
            'priority': job.priority,
            'format': job.format,
            'extract_images': job.extract_images,
            'status': 'submitted',
            'submitted_at': datetime.now().timestamp(),
            'submitted_at_iso': datetime.now().isoformat()
        }
        store_job_history(job_id, job_history)
        
        return {
            "status": "submitted",
            "job_id": job_id,
            "task_id": task.id,
            "pdf": pdf_path.name,
            "priority": job.priority
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/submit-batch")
def submit_batch(batch: BatchJobSubmission):
    """Submit all PDFs in a directory."""
    try:
        pdf_dir = Path(batch.directory).resolve()
        
        if not pdf_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Directory not found: {pdf_dir}")
        
        pdf_files = sorted(pdf_dir.glob(batch.pattern))
        
        if not pdf_files:
            raise HTTPException(status_code=404, detail=f"No PDFs found matching {batch.pattern}")
        
        results = []
        priority = get_priority_value(batch.priority)
        
        for pdf_path in pdf_files:
            # Check cache
            pdf_hash = get_pdf_hash(str(pdf_path))
            cached = get_cached_result(pdf_hash)
            
            if cached:
                results.append({
                    "status": "cached",
                    "pdf": pdf_path.name
                })
                continue
            
            # Submit task
            task = process_pdf_task.apply_async(
                args=[str(pdf_path)],
                kwargs={'output_dir': batch.output_dir},
                priority=priority
            )
            
            results.append({
                "status": "submitted",
                "task_id": task.id,
                "pdf": pdf_path.name
            })
        
        submitted = sum(1 for r in results if r['status'] == 'submitted')
        cached = sum(1 for r in results if r['status'] == 'cached')
        
        # Store batch history
        batch_id = str(uuid.uuid4())
        batch_history = {
            'batch_id': batch_id,
            'type': 'batch',
            'directory': str(pdf_dir),
            'pattern': batch.pattern,
            'output_dir': batch.output_dir,
            'priority': batch.priority,
            'total_files': len(pdf_files),
            'submitted': submitted,
            'cached': cached,
            'status': 'submitted',
            'submitted_at': datetime.now().timestamp(),
            'submitted_at_iso': datetime.now().isoformat(),
            'tasks': results
        }
        store_batch_history(batch_id, batch_history)
        
        return {
            "batch_id": batch_id,
            "total": len(pdf_files),
            "submitted": submitted,
            "cached": cached,
            "tasks": results
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks")
def list_tasks():
    """Get list of all tasks (active, scheduled, reserved)."""
    try:
        inspect = celery_app.control.inspect()
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        scheduled = inspect.scheduled() or {}
        
        all_tasks = []
        
        # Active tasks
        for worker, tasks in active.items():
            for task in tasks:
                all_tasks.append({
                    'task_id': task['id'],
                    'name': task['name'],
                    'state': 'ACTIVE',
                    'worker': worker,
                    'args': task.get('args', []),
                    'kwargs': task.get('kwargs', {}),
                })
        
        # Reserved tasks
        for worker, tasks in reserved.items():
            for task in tasks:
                all_tasks.append({
                    'task_id': task['id'],
                    'name': task['name'],
                    'state': 'RESERVED',
                    'worker': worker,
                    'args': task.get('args', []),
                    'kwargs': task.get('kwargs', {}),
                })
        
        # Scheduled tasks
        for worker, tasks in scheduled.items():
            for task in tasks:
                all_tasks.append({
                    'task_id': task['request']['id'],
                    'name': task['request']['name'],
                    'state': 'SCHEDULED',
                    'worker': worker,
                    'eta': task.get('eta'),
                })
        
        return {
            "tasks": all_tasks,
            "total": len(all_tasks)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks/{task_id}")
def get_task_status(task_id: str):
    """Get status of a specific task."""
    try:
        task = AsyncResult(task_id, app=celery_app)
        
        result = {
            'task_id': task_id,
            'state': task.state,
            'ready': task.ready(),
            'successful': task.successful() if task.ready() else None,
            'failed': task.failed() if task.ready() else None
        }
        
        if task.ready():
            if task.successful():
                task_result = task.result
                result['result'] = task_result
                # Update job history with metrics
                if isinstance(task_result, dict):
                    update_job_metrics(task_id, task_result)
            else:
                error_str = str(task.info)
                result['error'] = error_str
                # Update job history with error
                update_job_metrics(task_id, {'error': error_str, 'success': False})
        elif task.state == 'PENDING':
            result['info'] = 'Task is waiting to be processed'
        else:
            result['info'] = task.info
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/tasks/{task_id}")
def revoke_task(task_id: str):
    """Revoke/cancel a task."""
    try:
        celery_app.control.revoke(task_id, terminate=True)
        return {
            "status": "success",
            "message": f"Task {task_id} revoked"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pdfs")
def list_pdfs():
    """List all PDFs in the pdfs directory."""
    try:
        pdf_dir = Path('/home/yassine/OCR_gem_json/pdfs')
        pdfs = []
        
        for pdf_path in sorted(pdf_dir.glob('*.pdf')):
            stat = pdf_path.stat()
            pdfs.append({
                'name': pdf_path.name,
                'path': str(pdf_path),
                'size': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return {
            "pdfs": pdfs,
            "total": len(pdfs)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/outputs")
def list_outputs():
    """List all generated outputs."""
    try:
        outputs_dir = Path('/home/yassine/OCR_gem_json/outputs')
        outputs = []
        
        if outputs_dir.exists():
            for file_path in sorted(outputs_dir.iterdir()):
                if file_path.suffix in ['.html', '.json']:
                    stat = file_path.stat()
                    outputs.append({
                        'name': file_path.name,
                        'path': str(file_path),
                        'type': file_path.suffix[1:],
                        'size': stat.st_size,
                        'size_kb': round(stat.st_size / 1024, 2),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
        
        return {
            "outputs": outputs,
            "total": len(outputs)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/redis/flush")
def flush_redis():
    """Clear all data from Redis (use with caution)."""
    try:
        redis_client.flushdb()
        return {
            "status": "success",
            "message": "Redis database flushed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/jobs")
def get_job_history(limit: int = 50, offset: int = 0):
    """Get job execution history."""
    try:
        # Get job IDs in reverse chronological order
        job_ids = redis_client.zrevrange('job_history_index', offset, offset + limit - 1)
        
        jobs = []
        for job_id in job_ids:
            job_key = f'job_history:{job_id}'
            if redis_client.exists(job_key):
                data_str = redis_client.hget(job_key, 'data')
                if data_str:
                    job_data = json.loads(data_str)
                    # Enrich with current task status if available
                    if 'task_id' in job_data:
                        try:
                            task = AsyncResult(job_data['task_id'], app=celery_app)
                            job_data['current_state'] = task.state
                        except:
                            pass
                    jobs.append(job_data)
        
        total = redis_client.zcard('job_history_index')
        
        return {
            "jobs": jobs,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/batches")
def get_batch_history(limit: int = 50, offset: int = 0):
    """Get batch execution history."""
    try:
        # Get batch IDs in reverse chronological order
        batch_ids = redis_client.zrevrange('batch_history_index', offset, offset + limit - 1)
        
        batches = []
        for batch_id in batch_ids:
            batch_key = f'batch_history:{batch_id}'
            if redis_client.exists(batch_key):
                data_str = redis_client.hget(batch_key, 'data')
                if data_str:
                    batch_data = json.loads(data_str)
                    batches.append(batch_data)
        
        total = redis_client.zcard('batch_history_index')
        
        return {
            "batches": batches,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/statistics")
def get_history_statistics():
    """Get aggregate statistics from job and batch history."""
    try:
        stats = {
            'total_jobs': 0,
            'total_batches': 0,
            'total_files_processed': 0,
            'jobs_by_status': {},
            'jobs_by_priority': {},
            'recent_activity': [],
            'cache_hit_rate': 0,
            'total_cost_usd': 0,
            'average_processing_time': 0,
            'total_processing_time': 0,
            'failed_jobs': 0,
            'retry_count': 0
        }
        
        # Count jobs and batches
        stats['total_jobs'] = redis_client.zcard('job_history_index')
        stats['total_batches'] = redis_client.zcard('batch_history_index')
        
        # Get recent jobs for statistics
        job_ids = redis_client.zrevrange('job_history_index', 0, 99)
        total_files = 0
        cached_count = 0
        processing_times = []
        
        for job_id in job_ids:
            job_key = f'job_history:{job_id}'
            if redis_client.exists(job_key):
                data_str = redis_client.hget(job_key, 'data')
                if data_str:
                    job_data = json.loads(data_str)
                    
                    # Count by status
                    status = job_data.get('status', 'unknown')
                    stats['jobs_by_status'][status] = stats['jobs_by_status'].get(status, 0) + 1
                    
                    # Count by priority
                    priority = job_data.get('priority', 'normal')
                    stats['jobs_by_priority'][priority] = stats['jobs_by_priority'].get(priority, 0) + 1
                    
                    # Aggregate cost
                    if 'cost' in job_data:
                        stats['total_cost_usd'] += job_data['cost'].get('total_cost_usd', 0)
                    
                    # Aggregate processing time
                    if 'processing_time' in job_data:
                        processing_times.append(job_data['processing_time'])
                        stats['total_processing_time'] += job_data['processing_time']
                    
                    # Count failures
                    if status == 'failed':
                        stats['failed_jobs'] += 1
                    
                    # Check if cached
                    if job_data.get('cached'):
                        cached_count += 1
                    
                    total_files += 1
        
        # Get batch statistics
        batch_ids = redis_client.zrevrange('batch_history_index', 0, 99)
        for batch_id in batch_ids:
            batch_key = f'batch_history:{batch_id}'
            if redis_client.exists(batch_key):
                data_str = redis_client.hget(batch_key, 'data')
                if data_str:
                    batch_data = json.loads(data_str)
                    total_files += batch_data.get('total_files', 0)
                    cached_count += batch_data.get('cached', 0)
        
        stats['total_files_processed'] = total_files
        
        # Calculate cache hit rate
        if total_files > 0:
            stats['cache_hit_rate'] = round((cached_count / total_files) * 100, 2)
        
        # Calculate average processing time
        if processing_times:
            stats['average_processing_time'] = round(sum(processing_times) / len(processing_times), 2)
        
        # Round cost
        stats['total_cost_usd'] = round(stats['total_cost_usd'], 4)
        stats['total_processing_time'] = round(stats['total_processing_time'], 2)
        
        # Get recent activity (last 10 items)
        recent_jobs = redis_client.zrevrange('job_history_index', 0, 4)
        recent_batches = redis_client.zrevrange('batch_history_index', 0, 4)
        
        for job_id in recent_jobs:
            job_key = f'job_history:{job_id}'
            if redis_client.exists(job_key):
                data_str = redis_client.hget(job_key, 'data')
                if data_str:
                    job_data = json.loads(data_str)
                    stats['recent_activity'].append({
                        'type': 'job',
                        'id': job_data['job_id'],
                        'name': job_data.get('pdf_name', 'unknown'),
                        'status': job_data.get('status', 'unknown'),
                        'timestamp': job_data.get('submitted_at_iso')
                    })
        
        for batch_id in recent_batches:
            batch_key = f'batch_history:{batch_id}'
            if redis_client.exists(batch_key):
                data_str = redis_client.hget(batch_key, 'data')
                if data_str:
                    batch_data = json.loads(data_str)
                    stats['recent_activity'].append({
                        'type': 'batch',
                        'id': batch_data['batch_id'],
                        'name': f"{batch_data.get('total_files', 0)} files",
                        'status': batch_data.get('status', 'unknown'),
                        'timestamp': batch_data.get('submitted_at_iso')
                    })
        
        # Sort recent activity by timestamp
        stats['recent_activity'].sort(key=lambda x: x['timestamp'], reverse=True)
        stats['recent_activity'] = stats['recent_activity'][:10]
        
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
