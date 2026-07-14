"""complete immutable snapshot payload

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14 08:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0004"
down_revision: str | None = "20260713_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

money_precision = sa.Numeric(28, 12)


def upgrade() -> None:
    op.add_column(
        "snapshots",
        sa.Column("has_manual_data", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("snapshot_items", sa.Column("holding_name", sa.String(length=200), nullable=True))
    op.add_column("snapshot_items", sa.Column("target_weight", money_precision, nullable=True))
    op.add_column("snapshot_items", sa.Column("fx_neutral_value_cny", money_precision, nullable=True))
    op.add_column("snapshot_items", sa.Column("price_effect_cny", money_precision, nullable=True))
    op.add_column("snapshot_items", sa.Column("fx_effect_cny", money_precision, nullable=True))
    op.add_column("snapshot_items", sa.Column("price_status", sa.String(length=16), nullable=True))
    op.add_column("snapshot_items", sa.Column("fx_status", sa.String(length=16), nullable=True))
    op.execute(
        """
        UPDATE snapshot_items AS item
        SET holding_name = COALESCE(holding.name, item.symbol),
            target_weight = asset_class.target_weight,
            fx_neutral_value_cny = item.market_value_cny,
            price_effect_cny = item.unrealized_pnl_amount_cny,
            fx_effect_cny = 0,
            price_status = CASE WHEN item.market_price IS NULL THEN 'missing' ELSE 'valid' END,
            fx_status = CASE WHEN item.current_fx_to_cny IS NULL THEN 'missing' ELSE 'valid' END
        FROM holdings AS holding
        JOIN asset_classes AS asset_class ON asset_class.id = holding.asset_class_id
        WHERE holding.id = item.holding_id
        """
    )
    op.execute(
        """
        UPDATE snapshot_items
        SET holding_name = COALESCE(holding_name, symbol),
            target_weight = COALESCE(target_weight, 0),
            fx_neutral_value_cny = COALESCE(fx_neutral_value_cny, market_value_cny),
            price_effect_cny = COALESCE(price_effect_cny, unrealized_pnl_amount_cny),
            fx_effect_cny = COALESCE(fx_effect_cny, 0),
            price_status = COALESCE(price_status, 'missing'),
            fx_status = COALESCE(fx_status, 'missing')
        """
    )
    for column in (
        "holding_name",
        "target_weight",
        "price_status",
        "fx_status",
    ):
        op.alter_column("snapshot_items", column, nullable=False)


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
