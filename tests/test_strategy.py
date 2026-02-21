"""Tests for the strategy engine and alert endpoints."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from api.main import app
from api.models import Trade
from api.strategy_engine import (
    MovingAverageCrossoverStrategy,
    VolumeSpikeStrategy,
    VWAPDeviationStrategy,
    list_strategies,
)
from tests.conftest import TestSession

_seeded = False


def _seed_market_data():
    """Insert market data for strategy tests (idempotent)."""
    global _seeded
    if _seeded:
        return
    db = TestSession()
    now = datetime.utcnow()
    trades = [
        Trade(symbol="AAPL", price=190.00, volume=500, trade_timestamp=1700000030000, ingested_at=now),
        Trade(symbol="GOOG", price=140.00, volume=300, trade_timestamp=1700000030000, ingested_at=now),
    ]
    for t in trades:
        db.add(t)
    db.commit()
    db.close()
    _seeded = True


# --- Strategy engine unit tests ---


class TestVWAPDeviation:
    def test_buy_signal_below_vwap(self):
        strategy = VWAPDeviationStrategy(threshold_pct=1.0)
        metrics = {"latest_price": 98.0, "vwap": 100.0}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is not None
        assert signal.action == "BUY"
        assert signal.symbol == "AAPL"
        assert "below VWAP" in signal.reason

    def test_sell_signal_above_vwap(self):
        strategy = VWAPDeviationStrategy(threshold_pct=1.0)
        metrics = {"latest_price": 102.0, "vwap": 100.0}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is not None
        assert signal.action == "SELL"
        assert "above VWAP" in signal.reason

    def test_no_signal_within_threshold(self):
        strategy = VWAPDeviationStrategy(threshold_pct=1.0)
        metrics = {"latest_price": 100.5, "vwap": 100.0}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is None

    def test_no_signal_missing_data(self):
        strategy = VWAPDeviationStrategy()
        metrics = {"latest_price": 100.0}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is None

    def test_strength_scales_with_deviation(self):
        strategy = VWAPDeviationStrategy(threshold_pct=1.0)
        # 5% deviation → strength = 5/5 = 1.0
        metrics = {"latest_price": 95.0, "vwap": 100.0}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is not None
        assert signal.strength == 1.0


class TestMACrossover:
    def test_first_metric_returns_none(self):
        strategy = MovingAverageCrossoverStrategy()
        metrics = {"latest_price": 100.0, "avg_price": 100.0}
        signal = strategy.on_metric("TEST", metrics)
        assert signal is None  # initializes long EMA

    def test_bullish_crossover(self):
        strategy = MovingAverageCrossoverStrategy(ema_alpha=0.3)

        # First call: initialize both at 100
        strategy.on_metric("TEST", {"latest_price": 100.0, "avg_price": 100.0})

        # Second call: short drops to 95, long EMA = 0.3*95 + 0.7*100 = 98.5
        # Now prev_short=95 < prev_long=98.5
        strategy.on_metric("TEST", {"latest_price": 95.0, "avg_price": 95.0})

        # Third call: short jumps to 110, long EMA = 0.3*110 + 0.7*98.5 = 101.95
        # prev_short(95) < prev_long(98.5) → was_below=True
        # short(110) > long(101.95) → now_above=True → BUY
        signal = strategy.on_metric("TEST", {"latest_price": 110.0, "avg_price": 110.0})
        assert signal is not None
        assert signal.action == "BUY"
        assert "Bullish crossover" in signal.reason

    def test_no_crossover(self):
        strategy = MovingAverageCrossoverStrategy(ema_alpha=0.1)

        # Initialize
        strategy.on_metric("FLAT", {"latest_price": 100.0, "avg_price": 100.0})

        # Small movement — no crossover
        signal = strategy.on_metric("FLAT", {"latest_price": 100.5, "avg_price": 100.5})
        assert signal is None


class TestVolumeSpikeStrategy:
    def test_first_metric_returns_none(self):
        strategy = VolumeSpikeStrategy()
        metrics = {"latest_price": 100.0, "total_volume": 10000}
        signal = strategy.on_metric("TEST", metrics)
        assert signal is None  # initializes average

    def test_volume_spike_buy(self):
        strategy = VolumeSpikeStrategy(spike_multiplier=2.0)
        strategy._avg_volume["AAPL"] = 1000

        metrics = {"latest_price": 100.0, "total_volume": 3000, "price_change_pct": 2.5}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is not None
        assert signal.action == "BUY"
        assert "spike" in signal.reason.lower()

    def test_volume_spike_sell(self):
        strategy = VolumeSpikeStrategy(spike_multiplier=2.0)
        strategy._avg_volume["AAPL"] = 1000

        metrics = {"latest_price": 95.0, "total_volume": 3000, "price_change_pct": -1.5}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is not None
        assert signal.action == "SELL"

    def test_normal_volume_no_signal(self):
        strategy = VolumeSpikeStrategy(spike_multiplier=2.0)
        strategy._avg_volume["AAPL"] = 1000

        metrics = {"latest_price": 100.0, "total_volume": 1200, "price_change_pct": 0.1}
        signal = strategy.on_metric("AAPL", metrics)
        assert signal is None


class TestListStrategies:
    def test_returns_all_builtin(self):
        strategies = list_strategies()
        names = [s["name"] for s in strategies]
        assert "vwap_deviation" in names
        assert "ma_crossover" in names
        assert "volume_spike" in names

    def test_has_description(self):
        strategies = list_strategies()
        for s in strategies:
            assert "description" in s
            assert len(s["description"]) > 0


# --- API endpoint tests ---

client = TestClient(app)


class TestStrategyAPI:
    def test_list_strategies(self):
        resp = client.get("/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data
        names = [s["name"] for s in data["strategies"]]
        assert "vwap_deviation" in names

    def test_activate_strategy(self):
        resp = client.post(
            "/strategies/activate?strategy_name=vwap_deviation&symbol=AAPL&active=true"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_name"] == "vwap_deviation"
        assert data["symbol"] == "AAPL"
        assert data["is_active"] is True

    def test_activate_unknown_strategy(self):
        resp = client.post(
            "/strategies/activate?strategy_name=nonexistent&symbol=AAPL"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_deactivate_strategy(self):
        # Activate first
        client.post("/strategies/activate?strategy_name=volume_spike&symbol=GOOG&active=true")
        # Deactivate
        resp = client.post("/strategies/activate?strategy_name=volume_spike&symbol=GOOG&active=false")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_get_signals_empty(self):
        resp = client.get("/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data
        assert isinstance(data["signals"], list)

    def test_get_signals_filtered(self):
        resp = client.get("/signals?strategy_name=vwap_deviation&symbol=AAPL&limit=10")
        assert resp.status_code == 200
        assert "signals" in resp.json()


class TestAlertRulesAPI:
    def test_create_alert_rule(self):
        resp = client.post(
            "/alerts/rules?name=AAPL+above+200&symbol=AAPL&condition=price_above&threshold=200"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "AAPL above 200"
        assert data["symbol"] == "AAPL"
        assert data["condition"] == "price_above"
        assert data["threshold"] == 200.0
        assert data["is_active"] is True

    def test_create_invalid_condition(self):
        resp = client.post(
            "/alerts/rules?name=Bad&symbol=AAPL&condition=invalid&threshold=100"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_list_alert_rules(self):
        resp = client.get("/alerts/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert "rules" in data
        assert len(data["rules"]) > 0

    def test_list_alert_rules_by_symbol(self):
        resp = client.get("/alerts/rules?symbol=AAPL")
        assert resp.status_code == 200
        for rule in resp.json()["rules"]:
            assert rule["symbol"] == "AAPL"

    def test_delete_alert_rule(self):
        # Create one
        resp = client.post(
            "/alerts/rules?name=to_delete&symbol=GOOG&condition=price_below&threshold=100"
        )
        rule_id = resp.json()["rule_id"]

        # Delete it
        resp = client.delete(f"/alerts/rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == rule_id

    def test_delete_nonexistent_rule(self):
        resp = client.delete("/alerts/rules/999999")
        assert resp.status_code == 200
        assert "error" in resp.json()
