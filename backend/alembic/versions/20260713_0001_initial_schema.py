"""initial schema

Revision ID: 20260713_0001
Revises:
Create Date: 2026-07-13 00:01:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

money_precision = sa.Numeric(28, 12)
default_settings_id = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "asset_classes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("target_weight", money_precision, nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_classes")),
    )
    op.create_index(
        "uq_asset_classes_active_name",
        "asset_classes",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "market_data",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_type", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("value", money_precision, nullable=True),
        sa.Column("market_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data")),
        sa.UniqueConstraint(
            "data_type",
            "symbol",
            "source",
            "market_time",
            name="uq_market_data_source_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    op.create_table(
        "market_data_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_type", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("value", money_precision, nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_overrides")),
    )

    op.create_table(
        "rebalance_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("suggested_actions", sa.JSON(), nullable=False),
        sa.Column("projected_result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rebalance_plans")),
    )

    op.create_table(
        "settings",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{default_settings_id}'::uuid"),
        ),
        sa.Column("refresh_hour", sa.Integer(), nullable=False),
        sa.Column("refresh_minute", sa.Integer(), nullable=False),
        sa.Column("provider_priority", sa.JSON(), nullable=False),
        sa.Column("default_tolerance", money_precision, nullable=False),
        sa.Column("minimum_trade_amount_cny", money_precision, nullable=False),
        sa.Column("allow_sell", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_fx", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            f"id = '{default_settings_id}'::uuid",
            name="ck_settings_singleton_id",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
    )

    op.create_table(
        "encrypted_secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("masked_value", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=True),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_encrypted_secrets")),
        sa.UniqueConstraint("provider", name="uq_encrypted_secrets_provider"),
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("data_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("has_stale_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    op.create_index(
        "uq_snapshots_daily_local_date",
        "snapshots",
        ["local_date"],
        unique=True,
        postgresql_where=sa.text("snapshot_type = 'daily'"),
    )

    op.create_table(
        "holdings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_class_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("trade_currency", sa.String(length=8), nullable=False),
        sa.Column("quantity", money_precision, nullable=False),
        sa.Column("average_cost_price", money_precision, nullable=False),
        sa.Column("cost_fx_to_cny", money_precision, nullable=False),
        sa.Column("baseline_fx_to_cny", money_precision, nullable=False),
        sa.Column("lot_size", money_precision, nullable=False),
        sa.Column("quantity_precision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_rebalance_preferred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_class_id"],
            ["asset_classes.id"],
            name=op.f("fk_holdings_asset_class_id_asset_classes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holdings")),
        sa.UniqueConstraint("symbol", "account_name", name="uq_holdings_symbol_account_name"),
    )
    op.create_index(
        "uq_holdings_active_preferred_asset_class",
        "holdings",
        ["asset_class_id"],
        unique=True,
        postgresql_where=sa.text("is_rebalance_preferred AND is_active"),
    )

    op.create_table(
        "cost_adjustments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("before_quantity", money_precision, nullable=False),
        sa.Column("before_average_cost_price", money_precision, nullable=False),
        sa.Column("before_cost_fx_to_cny", money_precision, nullable=False),
        sa.Column("after_quantity", money_precision, nullable=False),
        sa.Column("after_average_cost_price", money_precision, nullable=False),
        sa.Column("after_cost_fx_to_cny", money_precision, nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["holdings.id"],
            name=op.f("fk_cost_adjustments_holding_id_holdings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cost_adjustments")),
    )

    op.create_table(
        "holding_defaults",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=False),
        sa.Column("fee_currency", sa.String(length=8), nullable=False),
        sa.Column("commission_rate", money_precision, nullable=False),
        sa.Column("minimum_commission", money_precision, nullable=False),
        sa.Column("per_share_fee", money_precision, nullable=False),
        sa.Column("fixed_fee", money_precision, nullable=False),
        sa.Column("default_data_source", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["holdings.id"],
            name=op.f("fk_holding_defaults_holding_id_holdings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holding_defaults")),
        sa.UniqueConstraint("holding_id", name="uq_holding_defaults_holding_id"),
    )

    op.create_table(
        "snapshot_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=True),
        sa.Column("asset_class_name", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("trade_currency", sa.String(length=8), nullable=False),
        sa.Column("quantity", money_precision, nullable=False),
        sa.Column("market_price", money_precision, nullable=True),
        sa.Column("current_fx_to_cny", money_precision, nullable=True),
        sa.Column("baseline_fx_to_cny", money_precision, nullable=False),
        sa.Column("average_cost_price", money_precision, nullable=False),
        sa.Column("cost_fx_to_cny", money_precision, nullable=False),
        sa.Column("market_value_cny", money_precision, nullable=True),
        sa.Column("cost_value_cny", money_precision, nullable=True),
        sa.Column("unrealized_pnl_amount_cny", money_precision, nullable=True),
        sa.Column("unrealized_pnl_rate", money_precision, nullable=True),
        sa.Column("actual_weight", money_precision, nullable=True),
        sa.Column("fx_neutral_weight", money_precision, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["holdings.id"],
            name=op.f("fk_snapshot_items_holding_id_holdings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_snapshot_items_snapshot_id_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshot_items")),
    )


def downgrade() -> None:
    op.drop_table("snapshot_items")
    op.drop_table("holding_defaults")
    op.drop_table("cost_adjustments")
    op.drop_index("uq_holdings_active_preferred_asset_class", table_name="holdings")
    op.drop_table("holdings")
    op.drop_index("uq_snapshots_daily_local_date", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_table("encrypted_secrets")
    op.drop_table("settings")
    op.drop_table("rebalance_plans")
    op.drop_table("market_data_overrides")
    op.drop_table("market_data")
    op.drop_index("uq_asset_classes_active_name", table_name="asset_classes")
    op.drop_table("asset_classes")
