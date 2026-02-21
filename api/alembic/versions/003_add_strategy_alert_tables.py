"""add strategy and alert tables

Revision ID: 003
Revises: 002
Create Date: 2026-02-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_name", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_strategy_name", "strategy_signals", ["strategy_name"])
    op.create_index("ix_signals_symbol", "strategy_signals", ["symbol"])
    op.create_index(
        "ix_signals_strategy_symbol", "strategy_signals", ["strategy_name", "symbol"]
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("condition", sa.String(length=20), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("triggered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rules_symbol", "alert_rules", ["symbol"])

    op.create_table(
        "active_strategies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_name", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_active_strategy_symbol",
        "active_strategies",
        ["strategy_name", "symbol"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_active_strategy_symbol", table_name="active_strategies")
    op.drop_table("active_strategies")
    op.drop_index("ix_alert_rules_symbol", table_name="alert_rules")
    op.drop_table("alert_rules")
    op.drop_index("ix_signals_strategy_symbol", table_name="strategy_signals")
    op.drop_index("ix_signals_symbol", table_name="strategy_signals")
    op.drop_index("ix_signals_strategy_name", table_name="strategy_signals")
    op.drop_table("strategy_signals")
