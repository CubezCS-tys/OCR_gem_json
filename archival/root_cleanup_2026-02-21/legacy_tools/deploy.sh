#!/bin/bash

# Production deployment script for PDF OCR pipeline
# Run with: ./deploy.sh

set -e  # Exit on error

echo "=========================================="
echo "PDF OCR Production Pipeline Setup"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo -e "\n${YELLOW}Checking Python version...${NC}"
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then 
    echo -e "${RED}Error: Python 3.10+ required (found $python_version)${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $python_version${NC}"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo -e "\n${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "\n${GREEN}✓ Virtual environment exists${NC}"
fi

# Activate virtual environment
echo -e "\n${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Upgrade pip
echo -e "\n${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip

# Install dependencies
echo -e "\n${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check for .env file
if [ ! -f ".env" ]; then
    echo -e "\n${YELLOW}Creating .env file from template...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ .env file created${NC}"
    echo -e "${YELLOW}⚠ Please edit .env and add your GEMINI_API_KEY${NC}"
else
    echo -e "\n${GREEN}✓ .env file exists${NC}"
fi

# Check for GEMINI_API_KEY
source .env
if [ -z "$GEMINI_API_KEY" ] || [ "$GEMINI_API_KEY" = "your_api_key_here" ]; then
    echo -e "${YELLOW}⚠ GEMINI_API_KEY not configured in .env${NC}"
    echo -e "  Please add your API key before starting workers"
fi

# Check Redis
echo -e "\n${YELLOW}Checking Redis...${NC}"
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &> /dev/null; then
        echo -e "${GREEN}✓ Redis is running${NC}"
    else
        echo -e "${YELLOW}⚠ Redis is installed but not running${NC}"
        echo -e "  Start with: ${NC}redis-server${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Redis not installed${NC}"
    echo ""
    echo "Install Redis:"
    echo "  Ubuntu/Debian: sudo apt install redis-server"
    echo "  macOS: brew install redis"
    echo "  Docker: docker run -d -p 6379:6379 redis:latest"
fi

# Create necessary directories
echo -e "\n${YELLOW}Creating directories...${NC}"
mkdir -p pdfs
mkdir -p json_outputs
mkdir -p html_outputs
mkdir -p logs
echo -e "${GREEN}✓ Directories created${NC}"

# Test import
echo -e "\n${YELLOW}Testing imports...${NC}"
python3 -c "import celery; import redis; import google.genai; print('✓ All imports successful')" || {
    echo -e "${RED}✗ Import test failed${NC}"
    exit 1
}
echo -e "${GREEN}✓ All imports successful${NC}"

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start Redis (if not running):"
echo "   redis-server"
echo ""
echo "2. Start Celery workers:"
echo "   celery -A celery_config worker --loglevel=info"
echo ""
echo "3. (Optional) Start monitoring:"
echo "   python monitor.py"
echo "   # or web UI:"
echo "   celery -A celery_config flower"
echo ""
echo "4. Submit jobs:"
echo "   python submit_jobs.py my_document.pdf"
echo "   # or directory:"
echo "   python submit_jobs.py --directory ./pdfs"
echo ""
echo "Documentation:"
echo "   - Production setup: PRODUCTION_SETUP.md"
echo "   - Usage guide: README.md"
echo ""
echo "=========================================="
