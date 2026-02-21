# OCR Pipeline Control Panel

A professional, production-grade web UI for managing and monitoring your OCR pipeline infrastructure.

## Features

### 🎯 System Overview
- **Real-time Status Dashboard** - Monitor Redis, workers, queues, and system health
- **Live Metrics** - CPU, memory, and disk usage with color-coded alerts
- **Auto-refresh** - Updates every 5 seconds, can be paused

### 👷 Worker Management
- **Start/Stop/Restart Workers** - Full control over Celery workers
- **Configure Concurrency** - Adjust number of parallel workers (1-16)
- **Process Monitoring** - View active worker processes and PIDs
- **Health Status** - Real-time worker status and task counts

### 📋 Job Submission
- **Single Job Submission** - Process individual PDFs with custom settings
- **Batch Processing** - Submit entire directories of PDFs
- **Priority Control** - Set task priority (urgent, high, normal, low)
- **Format Options** - Choose HTML, JSON, or both
- **PDF Browser** - View and select from available PDFs

### 📊 Task Monitoring
- **Active Task List** - View all running, pending, and scheduled tasks
- **Task Search** - Look up any task by ID
- **Task Details** - See full task status, results, and errors
- **Task Revocation** - Cancel running or pending tasks
- **State Tracking** - Visual indicators for task states

### 💎 UI/UX Features
- **Modern Design** - Clean, professional interface with Tailwind CSS
- **Dark Mode Support** - Automatic theme switching
- **Responsive Layout** - Works on desktop and mobile
- **Real-time Updates** - Live data without page refresh
- **Toast Notifications** - Instant feedback for all actions
- **Color-coded Status** - Easy visual identification of states

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (Next.js)                       │
│                   http://localhost:3000                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Workers    │  │     Jobs     │  │    Tasks     │     │
│  │    Panel     │  │    Panel     │  │    Panel     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP REST API
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 Backend API (FastAPI)                        │
│                   http://localhost:8000                      │
│                                                              │
│  Endpoints:                                                  │
│  • GET  /api/system/status                                  │
│  • GET  /api/workers                                        │
│  • POST /api/workers/start                                  │
│  • POST /api/workers/stop                                   │
│  • POST /api/jobs/submit                                    │
│  • POST /api/jobs/submit-batch                              │
│  • GET  /api/tasks                                          │
│  • GET  /api/tasks/{id}                                     │
│  • DELETE /api/tasks/{id}                                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ┌────┴────┐
                    │         │
                    ▼         ▼
            ┌─────────┐  ┌─────────┐
            │  Redis  │  │ Celery  │
            │ Broker  │  │ Workers │
            └─────────┘  └─────────┘
```

## Installation

### Quick Setup

```bash
cd /home/yassine/OCR_gem_json
chmod +x setup_control_panel.sh
./setup_control_panel.sh
```

### Manual Setup

#### Backend

```bash
cd /home/yassine/OCR_gem_json

# Install dependencies
pip install fastapi uvicorn python-multipart psutil

# Or use requirements file
pip install -r requirements_control_panel.txt
```

#### Frontend

```bash
cd viewer-frontend

# Install dependencies
npm install

# Install additional dependencies
npm install @radix-ui/react-label @radix-ui/react-progress
```

## Usage

### Starting the Control Panel

**Option 1: Start Everything Together**
```bash
./start_control_panel.sh
```

**Option 2: Start Separately**
```bash
# Terminal 1 - Backend
./start_control_panel_backend.sh

# Terminal 2 - Frontend
./start_control_panel_frontend.sh
```

**Option 3: Manual Start**
```bash
# Terminal 1 - Backend API
cd /home/yassine/OCR_gem_json
uvicorn control_panel_api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Frontend
cd viewer-frontend
npm run dev
```

### Accessing the Control Panel

Open your browser and navigate to:
```
http://localhost:3000/control-panel
```

The backend API documentation is available at:
```
http://localhost:8000/docs
```

## Workflow Examples

### Starting Workers and Processing PDFs

1. **Navigate to Control Panel**
   - Open `http://localhost:3000/control-panel`

2. **Check System Status**
   - Verify Redis is online (green badge)
   - Check system metrics (CPU, memory, disk)

3. **Start Workers**
   - Go to "Workers" tab
   - Set concurrency (e.g., 4 workers)
   - Click "Start"
   - Wait for workers to appear in the list

4. **Submit Jobs**
   - Go to "Jobs" tab
   - Choose single PDF or batch directory
   - Set priority and output format
   - Click "Submit Job" or "Submit Batch"

5. **Monitor Progress**
   - Go to "Tasks" tab
   - Watch tasks progress from PENDING → ACTIVE → SUCCESS
   - Search for specific task IDs
   - View results when complete

6. **Stop Workers** (when done)
   - Go to "Workers" tab
   - Click "Stop"

### Batch Processing Workflow

1. Place PDFs in `/home/yassine/OCR_gem_json/pdfs/`
2. Start workers with desired concurrency
3. Go to Jobs → Batch submission
4. Enter directory: `/home/yassine/OCR_gem_json/pdfs`
5. Set priority (normal for background, high for urgent)
6. Click "Submit Batch"
7. Monitor progress in Tasks tab
8. Check outputs in `/home/yassine/OCR_gem_json/outputs/`

## API Reference

### System Status
```bash
curl http://localhost:8000/api/system/status
```

### List Workers
```bash
curl http://localhost:8000/api/workers
```

### Start Workers
```bash
curl -X POST http://localhost:8000/api/workers/start \
  -H "Content-Type: application/json" \
  -d '{"concurrency": 4, "queues": ["pdf_processing"]}'
```

### Submit Job
```bash
curl -X POST http://localhost:8000/api/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_path": "/path/to/file.pdf",
    "priority": "normal",
    "format": "both"
  }'
```

### Check Task Status
```bash
curl http://localhost:8000/api/tasks/{task_id}
```

## Troubleshooting

### Backend Won't Start
```bash
# Check if port 8000 is in use
lsof -i :8000

# Install missing dependencies
pip install fastapi uvicorn psutil
```

### Frontend Won't Start
```bash
# Install missing dependencies
cd viewer-frontend
npm install @radix-ui/react-label @radix-ui/react-progress

# Clear cache and rebuild
rm -rf .next node_modules
npm install
npm run dev
```

### Workers Not Starting
```bash
# Check Redis
redis-cli ping

# Check Celery config
python -c "from celery_config import app; print(app.conf)"

# Check for existing workers
ps aux | grep celery
```

### CORS Errors
The backend is configured to allow requests from:
- `http://localhost:3000`
- `http://localhost:3001`

If using a different port, update `control_panel_api.py`:
```python
allow_origins=["http://localhost:YOUR_PORT"]
```

## Tech Stack

### Frontend
- **Next.js 14** - React framework with App Router
- **TypeScript** - Type-safe development
- **Tailwind CSS** - Utility-first styling
- **Radix UI** - Accessible component primitives
- **Lucide React** - Beautiful icons
- **Sonner** - Toast notifications

### Backend
- **FastAPI** - Modern Python web framework
- **Uvicorn** - ASGI server
- **Redis** - Message broker and result backend
- **Celery** - Distributed task queue
- **Psutil** - System metrics

## Features in Detail

### Real-time Updates
- Auto-refresh every 5 seconds
- Pause/resume functionality
- Manual refresh button
- WebSocket support (future)

### Priority Queues
- **Urgent (9)**: Critical tasks, highest priority
- **High (7)**: Important tasks
- **Normal (5)**: Standard processing (default)
- **Low (3)**: Background tasks

### Task States
- **PENDING**: Waiting in queue
- **ACTIVE**: Currently processing
- **RESERVED**: Assigned to worker
- **SCHEDULED**: Scheduled for future execution
- **SUCCESS**: Completed successfully
- **FAILURE**: Failed with error
- **REVOKED**: Cancelled by user

### System Metrics Alerts
- **Green**: Normal operation (< 50%)
- **Yellow**: Moderate usage (50-75%)
- **Orange**: High usage (75-90%)
- **Red**: Critical usage (> 90%)

## Development

### Running in Development Mode
```bash
# Backend with auto-reload
uvicorn control_panel_api:app --reload --port 8000

# Frontend with hot reload
cd viewer-frontend && npm run dev
```

### Building for Production
```bash
cd viewer-frontend
npm run build
npm start
```

## Future Enhancements

- [ ] WebSocket support for real-time updates
- [ ] Task history and analytics
- [ ] Cost tracking dashboard
- [ ] Email/Slack notifications
- [ ] Multi-user authentication
- [ ] API key management
- [ ] Scheduled jobs
- [ ] Performance charts
- [ ] Log viewer
- [ ] Export reports

## License

Same as the main OCR project.

## Support

For issues or questions, check:
1. API docs: `http://localhost:8000/docs`
2. Browser console for frontend errors
3. Backend logs for API errors
4. Celery worker logs for task errors
