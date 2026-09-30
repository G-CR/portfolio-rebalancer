from datetime import datetime, date, UTC
from sqlalchemy import Integer, String, Date, DateTime, JSON, Boolean, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class DecisionPolicy(Base):
    __tablename__ = 'decision_policy'
    __table_args__ = (CheckConstraint('id = 1', name='singleton'), CheckConstraint('review_day BETWEEN 1 AND 31', name='review_day'), CheckConstraint("notification_mode IN ('daily', 'attention')", name='notification_mode'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    review_day: Mapped[int] = mapped_column(Integer, default=1)
    notification_mode: Mapped[str] = mapped_column(String(16), default='daily')
    monthly_email: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_month: Mapped[str | None] = mapped_column(String(7))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rule_fingerprint: Mapped[str | None] = mapped_column(String(64))
    streaks: Mapped[dict] = mapped_column(JSON, default=dict)
    anomalies: Mapped[dict] = mapped_column(JSON, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_valid_date: Mapped[date | None] = mapped_column(Date)

class DecisionObservation(Base):
    __tablename__ = 'decision_observations'
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    valid: Mapped[bool] = mapped_column(Boolean)
    has_manual_data: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_fingerprint: Mapped[str] = mapped_column(String(64))
    classes: Mapped[list] = mapped_column(JSON, default=list)
    anomaly_keys: Mapped[list] = mapped_column(JSON, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

class NotificationOutbox(Base):
    __tablename__ = 'notification_outbox'
    event_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    html: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
