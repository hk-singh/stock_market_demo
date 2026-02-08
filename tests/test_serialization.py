"""Tests for message serialization used by the producer and consumers."""

import json


class TestMessageSerialization:
    """Verify that trade messages round-trip through JSON correctly."""

    def test_trade_roundtrip(self):
        trade = {
            "s": "AAPL",
            "p": 178.52,
            "v": 100,
            "t": 1700000000000,
            "c": ["1", "12"],
        }
        encoded = json.dumps(trade).encode("utf-8")
        decoded = json.loads(encoded.decode("utf-8"))

        assert decoded == trade
        assert isinstance(decoded["p"], float)
        assert isinstance(decoded["v"], int)
        assert isinstance(decoded["t"], int)

    def test_key_serialization(self):
        """Symbol keys are encoded/decoded as UTF-8 strings."""
        key = "GOOGL"
        encoded = key.encode("utf-8")
        decoded = encoded.decode("utf-8")
        assert decoded == key

    def test_metrics_roundtrip(self):
        metrics = {
            "symbol": "TSLA",
            "trade_count": 42,
            "window_size": 20,
            "avg_price": 245.67,
            "min_price": 240.0,
            "max_price": 250.0,
            "latest_price": 248.33,
            "total_volume": 15000,
            "vwap": 246.12,
            "price_change_pct": 1.35,
            "timestamp": "2025-01-15T10:30:00",
        }
        encoded = json.dumps(metrics).encode("utf-8")
        decoded = json.loads(encoded.decode("utf-8"))
        assert decoded == metrics
