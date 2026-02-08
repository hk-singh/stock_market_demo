"""Portfolio business logic — pure functions that operate on DB sessions."""

from datetime import datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.models import PaperTrade, Portfolio, PortfolioSnapshot, Position, Trade


def get_or_create_portfolio(db: Session, portfolio_id: int | None = None) -> Portfolio:
    """Get existing portfolio or create the default one."""
    if portfolio_id:
        portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
        if portfolio:
            return portfolio

    # Return the first portfolio, or create one
    portfolio = db.query(Portfolio).first()
    if not portfolio:
        portfolio = Portfolio(
            name="Default",
            starting_cash=100_000.0,
            cash_balance=100_000.0,
            created_at=datetime.utcnow(),
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio


def get_latest_price(db: Session, symbol: str) -> float | None:
    """Get the latest trade price for a symbol."""
    trade = (
        db.query(Trade)
        .filter(Trade.symbol == symbol)
        .order_by(desc(Trade.trade_timestamp))
        .first()
    )
    return trade.price if trade else None


def execute_paper_trade(
    db: Session, portfolio_id: int, symbol: str, side: str, shares: int
) -> dict:
    """Execute a paper buy or sell.

    Returns dict with trade details or error.
    """
    symbol = symbol.upper()
    side = side.upper()

    if side not in ("BUY", "SELL"):
        return {"error": "side must be BUY or SELL"}
    if shares <= 0:
        return {"error": "shares must be positive"}

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return {"error": f"Portfolio {portfolio_id} not found"}

    price = get_latest_price(db, symbol)
    if price is None:
        return {"error": f"No market data for {symbol}"}

    total_cost = round(price * shares, 2)

    # Get or create position
    position = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )

    pnl = None

    if side == "BUY":
        if total_cost > portfolio.cash_balance:
            return {
                "error": f"Insufficient cash. Need ${total_cost:.2f}, "
                f"have ${portfolio.cash_balance:.2f}"
            }

        portfolio.cash_balance -= total_cost

        if position:
            # Update average cost
            old_value = position.avg_cost * position.shares
            new_value = old_value + total_cost
            position.shares += shares
            position.avg_cost = round(new_value / position.shares, 4)
        else:
            position = Position(
                portfolio_id=portfolio_id,
                symbol=symbol,
                shares=shares,
                avg_cost=price,
            )
            db.add(position)

    elif side == "SELL":
        if not position or position.shares < shares:
            available = position.shares if position else 0
            return {
                "error": f"Insufficient shares. Want to sell {shares}, "
                f"have {available}"
            }

        # Calculate P&L on this sell
        pnl = round((price - position.avg_cost) * shares, 2)
        portfolio.cash_balance += total_cost
        position.shares -= shares

        # Remove position if fully sold
        if position.shares == 0:
            db.delete(position)

    # Record the trade
    paper_trade = PaperTrade(
        portfolio_id=portfolio_id,
        symbol=symbol,
        side=side,
        shares=shares,
        price=price,
        total_cost=total_cost,
        pnl=pnl,
        executed_at=datetime.utcnow(),
    )
    db.add(paper_trade)
    db.commit()

    return {
        "trade_id": paper_trade.id,
        "symbol": symbol,
        "side": side,
        "shares": shares,
        "price": price,
        "total_cost": total_cost,
        "pnl": pnl,
        "cash_remaining": round(portfolio.cash_balance, 2),
    }


def get_portfolio_summary(db: Session, portfolio_id: int) -> dict:
    """Get current portfolio state: holdings, cash, total value."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return {"error": f"Portfolio {portfolio_id} not found"}

    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.shares > 0)
        .all()
    )

    holdings = []
    positions_value = 0.0

    for pos in positions:
        current_price = get_latest_price(db, pos.symbol)
        if current_price is None:
            current_price = pos.avg_cost  # fallback

        market_value = round(current_price * pos.shares, 2)
        unrealized_pnl = round((current_price - pos.avg_cost) * pos.shares, 2)
        positions_value += market_value

        holdings.append({
            "symbol": pos.symbol,
            "shares": pos.shares,
            "avg_cost": pos.avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
        })

    total_value = round(portfolio.cash_balance + positions_value, 2)
    total_pnl = round(total_value - portfolio.starting_cash, 2)
    total_pnl_pct = round((total_pnl / portfolio.starting_cash) * 100, 2) if portfolio.starting_cash else 0

    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "cash_balance": round(portfolio.cash_balance, 2),
        "positions_value": round(positions_value, 2),
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "starting_cash": portfolio.starting_cash,
        "holdings": holdings,
    }


def get_trade_history(db: Session, portfolio_id: int, limit: int = 50) -> list[dict]:
    """Get the trade log for a portfolio."""
    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_id == portfolio_id)
        .order_by(desc(PaperTrade.executed_at))
        .limit(limit)
        .all()
    )

    return [
        {
            "trade_id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "shares": t.shares,
            "price": t.price,
            "total_cost": t.total_cost,
            "pnl": t.pnl,
            "executed_at": t.executed_at.isoformat(),
        }
        for t in trades
    ]


def get_performance(db: Session, portfolio_id: int) -> dict:
    """Calculate portfolio performance metrics."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return {"error": f"Portfolio {portfolio_id} not found"}

    summary = get_portfolio_summary(db, portfolio_id)

    # Get all completed (SELL) trades for realized P&L
    sells = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_id == portfolio_id, PaperTrade.side == "SELL")
        .all()
    )
    realized_pnl = round(sum(t.pnl for t in sells if t.pnl is not None), 2)

    # Unrealized P&L from holdings
    unrealized_pnl = round(
        sum(h["unrealized_pnl"] for h in summary.get("holdings", [])), 2
    )

    # Get snapshots for max drawdown
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.snapshot_at)
        .all()
    )

    max_drawdown = 0.0
    peak = portfolio.starting_cash
    for snap in snapshots:
        if snap.total_value > peak:
            peak = snap.total_value
        drawdown = (peak - snap.total_value) / peak * 100 if peak > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Trade stats
    all_trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_id == portfolio_id)
        .all()
    )
    total_trades = len(all_trades)
    winning_trades = sum(1 for t in all_trades if t.pnl is not None and t.pnl > 0)
    win_rate = round((winning_trades / total_trades) * 100, 1) if total_trades > 0 else 0

    return {
        "portfolio_id": portfolio_id,
        "total_value": summary["total_value"],
        "total_return": summary["total_pnl"],
        "total_return_pct": summary["total_pnl_pct"],
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "max_drawdown_pct": round(max_drawdown, 2),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate_pct": win_rate,
    }


def take_snapshot(db: Session, portfolio_id: int) -> PortfolioSnapshot | None:
    """Record a point-in-time snapshot of portfolio value."""
    summary = get_portfolio_summary(db, portfolio_id)
    if "error" in summary:
        return None

    snapshot = PortfolioSnapshot(
        portfolio_id=portfolio_id,
        total_value=summary["total_value"],
        cash_balance=summary["cash_balance"],
        positions_value=summary["positions_value"],
        pnl=summary["total_pnl"],
        pnl_pct=summary["total_pnl_pct"],
        snapshot_at=datetime.utcnow(),
    )
    db.add(snapshot)
    db.commit()
    return snapshot
