"""Tests for the DB consumer's write functions."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.db_consumer import write_metric, write_trade
from api.models import AggregatedMetric, Trade
from tests.conftest import TestSession


class TestWriteTrade:
    def test_write_trade_inserts_row(self):
        db = TestSession()
        trade_data = {
            "s": "AMZN",
            "p": 185.50,
            "v": 300,
            "t": 1700000000000,
        }
        write_trade(db, trade_data)
        db.commit()

        row = db.query(Trade).filter(Trade.symbol == "AMZN").first()
        assert row is not None
        assert row.price == 185.50
        assert row.volume == 300
        assert row.trade_timestamp == 1700000000000
        db.close()

    def test_write_trade_handles_missing_fields(self):
        db = TestSession()
        write_trade(db, {})
        db.commit()

        row = db.query(Trade).filter(Trade.symbol == "UNKNOWN").first()
        assert row is not None
        assert row.price == 0
        db.close()


class TestWriteMetric:
    def test_write_metric_inserts_row(self):
        db = TestSession()
        metric_data = {
            "symbol": "AMZN",
            "trade_count": 100,
            "window_size": 20,
            "avg_price": 185.50,
            "min_price": 183.00,
            "max_price": 188.00,
            "latest_price": 186.00,
            "total_volume": 10000,
            "vwap": 185.90,
            "price_change_pct": 1.5,
        }
        write_metric(db, metric_data)
        db.commit()

        row = db.query(AggregatedMetric).filter(AggregatedMetric.symbol == "AMZN").first()
        assert row is not None
        assert row.vwap == 185.90
        assert row.trade_count == 100
        db.close()
