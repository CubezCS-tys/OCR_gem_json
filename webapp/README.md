# ScanToText — Free OCR Web App

A simple B2C web application that converts scanned PDFs and images into searchable documents.

## Features

| Tier | Input | Output | Price |
|------|-------|--------|-------|
| **Free** | Scanned PDF | Searchable PDF (text-selectable, Ctrl+F) | $0 |
| **Free** | Image (JPG/PNG/TIFF/WebP) | Searchable PDF | $0 |
| **Pro** (Stripe) | Scanned PDF or Image | Pixel-perfect HTML recreation | Pay per document |

## Quick Start

### 1. Install dependencies

```bash
cd webapp
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your Azure DI + Stripe keys
```

### 3. Run

```bash
python run.py
# Open http://localhost:8000
```

## Architecture

```
webapp/
├── app.py              # FastAPI backend
├── ocr_service.py      # Wraps fixed_layout_pipeline (no modifications)
├── stripe_service.py   # Stripe checkout + webhook handling
├── run.py              # Entry point
├── requirements.txt
├── .env.example
├── static/
│   ├── index.html      # Single-page frontend
│   ├── style.css
│   └── app.js
└── uploads/            # Temporary file storage (auto-created)
```

The backend imports from `fixed_layout_pipeline` as a library — **zero modifications** to the existing pipeline code.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_DI_ENDPOINT` | Yes | Azure Document Intelligence endpoint |
| `AZURE_DI_API_KEY` | Yes | Azure Document Intelligence API key |
| `STRIPE_SECRET_KEY` | Yes | Stripe secret key (sk_test_... or sk_live_...) |
| `STRIPE_PUBLISHABLE_KEY` | Yes | Stripe publishable key (pk_test_... or pk_live_...) |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signing secret (whsec_...) |
| `STRIPE_PRICE_ID` | Yes | Stripe Price ID for the HTML conversion product |
| `PRO_PRICE_CENTS` | No | Price in cents (default: 299 = $2.99) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: 50) |
| `BASE_URL` | No | Public URL (default: http://localhost:8000) |
