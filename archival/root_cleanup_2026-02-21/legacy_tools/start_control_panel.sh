#!/bin/bash

echo "Starting OCR Pipeline Control Panel..."
echo ""
echo "Backend API: http://localhost:8000"
echo "Frontend UI: http://localhost:3000"
echo ""

# Start backend in background
cd /home/yassine/OCR_gem_json
source venv/bin/activate 2>/dev/null || true
uvicorn control_panel_api:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend in background
cd /home/yassine/OCR_gem_json/viewer-frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Press Ctrl+C to stop both services"
echo ""

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
