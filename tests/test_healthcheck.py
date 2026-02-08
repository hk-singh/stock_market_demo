"""Tests for the health check HTTP server."""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.healthcheck import start_health_server


class TestHealthCheck:
    """Tests for the /healthz endpoint."""

    def test_healthz_returns_200(self):
        server = start_health_server(port=18000)
        try:
            resp = urllib.request.urlopen("http://localhost:18000/healthz")
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body == {"status": "ok"}
        finally:
            server.shutdown()

    def test_unknown_path_returns_404(self):
        server = start_health_server(port=18001)
        try:
            try:
                urllib.request.urlopen("http://localhost:18001/unknown")
                raise AssertionError("Should have raised HTTPError")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            server.shutdown()
