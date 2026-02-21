"""FastAPI application for the stock market streaming platform."""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import (
    ActiveStrategy,
    AggregatedMetric,
    AlertRule,
    StrategySignal,
    Trade,
)
from api.portfolio_service import (
    execute_paper_trade,
    get_or_create_portfolio,
    get_performance,
    get_portfolio_summary,
    get_trade_history,
)
from api.strategy_engine import list_strategies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Stock Market Streaming API",
    description="Real-time stock market data from Kafka pipeline",
    version="1.0.0",
)


# --- WebSocket connection manager ---

class ConnectionManager:
    """Manages active WebSocket connections for live streaming."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in self.active[:]:
            try:
                await ws.send_json(message)
            except Exception:
                self.active.remove(ws)


manager = ConnectionManager()


# --- REST endpoints ---

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/symbols")
def list_symbols(db: Session = Depends(get_db)):
    """List all symbols that have trade data."""
    rows = db.query(Trade.symbol).distinct().order_by(Trade.symbol).all()
    return {"symbols": [r[0] for r in rows]}


@app.get("/symbols/{symbol}/price")
def get_symbol_price(symbol: str, db: Session = Depends(get_db)):
    """Get the latest price and metrics for a symbol."""
    symbol = symbol.upper()

    # Latest trade
    latest_trade = (
        db.query(Trade)
        .filter(Trade.symbol == symbol)
        .order_by(desc(Trade.trade_timestamp))
        .first()
    )

    # Latest metrics
    latest_metric = (
        db.query(AggregatedMetric)
        .filter(AggregatedMetric.symbol == symbol)
        .order_by(desc(AggregatedMetric.calculated_at))
        .first()
    )

    if not latest_trade:
        return {"error": f"No data for symbol {symbol}"}, 404

    result = {
        "symbol": symbol,
        "latest_price": latest_trade.price,
        "latest_volume": latest_trade.volume,
        "trade_timestamp": latest_trade.trade_timestamp,
    }

    if latest_metric:
        result.update({
            "vwap": latest_metric.vwap,
            "avg_price": latest_metric.avg_price,
            "min_price": latest_metric.min_price,
            "max_price": latest_metric.max_price,
            "total_volume": latest_metric.total_volume,
            "price_change_pct": latest_metric.price_change_pct,
            "trade_count": latest_metric.trade_count,
        })

    return result


@app.get("/symbols/{symbol}/history")
def get_symbol_history(
    symbol: str,
    window: str = Query("1h", description="Time window: 1h, 6h, 24h"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """Get recent trade history for a symbol within a time window."""
    symbol = symbol.upper()

    hours_map = {"1h": 1, "6h": 6, "24h": 24}
    hours = hours_map.get(window, 1)
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    trades = (
        db.query(Trade)
        .filter(Trade.symbol == symbol, Trade.ingested_at >= cutoff)
        .order_by(desc(Trade.trade_timestamp))
        .limit(limit)
        .all()
    )

    return {
        "symbol": symbol,
        "window": window,
        "count": len(trades),
        "trades": [
            {
                "price": t.price,
                "volume": t.volume,
                "timestamp": t.trade_timestamp,
                "ingested_at": t.ingested_at.isoformat(),
            }
            for t in trades
        ],
    }


@app.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """Get the latest aggregated metrics for all tracked symbols."""
    # Subquery for max calculated_at per symbol
    subq = (
        db.query(
            AggregatedMetric.symbol,
            func.max(AggregatedMetric.calculated_at).label("max_at"),
        )
        .group_by(AggregatedMetric.symbol)
        .subquery()
    )

    metrics = (
        db.query(AggregatedMetric)
        .join(
            subq,
            (AggregatedMetric.symbol == subq.c.symbol)
            & (AggregatedMetric.calculated_at == subq.c.max_at),
        )
        .order_by(AggregatedMetric.symbol)
        .all()
    )

    return {
        "metrics": [
            {
                "symbol": m.symbol,
                "latest_price": m.latest_price,
                "vwap": m.vwap,
                "avg_price": m.avg_price,
                "min_price": m.min_price,
                "max_price": m.max_price,
                "total_volume": m.total_volume,
                "price_change_pct": m.price_change_pct,
                "trade_count": m.trade_count,
                "calculated_at": m.calculated_at.isoformat(),
            }
            for m in metrics
        ]
    }


# --- Portfolio endpoints ---

@app.post("/portfolio/init")
def init_portfolio(
    name: str = Query("Default"),
    starting_cash: float = Query(100_000.0, ge=1),
    db: Session = Depends(get_db),
):
    """Create or get the default portfolio."""
    portfolio = get_or_create_portfolio(db)
    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "cash_balance": portfolio.cash_balance,
        "starting_cash": portfolio.starting_cash,
    }


@app.post("/portfolio/trade")
def post_trade(
    symbol: str = Query(..., description="Stock symbol, e.g. AAPL"),
    side: str = Query(..., description="BUY or SELL"),
    shares: int = Query(..., ge=1, description="Number of shares"),
    db: Session = Depends(get_db),
):
    """Execute a paper buy or sell at current market price."""
    portfolio = get_or_create_portfolio(db)
    result = execute_paper_trade(db, portfolio.id, symbol, side, shares)
    return result


@app.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    """Get current portfolio: holdings, cash, total value."""
    portfolio = get_or_create_portfolio(db)
    return get_portfolio_summary(db, portfolio.id)


@app.get("/portfolio/history")
def get_portfolio_history(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Get the trade log with P&L per trade."""
    portfolio = get_or_create_portfolio(db)
    return {"trades": get_trade_history(db, portfolio.id, limit)}


@app.get("/portfolio/performance")
def get_portfolio_performance(db: Session = Depends(get_db)):
    """Get portfolio performance: returns, max drawdown, win rate."""
    portfolio = get_or_create_portfolio(db)
    return get_performance(db, portfolio.id)


# --- Strategy & Alert endpoints ---

@app.get("/strategies")
def get_strategies(db: Session = Depends(get_db)):
    """List all available strategies and their activation status."""
    strategies = list_strategies()

    # Enrich with activation info
    for s in strategies:
        active_rows = (
            db.query(ActiveStrategy)
            .filter(ActiveStrategy.strategy_name == s["name"], ActiveStrategy.is_active == 1)
            .all()
        )
        s["active_symbols"] = [r.symbol for r in active_rows]

    return {"strategies": strategies}


@app.post("/strategies/activate")
def activate_strategy(
    strategy_name: str = Query(..., description="Strategy name, e.g. vwap_deviation"),
    symbol: str = Query(..., description="Stock symbol, e.g. AAPL"),
    active: bool = Query(True, description="Activate (true) or deactivate (false)"),
    db: Session = Depends(get_db),
):
    """Activate or deactivate a strategy for a specific symbol."""
    from api.strategy_engine import get_strategy

    if not get_strategy(strategy_name):
        return {"error": f"Unknown strategy: {strategy_name}"}

    symbol = symbol.upper()
    existing = (
        db.query(ActiveStrategy)
        .filter(
            ActiveStrategy.strategy_name == strategy_name,
            ActiveStrategy.symbol == symbol,
        )
        .first()
    )

    if existing:
        existing.is_active = 1 if active else 0
    else:
        existing = ActiveStrategy(
            strategy_name=strategy_name,
            symbol=symbol,
            is_active=1 if active else 0,
            created_at=datetime.utcnow(),
        )
        db.add(existing)

    db.commit()
    return {
        "strategy_name": strategy_name,
        "symbol": symbol,
        "is_active": active,
    }


@app.get("/signals")
def get_signals(
    strategy_name: str = Query(None, description="Filter by strategy name"),
    symbol: str = Query(None, description="Filter by symbol"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Get recent strategy signals, optionally filtered."""
    query = db.query(StrategySignal)

    if strategy_name:
        query = query.filter(StrategySignal.strategy_name == strategy_name)
    if symbol:
        query = query.filter(StrategySignal.symbol == symbol.upper())

    signals = query.order_by(desc(StrategySignal.created_at)).limit(limit).all()

    return {
        "signals": [
            {
                "id": s.id,
                "strategy_name": s.strategy_name,
                "symbol": s.symbol,
                "action": s.action,
                "reason": s.reason,
                "strength": s.strength,
                "price": s.price,
                "created_at": s.created_at.isoformat(),
            }
            for s in signals
        ]
    }


@app.post("/alerts/rules")
def create_alert_rule(
    name: str = Query(..., description="Rule name"),
    symbol: str = Query(..., description="Stock symbol"),
    condition: str = Query(..., description="price_above, price_below, or volume_above"),
    threshold: float = Query(..., description="Threshold value"),
    db: Session = Depends(get_db),
):
    """Create a custom alert rule."""
    valid_conditions = ("price_above", "price_below", "volume_above")
    if condition not in valid_conditions:
        return {"error": f"condition must be one of {valid_conditions}"}

    rule = AlertRule(
        name=name,
        symbol=symbol.upper(),
        condition=condition,
        threshold=threshold,
        is_active=1,
        triggered_count=0,
        created_at=datetime.utcnow(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    return {
        "rule_id": rule.id,
        "name": rule.name,
        "symbol": rule.symbol,
        "condition": rule.condition,
        "threshold": rule.threshold,
        "is_active": True,
    }


@app.get("/alerts/rules")
def get_alert_rules(
    symbol: str = Query(None, description="Filter by symbol"),
    db: Session = Depends(get_db),
):
    """List all alert rules."""
    query = db.query(AlertRule)
    if symbol:
        query = query.filter(AlertRule.symbol == symbol.upper())

    rules = query.order_by(desc(AlertRule.created_at)).all()
    return {
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "symbol": r.symbol,
                "condition": r.condition,
                "threshold": r.threshold,
                "is_active": bool(r.is_active),
                "triggered_count": r.triggered_count,
                "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
            }
            for r in rules
        ]
    }


@app.delete("/alerts/rules/{rule_id}")
def delete_alert_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete an alert rule."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        return {"error": f"Rule {rule_id} not found"}
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


# --- WebSocket endpoint ---

@app.websocket("/ws/stream")
async def websocket_stream(ws: WebSocket):
    """Stream real-time trade data to connected clients.

    Polls the database for new trades every second and pushes them
    to connected WebSocket clients.
    """
    await manager.connect(ws)
    logger.info(f"WebSocket client connected ({len(manager.active)} total)")
    try:
        last_id = 0
        # Get the current max trade id so we only stream new ones
        from api.database import SessionLocal

        db = SessionLocal()
        try:
            row = db.query(func.max(Trade.id)).scalar()
            last_id = row or 0
        finally:
            db.close()

        while True:
            # Check for new trades
            db = SessionLocal()
            try:
                new_trades = (
                    db.query(Trade)
                    .filter(Trade.id > last_id)
                    .order_by(Trade.id)
                    .limit(100)
                    .all()
                )
                if new_trades:
                    last_id = new_trades[-1].id
                    for t in new_trades:
                        await ws.send_json({
                            "type": "trade",
                            "symbol": t.symbol,
                            "price": t.price,
                            "volume": t.volume,
                            "timestamp": t.trade_timestamp,
                        })
            finally:
                db.close()

            # Also handle incoming messages (ping/pong, close)
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(ws)
        logger.info(f"WebSocket client disconnected ({len(manager.active)} total)")
