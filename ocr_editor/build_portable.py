#!/usr/bin/env python3
"""
Build portable OCR Editor executable.

Creates a single .exe / binary with everything embedded.
No Python or other prerequisites needed on the target machine.

Usage:
    python3 build_portable.py              # Build for current OS
    python3 build_portable.py --name MyApp # Custom output name

Requirements (build machine only):
    pip install pyinstaller
"""

import subprocess, sys, os, tempfile, shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    name = "OCR_Editor"
    for i, a in enumerate(sys.argv[1:]):
        if a == "--name" and i + 1 < len(sys.argv[1:]):
            name = sys.argv[i + 2]

    # Read the HTML file and embed it into the server script
    html_path = os.path.join(SCRIPT_DIR, "ocr_editor.html")
    server_path = os.path.join(SCRIPT_DIR, "start_server.py")

    if not os.path.exists(html_path):
        print("ERROR: ocr_editor.html not found")
        sys.exit(1)
    if not os.path.exists(server_path):
        print("ERROR: start_server.py not found")
        sys.exit(1)

    # Create the combined single-file script
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    with open(server_path, "r", encoding="utf-8") as f:
        server_content = f.read()

    combined = build_combined_script(server_content, html_content)

    # Write to temp file
    build_dir = os.path.join(SCRIPT_DIR, "build_temp")
    os.makedirs(build_dir, exist_ok=True)
    combined_path = os.path.join(build_dir, "ocr_editor_app.py")
    with open(combined_path, "w", encoding="utf-8") as f:
        f.write(combined)

    print(f"✅ Combined script created: {combined_path}")
    print(f"📦 Building with PyInstaller...")
    print()

    dist_dir = os.path.join(SCRIPT_DIR, "dist")

    try:
        subprocess.run([
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", name,
            "--distpath", dist_dir,
            "--workpath", os.path.join(build_dir, "pyinstaller_work"),
            "--specpath", build_dir,
            "--clean",
            "--noconfirm",
            combined_path,
        ], check=True)
    except FileNotFoundError:
        print("\n❌ PyInstaller not found. Install it with:")
        print("   pip install pyinstaller")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Build failed: {e}")
        sys.exit(1)

    # Clean up
    shutil.rmtree(build_dir, ignore_errors=True)

    exe_name = name + (".exe" if sys.platform == "win32" else "")
    exe_path = os.path.join(dist_dir, exe_name)

    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print()
        print("╔═══════════════════════════════════════════════════════╗")
        print("║         ✅  Build Successful!                        ║")
        print("╠═══════════════════════════════════════════════════════╣")
        print(f"║  Output: {exe_path:<44}║")
        print(f"║  Size:   {size_mb:.1f} MB{' ' * (41 - len(f'{size_mb:.1f} MB'))}║")
        print("╠═══════════════════════════════════════════════════════╣")
        print("║  USB Setup:                                          ║")
        print(f"║  1. Copy {exe_name} to USB stick")
        print("║  2. Copy output_final/ folder to same USB stick      ║")
        print(f"║  3. Double-click {exe_name} — it auto-finds data")
        print("║  4. No Python needed on target machine!               ║")
        print("╚═══════════════════════════════════════════════════════╝")
    else:
        print("❌ Build output not found")


def build_combined_script(server_py, html_content):
    """Create a single Python file with HTML embedded as a string constant."""

    # Escape the HTML for embedding as a Python string
    import base64
    html_b64 = base64.b64encode(html_content.encode("utf-8")).decode("ascii")

    return f'''#!/usr/bin/env python3
"""
OCR Correction Editor — Portable Standalone
=============================================
Single-file executable. No dependencies. No Python needed.
Just double-click and point to your output_final folder.
"""

import http.server, json, os, sys, webbrowser, urllib.parse
import threading, socket, signal, mimetypes, base64, tkinter as tk
from tkinter import filedialog
from pathlib import Path

# ══════════════════════════════════════════════════════════
# EMBEDDED HTML (base64 encoded)
# ══════════════════════════════════════════════════════════
_EDITOR_HTML_B64 = """{html_b64}"""

def get_editor_html():
    return base64.b64decode(_EDITOR_HTML_B64).decode("utf-8")


PORT = 8089
DATA_DIR = None

def get_exe_dir():
    """Get directory of the executable (works for PyInstaller frozen apps)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_output_folder():
    exe_dir = get_exe_dir()
    for c in [
        os.path.join(exe_dir, "output_final"),
        os.path.join(exe_dir, "..", "output_final"),
        os.path.join(os.getcwd(), "output_final"),
    ]:
        p = os.path.abspath(c)
        if os.path.isdir(p):
            return p
    return None


def ask_folder():
    """Show a folder picker dialog using tkinter."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(
            title="Select the output_final folder with your OCR documents"
        )
        root.destroy()
        return folder if folder and os.path.isdir(folder) else None
    except Exception:
        return None


def scan_documents(data_dir):
    docs = []
    if not data_dir or not os.path.isdir(data_dir):
        return docs
    for name in sorted(os.listdir(data_dir)):
        folder = os.path.join(data_dir, name)
        if not os.path.isdir(folder):
            continue
        info = {{"id": name, "has_json": False, "has_html": False, "has_pdf": False, "has_original_pdf": False}}
        for f in os.listdir(folder):
            if f.endswith("_ocr.json"):
                info["has_json"] = True
            elif f.endswith("_replace_text.html"):
                info["has_html"] = True
            elif f == name + ".pdf":
                info["has_original_pdf"] = True
            elif f.endswith("_searchable.pdf"):
                info["has_pdf"] = True
        if info["has_json"]:
            docs.append(info)
    return docs


class EditorHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        msg = args[0] if args else ""
        if "/api/" in str(msg) and "documents" not in str(msg):
            return
        super().log_message(fmt, *args)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path in ("/", "/index.html"):
            html = get_editor_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)
            return

        if path == "/api/documents":
            return self._json(scan_documents(DATA_DIR))

        if path.startswith("/api/ocr/"):
            doc_id = urllib.parse.unquote(path[9:])
            f = self._find(doc_id, "_ocr.json")
            return self._serve_file(f, "application/json") if f else self._404()

        if path.startswith("/api/html/"):
            doc_id = urllib.parse.unquote(path[10:])
            f = self._find(doc_id, "_replace_text.html") or self._find(doc_id, ".html")
            return self._serve_file(f, "text/html") if f else self._404()

        if path.startswith("/api/pdf/"):
            doc_id = urllib.parse.unquote(path[9:])
            f = self._find_exact(doc_id, doc_id + ".pdf") or self._find(doc_id, "_searchable.pdf") or self._find(doc_id, ".pdf")
            return self._serve_file(f, "application/pdf") if f else self._404()

        if path == "/api/corrections":
            cp = os.path.join(DATA_DIR, "_corrections.json") if DATA_DIR else None
            if cp and os.path.exists(cp):
                return self._serve_file(cp, "application/json")
            return self._json({{}})

        self._404()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))

        if path == "/api/corrections":
            try:
                data = json.loads(body)
                cp = os.path.join(DATA_DIR, "_corrections.json")
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return self._json({{"status": "ok", "path": cp}})
            except Exception as e:
                return self._json({{"status": "error", "message": str(e)}}, 500)

        if path == "/api/export":
            try:
                data = json.loads(body)
                ep = os.path.join(DATA_DIR, "ocr_corrections_export.json")
                with open(ep, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return self._json({{"status": "ok", "path": ep}})
            except Exception as e:
                return self._json({{"status": "error", "message": str(e)}}, 500)

        self._404()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _find(self, doc_id, suffix):
        folder = os.path.join(DATA_DIR, doc_id) if DATA_DIR else None
        if not folder or not os.path.isdir(folder):
            return None
        for f in os.listdir(folder):
            if f.endswith(suffix):
                return os.path.join(folder, f)
        return None

    def _find_exact(self, doc_id, filename):
        if not DATA_DIR:
            return None
        fp = os.path.join(DATA_DIR, doc_id, filename)
        return fp if os.path.isfile(fp) else None

    def _serve_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            ct = content_type + "; charset=utf-8" if "text" in content_type or "json" in content_type else content_type
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", len(data))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(500, str(e))

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _404(self):
        self.send_error(404)


def find_free_port(start=8089):
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    return start


def main():
    global DATA_DIR, PORT

    # Parse command-line args
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            PORT = int(args[i + 1])
        elif os.path.isdir(arg):
            DATA_DIR = os.path.abspath(arg)

    # Try auto-detect
    if not DATA_DIR:
        DATA_DIR = find_output_folder()

    # If still not found, show folder picker
    if not DATA_DIR:
        print("📂 No output_final folder found nearby.")
        print("   Opening folder picker...")
        DATA_DIR = ask_folder()

    if not DATA_DIR or not os.path.isdir(DATA_DIR):
        print("❌ No data folder selected. Exiting.")
        input("Press Enter to close...")
        sys.exit(1)

    PORT = find_free_port(PORT)
    docs = scan_documents(DATA_DIR)
    n_pdf = sum(1 for d in docs if d.get("has_original_pdf"))

    print()
    print("\\u2554" + "\\u2550" * 55 + "\\u2557")
    print("\\u2551         \\U0001f4dd  OCR Correction Editor  v2.0              \\u2551")
    print("\\u2560" + "\\u2550" * 55 + "\\u2563")
    print(f"\\u2551  Data folder: {{DATA_DIR[:43]:<43}} \\u2551")
    print(f"\\u2551  Documents:   {{len(docs):<43}} \\u2551")
    print(f"\\u2551  With PDF:    {{n_pdf:<43}} \\u2551")
    print(f"\\u2551  Server:      http://localhost:{{PORT:<32}} \\u2551")
    print("\\u2560" + "\\u2550" * 55 + "\\u2563")
    print("\\u2551  Opening in browser...                               \\u2551")
    print("\\u2551  Press Ctrl+C to stop. Close this window to quit.    \\u2551")
    print("\\u255a" + "\\u2550" * 55 + "\\u255d")
    print()

    server = http.server.HTTPServer(("0.0.0.0", PORT), EditorHandler)
    url = f"http://localhost:{{PORT}}"
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    def shutdown_handler(sig, frame):
        print("\\n\\U0001f44b Stopped.")
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
