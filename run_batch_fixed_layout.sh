#!/bin/bash
# Quick start script for batch processing scanned PDFs with fixed_layout_pipeline

# Activate virtual environment
source venv/bin/activate

# Process all scanned PDFs with 4 workers
python batch_process_fixed_layout.py \
  --input pdfs/2026/2026/scanned \
  --output batch_fixed_output \
  --workers 4 \
  --verbose

# Alternative: Use 8 workers for faster processing (requires more RAM)
# python batch_process_fixed_layout.py \
#   --input pdfs/2026/2026/scanned \
#   --output batch_fixed_output \
#   --workers 8 \
#   --verbose
