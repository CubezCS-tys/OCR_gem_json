#!/bin/bash

# Setup script for OCR Pipeline Control Panel

set -e

echo "=========================================="
echo "OCR Pipeline Control Panel Setup"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Backend setup
echo -e "\n${YELLOW}Setting up backend API...${NC}"
cd /home/yassine/OCR_gem_json

# Install backend dependencies
if [ -f "requirements_control_panel.txt" ]; then
    echo "Installing FastAPI dependencies..."
    pip install -r requirements_control_panel.txt
else
    echo "Installing FastAPI manually..."
    pip install fastapi uvicorn python-multipart psutil
fi

echo -e "${GREEN}✓ Backend dependencies installed${NC}"

# Frontend setup
echo -e "\n${YELLOW}Setting up frontend...${NC}"
cd viewer-frontend

# Install Node dependencies
if [ ! -d "node_modules" ]; then
    echo "Installing Node.js dependencies..."
    npm install
    npm install @radix-ui/react-label @radix-ui/react-progress
else
    echo "Updating Node.js dependencies..."
    npm install @radix-ui/react-label @radix-ui/react-progress --save
fi

echo -e "${GREEN}✓ Frontend dependencies installed${NC}"

# Create start scripts
echo -e "\n${YELLOW}Creating start scripts...${NC}"

cd /home/yassine/OCR_gem_json

# Backend start script
cat > start_control_panel_backend.sh << 'EOF'
#!/bin/bash
cd /home/yassine/OCR_gem_json
source venv/bin/activate 2>/dev/null || true
uvicorn control_panel_api:app --host 0.0.0.0 --port 8000 --reload
EOF

# Frontend start script
cat > start_control_panel_frontend.sh << 'EOF'
#!/bin/bash
cd /home/yassine/OCR_gem_json/viewer-frontend
npm run dev
EOF

# Combined start script
cat > start_control_panel.sh << 'EOF'
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
EOF

# Make scripts executable
chmod +x start_control_panel_backend.sh
chmod +x start_control_panel_frontend.sh
chmod +x start_control_panel.sh

echo -e "${GREEN}✓ Start scripts created${NC}"

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "To start the control panel:"
echo ""
echo "Option 1 - Start everything together:"
echo "  ./start_control_panel.sh"
echo ""
echo "Option 2 - Start separately:"
echo "  Terminal 1: ./start_control_panel_backend.sh"
echo "  Terminal 2: ./start_control_panel_frontend.sh"
echo ""
echo "Then open: http://localhost:3000/control-panel"
echo ""
echo "=========================================="
