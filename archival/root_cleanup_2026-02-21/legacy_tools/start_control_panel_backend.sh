#!/bin/bash
cd /home/yassine/OCR_gem_json
source venv/bin/activate 2>/dev/null || true
uvicorn control_panel_api:app --host 0.0.0.0 --port 8000 --reload
