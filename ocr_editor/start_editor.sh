#!/bin/bash
# OCR Correction Editor - Linux/Mac Launcher
# Double-click or run: bash start_editor.sh
#
# Requires: Python 3 (pre-installed on most Linux/Mac systems)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Auto-detect data folder: look for output_final next to this folder
DATA_DIR=""
if [ -d "$SCRIPT_DIR/../output_final" ]; then
    DATA_DIR="$SCRIPT_DIR/../output_final"
elif [ -d "$SCRIPT_DIR/output_final" ]; then
    DATA_DIR="$SCRIPT_DIR/output_final"
else
    # Ask user
    echo "Could not auto-detect output_final folder."
    echo "Enter path to your output_final folder:"
    read -r DATA_DIR
    if [ ! -d "$DATA_DIR" ]; then
        echo "ERROR: Folder not found: $DATA_DIR"
        echo "Press Enter to exit..."
        read -r
        exit 1
    fi
fi

echo "╔══════════════════════════════════════╗"
echo "║   📝 OCR Correction Editor            ║"
echo "║   Starting server...                  ║"
echo "║   Data: $DATA_DIR"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Check for Python 3
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "ERROR: Python 3 is required but not found."
    echo "Install Python 3 from https://www.python.org/downloads/"
    echo "Press Enter to exit..."
    read -r
    exit 1
fi

$PYTHON "$SCRIPT_DIR/start_server.py" "$DATA_DIR"
echo "      The folder picker feature requires Chrome/Edge."
