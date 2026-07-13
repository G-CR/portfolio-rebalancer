"""settings singleton

Revision ID: 20260713_0002
Revises: 20260713_0001
Create Date: 2026-07-13 00:02:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0002"
down_revision: str | None = "20260713_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

default_settings_id = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        """
        WITH chosen AS (
            SELECT id
            FROM settings
            ORDER BY created_at ASC, updated_at ASC, id ASC
            LIMIT 1
        )
        DELETE FROM settings
        WHERE id NOT IN (SELECT id FROM chosen)
        """
    )
    op.execute(
        f"""
        WITH chosen AS (
            SELECT id
            FROM settings
            ORDER BY created_at ASC, updated_at ASC, id ASC
            LIMIT 1
        )
        UPDATE settings
        SET id = '{default_settings_id}'::uuid
        WHERE id = (SELECT id FROM chosen)
          AND id <> '{default_settings_id}'::uuid
        """
    )
    op.alter_column(
        "settings",
        "id",
        existing_type=sa.Uuid(),
        server_default=sa.text(f"'{default_settings_id}'::uuid"),
    )
    op.create_check_constraint(
        "ck_settings_singleton_id",
        "settings",
        f"id = '{default_settings_id}'::uuid",
    )


def downgrade() -> None:
    op.drop_constraint("ck_settings_singleton_id", "settings", type_="check")
    op.alter_column(
        "settings",
        "id",
        existing_type=sa.Uuid(),
        server_default=None,
    )
