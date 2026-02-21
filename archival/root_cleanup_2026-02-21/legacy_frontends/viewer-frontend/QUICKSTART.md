# OCR Viewer Frontend - Quick Start

## Installation

```bash
cd viewer-frontend

# Make setup script executable (Linux/Mac)
chmod +x setup.sh

# Run setup
./setup.sh

# Or install manually
npm install
```

## Run Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Directory Requirements

The frontend expects these directories in the parent folder:

- `../outputs/` - Contains JSON and HTML files
- `../pdfs/` - Contains PDF files

## First Time Use

1. **Generate some documents** using the Python OCR script first:
   ```bash
   cd ..
   python pdf_to_html.py pdfs/your-file.pdf
   ```

2. **Start the frontend**:
   ```bash
   cd viewer-frontend
   npm run dev
   ```

3. **Open browser** and select a document from the file selector

## Features

- ✅ Side-by-side PDF and HTML comparison
- ✅ Inline text editing (preserves layout)
- ✅ Support for tables, equations, nested lists
- ✅ RTL/LTR text support
- ✅ Auto-regenerate HTML after edits
- ✅ Beautiful production-grade UI

## Troubleshooting

### "No documents found"
- Run the Python OCR script to generate JSON/HTML files first
- Check that files are in `../outputs/` directory

### PDF not loading
- Ensure PDF files are in `../pdfs/` directory
- Check file permissions

### Save fails
- Ensure `rebuild_html_simple.py` exists in parent directory
- Check Python is accessible from command line

## Production Build

```bash
npm run build
npm start
```

## Environment

The app automatically looks for:
- PDFs in `../pdfs/`
- JSON/HTML files in `../outputs/`

No configuration needed!
