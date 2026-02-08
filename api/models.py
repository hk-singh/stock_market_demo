"""SQLAlchemy models for trades and aggregated metrics."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    trade_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_trades_symbol_timestamp", "symbol", "trade_timestamp"),
    )


class AggregatedMetric(Base):
    __tablename__ = "aggregated_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    min_price: Mapped[float] = mapped_column(Float, nullable=False)
    max_price: Mapped[float] = mapped_column(Float, nullable=False)
    latest_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vwap: Mapped[float] = mapped_column(Float, nullable=False)
    price_change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_metrics_symbol_calculated", "symbol", "calculated_at"),
    )
