"""add email notification settings

Revision ID: 20260803_0008
Revises: 20260715_0007
Create Date: 2026-08-03 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0008"
down_revision: str | None = "20260715_0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("settings", sa.Column("email_recipient", sa.String(length=320), nullable=True))
    op.add_column("settings", sa.Column("email_smtp_host", sa.String(length=255), nullable=True))
    op.add_column(
        "settings",
        sa.Column("email_smtp_port", sa.Integer(), nullable=False, server_default="465"),
    )
    op.add_column(
        "settings",
        sa.Column(
            "email_smtp_security",
            sa.String(length=16),
            nullable=False,
            server_default="ssl",
        ),
    )
    op.add_column("settings", sa.Column("email_smtp_username", sa.String(length=320), nullable=True))
    op.add_column("settings", sa.Column("email_from", sa.String(length=320), nullable=True))
    op.create_check_constraint(
        "ck_settings_email_smtp_security",
        "settings",
        "email_smtp_security IN ('ssl', 'starttls')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_settings_email_smtp_security", "settings", type_="check")
    op.drop_column("settings", "email_from")
    op.drop_column("settings", "email_smtp_username")
    op.drop_column("settings", "email_smtp_security")
    op.drop_column("settings", "email_smtp_port")
    op.drop_column("settings", "email_smtp_host")
    op.drop_column("settings", "email_recipient")
    op.drop_column("settings", "email_enabled")
