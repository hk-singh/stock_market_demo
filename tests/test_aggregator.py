"""Tests for the TradeAggregator class."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'consumers'))

from aggregator_consumer import TradeAggregator


class TestTradeAggregator:
    """Tests for sliding-window aggregation logic."""

    def _make_aggregator(self, window_size=20):
        return TradeAggregator(window_size=window_size)

    def test_single_trade_metrics(self):
        agg = self._make_aggregator()
        agg.add_trade("AAPL", 150.0, 100, 1700000000000)

        metrics = agg.calculate_metrics("AAPL")
        assert metrics is not None
        assert metrics["symbol"] == "AAPL"
        assert metrics["avg_price"] == 150.0
        assert metrics["min_price"] == 150.0
        assert metrics["max_price"] == 150.0
        assert metrics["latest_price"] == 150.0
        assert metrics["total_volume"] == 100
        assert metrics["vwap"] == 150.0
        assert metrics["price_change_pct"] == 0  # single trade, no change
        assert metrics["trade_count"] == 1
        assert metrics["window_size"] == 1

    def test_multiple_trades_metrics(self):
        agg = self._make_aggregator()
        agg.add_trade("AAPL", 100.0, 200, 1700000000000)
        agg.add_trade("AAPL", 110.0, 300, 1700000001000)
        agg.add_trade("AAPL", 105.0, 100, 1700000002000)

        metrics = agg.calculate_metrics("AAPL")
        assert metrics["trade_count"] == 3
        assert metrics["min_price"] == 100.0
        assert metrics["max_price"] == 110.0
        assert metrics["latest_price"] == 105.0
        assert metrics["total_volume"] == 600
        # avg = (100 + 110 + 105) / 3 = 105.0
        assert metrics["avg_price"] == 105.0

    def test_vwap_calculation(self):
        agg = self._make_aggregator()
        # VWAP = sum(price * volume) / sum(volume)
        agg.add_trade("TSLA", 200.0, 100, 1700000000000)
        agg.add_trade("TSLA", 210.0, 200, 1700000001000)

        metrics = agg.calculate_metrics("TSLA")
        # VWAP = (200*100 + 210*200) / (100+200) = (20000 + 42000) / 300 = 206.67
        assert metrics["vwap"] == 206.67

    def test_price_change_percentage(self):
        agg = self._make_aggregator()
        agg.add_trade("MSFT", 100.0, 50, 1700000000000)
        agg.add_trade("MSFT", 120.0, 50, 1700000001000)

        metrics = agg.calculate_metrics("MSFT")
        # change = ((120 - 100) / 100) * 100 = 20.0%
        assert metrics["price_change_pct"] == 20.0

    def test_sliding_window_eviction(self):
        agg = self._make_aggregator(window_size=3)

        agg.add_trade("AAPL", 100.0, 10, 1700000000000)
        agg.add_trade("AAPL", 110.0, 10, 1700000001000)
        agg.add_trade("AAPL", 120.0, 10, 1700000002000)
        # Window full — next trade should evict the oldest (100.0)
        agg.add_trade("AAPL", 130.0, 10, 1700000003000)

        metrics = agg.calculate_metrics("AAPL")
        assert metrics["window_size"] == 3
        assert metrics["trade_count"] == 4  # total seen
        assert metrics["min_price"] == 110.0  # 100 was evicted
        assert metrics["max_price"] == 130.0

    def test_unknown_symbol_returns_none(self):
        agg = self._make_aggregator()
        assert agg.calculate_metrics("UNKNOWN") is None

    def test_multiple_symbols_independent(self):
        agg = self._make_aggregator()
        agg.add_trade("AAPL", 150.0, 100, 1700000000000)
        agg.add_trade("GOOGL", 2800.0, 50, 1700000000000)

        aapl = agg.calculate_metrics("AAPL")
        googl = agg.calculate_metrics("GOOGL")

        assert aapl["symbol"] == "AAPL"
        assert aapl["latest_price"] == 150.0
        assert googl["symbol"] == "GOOGL"
        assert googl["latest_price"] == 2800.0

    def test_zero_volume_vwap(self):
        agg = self._make_aggregator()
        agg.add_trade("AAPL", 150.0, 0, 1700000000000)

        metrics = agg.calculate_metrics("AAPL")
        assert metrics["vwap"] == 0  # division protected
