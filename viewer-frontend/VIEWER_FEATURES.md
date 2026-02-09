# OCR Viewer - Enhanced Features Guide

## Overview

The OCR Viewer has been significantly enhanced with robust features for viewing, comparing, editing, and exporting OCR-processed documents. This guide covers all the new features and how to use them.

## Table of Contents

1. [PDF Viewer Enhancements](#pdf-viewer-enhancements)
2. [Comparison View Features](#comparison-view-features)
3. [Editor Capabilities](#editor-capabilities)
4. [Export & Download](#export--download)
5. [Search Functionality](#search-functionality)
6. [Keyboard Shortcuts](#keyboard-shortcuts)
7. [Accessibility Features](#accessibility-features)

---

## PDF Viewer Enhancements

### Advanced Zoom Controls

- **Zoom In/Out**: Fine-grained control over PDF zoom levels (50% to 300%)
- **Fit Modes**:
  - **Fit Width**: Automatically adjusts PDF to fit the container width
  - **Fit Page**: Scales the PDF to fit the entire page
  - **Custom**: Manual zoom level control
- **Reset Zoom**: Quickly return to 100% zoom

### Page Rotation

- Rotate PDFs in 90-degree increments for easier reading
- Useful for documents that were scanned in incorrect orientations

### Thumbnail View

- Toggle a thumbnail sidebar showing all pages
- Click thumbnails for quick navigation
- Visual indicator shows the current page

### Fullscreen Mode

- Immersive fullscreen viewing experience
- Eliminates distractions for focused document review
- Easy toggle in and out

### Keyboard Navigation

All PDF viewer controls can be accessed via keyboard:

```
← / ↑       Navigate to previous page
→ / ↓       Navigate to next page
Home        Jump to first page
End         Jump to last page
Ctrl/Cmd +  Zoom in
Ctrl/Cmd -  Zoom out
Ctrl/Cmd 0  Reset zoom to 100%
Ctrl/Cmd R  Rotate page 90 degrees
Ctrl/Cmd F  Toggle fullscreen
```

---

## Comparison View Features

### Synchronized Scrolling

- **Auto-Sync Mode**: PDF and HTML views scroll together automatically
- **Independent Scrolling**: Disable sync to scroll each pane independently
- Visual indicator shows current sync status

### Adjustable Split Ratio

- **Draggable Divider**: Click and drag the center divider to adjust split
- **Quick Presets**: One-click buttons for common ratios:
  - 30/70 (PDF focused)
  - 50/50 (Equal split)
  - 70/30 (HTML focused)
- Ratio persists across sessions

### Overlay Comparison Mode

- **Visual Overlay**: View PDF and HTML overlaid on each other
- **Blend Modes**: Automatic blend mode for easy difference detection
- **Toggle**: Switch between split and overlay modes instantly

### Features Summary

| Feature | Description | Control |
|---------|-------------|---------|
| Sync Scrolling | Synchronized scrolling between panes | Toggle button |
| Split Ratio | Adjustable view split | Drag divider or use presets |
| Overlay Mode | Visual overlay comparison | Button in toolbar |

---

## Editor Capabilities

### Inline Text Editing

- **Edit Text Blocks**: Click edit icon to modify any text block
- **Rich Editing**: Preserve formatting including:
  - Text direction (LTR/RTL)
  - Indentation levels
  - Block types (heading, paragraph, list)
- **Save/Cancel**: Explicit save or cancel for each edit

### Table Editing

Full-featured table editing capabilities:

#### Cell Editing
- Click edit icon on any cell to modify content
- Inline editing with save/cancel options
- Preserves cell structure (colspan, rowspan)

#### Row Management
- **Add Row**: Insert new row at the end of table
- **Remove Row**: Delete any row (hover to see button)

#### Column Management
- **Add Column**: Append new column to table
- **Remove Column**: Delete column (hover header to see button)

### Undo/Redo System

- **Full History**: Complete undo/redo stack for all edits
- **Visual Indicators**: Buttons disabled when at history boundaries
- **Keyboard Shortcuts**: Ctrl+Z (undo), Ctrl+Y (redo)

### Auto-Save Indicator

- **Visual Feedback**: Save button highlights when changes exist
- **Persistent Storage**: Changes saved to server on explicit save
- **Unsaved Changes Warning**: Clear indication of unsaved work

### Drag and Reorder

- **Visual Handle**: Grab icon appears on hover
- **Drag to Reorder**: Drag text blocks to reorder (future enhancement)

---

## Export & Download

Comprehensive export options for maximum flexibility:

### Export Formats

#### JSON Export
- **Full Document JSON**: Complete document with all metadata
- **Current Page JSON**: Export just the active page
- **Formatted Output**: Pretty-printed with 2-space indentation
- **Use Case**: API integration, data processing

#### Markdown Export
- **Full Document Markdown**: All pages with proper formatting
- **Current Page Markdown**: Single page export
- **Features**:
  - Headers and footers as blockquotes
  - Tables with proper markdown syntax
  - Headings converted to markdown headers
  - Lists and quotes preserved
- **Use Case**: Documentation, static site generation

#### Plain Text Export
- **Full Document Text**: All content as plain text
- **Current Page Text**: Single page text export
- **Features**:
  - Clean, readable format
  - Page separators
  - Table data preserved
- **Use Case**: Text analysis, simple backups

#### HTML Export
- **Standalone HTML**: Self-contained HTML file
- **Features**:
  - Embedded CSS styling
  - Semantic HTML structure
  - Print-optimized
  - Page breaks for multi-page documents
- **Use Case**: Sharing, printing, web publishing

### Export Menu

Access all export options from the dropdown menu in the header:

```
Export → Full Document (JSON)
      → Current Page (JSON)
      → Full Document (Markdown)
      → Current Page (Markdown)
      → Full Document (Text)
      → Current Page (Text)
      → Export as HTML
```

---

## Search Functionality

### Global Document Search

- **Full-Text Search**: Search across all pages simultaneously
- **Real-Time Results**: Instant result updates as you type
- **Context Preview**: See surrounding text for each result
- **Result Count**: Clear indication of total matches

### Navigation

- **Jump to Results**: Click any result to navigate to that page
- **Next/Previous**: Navigate through results sequentially
- **Current Result Indicator**: Highlighted current result
- **Page Numbers**: Each result shows its page number

### Search Dialog

Accessible via:
- **Button**: Click "Search" in the header
- **Keyboard**: Press `Ctrl+F` (or `Cmd+F` on Mac)

### Search Keyboard Shortcuts

```
Ctrl/Cmd F      Open search dialog
Enter           Next search result
Shift+Enter     Previous search result
Escape          Close search dialog
```

---

## Keyboard Shortcuts

Complete keyboard shortcut reference:

### Global Shortcuts

```
Ctrl/Cmd F      Open search dialog
```

### PDF Viewer

```
← / ↑           Previous page
→ / ↓           Next page
Home            First page
End             Last page
Ctrl/Cmd +      Zoom in
Ctrl/Cmd -      Zoom out
Ctrl/Cmd 0      Reset zoom
Ctrl/Cmd R      Rotate page
Ctrl/Cmd F      Toggle fullscreen (conflicts with search - use button instead)
```

### Editor

```
Ctrl/Cmd Z      Undo last change
Ctrl/Cmd Y      Redo change
Ctrl/Cmd S      Save document (recommended: use Save button)
```

### Search

```
Enter           Next result / Start search
Shift+Enter     Previous result
Escape          Close search
```

### Navigation Tips

- **Arrow keys work globally** - no need to focus on PDF viewer
- **Shortcuts disabled in text inputs** - type freely without triggering shortcuts
- **Visual feedback** - buttons show tooltips with their shortcuts

---

## Accessibility Features

### Keyboard Navigation

- **Full Keyboard Support**: All features accessible via keyboard
- **Logical Tab Order**: Navigate through controls intuitively
- **Focus Indicators**: Clear visual indicators for focused elements
- **Skip to Content**: Efficient navigation patterns

### Screen Reader Support

- **ARIA Labels**: All interactive elements properly labeled
- **Semantic HTML**: Proper heading hierarchy and landmarks
- **Status Announcements**: Important changes announced to screen readers
- **Alt Text**: Descriptive text for all visual elements

### Visual Accessibility

- **High Contrast**: Proper color contrast ratios
- **Scalable Text**: Text scales with browser zoom
- **Focus Indicators**: Clear focus outlines for keyboard navigation
- **Color Independence**: Information not conveyed by color alone

### Responsive Design

- **Flexible Layout**: Works on various screen sizes
- **Touch Support**: Touch-friendly controls for tablets
- **Adaptive UI**: Controls adjust to available space

---

## State Persistence

Settings that persist across sessions:

- **Current Folder**: Last selected folder
- **View Mode**: Comparison or Editor mode
- **PDF Zoom Level**: Last zoom setting
- **PDF Fit Mode**: Fit width, fit page, or custom
- **Sidebar State**: Collapsed or expanded
- **Split Ratio**: Comparison view split ratio

This means you can close the browser and return to your preferred setup.

---

## Tips & Best Practices

### For Comparing Documents

1. **Start in Comparison View** for side-by-side review
2. **Enable Sync Scrolling** for parallel comparison
3. **Adjust Split Ratio** based on which side needs more focus
4. **Use Overlay Mode** to spot visual differences

### For Editing Documents

1. **Use Editor View** for making changes
2. **Edit in Small Chunks** - save frequently
3. **Use Undo/Redo** if you make mistakes
4. **Save Before Closing** to preserve changes

### For Exporting

1. **Choose the Right Format**:
   - JSON for data processing
   - Markdown for documentation
   - Text for analysis
   - HTML for sharing
2. **Export Current Page** for quick reviews
3. **Export Full Document** for complete records

### For Searching

1. **Use Specific Terms** for better results
2. **Check All Results** using next/previous
3. **Open in Editor** to see full context
4. **Search Before Editing** to find all instances

---

## Troubleshooting

### PDF Not Loading

- **Check File Path**: Ensure PDF exists in the correct folder
- **Browser Console**: Check for error messages
- **File Permissions**: Verify file is readable

### Search Not Working

- **Load Document First**: Search requires a loaded document
- **Check Query**: Ensure search term is not empty
- **Try Different Terms**: Search is case-insensitive

### Edits Not Saving

- **Click Save Button**: Changes must be explicitly saved
- **Check Permissions**: Ensure write access to the folder
- **Server Status**: Verify backend server is running

### Performance Issues

- **Large Documents**: Consider viewing page-by-page
- **Browser Memory**: Close other tabs if sluggish
- **Zoom Level**: Lower zoom if PDF rendering is slow

---

## Architecture Notes

### Store Management

The application uses Zustand for state management with:
- **Persistence**: Settings persist via localStorage
- **Devtools**: Redux DevTools integration for debugging
- **Type Safety**: Full TypeScript support

### Component Structure

```
ViewerLayout
├── ViewerHeader
│   ├── ExportMenu
│   └── SearchDialog
├── PageThumbnails
└── ComparisonView / EditorView
    ├── PDFViewer
    └── HTMLPreview / ContentEditor
```

### API Routes

- `GET /api/pdf/[fileName]` - Fetch PDF file
- `GET /api/html/[fileName]` - Fetch HTML file
- `GET /api/document/[fileName]` - Fetch JSON data
- `POST /api/save` - Save edited document
- `GET /api/files` - List available files
- `GET /api/folders` - List output folders

---

## Future Enhancements

Potential improvements for future versions:

### Planned Features

- [ ] Drag-and-drop reordering of text blocks
- [ ] Collaborative editing with real-time sync
- [ ] Comment/annotation system
- [ ] Version history and diff view
- [ ] Batch operations on multiple documents
- [ ] Custom export templates
- [ ] Advanced search with regex support
- [ ] Document comparison across different files
- [ ] PDF annotation drawing tools
- [ ] OCR re-processing for selected regions

### Community Contributions

Feel free to contribute! Check the project repository for:
- Open issues
- Feature requests
- Pull request guidelines
- Development setup instructions

---

## Support & Feedback

For questions, bug reports, or feature requests:

1. **Check this documentation** first
2. **Review the README** in the project root
3. **Open an issue** on GitHub
4. **Submit a pull request** for improvements

---

## Version History

### v2.0.0 (Current)
- ✨ Enhanced PDF viewer with advanced controls
- ✨ Synchronized scrolling in comparison view
- ✨ Full inline editing capabilities
- ✨ Comprehensive export options
- ✨ Global search functionality
- ✨ Complete keyboard navigation
- ✨ Accessibility improvements
- ✨ State persistence
- 🐛 Fixed store initialization issues
- 🐛 Improved error handling
- 📝 Complete documentation

### v1.0.0 (Legacy)
- Basic PDF and HTML viewing
- Simple comparison mode
- Read-only document display

---

## License

See the project LICENSE file for details.

---

## Credits

Built with:
- Next.js 16
- React 18
- TypeScript
- Tailwind CSS
- Radix UI
- React-PDF
- Zustand
- Sonner

---

**Happy Document Viewing! 🎉**
