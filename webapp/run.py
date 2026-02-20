#!/usr/bin/env python3
"""
Run the ScanToText web app.

Usage:
    python run.py
    python run.py --host 0.0.0.0 --port 8000
"""

import argparse
import sys
from pathlib import Path

# Ensure parent dir is on path for fixed_layout_pipeline imports
parent = str(Path(__file__).resolve().parent.parent)
if parent not in sys.path:
    sys.path.insert(0, parent)


def main():
    parser = argparse.ArgumentParser(description="ScanToText — Free OCR Web App")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    import uvicorn

    print(f"\n  ScanToText starting at http://{args.host}:{args.port}\n")
    uvicorn.run(
        "app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
