"""
Pipeline API Server

FastAPI server for controlling the OCR pipeline backend.
Provides REST endpoints for worker management, job submission, and monitoring.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()
load_dotenv(Path(__file__).parent.parent / '.env')

# Import Celery components
from celery_config import app as celery_app
from celery.result import AsyncResult
from celery_tasks import process_pdf, process_pdf_batch
from celery_config import PRIORITY_URGENT, PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW

# FastAPI app
app = FastAPI(
    title="OCR Pipeline API",
    description="REST API for controlling the OCR pipeline backend",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
PDF_DIRECTORIES = os.getenv("PDF_DIRECTORIES", "/home/yassine/OCR_gem_json/pdfs").split(",")
OUTPUT_DIRECTORY = os.getenv("OUTPUT_DIRECTORY", "/home/yassine/OCR_gem_json/outputs")


# ============================================================================
# Pydantic Models
# ============================================================================

class JobStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILURE = "failure"
    REVOKED = "revoked"


class Priority(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


PRIORITY_MAP = {
    Priority.URGENT: PRIORITY_URGENT,
    Priority.HIGH: PRIORITY_HIGH,
    Priority.NORMAL: PRIORITY_NORMAL,
    Priority.LOW: PRIORITY_LOW,
}


class WorkerInfo(BaseModel):
    hostname: str
    status: str
    active_tasks: int
    processed_total: int
    concurrency: int
    pid: Optional[int] = None
    uptime: Optional[str] = None


class QueueInfo(BaseModel):
    name: str
    length: int
    consumers: int


class JobInfo(BaseModel):
    task_id: str
    status: str
    pdf_path: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class JobSubmission(BaseModel):
    pdf_paths: List[str] = Field(..., description="List of PDF file paths to process")
    output_dir: Optional[str] = Field(None, description="Output directory")
    output_format: str = Field("both", description="Output format: html, json, both, or gemini_html (Gemini direct HTML with image injection)")
    resolution: str = Field("high", description="Processing resolution: low, medium, high")
    pages_per_chunk: int = Field(15, description="Pages per processing chunk")
    priority: Priority = Field(Priority.NORMAL, description="Task priority")


class FileInfo(BaseModel):
    name: str
    path: str
    is_directory: bool
    size: Optional[int] = None
    modified: Optional[str] = None
    extension: Optional[str] = None


class StatsInfo(BaseModel):
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    pending_jobs: int
    active_jobs: int
    success_rate: float
    avg_processing_time: Optional[float] = None


# ============================================================================
# Worker Endpoints
# ============================================================================

@app.get("/api/workers", response_model=List[WorkerInfo])
async def get_workers():
    """Get list of active Celery workers with their status."""
    try:
        inspect = celery_app.control.inspect()
        
        # Get active tasks per worker
        active = inspect.active() or {}
        stats = inspect.stats() or {}
        
        workers = []
        for hostname, worker_stats in stats.items():
            active_tasks = active.get(hostname, [])
            pool_info = worker_stats.get('pool', {})
            
            workers.append(WorkerInfo(
                hostname=hostname,
                status="online",
                active_tasks=len(active_tasks),
                processed_total=worker_stats.get('total', {}).get('celery_tasks.process_pdf', 0),
                concurrency=pool_info.get('max-concurrency', 1),
                pid=worker_stats.get('pid'),
                uptime=None  # Could calculate from clock info
            ))
        
        return workers
    except Exception as e:
        # Return empty list if can't connect to workers
        return []


@app.get("/api/workers/{hostname}/tasks")
async def get_worker_tasks(hostname: str):
    """Get active tasks for a specific worker."""
    try:
        inspect = celery_app.control.inspect([hostname])
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        
        return {
            "hostname": hostname,
            "active": active.get(hostname, []),
            "reserved": reserved.get(hostname, [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workers/{hostname}/control")
async def control_worker(hostname: str, action: str = Query(..., description="Action: shutdown, pool_restart")):
    """Control a specific worker (requires careful use)."""
    try:
        if action == "shutdown":
            celery_app.control.shutdown(destination=[hostname])
            return {"message": f"Shutdown signal sent to {hostname}"}
        elif action == "pool_restart":
            celery_app.control.pool_restart(destination=[hostname])
            return {"message": f"Pool restart signal sent to {hostname}"}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Queue Endpoints
# ============================================================================

@app.get("/api/queue", response_model=List[QueueInfo])
async def get_queue_info():
    """Get information about task queues."""
    try:
        inspect = celery_app.control.inspect()
        active_queues = inspect.active_queues() or {}
        
        # Get queue lengths from Redis
        import redis
        broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
        r = redis.from_url(broker_url)
        
        queues = []
        seen_queues = set()
        
        for hostname, worker_queues in active_queues.items():
            for q in worker_queues:
                queue_name = q.get('name', 'celery')
                if queue_name not in seen_queues:
                    seen_queues.add(queue_name)
                    try:
                        length = r.llen(queue_name)
                    except:
                        length = 0
                    
                    queues.append(QueueInfo(
                        name=queue_name,
                        length=length,
                        consumers=len([h for h, wq in active_queues.items() 
                                      if any(q2.get('name') == queue_name for q2 in wq)])
                    ))
        
        # Add default queue if no workers are connected
        if not queues:
            try:
                length = r.llen('pdf_processing')
            except:
                length = 0
            queues.append(QueueInfo(name="pdf_processing", length=length, consumers=0))
        
        return queues
    except Exception as e:
        return [QueueInfo(name="pdf_processing", length=0, consumers=0)]


@app.post("/api/queue/purge")
async def purge_queue(queue_name: Optional[str] = None):
    """Purge pending tasks from queue."""
    try:
        if queue_name:
            # Purge specific queue
            import redis
            broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
            r = redis.from_url(broker_url)
            count = r.llen(queue_name)
            r.delete(queue_name)
            return {"message": f"Purged {count} tasks from {queue_name}"}
        else:
            # Purge all queues
            count = celery_app.control.purge()
            return {"message": f"Purged {count} tasks from all queues"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Job Endpoints
# ============================================================================

@app.post("/api/jobs", response_model=Dict[str, Any])
async def submit_jobs(submission: JobSubmission):
    """Submit PDF files for processing."""
    try:
        output_dir = submission.output_dir or OUTPUT_DIRECTORY
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Validate PDF paths
        valid_paths = []
        for pdf_path in submission.pdf_paths:
            p = Path(pdf_path)
            if p.exists() and p.suffix.lower() == '.pdf':
                valid_paths.append(str(p.absolute()))
            else:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid or missing PDF: {pdf_path}"
                )
        
        if not valid_paths:
            raise HTTPException(status_code=400, detail="No valid PDF files provided")
        
        # Submit tasks
        task_ids = []
        priority = PRIORITY_MAP.get(submission.priority, PRIORITY_NORMAL)
        
        for pdf_path in valid_paths:
            pdf_name = Path(pdf_path).stem
            output_html = str(Path(output_dir) / f"{pdf_name}.html")
            output_json = str(Path(output_dir) / f"{pdf_name}.json")
            
            result = process_pdf.apply_async(
                kwargs={
                    'pdf_path': pdf_path,
                    'output_html': output_html,
                    'output_json': output_json,
                    'output_format': submission.output_format,
                    'resolution': submission.resolution,
                    'pages_per_chunk': submission.pages_per_chunk,
                },
                priority=priority
            )
            task_ids.append({
                'task_id': result.id,
                'pdf_path': pdf_path,
                'pdf_name': pdf_name
            })
        
        return {
            'status': 'submitted',
            'total_files': len(valid_paths),
            'output_dir': output_dir,
            'tasks': task_ids
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs", response_model=List[JobInfo])
async def list_jobs(
    limit: int = Query(50, description="Maximum number of jobs to return"),
    status: Optional[str] = Query(None, description="Filter by status")
):
    """List recent jobs with their status."""
    try:
        # Get task results from Redis backend
        import redis
        backend_url = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
        r = redis.from_url(backend_url)
        
        jobs = []
        
        # Get recent task keys
        task_keys = r.keys('celery-task-meta-*')
        task_keys = sorted(task_keys, reverse=True)[:limit * 2]  # Get more to filter
        
        for key in task_keys:
            try:
                task_data = r.get(key)
                if task_data:
                    import json
                    data = json.loads(task_data)
                    task_id = key.decode().replace('celery-task-meta-', '')
                    task_status = data.get('status', 'UNKNOWN').lower()
                    
                    # Filter by status if specified
                    if status and task_status != status.lower():
                        continue
                    
                    result = data.get('result', {})
                    
                    jobs.append(JobInfo(
                        task_id=task_id,
                        status=task_status,
                        pdf_path=result.get('pdf_path') if isinstance(result, dict) else None,
                        result=result if isinstance(result, dict) else None,
                        error=str(result) if task_status == 'failure' else None
                    ))
                    
                    if len(jobs) >= limit:
                        break
            except:
                continue
        
        return jobs
    except Exception as e:
        return []


@app.get("/api/jobs/{task_id}", response_model=JobInfo)
async def get_job(task_id: str):
    """Get status and result of a specific job."""
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        job_result = None
        error = None
        
        if result.ready():
            try:
                job_result = result.result
                if isinstance(result.result, Exception):
                    error = str(result.result)
                    job_result = None
            except:
                pass
        
        # Get meta info if processing
        meta = {}
        if result.state == 'PROCESSING':
            meta = result.info or {}
        
        return JobInfo(
            task_id=task_id,
            status=result.state.lower(),
            pdf_path=meta.get('pdf') or (job_result.get('pdf_path') if isinstance(job_result, dict) else None),
            progress=meta.get('progress'),
            result=job_result if isinstance(job_result, dict) else None,
            error=error
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/{task_id}/cancel")
async def cancel_job(task_id: str, terminate: bool = Query(False)):
    """Cancel a pending or running job."""
    try:
        celery_app.control.revoke(task_id, terminate=terminate)
        return {"message": f"Job {task_id} cancelled", "terminated": terminate}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/{task_id}/retry")
async def retry_job(task_id: str):
    """Retry a failed job."""
    try:
        # Get original task info
        result = AsyncResult(task_id, app=celery_app)
        if result.state != 'FAILURE':
            raise HTTPException(status_code=400, detail="Can only retry failed jobs")
        
        # Get original args/kwargs
        original_result = result.result
        if isinstance(original_result, dict) and 'pdf_path' in original_result:
            # Resubmit with same parameters
            new_result = process_pdf_task.apply_async(
                kwargs={
                    'pdf_path': original_result['pdf_path'],
                    'output_dir': str(Path(original_result.get('output_html', '')).parent),
                }
            )
            return {
                "message": "Job resubmitted",
                "original_task_id": task_id,
                "new_task_id": new_result.id
            }
        else:
            raise HTTPException(status_code=400, detail="Cannot determine original job parameters")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# File Browser Endpoints
# ============================================================================

@app.get("/api/files", response_model=List[FileInfo])
async def list_files(
    directory: Optional[str] = Query(None, description="Directory to list"),
    extensions: str = Query(".pdf", description="Comma-separated file extensions to include")
):
    """List files in a directory."""
    try:
        # Determine directory to list
        if directory:
            base_dir = Path(directory)
        else:
            # Use first configured PDF directory
            base_dir = Path(PDF_DIRECTORIES[0].strip())
        
        if not base_dir.exists():
            return []
        
        # Parse extensions
        ext_list = [e.strip().lower() for e in extensions.split(',')]
        if not ext_list[0].startswith('.'):
            ext_list = ['.' + e for e in ext_list]
        
        files = []
        for item in sorted(base_dir.iterdir()):
            if item.name.startswith('.'):
                continue
            
            is_dir = item.is_dir()
            include = is_dir or item.suffix.lower() in ext_list
            
            if include:
                stat = item.stat()
                files.append(FileInfo(
                    name=item.name,
                    path=str(item.absolute()),
                    is_directory=is_dir,
                    size=stat.st_size if not is_dir else None,
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    extension=item.suffix.lower() if not is_dir else None
                ))
        
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/files/directories")
async def get_configured_directories():
    """Get list of configured PDF directories."""
    dirs = []
    for d in PDF_DIRECTORIES:
        d = d.strip()
        p = Path(d)
        dirs.append({
            "path": d,
            "exists": p.exists(),
            "absolute": str(p.absolute()) if p.exists() else d
        })
    return dirs


# ============================================================================
# Statistics Endpoints
# ============================================================================

@app.get("/api/stats", response_model=StatsInfo)
async def get_stats():
    """Get overall processing statistics."""
    try:
        import redis
        backend_url = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
        r = redis.from_url(backend_url)
        
        # Count tasks by status
        task_keys = r.keys('celery-task-meta-*')
        
        total = len(task_keys)
        completed = 0
        failed = 0
        pending = 0
        active = 0
        processing_times = []
        
        for key in task_keys:
            try:
                import json
                data = json.loads(r.get(key))
                status = data.get('status', '').upper()
                
                if status == 'SUCCESS':
                    completed += 1
                    result = data.get('result', {})
                    if isinstance(result, dict) and 'processing_time' in result:
                        processing_times.append(result['processing_time'])
                elif status == 'FAILURE':
                    failed += 1
                elif status == 'PENDING':
                    pending += 1
                elif status in ('STARTED', 'PROCESSING'):
                    active += 1
            except:
                continue
        
        success_rate = (completed / total * 100) if total > 0 else 0.0
        avg_time = sum(processing_times) / len(processing_times) if processing_times else None
        
        return StatsInfo(
            total_jobs=total,
            completed_jobs=completed,
            failed_jobs=failed,
            pending_jobs=pending,
            active_jobs=active,
            success_rate=round(success_rate, 1),
            avg_processing_time=round(avg_time, 2) if avg_time else None
        )
    except Exception as e:
        return StatsInfo(
            total_jobs=0,
            completed_jobs=0,
            failed_jobs=0,
            pending_jobs=0,
            active_jobs=0,
            success_rate=0.0
        )


# ============================================================================
# Health Check
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    import redis
    
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "redis": False,
        "workers": 0
    }
    
    # Check Redis
    try:
        broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
        r = redis.from_url(broker_url)
        r.ping()
        health["redis"] = True
    except:
        health["status"] = "degraded"
    
    # Check workers
    try:
        inspect = celery_app.control.inspect()
        stats = inspect.stats() or {}
        health["workers"] = len(stats)
        if health["workers"] == 0:
            health["status"] = "degraded"
    except:
        health["status"] = "degraded"
    
    return health


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PIPELINE_API_PORT", 8001))
    host = os.getenv("PIPELINE_API_HOST", "0.0.0.0")
    
    print(f"Starting Pipeline API on {host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=True)

