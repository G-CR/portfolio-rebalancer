"""add holding preferred data source

Revision ID: 20260714_0006
Revises: 20260714_0005
Create Date: 2026-07-14 17:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0006"
down_revision: str | None = "20260714_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "holdings",
        sa.Column("preferred_data_source", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE holdings AS h
        SET preferred_data_source = d.default_data_source
        FROM holding_defaults AS d
        WHERE d.holding_id = h.id AND d.default_data_source IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("holdings", "preferred_data_source")
