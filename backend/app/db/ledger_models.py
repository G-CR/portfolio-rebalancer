from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

NUMBER = Numeric(28, 12)


def now():
    return datetime.now(timezone.utc)


class LedgerPeriod(Base):
    __tablename__ = 'ledger_periods'
    __table_args__ = (CheckConstraint('singleton = 1', name='ck_ledger_period_singleton'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    singleton: Mapped[int] = mapped_column(Integer, unique=True, default=1)
    opened_on: Mapped[date] = mapped_column(Date)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LedgerOpening(Base):
    __tablename__ = 'ledger_openings'
    __table_args__ = (UniqueConstraint('period_id', 'holding_id', name='uq_ledger_opening_holding'),
        CheckConstraint('quantity >= 0 AND original_cost >= 0 AND average_cost_price >= 0', name='ck_ledger_opening_original_cost'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period_id: Mapped[UUID] = mapped_column(ForeignKey('ledger_periods.id', ondelete='CASCADE'))
    holding_id: Mapped[UUID] = mapped_column(ForeignKey('holdings.id', ondelete='RESTRICT'))
    trade_currency: Mapped[str] = mapped_column(String(8))
    symbol: Mapped[str] = mapped_column(String(32))
    account_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(NUMBER)
    average_cost_price: Mapped[Decimal] = mapped_column(NUMBER)
    original_cost: Mapped[Decimal] = mapped_column(NUMBER)
    legacy_cost_fx: Mapped[Decimal] = mapped_column(NUMBER)
    baseline_fx: Mapped[Decimal] = mapped_column(NUMBER)
    market_price: Mapped[Decimal | None] = mapped_column(NUMBER)
    reference_fx: Mapped[Decimal | None] = mapped_column(NUMBER)
    reference_value_cny: Mapped[Decimal | None] = mapped_column(NUMBER)
    reference_details: Mapped[dict] = mapped_column(JSON, default=dict)


class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'
    __table_args__ = (
        CheckConstraint("kind IN ('purchase','sale','dividend','split','manual_correction','reversal')", name='ck_ledger_entry_kind'),
        CheckConstraint('sequence >= 1 AND quantity >= 0 AND price >= 0 AND amount >= 0 AND fee >= 0 AND ratio > 0', name='ck_ledger_entry_values'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period_id: Mapped[UUID] = mapped_column(ForeignKey('ledger_periods.id', ondelete='CASCADE'))
    holding_id: Mapped[UUID] = mapped_column(ForeignKey('holdings.id', ondelete='RESTRICT'))
    kind: Mapped[str] = mapped_column(String(32))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(NUMBER, default=0)
    price: Mapped[Decimal] = mapped_column(NUMBER, default=0)
    amount: Mapped[Decimal] = mapped_column(NUMBER, default=0)
    fee: Mapped[Decimal] = mapped_column(NUMBER, default=0)
    fee_currency: Mapped[str] = mapped_column(String(8))
    fee_original: Mapped[Decimal | None] = mapped_column(NUMBER)
    ratio: Mapped[Decimal] = mapped_column(NUMBER, default=1)
    reference_fx: Mapped[Decimal | None] = mapped_column(NUMBER)
    reference_cash_flow_cny: Mapped[Decimal | None] = mapped_column(NUMBER)
    reference_details: Mapped[dict] = mapped_column(JSON, default=dict)
    reverses_id: Mapped[UUID | None] = mapped_column(ForeignKey('ledger_entries.id', ondelete='RESTRICT'))
    replaces_id: Mapped[UUID | None] = mapped_column(ForeignKey('ledger_entries.id', ondelete='RESTRICT'))
    linked_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey('ledger_entries.id', ondelete='RESTRICT'))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    incomplete_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReferenceFxDay(Base):
    __tablename__ = 'reference_fx_days'
    __table_args__ = (UniqueConstraint('currency', 'local_date', name='uq_reference_fx_day'),
        CheckConstraint('rate > 0 AND actual_date <= local_date AND local_date - actual_date <= 7', name='ck_reference_fx_date_rate'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    currency: Mapped[str] = mapped_column(String(8))
    local_date: Mapped[date] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(NUMBER)
    source: Mapped[str] = mapped_column(String(64))
    market_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    quote_id: Mapped[UUID | None] = mapped_column(ForeignKey('market_data.id', ondelete='SET NULL'))
    actual_date: Mapped[date] = mapped_column(Date)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)


class ReferenceFxRevision(Base):
    __tablename__ = 'reference_fx_revisions'
    __table_args__ = (CheckConstraint('(entry_id IS NULL) <> (opening_id IS NULL)', name='ck_reference_fx_revision_target'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    entry_id: Mapped[UUID | None] = mapped_column(ForeignKey('ledger_entries.id', ondelete='CASCADE'))
    opening_id: Mapped[UUID | None] = mapped_column(ForeignKey('ledger_openings.id', ondelete='CASCADE'))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
