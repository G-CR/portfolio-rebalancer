"""limit holding identity uniqueness to active rows

Revision ID: 20260713_0003
Revises: 20260713_0002
Create Date: 2026-07-13 23:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0003"
down_revision: str | None = "20260713_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_holdings_symbol_account_name",
        "holdings",
        type_="unique",
    )
    op.create_index(
        "uq_holdings_active_symbol_account_name",
        "holdings",
        ["symbol", "account_name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_holdings_active_symbol_account_name",
        table_name="holdings",
    )
    op.create_unique_constraint(
        "uq_holdings_symbol_account_name",
        "holdings",
        ["symbol", "account_name"],
    )
