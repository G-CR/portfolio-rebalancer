from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MONEY_PRECISION = Numeric(28, 12)
DEFAULT_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_SETTINGS_ID_SQL = f"'{DEFAULT_SETTINGS_ID}'::uuid"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AssetClass(Base):
    __tablename__ = "asset_classes"
    __table_args__ = (
        Index(
            "uq_asset_classes_active_name",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_weight: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    holdings: Mapped[list[Holding]] = relationship(back_populates="asset_class")


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (
        Index(
            "uq_holdings_active_symbol_account_name",
            "symbol",
            "account_name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "uq_holdings_active_preferred_asset_class",
            "asset_class_id",
            unique=True,
            postgresql_where=text("is_rebalance_preferred AND is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_class_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_classes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    trade_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    average_cost_price: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    cost_fx_to_cny: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    baseline_fx_to_cny: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    lot_size: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    quantity_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_rebalance_preferred: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    asset_class: Mapped[AssetClass] = relationship(back_populates="holdings")
    defaults: Mapped[HoldingDefault | None] = relationship(back_populates="holding")
    cost_adjustments: Mapped[list[CostAdjustment]] = relationship(back_populates="holding")


class HoldingDefault(Base):
    __tablename__ = "holding_defaults"
    __table_args__ = (UniqueConstraint("holding_id", name="uq_holding_defaults_holding_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    holding_id: Mapped[UUID] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"),
        nullable=False,
    )
    fee_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    commission_rate: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    minimum_commission: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    per_share_fee: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    fixed_fee: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    default_data_source: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    holding: Mapped[Holding] = relationship(back_populates="defaults")


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint(
            "data_type",
            "symbol",
            "source",
            "market_time",
            name="uq_market_data_source_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    data_type: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    market_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )


class MarketDataOverride(Base):
    __tablename__ = "market_data_overrides"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    data_type: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class CostAdjustment(Base):
    __tablename__ = "cost_adjustments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    holding_id: Mapped[UUID] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    before_quantity: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    before_average_cost_price: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION,
        nullable=False,
    )
    before_cost_fx_to_cny: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION,
        nullable=False,
    )
    after_quantity: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    after_average_cost_price: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION,
        nullable=False,
    )
    after_cost_fx_to_cny: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    input_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    holding: Mapped[Holding] = relationship(back_populates="cost_adjustments")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        Index(
            "uq_snapshots_daily_local_date",
            "local_date",
            unique=True,
            postgresql_where=text("snapshot_type = 'daily'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    data_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_stale_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    items: Mapped[list[SnapshotItem]] = relationship(back_populates="snapshot")


class SnapshotItem(Base):
    __tablename__ = "snapshot_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    holding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("holdings.id", ondelete="SET NULL"),
    )
    asset_class_name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    trade_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    market_price: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    current_fx_to_cny: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    baseline_fx_to_cny: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    average_cost_price: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    cost_fx_to_cny: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    market_value_cny: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    cost_value_cny: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    unrealized_pnl_amount_cny: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    unrealized_pnl_rate: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    actual_weight: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    fx_neutral_weight: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    snapshot: Mapped[Snapshot] = relationship(back_populates="items")


class RebalancePlan(Base):
    __tablename__ = "rebalance_plans"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    suggested_actions: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    projected_result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint(
            f"id = {DEFAULT_SETTINGS_ID_SQL}",
            name="ck_settings_singleton_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=DEFAULT_SETTINGS_ID,
        server_default=text(DEFAULT_SETTINGS_ID_SQL),
    )
    refresh_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    refresh_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_priority: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    default_tolerance: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    minimum_trade_amount_cny: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION,
        nullable=False,
    )
    allow_sell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_fx: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class EncryptedSecret(Base):
    __tablename__ = "encrypted_secrets"
    __table_args__ = (
        UniqueConstraint("provider", name="uq_encrypted_secrets_provider"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    masked_value: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_status: Mapped[str | None] = mapped_column(String(32))
    validation_message: Mapped[str | None] = mapped_column(Text)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
