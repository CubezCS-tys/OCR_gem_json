# PDF to HTML Converter with Google Gemini

Convert Arabic/RTL PDFs to structured HTML using Google Gemini's document understanding API with distributed processing for scale.

## Features

- ✅ **Multi-language support:** Arabic, English, Hebrew, and other RTL languages
- ✅ **Structured extraction:** Headers, footers, paragraphs, tables, images, equations
- ✅ **Math rendering:** LaTeX equations with MathJax
- ✅ **Chunked processing:** Handle large documents (default: 15 pages per chunk)
- ✅ **Image extraction:** Extract and embed images from PDFs
- ✅ **JSON output:** Structured data for further processing
- ✅ **HTML rebuild:** Regenerate HTML from JSON without API calls
- 🚀 **Distributed processing:** Celery + Redis for production scale
- 📊 **Real-time monitoring:** Web dashboard and CLI tools
- 💰 **Cost optimization:** PDF deduplication and result caching

## Quick Start

### Single Document Processing

```bash
# Clone or download this repo
cd OCR_gem_json

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your Gemini API key
export GEMINI_API_KEY="your-api-key-here"
# Or create .env file: echo "GEMINI_API_KEY=your-key" > .env
```

Get your API key at: https://aistudio.google.com/app/apikey

### 2. Process a PDF

```bash
# Basic usage
python pdf_to_html.py pdfs/document.pdf

# With JSON output
python pdf_to_html.py pdfs/document.pdf --format both

# Custom output name
python pdf_to_html.py pdfs/document.pdf output.html

# Extract images (requires PyMuPDF)
python pdf_to_html.py pdfs/document.pdf --extract-images

# High resolution processing
python pdf_to_html.py pdfs/document.pdf -r high
```

### 3. Rebuild HTML from JSON

```bash
# Regenerate HTML without API calls
python rebuild_html.py json_outputs/document.json

# Custom output
python rebuild_html.py json_outputs/document.json -o custom.html

# Re-extract images
python rebuild_html.py json_outputs/document.json --pdf pdfs/document.pdf --extract-images
```

## Production Scale Processing

For batch processing and distributed workloads, use the Celery + Redis pipeline:

### Quick Setup

```bash
# Run automated setup
./deploy.sh

# Or manual setup:
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add GEMINI_API_KEY

# Start Redis
redis-server

# Start Celery workers (submit_jobs.py / tasks.py)
python -m celery -A celery_config worker --loglevel=info --include=tasks

# Or: submit_batch.py / celery_tasks.py
python -m celery -A celery_config worker --loglevel=info --queue=pdf_processing --include=celery_tasks

# Start monitoring dashboard
celery -A celery_config flower
```

### Submit Jobs

```bash
# Batch pipeline (submit_batch.py)
python submit_batch.py pdfs/*.pdf --output-dir outputs/ --monitor

# Production pipeline (submit_jobs.py)
# Single PDF
python submit_jobs.py document.pdf

# Entire directory
python submit_jobs.py --directory ./pdfs --output ./outputs

# High priority processing
python submit_jobs.py urgent.pdf --priority high

# Check task status
python submit_jobs.py --status <task_id>
```

### Monitor Progress

```bash
# Real-time CLI monitoring
python monitor.py

# Check statistics
python monitor.py --stats

# Web dashboard (Flower)
# Open http://localhost:5555
```

**Features:**
- 📦 **PDF deduplication:** Automatic hash-based duplicate detection
- 💾 **Result caching:** 7-day cache for instant retrieval
- ⚡ **Priority queues:** URGENT, HIGH, NORMAL, LOW priorities
- 🔄 **Auto-retry:** Exponential backoff on failures
- 📊 **Real-time monitoring:** CLI and web dashboards
- 🌐 **Multi-worker:** Scale across multiple machines

See [PRODUCTION_SETUP.md](PRODUCTION_SETUP.md) for complete deployment guide.

## Project Structure

```
OCR_gem_json/
├── pdf_to_html.py      # Main script: PDF → JSON → HTML
├── rebuild_html.py     # Rebuild HTML from JSON
├── celery_config.py    # Celery configuration
├── tasks.py            # Celery task definitions
├── submit_jobs.py      # Job submission CLI
├── monitor.py          # Monitoring CLI
├── deploy.sh           # Production deployment script
├── requirements.txt    # Dependencies
├── README.md          # This file
├── PRODUCTION_SETUP.md # Production deployment guide
├── USAGE.md           # Detailed usage guide
├── .env               # API key (git-ignored)
├── venv/              # Virtual environment
├── pdfs/              # Input PDFs
├── json_outputs/      # Structured JSON output
├── html_outputs/      # Generated HTML files
├── archives/          # Old files/experiments
└── docs/              # Additional documentation
```

## Key Scripts

### pdf_to_html.py

Main processing script. Uploads PDF to Gemini, extracts structured data, generates HTML.

**Arguments:**
- `input`: PDF file path
- `output`: Output file path (optional)
- `--format`: Output format (`html`, `json`, `both`)
- `--resolution`: Media resolution (`low`, `medium`, `high`)
- `--chunk-size`: Pages per chunk (default: 15)
- `--extract-images`: Extract actual images
- `--image-dpi`: Image resolution (default: 150)
- `--max-tokens`: Max output tokens (default: 65536)

### rebuild_html.py

Regenerate HTML from existing JSON without API calls.

**Arguments:**
- `json_file`: Input JSON path
- `-o, --output`: Output HTML path
- `--pdf`: Original PDF (for image extraction)
- `--extract-images`: Re-extract images
- `--image-dpi`: Image resolution

## Cost Estimation

Gemini 3 Flash Preview pricing (Jan 2026):
- **Input:** $0.50 per 1M tokens
- **Output:** $3.00 per 1M tokens

Typical cost: **$0.05-$0.10 per 35-page document** (depending on complexity)

## Requirements

- Python 3.10+
- Google Gemini API key
- `google-genai` SDK
- `pydantic` for validation
- `PyMuPDF` (optional, for image extraction)

## Documentation

- [USAGE.md](USAGE.md) - Detailed usage examples
- [docs/claude.md](docs/claude.md) - Architecture notes
- [docs/PDF_PROCESSING.md](docs/PDF_PROCESSING.md) - PDF processing details

## License

MIT License

## Support

For issues or questions, please open an issue on GitHub.
