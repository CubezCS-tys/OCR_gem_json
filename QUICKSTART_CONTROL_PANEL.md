# Quick Start - OCR Pipeline Control Panel

Get your production control panel running in 3 steps!

## Step 1: Run Setup
```bash
cd /home/yassine/OCR_gem_json
chmod +x setup_control_panel.sh
./setup_control_panel.sh
```

This will:
- Install FastAPI backend dependencies
- Install Next.js frontend dependencies  
- Create start scripts

## Step 2: Start the Control Panel
```bash
./start_control_panel.sh
```

This starts both:
- **Backend API**: http://localhost:8000
- **Frontend UI**: http://localhost:3000

## Step 3: Open the Dashboard
Open your browser to:
```
http://localhost:3000/control-panel
```

## What You'll See

### Dashboard Overview
- ✅ Redis status indicator
- 👷 Active workers count
- ⏰ Queue tasks count
- 💚 System health status
- 📊 CPU/Memory/Disk metrics

### Three Main Tabs

#### 1. Workers Tab
- **Start Workers**: Click "Start" button, set concurrency (4 is good default)
- **View Active Workers**: See all running workers with their task counts
- **Stop/Restart**: Full worker lifecycle management

#### 2. Jobs Tab
- **Single Job**: Select a PDF from dropdown, choose priority/format, submit
- **Batch Jobs**: Enter directory path, submit all PDFs at once
- **PDF Browser**: See all available PDFs with file sizes

#### 3. Tasks Tab
- **Active Tasks**: Live view of all running tasks
- **Task Search**: Look up any task by ID
- **Task Control**: Revoke/cancel tasks if needed

## Quick Workflow Example

```bash
# 1. Start everything
./start_control_panel.sh

# 2. Open http://localhost:3000/control-panel

# 3. Start Workers
#    - Go to Workers tab
#    - Click "Start" (use 4 workers)
#    - Wait for green "online" badges

# 4. Submit a Job
#    - Go to Jobs tab
#    - Select a PDF or enter directory
#    - Click "Submit"

# 5. Monitor Progress
#    - Go to Tasks tab
#    - Watch tasks progress
#    - See SUCCESS when complete
```

## Common Commands

### Start Backend Only
```bash
./start_control_panel_backend.sh
```

### Start Frontend Only
```bash
./start_control_panel_frontend.sh
```

### Stop Everything
```bash
# Ctrl+C in the terminal running start_control_panel.sh
# Or kill the processes:
pkill -f "uvicorn control_panel_api"
pkill -f "next dev"
```

### Check if Services are Running
```bash
# Check backend
curl http://localhost:8000/api/system/status

# Check frontend
curl http://localhost:3000
```

## Troubleshooting

### Port Already in Use
```bash
# Check what's using port 8000
lsof -i :8000

# Check what's using port 3000
lsof -i :3000

# Kill if needed
kill -9 <PID>
```

### Missing Dependencies
```bash
# Backend
pip install fastapi uvicorn psutil

# Frontend
cd viewer-frontend
npm install @radix-ui/react-label @radix-ui/react-progress
```

### Redis Not Running
```bash
# Check Redis
redis-cli ping

# Start Redis
redis-server

# Or with systemd
sudo systemctl start redis
```

## Next Steps

1. **Process Your PDFs**
   - Put PDFs in `/home/yassine/OCR_gem_json/pdfs/`
   - Use batch submission for multiple files
   - Check outputs in `/home/yassine/OCR_gem_json/outputs/`

2. **Monitor Performance**
   - Watch system metrics in dashboard
   - Adjust worker concurrency based on CPU usage
   - Use priority queues for urgent jobs

3. **Explore the API**
   - Visit http://localhost:8000/docs
   - Interactive API documentation
   - Test endpoints directly

## Features Highlights

- 🔴 **Live Updates**: Auto-refresh every 5 seconds
- 🎮 **Full Control**: Start/stop workers from UI
- 📊 **Real-time Monitoring**: See tasks progress live
- 🎯 **Priority Queues**: Control task urgency
- 📦 **Batch Processing**: Submit entire directories
- 🔍 **Task Search**: Look up any task instantly
- 💾 **Caching**: Duplicate PDFs return cached results
- 🎨 **Modern UI**: Clean, professional design

## Tips

- Start with 4 workers for testing
- Use "normal" priority for most jobs
- Check system metrics before heavy processing
- Use batch submission for multiple files
- Monitor the Tasks tab during processing
- Stop workers when done to free resources

Enjoy your professional OCR control panel! 🚀
