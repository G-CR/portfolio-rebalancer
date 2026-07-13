"""limit holding identity uniqueness to active rows

This migration is conditionally irreversible. Head-state data may validly contain
an archived holding and an active holding with the same symbol and account. The
old all-row unique constraint cannot represent that history, so downgrade must
refuse such data rather than deleting or rewriting archived holdings.

Revision ID: 20260713_0003
Revises: 20260713_0002
Create Date: 2026-07-13 23:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.util import CommandError

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
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE holdings IN ACCESS EXCLUSIVE MODE"))
    duplicate_identity = connection.execute(
        sa.text(
            """
            SELECT symbol, account_name
            FROM holdings
            GROUP BY symbol, account_name
            HAVING count(*) > 1
            ORDER BY symbol, account_name
            LIMIT 1
            """
        )
    ).mappings().first()
    if duplicate_identity is not None:
        raise CommandError(
            "cannot downgrade 20260713_0003 without discarding holding history: "
            "the previous schema requires symbol and account_name to be unique "
            "across active and archived holdings; resolve duplicate identities "
            "explicitly before retrying"
        )

    op.drop_index(
        "uq_holdings_active_symbol_account_name",
        table_name="holdings",
    )
    op.create_unique_constraint(
        "uq_holdings_symbol_account_name",
        "holdings",
        ["symbol", "account_name"],
    )
