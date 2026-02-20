#!/usr/bin/env python3
"""
OCR Correction Editor - Local Server
=====================================
Serves the 3-panel editor (PDF + HTML + Text) on localhost.

Usage:
    python3 start_server.py                          # auto-detect output_final
    python3 start_server.py /path/to/output_final    # specify folder
    python3 start_server.py --port 9090              # custom port
"""

import http.server, json, os, sys, webbrowser, urllib.parse
import threading, socket, signal, mimetypes
from pathlib import Path

PORT = 8089
DATA_DIR = None
EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))


def find_output_folder():
    for c in [
        os.path.join(EDITOR_DIR, '..', 'output_final'),
        os.path.join(EDITOR_DIR, 'output_final'),
        os.path.join(os.getcwd(), 'output_final'),
    ]:
        p = os.path.abspath(c)
        if os.path.isdir(p):
            return p
    return None


def scan_documents(data_dir):
    docs = []
    if not data_dir or not os.path.isdir(data_dir):
        return docs
    for name in sorted(os.listdir(data_dir)):
        folder = os.path.join(data_dir, name)
        if not os.path.isdir(folder):
            continue
        info = {'id': name, 'has_json': False, 'has_html': False, 'has_pdf': False, 'has_original_pdf': False}
        for f in os.listdir(folder):
            if f.endswith('_ocr.json'):
                info['has_json'] = True
            elif f.endswith('_replace_text.html'):
                info['has_html'] = True
            elif f == name + '.pdf':
                info['has_original_pdf'] = True
            elif f.endswith('_searchable.pdf'):
                info['has_pdf'] = True
        if info['has_json']:
            docs.append(info)
    return docs


class EditorHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        msg = args[0] if args else ''
        if '/api/' in str(msg) and 'documents' not in str(msg):
            return
        super().log_message(fmt, *args)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        # Root → editor HTML
        if path in ('/', '/index.html'):
            return self._serve_file(os.path.join(EDITOR_DIR, 'ocr_editor.html'), 'text/html')

        # ── API Endpoints ──────────────────────────────────────
        if path == '/api/documents':
            return self._json(scan_documents(DATA_DIR))

        if path.startswith('/api/ocr/'):
            doc_id = urllib.parse.unquote(path[9:])
            f = self._find(doc_id, '_ocr.json')
            return self._serve_file(f, 'application/json') if f else self._404()

        if path.startswith('/api/html/'):
            doc_id = urllib.parse.unquote(path[10:])
            f = self._find(doc_id, '_replace_text.html') or self._find(doc_id, '.html')
            return self._serve_file(f, 'text/html') if f else self._404()

        if path.startswith('/api/pdf/'):
            doc_id = urllib.parse.unquote(path[9:])
            # Prefer original, fallback searchable
            f = self._find_exact(doc_id, doc_id + '.pdf') or self._find(doc_id, '_searchable.pdf') or self._find(doc_id, '.pdf')
            return self._serve_file(f, 'application/pdf') if f else self._404()

        if path == '/api/corrections':
            cp = os.path.join(DATA_DIR, '_corrections.json') if DATA_DIR else None
            if cp and os.path.exists(cp):
                return self._serve_file(cp, 'application/json')
            return self._json({})

        # Static files from editor dir
        fp = os.path.join(EDITOR_DIR, path.lstrip('/'))
        if os.path.isfile(fp):
            ct = mimetypes.guess_type(fp)[0] or 'application/octet-stream'
            return self._serve_file(fp, ct)

        self._404()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))

        if path == '/api/corrections':
            try:
                data = json.loads(body)
                cp = os.path.join(DATA_DIR, '_corrections.json')
                with open(cp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return self._json({'status': 'ok', 'path': cp})
            except Exception as e:
                return self._json({'status': 'error', 'message': str(e)}, 500)

        if path == '/api/export':
            try:
                data = json.loads(body)
                ep = os.path.join(DATA_DIR, 'ocr_corrections_export.json')
                with open(ep, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return self._json({'status': 'ok', 'path': ep})
            except Exception as e:
                return self._json({'status': 'error', 'message': str(e)}, 500)

        self._404()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ── Helpers ────────────────────────────────────────────────
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
            with open(filepath, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type + '; charset=utf-8' if 'text' in content_type or 'json' in content_type else content_type)
            self.send_header('Content-Length', len(data))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(500, str(e))

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _404(self):
        self.send_error(404)


def find_free_port(start=8089):
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    return start


def main():
    global DATA_DIR, PORT
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--port' and i + 1 < len(args):
            PORT = int(args[i + 1])
        elif os.path.isdir(arg):
            DATA_DIR = os.path.abspath(arg)

    if not DATA_DIR:
        DATA_DIR = find_output_folder()
    if not DATA_DIR:
        print("⚠️  Could not find output_final folder.")
        print("   Usage: python3 start_server.py /path/to/output_final")
        DATA_DIR = os.getcwd()

    PORT = find_free_port(PORT)
    docs = scan_documents(DATA_DIR)
    n_pdf = sum(1 for d in docs if d.get('has_original_pdf'))

    print()
    print("╔═══════════════════════════════════════════════════════╗")
    print("║         📝  OCR Correction Editor  v2.0              ║")
    print("╠═══════════════════════════════════════════════════════╣")
    print(f"║  Data folder: {DATA_DIR[:43]:<43} ║")
    print(f"║  Documents:   {len(docs):<43} ║")
    print(f"║  With PDF:    {n_pdf:<43} ║")
    print(f"║  Server:      http://localhost:{PORT:<32} ║")
    print("╠═══════════════════════════════════════════════════════╣")
    print("║  Opening in browser...                               ║")
    print("║  Press Ctrl+C to stop the server.                    ║")
    print("╚═══════════════════════════════════════════════════════╝")
    print()

    server = http.server.HTTPServer(('0.0.0.0', PORT), EditorHandler)
    url = f'http://localhost:{PORT}'
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    signal.signal(signal.SIGINT, lambda s, f: (print("\n👋 Stopped."), server.shutdown()))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
