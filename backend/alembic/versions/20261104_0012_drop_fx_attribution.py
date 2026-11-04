"""Drop manual cost-FX and FX PnL attribution.

The repository no longer infers a CNY cost basis from a user-entered
"cost FX". Holdings keep their trade-currency average cost; CNY cost and PnL
are reference values derived from the current FX rate at read time.

Historical snapshot rows are normalized first: their CNY cost and PnL are
recomputed from the stored quantity, average cost and current FX, so the old
cost-FX distortion does not remain in snapshot history. The removed columns
are dropped afterwards. The downgrade recreates the columns with neutral
defaults, but it cannot recover the deleted historical FX values.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0012"
down_revision: str | None = "20261001_0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Normalize snapshot history to the new reference-cost semantics before
    # dropping the inputs that produced the old values.
    op.execute(
        """
        UPDATE snapshot_items
        SET cost_value_cny = quantity * average_cost_price * current_fx_to_cny
        WHERE current_fx_to_cny IS NOT NULL
        """
    )
    # Rows captured while the current FX was missing have no valid reference
    # cost under the new semantics. Clear the old cost-FX-derived values
    # before their inputs are dropped.
    op.execute(
        """
        UPDATE snapshot_items
        SET cost_value_cny = NULL,
            unrealized_pnl_amount_cny = NULL,
            unrealized_pnl_rate = NULL
        WHERE current_fx_to_cny IS NULL
        """
    )
    op.execute(
        """
        UPDATE snapshot_items
        SET unrealized_pnl_amount_cny = market_value_cny - cost_value_cny
        WHERE market_value_cny IS NOT NULL AND cost_value_cny IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE snapshot_items
        SET unrealized_pnl_rate = CASE
            WHEN cost_value_cny <> 0
            THEN unrealized_pnl_amount_cny / cost_value_cny
            ELSE 0
        END
        WHERE unrealized_pnl_amount_cny IS NOT NULL AND cost_value_cny IS NOT NULL
        """
    )

    op.drop_column("snapshot_items", "fx_neutral_weight")
    op.drop_column("snapshot_items", "fx_effect_cny")
    op.drop_column("snapshot_items", "price_effect_cny")
    op.drop_column("snapshot_items", "fx_neutral_value_cny")
    op.drop_column("snapshot_items", "cost_fx_to_cny")
    op.drop_column("snapshot_items", "baseline_fx_to_cny")

    op.drop_column("cost_adjustments", "after_cost_fx_to_cny")
    op.drop_column("cost_adjustments", "before_cost_fx_to_cny")

    op.drop_column("holdings", "baseline_fx_to_cny")
    op.drop_column("holdings", "cost_fx_to_cny")

    op.drop_constraint(
        "ck_settings_rebalance_valuation_basis",
        "settings",
        type_="check",
    )
    op.drop_column("settings", "rebalance_valuation_basis")

    op.drop_column("rebalance_plans", "baseline_reset_at")
    op.drop_column("rebalance_plans", "strategy_mode")


def downgrade() -> None:
    op.add_column(
        "rebalance_plans",
        sa.Column("strategy_mode", sa.String(length=16), nullable=False, server_default="actual"),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("baseline_reset_at", sa.DateTime(timezone=True), nullable=True),
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

    op.add_column(
        "holdings",
        sa.Column("cost_fx_to_cny", sa.Numeric(28, 12), nullable=False, server_default="1"),
    )
    op.add_column(
        "holdings",
        sa.Column("baseline_fx_to_cny", sa.Numeric(28, 12), nullable=False, server_default="1"),
    )

    op.add_column(
        "cost_adjustments",
        sa.Column(
            "before_cost_fx_to_cny",
            sa.Numeric(28, 12),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "cost_adjustments",
        sa.Column(
            "after_cost_fx_to_cny",
            sa.Numeric(28, 12),
            nullable=False,
            server_default="1",
        ),
    )

    op.add_column(
        "snapshot_items",
        sa.Column(
            "baseline_fx_to_cny",
            sa.Numeric(28, 12),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "snapshot_items",
        sa.Column(
            "cost_fx_to_cny",
            sa.Numeric(28, 12),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("fx_neutral_value_cny", sa.Numeric(28, 12), nullable=True),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("price_effect_cny", sa.Numeric(28, 12), nullable=True),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("fx_effect_cny", sa.Numeric(28, 12), nullable=True),
    )
    op.add_column(
        "snapshot_items",
        sa.Column("fx_neutral_weight", sa.Numeric(28, 12), nullable=True),
    )
