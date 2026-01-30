#!/usr/bin/env python3
"""Test Celery setup without running tasks."""

import sys

print("Testing Celery setup...")
print("=" * 60)

# Test 1: Import celery config
try:
    from celery_config import app
    print("✓ Celery config imported")
    print(f"  Broker: {app.conf.broker_url}")
    print(f"  Backend: {app.conf.result_backend}")
except Exception as e:
    print(f"✗ Failed to import celery_config: {e}")
    sys.exit(1)

# Test 2: Import pdf_to_html components
try:
    from pdf_to_html import PDFProcessor, ProcessingConfig, MediaResolution
    print("✓ PDF processing classes imported")
except Exception as e:
    print(f"✗ Failed to import from pdf_to_html: {e}")
    sys.exit(1)

# Test 3: Import celery tasks
try:
    from celery_tasks import process_pdf, process_pdf_batch
    print("✓ Celery tasks imported")
except Exception as e:
    print(f"✗ Failed to import celery_tasks: {e}")
    sys.exit(1)

# Test 4: Check Redis connection
try:
    import redis
    r = redis.Redis(host='localhost', port=6379, db=0)
    r.ping()
    print("✓ Redis connection successful")
except Exception as e:
    print(f"✗ Redis connection failed: {e}")
    print("  Start Redis with: redis-server")

print("=" * 60)
print("✓ Setup complete! Ready to use Celery.")
print("\nNext steps:")
print("1. Start Redis: redis-server")
print("2. Start workers: celery -A celery_config worker --loglevel=info")
print("3. Submit PDFs: python submit_batch.py pdfs/*.pdf --output-dir output/")
