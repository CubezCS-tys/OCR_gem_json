"""
Celery configuration for distributed PDF processing.

This enables processing multiple PDFs in parallel across multiple workers,
with each PDF's chunks also processed in parallel.
"""

from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

# Priority levels for task scheduling (lower = higher priority)
PRIORITY_URGENT = 0
PRIORITY_HIGH = 3
PRIORITY_NORMAL = 5
PRIORITY_LOW = 9

# Celery app configuration
app = Celery(
    'pdf_processor',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
)

# Celery settings
app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,

    # Performance settings
    worker_prefetch_multiplier=1,  # Only fetch one task at a time (important for large PDFs)
    task_acks_late=True,  # Acknowledge task after completion (for reliability)
    worker_max_tasks_per_child=10,  # Restart worker after 10 tasks (prevent memory leaks)

    # Result settings
    result_expires=3600,  # Results expire after 1 hour

    # Rate limiting (prevent API overload)
    task_default_rate_limit='10/m',  # 10 tasks per minute by default
)

# Task routing (optional - for different queues)
app.conf.task_routes = {
    'celery_tasks.process_pdf': {'queue': 'pdf_processing'},
    'celery_tasks.process_pdf_batch': {'queue': 'pdf_processing'},
}
