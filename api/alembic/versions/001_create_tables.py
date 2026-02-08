"""create trades and aggregated_metrics tables

Revision ID: 001
Revises:
Create Date: 2026-02-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("trade_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_symbol", "trades", ["symbol"])
    op.create_index("ix_trades_symbol_timestamp", "trades", ["symbol", "trade_timestamp"])

    op.create_table(
        "aggregated_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("window_size", sa.Integer(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=False),
        sa.Column("min_price", sa.Float(), nullable=False),
        sa.Column("max_price", sa.Float(), nullable=False),
        sa.Column("latest_price", sa.Float(), nullable=False),
        sa.Column("total_volume", sa.BigInteger(), nullable=False),
        sa.Column("vwap", sa.Float(), nullable=False),
        sa.Column("price_change_pct", sa.Float(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metrics_symbol", "aggregated_metrics", ["symbol"])
    op.create_index(
        "ix_metrics_symbol_calculated", "aggregated_metrics", ["symbol", "calculated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_metrics_symbol_calculated", table_name="aggregated_metrics")
    op.drop_index("ix_metrics_symbol", table_name="aggregated_metrics")
    op.drop_table("aggregated_metrics")
    op.drop_index("ix_trades_symbol_timestamp", table_name="trades")
    op.drop_index("ix_trades_symbol", table_name="trades")
    op.drop_table("trades")
