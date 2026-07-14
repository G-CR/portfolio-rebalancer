"""complete immutable snapshot payload

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14 08:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.util import CommandError

revision: str = "20260714_0004"
down_revision: str | None = "20260713_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

money_precision = sa.Numeric(28, 12)


def _require_empty_snapshot_history() -> None:
    has_legacy_rows = op.get_bind().scalar(
        sa.text(
            """
            SELECT EXISTS (SELECT 1 FROM snapshots LIMIT 1)
                OR EXISTS (SELECT 1 FROM snapshot_items LIMIT 1)
            """
        )
    )
    if has_legacy_rows:
        raise CommandError(
            "cannot upgrade 20260714_0004 with existing snapshot history; "
            "the immutable payload cannot be reconstructed safely"
        )


def upgrade() -> None:
    _require_empty_snapshot_history()
    op.add_column(
        "snapshots",
        sa.Column("has_manual_data", sa.Boolean(), nullable=False),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("holding_name", sa.String(length=200), nullable=False),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("target_weight", money_precision, nullable=False),
    )
    op.add_column("snapshot_items", sa.Column("fx_neutral_value_cny", money_precision, nullable=True))
    op.add_column("snapshot_items", sa.Column("price_effect_cny", money_precision, nullable=True))
    op.add_column("snapshot_items", sa.Column("fx_effect_cny", money_precision, nullable=True))
    op.add_column(
        "snapshot_items",
        sa.Column("price_status", sa.String(length=16), nullable=False),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("fx_status", sa.String(length=16), nullable=False),
    )


def downgrade() -> None:
    for column in (
        "fx_status",
        "price_status",
        "fx_effect_cny",
        "price_effect_cny",
        "fx_neutral_value_cny",
        "target_weight",
        "holding_name",
    ):
        op.drop_column("snapshot_items", column)
    op.drop_column("snapshots", "has_manual_data")
