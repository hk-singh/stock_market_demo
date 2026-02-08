"""Tests for FastAPI endpoints using the shared test database."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from api.main import app
from api.models import AggregatedMetric, Trade

# Import shared session from conftest
from tests.conftest import TestSession

_seeded = False


def _seed_data():
    """Insert sample trades and metrics (idempotent)."""
    global _seeded
    if _seeded:
        return
    db = TestSession()
    now = datetime.utcnow()

    trades = [
        Trade(symbol="AAPL", price=178.50, volume=100, trade_timestamp=1700000000000, ingested_at=now),
        Trade(symbol="AAPL", price=179.00, volume=200, trade_timestamp=1700000001000, ingested_at=now),
        Trade(symbol="GOOGL", price=141.25, volume=50, trade_timestamp=1700000000000, ingested_at=now),
    ]
    for t in trades:
        db.add(t)

    metric = AggregatedMetric(
        symbol="AAPL",
        trade_count=50,
        window_size=20,
        avg_price=178.75,
        min_price=177.00,
        max_price=180.00,
        latest_price=179.00,
        total_volume=5000,
        vwap=178.80,
        price_change_pct=0.56,
        calculated_at=now,
    )
    db.add(metric)
    db.commit()
    db.close()
    _seeded = True


client = TestClient(app)


class TestHealthEndpoint:
    def test_healthz(self):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestSymbolsEndpoint:
    def test_list_symbols(self):
        _seed_data()
        resp = client.get("/symbols")
        assert resp.status_code == 200
        data = resp.json()
        assert "AAPL" in data["symbols"]
        assert "GOOGL" in data["symbols"]

    def test_symbols_sorted(self):
        resp = client.get("/symbols")
        symbols = resp.json()["symbols"]
        assert symbols == sorted(symbols)


class TestPriceEndpoint:
    def test_get_price(self):
        _seed_data()
        resp = client.get("/symbols/AAPL/price")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert "vwap" in data

    def test_get_price_case_insensitive(self):
        resp = client.get("/symbols/aapl/price")
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "AAPL"

    def test_unknown_symbol(self):
        resp = client.get("/symbols/ZZZZ/price")
        data = resp.json()
        assert "error" in str(data) or "No data" in str(data)


class TestHistoryEndpoint:
    def test_get_history(self):
        _seed_data()
        resp = client.get("/symbols/AAPL/history?window=24h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert data["window"] == "24h"
        assert isinstance(data["trades"], list)

    def test_history_limit(self):
        resp = client.get("/symbols/AAPL/history?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()["trades"]) <= 1


class TestMetricsEndpoint:
    def test_get_metrics(self):
        _seed_data()
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["metrics"], list)
        symbols = [m["symbol"] for m in data["metrics"]]
        assert "AAPL" in symbols

    def test_metrics_have_expected_fields(self):
        resp = client.get("/metrics")
        for m in resp.json()["metrics"]:
            assert "vwap" in m
            assert "latest_price" in m
            assert "price_change_pct" in m
            assert "calculated_at" in m
