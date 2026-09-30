"""Persist long-term decisions and notification delivery state."""
from alembic import op
import sqlalchemy as sa
revision = '20261001_0011'
down_revision = '20261001_0010'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('decision_policy',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('review_day', sa.Integer(), nullable=False),
        sa.Column('notification_mode', sa.String(16), nullable=False),
        sa.Column('monthly_email', sa.Boolean(), nullable=False),
        sa.Column('acknowledged_month', sa.String(7)),
        sa.Column('last_reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('rule_fingerprint', sa.String(64)),
        sa.Column('streaks', sa.JSON(), nullable=False),
        sa.Column('anomalies', sa.JSON(), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True)),
        sa.Column('latest_valid_date', sa.Date()),
        sa.CheckConstraint('id = 1', name=op.f('ck_decision_policy_singleton')),
        sa.CheckConstraint('review_day BETWEEN 1 AND 31', name=op.f('ck_decision_policy_review_day')),
        sa.CheckConstraint("notification_mode IN ('daily', 'attention')", name=op.f('ck_decision_policy_notification_mode')))
    op.create_table('decision_observations',
        sa.Column('local_date', sa.Date(), primary_key=True),
        sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('has_manual_data', sa.Boolean(), nullable=False),
        sa.Column('rule_fingerprint', sa.String(64), nullable=False),
        sa.Column('classes', sa.JSON(), nullable=False),
        sa.Column('anomaly_keys', sa.JSON(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('notification_outbox',
        sa.Column('event_key', sa.String(255), primary_key=True),
        sa.Column('subject', sa.String(255), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)))

def downgrade():
    op.drop_table('notification_outbox')
    op.drop_table('decision_observations')
    op.drop_table('decision_policy')
