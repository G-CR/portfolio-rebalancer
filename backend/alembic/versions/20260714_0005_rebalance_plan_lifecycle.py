"""add rebalance lifecycle metadata

Revision ID: 20260714_0005
Revises: 20260714_0004
Create Date: 2026-07-14 14:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260714_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rebalance_plans",
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("before_snapshot_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("after_snapshot_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("baseline_reset_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("start_market_data_record_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("completion_market_data_record_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("start_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("cancel_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "rebalance_plans",
        sa.Column("complete_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint(
        "uq_rebalance_plans_create_idempotency_key",
        "rebalance_plans",
        ["create_idempotency_key"],
    )
    op.create_foreign_key(
        op.f("fk_rebalance_plans_before_snapshot_id_snapshots"),
        "rebalance_plans",
        "snapshots",
        ["before_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_rebalance_plans_after_snapshot_id_snapshots"),
        "rebalance_plans",
        "snapshots",
        ["after_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_rebalance_plans_after_snapshot_id_snapshots"),
        "rebalance_plans",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_rebalance_plans_before_snapshot_id_snapshots"),
        "rebalance_plans",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_rebalance_plans_create_idempotency_key",
        "rebalance_plans",
        type_="unique",
    )
    for column in (
        "complete_idempotency_key",
        "cancel_idempotency_key",
        "start_idempotency_key",
        "completion_market_data_record_ids",
        "start_market_data_record_ids",
        "baseline_reset_at",
        "cancelled_at",
        "started_at",
        "after_snapshot_id",
        "before_snapshot_id",
        "create_idempotency_key",
    ):
        op.drop_column("rebalance_plans", column)
