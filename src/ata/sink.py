import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any
from datetime import datetime, timezone


class SinkHandler(BaseHTTPRequestHandler):
    captures: List[Dict[str, Any]] = []
    lock = threading.Lock()
    _counter = 0

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8", errors="ignore")

        with SinkHandler.lock:
            SinkHandler._counter += 1
            # ПРАВКА 5: capture_id через монотонный класс-level счётчик +
            # id объекта процесса, чтобы не схлопывался между прогонами.
            capture_id = f"cap-{id(SinkHandler)}-{SinkHandler._counter}"
            record = {
                "capture_id": capture_id,
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            SinkHandler.captures.append(record)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"status": "captured", "capture_id": capture_id}).encode())

    def log_message(self, format, *args):
        pass


class LocalSink:
    def __init__(self, host: str = "127.0.0.1", port: int = 8888):
        self.server = HTTPServer((host, port), SinkHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.port = port

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def clear(self):
        # Очищает список захватов, но НЕ сбрасывает счётчик —
        # capture_id остаются уникальными в рамках всего процесса (ПРАВКА 5).
        with SinkHandler.lock:
            SinkHandler.captures.clear()

    def find_canary_captures(self, canary: str) -> List[Dict[str, Any]]:
        with SinkHandler.lock:
            return [c for c in SinkHandler.captures if canary in c["body"] or canary in c["path"]]
