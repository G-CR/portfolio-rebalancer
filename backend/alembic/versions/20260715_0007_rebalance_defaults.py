"""add persisted rebalance defaults

Revision ID: 20260715_0007
Revises: 20260714_0006
Create Date: 2026-07-15 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_0007"
down_revision: str | None = "20260714_0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column(
            "rebalance_available_cny",
            sa.Numeric(28, 12),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "rebalance_available_usd",
            sa.Numeric(28, 12),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "rebalance_valuation_basis",
            sa.String(length=16),
            nullable=False,
            server_default="actual",
        ),
    )
    op.create_check_constraint(
        "ck_settings_rebalance_valuation_basis",
        "settings",
        "rebalance_valuation_basis IN ('actual', 'fx_neutral')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_settings_rebalance_valuation_basis",
        "settings",
        type_="check",
    )
    op.drop_column("settings", "rebalance_valuation_basis")
    op.drop_column("settings", "rebalance_available_usd")
    op.drop_column("settings", "rebalance_available_cny")
