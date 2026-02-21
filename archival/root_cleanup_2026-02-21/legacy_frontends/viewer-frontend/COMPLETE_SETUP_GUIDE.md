# OCR Viewer Frontend - Complete Setup Guide

## 🎯 Project Overview

A production-grade Next.js 14 application for viewing, comparing, and editing OCR-generated documents with:
- **Side-by-side comparison** of original PDF and generated HTML
- **Inline text editing** with JSON as single source of truth
- **Beautiful UI** with Tailwind CSS and shadcn/ui components
- **Production features**: error handling, loading states, toast notifications

---

## 📁 Project Structure

```
viewer-frontend/
├── app/
│   ├── api/                          # Backend API routes
│   │   ├── files/route.ts           # GET - List available documents
│   │   ├── document/[fileName]/     # GET - Load JSON data
│   │   ├── pdf/[fileName]/          # GET - Serve PDF files
│   │   ├── html/[fileName]/         # GET - Serve HTML files
│   │   └── save/route.ts            # POST - Save edits & regenerate
│   ├── viewer/page.tsx              # Main viewer page
│   ├── layout.tsx                   # Root layout with Toaster
│   ├── page.tsx                     # Home (redirects to /viewer)
│   └── globals.css                  # Tailwind + custom styles
│
├── components/
│   ├── ui/                          # shadcn/ui components
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── select.tsx
│   │   ├── tabs.tsx
│   │   ├── textarea.tsx
│   │   ├── separator.tsx
│   │   ├── card.tsx
│   │   └── badge.tsx
│   │
│   └── viewer/                      # Custom viewer components
│       ├── ViewerLayout.tsx         # Main layout coordinator
│       ├── ViewerHeader.tsx         # Header with nav & actions
│       ├── FileSelector.tsx         # Document selector modal
│       ├── ComparisonView.tsx       # Split PDF/HTML view
│       ├── EditorView.tsx           # Editing interface
│       ├── PDFViewer.tsx            # react-pdf integration
│       ├── HTMLPreview.tsx          # Iframe HTML preview
│       ├── TextBlockEditor.tsx      # Text block editor
│       └── TableEditor.tsx          # Table cell editor
│
├── lib/
│   ├── types.ts                     # TypeScript types (matches Python)
│   ├── store.ts                     # Zustand state management
│   └── utils.ts                     # Utility functions
│
├── public/                          # Static assets
├── package.json                     # Dependencies
├── tsconfig.json                    # TypeScript config
├── tailwind.config.ts               # Tailwind configuration
├── next.config.js                   # Next.js configuration
├── README.md                        # Full documentation
├── QUICKSTART.md                    # Quick start guide
└── setup.sh                         # Auto setup script
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd viewer-frontend

# Option A: Use setup script (Linux/Mac)
chmod +x setup.sh
./setup.sh

# Option B: Manual installation
npm install
```

### 2. Ensure Backend Files Exist

The viewer needs these directories in the parent folder:

```
OCR_gem_json/
├── pdfs/                 # Original PDF files
├── outputs/              # Generated JSON & HTML files
├── rebuild_html_simple.py # HTML regeneration script (created)
└── viewer-frontend/      # This Next.js app
```

### 3. Generate Some Documents (If None Exist)

```bash
cd ..  # Go to parent directory
python pdf_to_html.py pdfs/your-document.pdf
```

This creates:
- `outputs/your-document.json` (structured data)
- `outputs/your-document.html` (rendered HTML)

### 4. Start Development Server

```bash
cd viewer-frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

---

## 🎨 Features

### Comparison Mode
- **Left Panel**: Original PDF rendered with react-pdf
- **Right Panel**: Generated HTML in iframe
- **Synchronized Navigation**: Both panels show the same page
- **Purpose**: Verify OCR quality before editing

### Editor Mode
- **Text Blocks**: Edit content inline (headings, paragraphs, lists, equations)
- **Tables**: Click any cell to edit (headers and data rows)
- **Metadata Display**: Shows block types, positions, text direction
- **Layout Preservation**: All edits preserve bounding boxes and structure
- **Unsaved Changes Warning**: Yellow banner when changes pending

### File Management
- **File Selector**: Modal to choose from available documents
- **Metadata Display**: Shows title, author, language, page count
- **Page Navigation**: Dropdown + arrow buttons for quick page switching
- **View Mode Toggle**: Switch between Comparison and Editor

### Production Features
- ✅ **Error Boundaries**: Graceful error handling
- ✅ **Loading States**: Spinners during data fetching
- ✅ **Toast Notifications**: Success/error feedback
- ✅ **Responsive Design**: Works on desktop and tablets
- ✅ **Dark Mode Support**: Automatic theme switching
- ✅ **Type Safety**: Full TypeScript coverage
- ✅ **RTL Support**: Proper handling of Arabic/Hebrew text

---

## 🔧 Architecture

### Single Source of Truth: JSON

```
┌────────────┐
│  PDF File  │  (Read-only, for comparison)
└────────────┘

┌────────────┐     Edit      ┌──────────────┐
│ JSON Data  │ ◄──────────── │   Frontend   │
│  (Master)  │               │   (Next.js)  │
└────────────┘               └──────────────┘
      │
      │ Save Triggered
      ▼
┌────────────┐     Regenerate   ┌──────────────┐
│   Python   │ ◄──────────────  │  Save API    │
│  Renderer  │                  │   Route      │
└────────────┘                  └──────────────┘
      │
      ▼
┌────────────┐
│ HTML File  │  (Auto-generated)
└────────────┘
```

### Data Flow

1. **Load**: User selects document → API loads JSON → Frontend displays
2. **Edit**: User edits text → Changes stored in Zustand state
3. **Save**: User clicks "Save" → JSON updated → Python regenerates HTML
4. **View**: Updated HTML displayed in comparison view

### State Management (Zustand)

```typescript
{
  availableFiles: FileInfo[]        // List of documents
  currentFile: FileInfo | null      // Selected document
  documentData: DocumentStructure   // Editable data
  originalDocumentData: DocumentStructure  // For reset
  currentPage: number
  viewMode: "comparison" | "editor"
  hasUnsavedChanges: boolean
  editingBlockId: string | null
}
```

---

## 📝 What You Can Edit

### ✅ Editable
- Text content in all text blocks
- Table cell values (headers and rows)
- Equation LaTeX content
- Captions and labels

### ❌ Not Editable (Auto-Preserved)
- Bounding box coordinates (bbox_top, bbox_left, bbox_width, bbox_height)
- Block types (heading, paragraph, list_item, etc.)
- Heading levels (h1-h6)
- List nesting levels
- Text direction (RTL/LTR)
- Image metadata
- Table structure (row/column counts)

**Why?** Layout information ensures visual structure remains intact. Only OCR mistakes (text content) need correction.

---

## 🔌 API Routes

### `GET /api/files`
Returns list of available documents with their file paths.

**Response:**
```json
{
  "files": [
    {
      "name": "document-name",
      "pdfPath": "document-name.pdf",
      "jsonPath": "document-name.json",
      "htmlPath": "document-name.html"
    }
  ]
}
```

### `GET /api/document/[fileName]`
Loads JSON document structure for editing.

**Response:** Full `DocumentStructure` object

### `GET /api/pdf/[fileName]`
Streams PDF file for react-pdf viewer.

**Response:** PDF binary with `Content-Type: application/pdf`

### `GET /api/html/[fileName]`
Returns generated HTML for preview.

**Response:** HTML string with `Content-Type: text/html`

### `POST /api/save`
Saves edited JSON and triggers HTML regeneration.

**Request:**
```json
{
  "fileName": "document-name",
  "documentData": { /* Full DocumentStructure */ }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Document saved and HTML regenerated",
  "htmlPath": "document-name.html"
}
```

---

## 🎯 Component Guide

### ViewerLayout
Main coordinator that:
- Loads available files on mount
- Handles view mode switching
- Shows loading/error states
- Renders FileSelector modal

### ViewerHeader
Top navigation bar with:
- File name and metadata display
- Page navigation (prev/next, dropdown)
- View mode toggle (Comparison/Editor)
- Save and Reset buttons (in Editor mode)
- Unsaved changes warning banner

### ComparisonView
Split panel layout:
- Left: PDFViewer component
- Right: HTMLPreview component
- Synchronized to current page

### EditorView
Scrollable page editor showing:
- Page metadata (multi-column, RTL indicators)
- Info banner explaining editing rules
- TextBlockEditor for each text block
- TableEditor for each table
- Read-only image information

### TextBlockEditor
Inline editor for text blocks:
- Shows block type badge (color-coded)
- Displays metadata (level, direction, equation number)
- Edit/Save/Cancel buttons
- Preserves position information (read-only display)

### TableEditor
Inline table cell editor:
- Click any cell to edit
- Supports header and data rows
- Save/Cancel for each cell
- Preserves table structure

---

## 🛠️ Development Tips

### Hot Reload
Next.js watches all files. Changes to components auto-refresh the browser.

### State Debugging
```typescript
// In any component
const store = useViewerStore();
console.log(store);  // Inspect entire state
```

### API Testing
```bash
# Test file list
curl http://localhost:3000/api/files

# Test document load
curl http://localhost:3000/api/document/your-file

# Test save
curl -X POST http://localhost:3000/api/save \
  -H "Content-Type: application/json" \
  -d '{"fileName":"test","documentData":{...}}'
```

### Adding New Features

1. **New UI Component**: Add to `components/ui/` (shadcn style)
2. **New Viewer Component**: Add to `components/viewer/`
3. **New API Route**: Add to `app/api/[route-name]/route.ts`
4. **New State**: Update `lib/store.ts`
5. **New Types**: Update `lib/types.ts` (keep in sync with Python models)

---

## 📦 Dependencies Explained

### Core
- **next**: React framework with server/client rendering
- **react** + **react-dom**: UI library
- **typescript**: Type safety

### UI/Styling
- **tailwindcss**: Utility-first CSS
- **tailwindcss-animate**: Animation utilities
- **class-variance-authority**: Component variant management
- **clsx** + **tailwind-merge**: Class name utilities

### Components
- **@radix-ui/react-\***: Headless UI primitives (accessible)
- **lucide-react**: Icon library
- **sonner**: Toast notifications

### PDF
- **react-pdf**: PDF viewer
- **pdfjs-dist**: PDF.js library

### State/Data
- **zustand**: Lightweight state management
- **axios**: HTTP client

---

## 🚢 Production Deployment

### Build

```bash
npm run build
```

Creates optimized production build in `.next/` directory.

### Start Production Server

```bash
npm start
```

Runs on port 3000 by default.

### Environment Variables

Create `.env.local` for custom configuration:

```env
# Optional: Custom directories
OUTPUTS_DIR=../outputs
PDFS_DIR=../pdfs
PYTHON_PATH=/usr/bin/python3

# Optional: Port
PORT=3000
```

### Deployment Options

1. **Vercel**: `vercel deploy` (easiest)
2. **Docker**: Create Dockerfile with Node 18+
3. **PM2**: Process manager for Node.js apps
4. **Nginx**: Reverse proxy to Node.js

Note: Python backend must be accessible for HTML regeneration.

---

## 🐛 Troubleshooting

### "No documents found"
**Cause**: No JSON files in `../outputs/`
**Fix**: Run Python OCR script first: `python pdf_to_html.py pdfs/file.pdf`

### PDF not loading
**Cause**: PDF file missing or wrong path
**Fix**: 
- Check PDF exists in `../pdfs/`
- Verify file permissions
- Check browser console for errors

### HTML preview blank
**Cause**: HTML file missing or iframe blocked
**Fix**:
- Ensure HTML file exists in `../outputs/`
- Check browser console
- Try regenerating: delete HTML and re-save in editor

### Save fails with "Python error"
**Cause**: Python script not found or execution failed
**Fix**:
- Verify `rebuild_html_simple.py` exists in parent directory
- Test Python script manually: `python3 rebuild_html_simple.py test.json test.html`
- Check Python dependencies installed

### react-pdf canvas errors
**Cause**: PDF.js uses canvas, some warnings are normal
**Fix**: Ignore warnings. PDF still renders correctly.

### State not updating
**Cause**: Zustand store mutation instead of immutable update
**Fix**: Always create new objects: `set({ data: {...oldData} })`

---

## 📚 Additional Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [shadcn/ui](https://ui.shadcn.com/)
- [Zustand](https://github.com/pmndrs/zustand)
- [react-pdf](https://github.com/wojtekmaj/react-pdf)

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open Pull Request

---

## ✨ Summary

You now have a **production-grade OCR viewer and editor** with:

✅ Side-by-side comparison
✅ Inline text editing (text only, layout preserved)
✅ JSON as single source of truth
✅ Auto HTML regeneration
✅ Beautiful, responsive UI
✅ Full TypeScript type safety
✅ Error handling and loading states
✅ RTL/LTR support
✅ Dark mode support
✅ Toast notifications

**Ready for production use!** 🚀
