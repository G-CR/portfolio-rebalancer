"""add rebalance preview jobs

Revision ID: 20260915_0009
Revises: 20260803_0008
Create Date: 2026-09-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0009"
down_revision: str | None = "20260803_0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rebalance_preview_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_token", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'refreshing', 'calculating', 'succeeded', 'failed')",
            name="ck_rebalance_preview_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_token"),
    )
    op.create_index(
        "ix_rebalance_preview_jobs_status_created_at",
        "rebalance_preview_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rebalance_preview_jobs_status_created_at", table_name="rebalance_preview_jobs")
    op.drop_table("rebalance_preview_jobs")
