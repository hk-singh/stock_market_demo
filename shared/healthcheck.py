"""
Lightweight health check HTTP server.

Runs in a background daemon thread so it doesn't block the main Kafka loop.
Exposes GET /healthz on a configurable port. Kubernetes liveness/readiness
probes (or Cloud Run) can hit this endpoint to verify the service is alive.
"""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that responds 200 on /healthz."""

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress default request logging — we have our own logger
    def log_message(self, format, *args):
        return


def start_health_server(port: int = 8000) -> HTTPServer:
    """Start the health check server in a daemon thread.

    Args:
        port: TCP port to listen on (default 8000).

    Returns:
        The running HTTPServer instance (call .shutdown() to stop).
    """
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server listening on :{port}/healthz")
    return server
