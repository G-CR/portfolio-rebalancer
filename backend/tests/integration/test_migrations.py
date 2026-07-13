from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import AssetClass, Holding, MarketData


async def test_initial_migration_creates_core_tables(db_session) -> None:
    rows = await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    names = {row[0] for row in rows}

    assert {
        "asset_classes",
        "holdings",
        "holding_defaults",
        "market_data",
        "market_data_overrides",
        "cost_adjustments",
        "snapshots",
        "snapshot_items",
        "rebalance_plans",
        "settings",
        "encrypted_secrets",
    } <= names


async def test_holding_orm_update_increments_version(db_session) -> None:
    asset_class = AssetClass(
        name="Equity",
        target_weight=Decimal("1"),
        display_order=1,
    )
    holding = Holding(
        asset_class=asset_class,
        symbol="SPY",
        name="SPDR S&P 500 ETF",
        market="NYSEARCA",
        account_name="Brokerage",
        trade_currency="USD",
        quantity=Decimal("10"),
        average_cost_price=Decimal("500"),
        cost_fx_to_cny=Decimal("7.2"),
        baseline_fx_to_cny=Decimal("7.2"),
        lot_size=Decimal("1"),
        quantity_precision=0,
        is_rebalance_preferred=True,
    )
    db_session.add(holding)
    await db_session.commit()
    await db_session.refresh(holding)

    assert holding.version == 1

    holding.quantity = Decimal("11")
    await db_session.commit()
    await db_session.refresh(holding)

    assert holding.version == 2


async def test_market_data_duplicate_null_time_key_is_rejected(db_session) -> None:
    first = MarketData(
        data_type="price",
        symbol="SPY",
        source="yahoo",
        value=Decimal("500"),
        market_time=None,
        fetched_at=datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc),
        status="valid",
    )
    duplicate = MarketData(
        data_type="price",
        symbol="SPY",
        source="yahoo",
        value=Decimal("501"),
        market_time=None,
        fetched_at=datetime(2026, 7, 13, 8, 5, tzinfo=timezone.utc),
        status="valid",
    )

    db_session.add(first)
    await db_session.commit()

    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
