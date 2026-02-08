"""Tests for the DB consumer's write functions."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base
from api.db_consumer import write_metric, write_trade
from api.models import AggregatedMetric, Trade

TEST_DATABASE_URL = "sqlite:///file:test_db_consumer?mode=memory&cache=shared&uri=true"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def setup_module():
    Base.metadata.create_all(bind=engine)


def teardown_module():
    Base.metadata.drop_all(bind=engine)


class TestWriteTrade:
    def test_write_trade_inserts_row(self):
        db = TestSession()
        trade_data = {
            "s": "TSLA",
            "p": 245.67,
            "v": 300,
            "t": 1700000000000,
        }
        write_trade(db, trade_data)
        db.commit()

        row = db.query(Trade).filter(Trade.symbol == "TSLA").first()
        assert row is not None
        assert row.price == 245.67
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
            "symbol": "AAPL",
            "trade_count": 100,
            "window_size": 20,
            "avg_price": 178.50,
            "min_price": 175.00,
            "max_price": 182.00,
            "latest_price": 180.00,
            "total_volume": 10000,
            "vwap": 178.90,
            "price_change_pct": 1.5,
        }
        write_metric(db, metric_data)
        db.commit()

        row = db.query(AggregatedMetric).filter(AggregatedMetric.symbol == "AAPL").first()
        assert row is not None
        assert row.vwap == 178.90
        assert row.trade_count == 100
        db.close()
