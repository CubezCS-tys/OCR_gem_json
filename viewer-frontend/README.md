# OCR Viewer & Editor - Production Frontend

A production-grade Next.js application for comparing original PDFs with OCR-generated HTML and editing OCR content with inline text editing capabilities.

## Features

### 🔍 Side-by-Side Comparison
- View original PDF alongside generated HTML
- Synchronized page navigation
- Responsive layout with resizable panels

### ✏️ Inline Text Editing
- Edit text content directly (text blocks, tables, equations)
- Preserve layout structure (positions, sizes, styles)
- Edit nested lists, merged table cells, and numbered equations
- Support for RTL/LTR text directions

### 💾 JSON as Single Source of Truth
- All edits modify the JSON document structure
- HTML is automatically regenerated after saving
- Undo/reset functionality to discard changes

### 🎨 Production-Grade UI
- Beautiful interface with Tailwind CSS + shadcn/ui
- Dark mode support
- Toast notifications for user feedback
- Loading states and error handling
- Responsive design

### 📄 Document Management
- File selector for choosing documents
- Metadata display (title, author, language)
- Page-by-page navigation
- Support for multi-column layouts

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   PDF File  │────▶│  JSON Data   │────▶│  HTML File  │
│  (Original) │     │ (Structured) │     │ (Generated) │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                           │ Edit
                           ▼
                    ┌──────────────┐
                    │   Frontend   │
                    │   (Next.js)  │
                    └──────────────┘
                           │
                           │ Save
                           ▼
                    ┌──────────────┐
                    │   Python     │
                    │   Renderer   │
                    └──────────────┘
```

## Tech Stack

- **Framework:** Next.js 14 (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS
- **UI Components:** shadcn/ui + Radix UI
- **PDF Viewing:** react-pdf
- **State Management:** Zustand
- **Notifications:** Sonner

## Prerequisites

- Node.js 18+ and npm
- Python 3.10+ (for HTML regeneration)
- The OCR backend must be in the parent directory

## Installation

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

The application will be available at `http://localhost:3000`

## Directory Structure

```
viewer-frontend/
├── app/
│   ├── api/                  # API routes
│   │   ├── files/           # List available documents
│   │   ├── document/        # Load JSON data
│   │   ├── pdf/             # Serve PDF files
│   │   ├── html/            # Serve HTML files
│   │   └── save/            # Save edits & regenerate HTML
│   ├── viewer/              # Main viewer page
│   ├── layout.tsx           # Root layout
│   ├── page.tsx             # Home page (redirects to viewer)
│   └── globals.css          # Global styles
├── components/
│   ├── ui/                  # shadcn/ui components
│   └── viewer/              # Viewer-specific components
│       ├── ViewerLayout.tsx
│       ├── ViewerHeader.tsx
│       ├── FileSelector.tsx
│       ├── ComparisonView.tsx
│       ├── EditorView.tsx
│       ├── PDFViewer.tsx
│       ├── HTMLPreview.tsx
│       ├── TextBlockEditor.tsx
│       └── TableEditor.tsx
├── lib/
│   ├── types.ts             # TypeScript types (matches Python models)
│   ├── store.ts             # Zustand state management
│   └── utils.ts             # Utility functions
└── public/                  # Static assets
```

## Usage

### 1. Comparison Mode
- Select a document from the file selector
- View PDF on the left, HTML on the right
- Navigate between pages
- Compare OCR quality

### 2. Editor Mode
- Switch to "Edit" mode
- Click "Edit" button on any text block or table cell
- Make corrections to OCR mistakes
- Layout properties are preserved (positions, sizes)
- Save changes to regenerate HTML

### 3. Workflow
1. **Load Document** → Choose from available files
2. **Compare** → Review OCR quality in comparison view
3. **Edit** → Fix any OCR errors in editor mode
4. **Save** → Save changes and regenerate HTML
5. **Compare Again** → Verify the updated HTML

## API Routes

### `GET /api/files`
List all available documents (with PDF, JSON, and HTML files)

### `GET /api/document/[fileName]`
Load JSON document data for a specific file

### `GET /api/pdf/[fileName]`
Serve PDF file for viewing

### `GET /api/html/[fileName]`
Serve generated HTML file for preview

### `POST /api/save`
Save edited JSON and trigger HTML regeneration

**Request Body:**
```json
{
  "fileName": "document-name",
  "documentData": { /* DocumentStructure object */ }
}
```

## What You Can Edit

✅ **Editable:**
- Text content in all text blocks
- Table cell contents (headers and data)
- Equation content (LaTeX)
- Captions and labels

❌ **Not Editable (Preserved):**
- Bounding box positions (bbox_top, bbox_left, bbox_width, bbox_height)
- Block types (heading, paragraph, etc.)
- List nesting levels
- Text direction (RTL/LTR)
- Image descriptions and metadata

## Features by Block Type

### Text Blocks
- Edit content while preserving block type, level, and position
- Support for headings (levels 1-6), paragraphs, lists, equations
- Nested list support with visual indicators
- RTL/LTR text direction support

### Tables
- Edit individual cells (headers and data rows)
- Support for merged cells (row_span, col_span)
- Caption editing
- Preserves table structure and position

### Equations
- Edit LaTeX content
- Display/inline math mode indicators
- Equation numbering support
- Mathematical notation preserved

### Images
- Read-only display of image metadata
- Shows image type, description, caption
- Position information displayed

## Production Deployment

```bash
# Build for production
npm run build

# Start production server
npm run start
```

## Environment Variables

Create a `.env.local` file if needed:

```env
# Optional: Custom paths
OUTPUTS_DIR=../outputs
PDFS_DIR=../pdfs
PYTHON_PATH=/usr/bin/python3
```

## Troubleshooting

### PDF not loading
- Ensure PDF files are in `../pdfs` directory
- Check PDF.js worker configuration

### HTML preview blank
- Verify HTML files exist in `../outputs` directory
- Check browser console for errors

### Save fails
- Ensure Python backend is accessible
- Check `rebuild_html.py` script exists
- Verify file permissions

### react-pdf errors
- Canvas errors are normal and suppressed
- Ensure PDF.js worker is loaded from CDN

## Performance Tips

1. **Large PDFs:** Use chunked processing in the OCR backend
2. **Many Pages:** Page navigation is optimized, only current page is rendered
3. **Big Tables:** Inline editing for individual cells avoids loading entire table state
4. **State Management:** Zustand minimizes re-renders

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

Same as parent project

## Support

For issues or questions, refer to the main project documentation or open an issue on GitHub.
