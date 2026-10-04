"""Serve the dashboard with caching disabled so a reload always picks up new code."""

import functools
import http.server
import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    # --lan also serves other devices on the network (phone mode).
    host = "0.0.0.0" if "--lan" in sys.argv else "127.0.0.1"
    handler = functools.partial(NoCacheHandler, directory=str(FRONTEND_DIR))
    with http.server.ThreadingHTTPServer((host, 5500), handler) as server:
        print(f"Serving dashboard on {host}:5500")
        server.serve_forever()
