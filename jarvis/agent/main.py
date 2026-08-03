#!/usr/bin/env python3
"""
JARVIS — HTTP server + API. Python standard library only.

Run: python3 jarvis/agent/main.py   (then open http://localhost:8765)
"""
import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import data  # noqa: E402
import memory  # noqa: E402
import tools  # noqa: E402
import voice  # noqa: E402
from vault import VAULT  # noqa: E402

ROOT = os.path.dirname(HERE)
UI_DIR = os.path.join(ROOT, "ui")
PORT = int(os.environ.get("JARVIS_PORT", "8765"))


def load_env():
    """Read .env into os.environ without overwriting anything already set."""
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("JARVIS_VERBOSE"):
            super().log_message(fmt, *args)

    # ---------- plumbing ----------

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json_body(self):
        raw = self._body()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    # ---------- routes ----------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/status":
                return self._send(200, self.status_payload())
            if path == "/api/graph":
                return self._send(200, VAULT.graph())
            if path == "/api/note":
                nid = (parse_qs(parsed.query).get("id") or [""])[0]
                note = VAULT.note(nid)
                if not note:
                    return self._send(404, {"error": "not found"})
                return self._send(200, note.as_dict(include_text=True))
            if path == "/api/path":
                q = parse_qs(parsed.query)
                a = (q.get("a") or [""])[0]
                b = (q.get("b") or [""])[0]
                return self._send(200, {"path": VAULT.shortest_path(a, b)})
            if path == "/api/memory":
                return self._send(200, {"facts": memory.list_facts()})
            return self.serve_static(path)
        except Exception:
            traceback.print_exc()
            return self._send(500, {"error": "server error"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/ask":
                payload = self._json_body()
                result = tools.handle_turn(
                    payload.get("text", ""),
                    history=payload.get("history") or [],
                )
                return self._send(200, result)
            if path == "/api/speak":
                payload = self._json_body()
                audio, err = voice.speak(payload.get("text", ""))
                if err:
                    return self._send(503, {"error": err})
                return self._send(200, audio, ctype="audio/mpeg")
            if path == "/api/listen":
                raw = self._body()
                ctype = self.headers.get("Content-Type", "audio/webm")
                text, err = voice.listen(raw, ctype)
                if err:
                    return self._send(503, {"error": err})
                return self._send(200, {"text": text})
            if path == "/api/reindex":
                return self._send(200, VAULT.index())
            return self._send(404, {"error": "no such endpoint"})
        except Exception:
            traceback.print_exc()
            return self._send(500, {"error": "server error"})

    # ---------- static ----------

    def serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(UI_DIR, rel))
        if not full.startswith(UI_DIR) or not os.path.isfile(full):
            return self._send(404, "not found", ctype="text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        return self._send(200, body, ctype=ctype)

    def status_payload(self):
        stats = VAULT.stats()
        stats["voice"] = voice.status()
        stats["model"] = tools.model_status()
        stats["memory_count"] = len(memory.list_facts())
        return stats


def main():
    load_env()
    stats = VAULT.index()
    mode = "DEMO" if stats["demo"] else "REAL"
    print(f"JARVIS [{mode}] — {stats['count']} notes, {stats['edges']} edges")
    for root in stats["roots"]:
        print(f"  reading: {root}")
    if not stats["roots"]:
        print("  ! no folders configured — set JARVIS_VAULT_PATHS in .env")
    v = voice.status()
    if not v["available"]:
        print(f"  ! voice unavailable: {v['reason']}")
    m = tools.model_status()
    if not m["available"]:
        print(f"  ! model unavailable: {m['reason']} (routing falls back to scoring)")
    print(f"  http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
