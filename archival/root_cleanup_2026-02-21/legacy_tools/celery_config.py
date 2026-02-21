"""
Celery configuration for distributed PDF processing.
"""

from celery import Celery
import os

# Redis connection
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Build Redis URL
if REDIS_PASSWORD:
    REDIS_URL = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'
else:
    REDIS_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'

# Create Celery app
app = Celery(
    'pdf_processing',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['tasks']
)

# Configuration
app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Result settings
    result_expires=3600 * 24 * 7,  # Results expire after 7 days
    result_backend_transport_options={'master_name': 'mymaster'},
    
    # Task execution
    task_acks_late=True,  # Acknowledge after task completes
    task_reject_on_worker_lost=True,
    task_track_started=True,
    
    # Rate limiting - Gemini 2.5 Flash: 1000 RPM, 10K RPD (daily limit is bottleneck)
    # Set to ~400/hour = 9,600/day to stay safely under 10K daily limit
    task_default_rate_limit='400/h',  # 400 tasks per hour (~6.7/min)
    
    # Worker settings
    worker_prefetch_multiplier=1,  # Take one task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory management)
    
    # Retry settings
    task_autoretry_for=(Exception,),
    task_retry_kwargs={'max_retries': 3},
    task_retry_backoff=True,
    task_retry_backoff_max=600,  # Max 10 min backoff
    task_retry_jitter=True,
    
    # Priority queues
    task_routes={
        'tasks.process_pdf_task': {'queue': 'pdf_processing'},
        'tasks.rebuild_html_task': {'queue': 'html_rebuild'},
    },
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Task priorities
PRIORITY_URGENT = 9
PRIORITY_HIGH = 7
PRIORITY_NORMAL = 5
PRIORITY_LOW = 3
PRIORITY_BACKGROUND = 1
