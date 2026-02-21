# OCR Correction Editor

A portable offline tool for human editors to review and correct OCR text output.
Runs from a USB stick — no installation needed, just Python 3 and a browser.

## Requirements

- **Python 3** (pre-installed on most Linux/Mac; download from https://python.org for Windows)
- **Any modern browser** (Chrome, Edge, Firefox, Safari)
- **No internet required** — works completely offline
- **No pip install, no dependencies** — uses only Python standard library

## Quick Start

### Linux / Mac
```bash
bash start_editor.sh
```

### Windows
Double-click `start_editor.bat`

### Manual
```bash
python3 start_server.py /path/to/output_final
```
Then open `http://localhost:8089` in your browser.

## USB Stick Setup

1. Copy these files to the USB stick:
```
USB_DRIVE/
├── ocr_editor/
│   ├── ocr_editor.html      ← Editor UI (served by server)
│   ├── start_server.py       ← Python server (no dependencies)
│   ├── start_editor.bat      ← Windows: double-click to launch
│   ├── start_editor.sh       ← Linux/Mac: double-click to launch
│   └── README.md
└── output_final/
    ├── 0005-052-002-003/
    │   ├── 0005-052-002-003.pdf              ← Original scanned PDF
    │   ├── 0005-052-002-003_ocr.json         ← OCR data (Azure)
    │   ├── 0005-052-002-003_replace_text.html ← HTML overlay
    │   └── 0005-052-002-003_searchable.pdf   ← Searchable PDF
    ├── 0005-052-004-004/
    │   └── ...
    └── ...
```

2. On any computer, plug in the USB and run the launcher script
3. The launcher auto-detects `output_final/` next to `ocr_editor/`
4. Browser opens automatically — start editing

### Windows without Python installed
Place a portable Python (e.g., [WinPython](https://winpython.github.io/) or [Embeddable Python](https://www.python.org/downloads/windows/)) in a `python/` subfolder inside `ocr_editor/`. The batch launcher will find it automatically.

## How to Use

### 1. Three-Panel View
- **Left panel**: Original scanned PDF
- **Center panel**: OCR HTML output (text overlaid on page images)
- **Right panel**: Editable text with confidence highlighting

### 2. Color Coding
- 🟢 **Green border** = High confidence (≥75%) — probably correct
- 🟡 **Yellow border** = Medium confidence (50-75%) — check these  
- 🔴 **Red border** = Low confidence (<50%) — likely needs correction
- ✅ **Green highlight** = Already corrected by you

### 3. Edit Words
- **Click** any word to edit it inline
- **Tab** / **Shift+Tab** to move between words
- **Enter** to confirm, **Escape** to cancel
- **✏️ button** on a line to edit the full line text

### 4. Features
- **🔗 Sync Scroll**: All three panels scroll together (toggle in toolbar)
- **Zoom**: +/− buttons on the HTML panel, auto-fit on load
- **Filters**: Show All / Low confidence / Edited words only
- **Panel toggles**: Show/hide PDF, HTML, Editor (keys 1, 2, 3)
- **Corrections shown in HTML**: Edits appear in the HTML panel in green

### 5. Save & Export
- **💾 Save**: Saves `_corrections.json` alongside data
- **📤 Export**: Downloads full export with original + corrected text

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` / `↓` | Previous / Next document |
| `Click` | Edit a word |
| `Tab` | Next word (while editing) |
| `Enter` | Confirm edit |
| `Escape` | Cancel edit |
| `Ctrl+S` | Save corrections |
| `Ctrl+E` | Export all |
| `1` `2` `3` | Toggle PDF / HTML / Editor panels |
| `+` / `-` | Zoom HTML in / out |

## Output Format

### Corrections file (`_corrections.json`)
```json
{
  "document-id": {
    "0": {
      "3": {
        "2": "corrected word",
        "_fullText": "full line override (when word count changed)"
      }
    }
  }
}
```

### Full export (`ocr_export.json`)
```json
{
  "document-id": {
    "original_pages": ["page 1 text...", "page 2..."],
    "corrected_pages": ["page 1 corrected...", "page 2..."],
    "corrections_count": 15
  }
}
