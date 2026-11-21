"""Persist the optional rebalance contribution floor."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0013"
down_revision = "20261104_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings", sa.Column(
        "rebalance_minimum_contribution_cny", sa.Numeric(28, 12),
        nullable=False, server_default="0",
    ))


def downgrade() -> None:
    op.drop_column("settings", "rebalance_minimum_contribution_cny")
