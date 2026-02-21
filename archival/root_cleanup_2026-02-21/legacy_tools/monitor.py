"""
Monitor Celery task progress and worker status.
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from celery import Celery
from celery.result import AsyncResult
from prettytable import PrettyTable


def get_celery_app():
    """Get Celery app instance."""
    from celery_config import app
    return app


def get_worker_stats(app: Celery) -> dict:
    """
    Get statistics about active workers.
    
    Args:
        app: Celery app instance
    
    Returns:
        dict with worker statistics
    """
    inspect = app.control.inspect()
    
    stats = inspect.stats()
    active = inspect.active()
    registered = inspect.registered()
    
    if not stats:
        return {'workers': 0, 'active_tasks': 0}
    
    worker_count = len(stats)
    active_task_count = sum(len(tasks) for tasks in (active or {}).values())
    
    return {
        'workers': worker_count,
        'active_tasks': active_task_count,
        'stats': stats,
        'active': active,
        'registered': registered
    }


def get_queue_length(app: Celery, queue_name: str = 'celery') -> int:
    """
    Get number of tasks in queue.
    
    Args:
        app: Celery app instance
        queue_name: Name of queue
    
    Returns:
        Number of tasks in queue
    """
    try:
        from redis import Redis
        redis_client = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD')
        )
        
        return redis_client.llen(queue_name)
    except Exception as e:
        print(f"Warning: Could not get queue length: {e}")
        return 0


def monitor_tasks(app: Celery, interval: int = 5, max_iterations: int = None):
    """
    Monitor task progress in real-time.
    
    Args:
        app: Celery app instance
        interval: Update interval in seconds
        max_iterations: Max iterations (None for infinite)
    """
    iteration = 0
    
    try:
        while max_iterations is None or iteration < max_iterations:
            os.system('clear' if os.name == 'posix' else 'cls')
            
            print("=" * 80)
            print(f"Celery Task Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 80)
            
            # Worker stats
            stats = get_worker_stats(app)
            
            print(f"\n📊 Workers: {stats['workers']} active")
            print(f"⚡ Active tasks: {stats['active_tasks']}")
            
            # Queue lengths
            queues = ['celery', 'pdf_processing', 'html_rebuild']
            print(f"\n📋 Queue Status:")
            for queue in queues:
                length = get_queue_length(app, queue)
                print(f"  • {queue}: {length} tasks")
            
            # Active tasks
            if stats.get('active'):
                print(f"\n🔄 Active Tasks:")
                table = PrettyTable(['Worker', 'Task', 'Started'])
                table.align = 'l'
                
                for worker, tasks in stats['active'].items():
                    worker_name = worker.split('@')[1] if '@' in worker else worker
                    for task in tasks:
                        task_name = task['name'].split('.')[-1]
                        started = datetime.fromtimestamp(task['time_start'])
                        elapsed = datetime.now() - started
                        
                        table.add_row([
                            worker_name[:20],
                            task_name[:30],
                            f"{int(elapsed.total_seconds())}s ago"
                        ])
                
                print(table)
            
            # Registered tasks
            if stats.get('registered'):
                print(f"\n📝 Registered Tasks:")
                for worker, tasks in stats['registered'].items():
                    worker_name = worker.split('@')[1] if '@' in worker else worker
                    print(f"  • {worker_name}: {len(tasks)} task types")
            
            print(f"\n⏱️  Updating every {interval}s... (Ctrl+C to stop)")
            
            time.sleep(interval)
            iteration += 1
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


def check_task(task_id: str):
    """
    Check status of a specific task.
    
    Args:
        task_id: Task ID to check
    """
    task = AsyncResult(task_id)
    
    print("=" * 80)
    print(f"Task Status: {task_id}")
    print("=" * 80)
    
    print(f"\nState: {task.state}")
    print(f"Ready: {task.ready()}")
    print(f"Successful: {task.successful()}")
    print(f"Failed: {task.failed()}")
    
    if task.ready():
        if task.successful():
            result = task.result
            print("\n✓ Result:")
            for key, value in result.items():
                if isinstance(value, (str, int, float, bool)):
                    print(f"  • {key}: {value}")
        else:
            print(f"\n✗ Error: {task.info}")
    elif task.state == 'PROCESSING':
        print(f"\nℹ️  Info: {task.info}")
    elif task.state == 'PENDING':
        print("\n⏳ Task is queued, waiting to start...")


def purge_queue(app: Celery, queue_name: str = None):
    """
    Purge tasks from queue.
    
    Args:
        app: Celery app instance
        queue_name: Queue to purge (None for all)
    """
    if queue_name:
        count = app.control.purge()
        print(f"Purged {count} tasks from {queue_name}")
    else:
        count = app.control.purge()
        print(f"Purged {count} tasks from all queues")


def revoke_task(task_id: str, terminate: bool = False):
    """
    Revoke (cancel) a task.
    
    Args:
        task_id: Task ID to revoke
        terminate: Whether to terminate if already executing
    """
    task = AsyncResult(task_id)
    task.revoke(terminate=terminate)
    
    action = "terminated" if terminate else "revoked"
    print(f"Task {task_id} {action}")


def show_statistics():
    """Show overall processing statistics."""
    try:
        from redis import Redis
        redis_client = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD'),
            decode_responses=True
        )
        
        # Get cached results
        cache_keys = list(redis_client.scan_iter("pdf_result:*"))
        
        print("=" * 80)
        print("Processing Statistics")
        print("=" * 80)
        
        print(f"\n📦 Cached Results: {len(cache_keys)}")
        
        # Calculate total costs
        total_cost = 0
        total_pages = 0
        total_tokens = 0
        
        if cache_keys:
            print("\nRecent Processing Jobs:")
            table = PrettyTable(['PDF Hash', 'Pages', 'Time (s)', 'Cost ($)', 'Age'])
            table.align = 'l'
            
            for key in cache_keys[-10:]:  # Show last 10
                import json
                data = json.loads(redis_client.get(key))
                
                pdf_hash = data.get('pdf_hash', 'N/A')[:16]
                pages = data.get('pages', 0)
                proc_time = data.get('processing_time', 0)
                cost_info = data.get('cost', {})
                cost = cost_info.get('total_cost_usd', 0)
                timestamp = data.get('timestamp', 0)
                
                total_pages += pages
                total_cost += cost
                total_tokens += cost_info.get('total_tokens', 0)
                
                if timestamp:
                    age = datetime.now() - datetime.fromtimestamp(timestamp)
                    age_str = f"{int(age.total_seconds() / 3600)}h ago"
                else:
                    age_str = "Unknown"
                
                table.add_row([
                    pdf_hash,
                    pages,
                    f"{proc_time:.1f}",
                    f"${cost:.6f}" if cost else "N/A",
                    age_str
                ])
            
            print(table)
            
            # Summary statistics
            print(f"\n💰 Total Cost (last 10): ${total_cost:.4f}")
            print(f"📄 Total Pages: {total_pages:,}")
            print(f"🔤 Total Tokens: {total_tokens:,}")
            if total_pages > 0:
                print(f"💵 Cost per Page: ${total_cost / total_pages:.6f}")
        
    except Exception as e:
        print(f"Error fetching statistics: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Celery tasks and workers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor in real-time
  python monitor.py
  
  # Check specific task
  python monitor.py --task 1a2b3c4d-5e6f-7g8h-9i0j
  
  # Show statistics
  python monitor.py --stats
  
  # Purge all queued tasks
  python monitor.py --purge
  
  # Cancel a running task
  python monitor.py --revoke 1a2b3c4d-5e6f --terminate
        """
    )
    
    parser.add_argument(
        '--task', '-t',
        help='Check status of specific task ID'
    )
    
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=5,
        help='Update interval in seconds (default: 5)'
    )
    
    parser.add_argument(
        '--stats', '-s',
        action='store_true',
        help='Show processing statistics'
    )
    
    parser.add_argument(
        '--purge',
        action='store_true',
        help='Purge all queued tasks'
    )
    
    parser.add_argument(
        '--revoke',
        help='Revoke (cancel) a task by ID'
    )
    
    parser.add_argument(
        '--terminate',
        action='store_true',
        help='Terminate task if already running (use with --revoke)'
    )
    
    args = parser.parse_args()
    
    app = get_celery_app()
    
    # Check specific task
    if args.task:
        check_task(args.task)
        return 0
    
    # Show statistics
    if args.stats:
        show_statistics()
        return 0
    
    # Purge queue
    if args.purge:
        confirm = input("Are you sure you want to purge all queued tasks? (yes/no): ")
        if confirm.lower() == 'yes':
            purge_queue(app)
        else:
            print("Cancelled.")
        return 0
    
    # Revoke task
    if args.revoke:
        revoke_task(args.revoke, terminate=args.terminate)
        return 0
    
    # Default: monitor in real-time
    print("Starting real-time monitoring...")
    print("Press Ctrl+C to stop\n")
    time.sleep(2)
    
    monitor_tasks(app, interval=args.interval)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
