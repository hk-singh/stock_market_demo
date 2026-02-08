"""Tests for the paper portfolio system."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from api.main import app
from api.models import Trade
from api.portfolio_service import (
    execute_paper_trade,
    get_or_create_portfolio,
    get_performance,
    get_portfolio_summary,
    get_trade_history,
    take_snapshot,
)
from tests.conftest import TestSession

_seeded = False


def _seed_market_data():
    """Insert market data for portfolio tests (idempotent)."""
    global _seeded
    if _seeded:
        return
    db = TestSession()
    now = datetime.utcnow()
    trades = [
        Trade(symbol="MSFT", price=420.00, volume=100, trade_timestamp=1700000010000, ingested_at=now),
        Trade(symbol="NVDA", price=800.00, volume=50, trade_timestamp=1700000010000, ingested_at=now),
    ]
    for t in trades:
        db.add(t)
    db.commit()
    db.close()
    _seeded = True


# --- Service layer tests ---

class TestPortfolioService:
    def test_create_default_portfolio(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        assert portfolio.id is not None
        assert portfolio.cash_balance == 100_000.0
        assert portfolio.name == "Default"
        db.close()

    def test_get_existing_portfolio(self):
        db = TestSession()
        p1 = get_or_create_portfolio(db)
        p2 = get_or_create_portfolio(db)
        assert p1.id == p2.id
        db.close()

    def test_buy_trade(self):
        _seed_market_data()
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        result = execute_paper_trade(db, portfolio.id, "MSFT", "BUY", 10)

        assert "error" not in result
        assert result["symbol"] == "MSFT"
        assert result["side"] == "BUY"
        assert result["shares"] == 10
        assert result["price"] == 420.00
        assert result["total_cost"] == 4200.00
        db.close()

    def test_sell_trade_with_pnl(self):
        _seed_market_data()
        db = TestSession()
        portfolio = get_or_create_portfolio(db)

        # Buy NVDA
        execute_paper_trade(db, portfolio.id, "NVDA", "BUY", 5)

        # Simulate price increase
        new_trade = Trade(
            symbol="NVDA", price=850.00, volume=10,
            trade_timestamp=1700000020000, ingested_at=datetime.utcnow(),
        )
        db.add(new_trade)
        db.commit()

        # Sell at higher price
        result = execute_paper_trade(db, portfolio.id, "NVDA", "SELL", 5)
        assert result["pnl"] == (850.00 - 800.00) * 5  # $250 profit
        db.close()

    def test_insufficient_cash(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        result = execute_paper_trade(db, portfolio.id, "MSFT", "BUY", 1_000_000)
        assert "error" in result
        assert "Insufficient cash" in result["error"]
        db.close()

    def test_insufficient_shares(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        result = execute_paper_trade(db, portfolio.id, "NVDA", "SELL", 999999)
        assert "error" in result
        assert "Insufficient shares" in result["error"]
        db.close()

    def test_invalid_side(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        result = execute_paper_trade(db, portfolio.id, "MSFT", "HOLD", 10)
        assert result == {"error": "side must be BUY or SELL"}
        db.close()

    def test_portfolio_summary(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        summary = get_portfolio_summary(db, portfolio.id)

        assert "holdings" in summary
        assert summary["total_value"] > 0
        assert summary["starting_cash"] == 100_000.0
        db.close()

    def test_trade_history(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        history = get_trade_history(db, portfolio.id)

        assert isinstance(history, list)
        assert len(history) > 0
        assert "symbol" in history[0]
        assert "side" in history[0]
        db.close()

    def test_performance_metrics(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        perf = get_performance(db, portfolio.id)

        assert "total_value" in perf
        assert "total_return" in perf
        assert "realized_pnl" in perf
        assert "win_rate_pct" in perf
        db.close()

    def test_snapshot(self):
        db = TestSession()
        portfolio = get_or_create_portfolio(db)
        snap = take_snapshot(db, portfolio.id)

        assert snap is not None
        assert snap.total_value > 0
        assert snap.portfolio_id == portfolio.id
        db.close()


# --- API endpoint tests ---

client = TestClient(app)


class TestPortfolioAPI:
    def test_init_portfolio(self):
        resp = client.post("/portfolio/init")
        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio_id" in data
        assert data["starting_cash"] == 100_000.0

    def test_buy_via_api(self):
        _seed_market_data()
        resp = client.post("/portfolio/trade?symbol=MSFT&side=BUY&shares=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "MSFT"
        assert data["side"] == "BUY"

    def test_get_portfolio_via_api(self):
        resp = client.get("/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "holdings" in data
        assert "total_value" in data

    def test_get_history_via_api(self):
        resp = client.get("/portfolio/history")
        assert resp.status_code == 200
        assert "trades" in resp.json()

    def test_get_performance_via_api(self):
        resp = client.get("/portfolio/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_return" in data
        assert "win_rate_pct" in data
