import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.util import CommandError
import pytest
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import (
    AssetClass,
    CostAdjustment,
    DEFAULT_SETTINGS_ID,
    Holding,
    MarketData,
    Setting,
)


MIGRATION_TEST_ENGINE = create_async_engine(
    "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio",
    pool_pre_ping=True,
    poolclass=NullPool,
)
MigrationSessionFactory = async_sessionmaker(MIGRATION_TEST_ENGINE, expire_on_commit=False)


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


async def _run_alembic_upgrade(revision: str) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_config(), revision)


async def _run_alembic_downgrade(revision: str) -> None:
    await asyncio.to_thread(command.downgrade, _alembic_config(), revision)


async def _holding_migration_state() -> dict[str, object]:
    async with MigrationSessionFactory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        indexes = set(
            await session.scalars(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'holdings'
                    """
                )
            )
        )
        constraints = set(
            await session.scalars(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'holdings'::regclass
                    """
                )
            )
        )
        rows = [
            dict(row)
            for row in (
                await session.execute(
                    text(
                        """
                        SELECT id, symbol, name, account_name, is_active
                        FROM holdings
                        ORDER BY id
                        """
                    )
                )
            ).mappings()
        ]

    return {
        "revision": revision,
        "indexes": indexes,
        "constraints": constraints,
        "rows": rows,
    }


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


def test_cost_adjustment_created_at_has_no_implicit_default() -> None:
    column = CostAdjustment.__table__.c.created_at

    assert column.default is None
    assert column.server_default is None


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


async def test_upgrade_from_0001_normalizes_settings_singleton() -> None:
    chosen_id = UUID("00000000-0000-0000-0000-0000000000aa")
    extra_id = UUID("00000000-0000-0000-0000-0000000000bb")

    try:
        await _run_alembic_downgrade("20260713_0001")

        async with MigrationSessionFactory() as session:
            await session.execute(text("TRUNCATE TABLE settings CASCADE"))
            await session.execute(
                text(
                    """
                    INSERT INTO settings (
                        id,
                        refresh_hour,
                        refresh_minute,
                        provider_priority,
                        default_tolerance,
                        minimum_trade_amount_cny,
                        allow_sell,
                        allow_fx,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        :chosen_id,
                        9,
                        15,
                        '["chosen"]'::json,
                        0.031250000000,
                        888.123456789012,
                        false,
                        true,
                        TIMESTAMPTZ '2026-07-13 01:00:00+00',
                        TIMESTAMPTZ '2026-07-13 01:05:00+00'
                    ),
                    (
                        :extra_id,
                        10,
                        45,
                        '["extra"]'::json,
                        0.050000000000,
                        999.000000000000,
                        true,
                        false,
                        TIMESTAMPTZ '2026-07-13 02:00:00+00',
                        TIMESTAMPTZ '2026-07-13 02:05:00+00'
                    )
                    """
                ),
                {"chosen_id": chosen_id, "extra_id": extra_id},
            )
            await session.commit()

        await _run_alembic_upgrade("head")

        async with MigrationSessionFactory() as session:
            settings = list(await session.scalars(select(Setting)))

            assert len(settings) == 1
            assert settings[0].id == DEFAULT_SETTINGS_ID
            assert (settings[0].refresh_hour, settings[0].refresh_minute) == (9, 15)
            assert settings[0].provider_priority == ["chosen"]
            assert settings[0].default_tolerance == Decimal("0.031250000000")
            assert settings[0].minimum_trade_amount_cny == Decimal("888.123456789012")
            assert settings[0].allow_sell is False
            assert settings[0].allow_fx is True
    finally:
        await _run_alembic_upgrade("head")


async def test_downgrade_0003_refuses_duplicate_holding_identity_without_changes(
    _reset_database,
) -> None:
    async with MigrationSessionFactory() as session:
        asset_class = AssetClass(
            name="Equity",
            target_weight=Decimal("1"),
            display_order=1,
        )
        archived = Holding(
            asset_class=asset_class,
            symbol="SPY",
            name="Archived SPDR S&P 500 ETF",
            market="NYSEARCA",
            account_name="Brokerage",
            trade_currency="USD",
            quantity=Decimal("0"),
            average_cost_price=Decimal("500"),
            cost_fx_to_cny=Decimal("7.2"),
            baseline_fx_to_cny=Decimal("7.2"),
            lot_size=Decimal("1"),
            quantity_precision=0,
            is_rebalance_preferred=False,
            is_active=False,
        )
        recreated = Holding(
            asset_class=asset_class,
            symbol="SPY",
            name="Recreated SPDR S&P 500 ETF",
            market="NYSEARCA",
            account_name="Brokerage",
            trade_currency="USD",
            quantity=Decimal("10"),
            average_cost_price=Decimal("510"),
            cost_fx_to_cny=Decimal("7.1"),
            baseline_fx_to_cny=Decimal("7.2"),
            lot_size=Decimal("1"),
            quantity_precision=0,
            is_rebalance_preferred=True,
        )
        session.add_all([archived, recreated])
        await session.commit()
        archived_id = archived.id
        recreated_id = recreated.id

    try:
        with pytest.raises(
            CommandError,
            match="cannot downgrade 20260713_0003 without discarding holding history",
        ):
            await _run_alembic_downgrade("20260713_0002")

        state = await _holding_migration_state()
        rows = {row["id"]: row for row in state["rows"]}

        assert state["revision"] == "20260713_0003"
        assert "uq_holdings_active_symbol_account_name" in state["indexes"]
        assert "uq_holdings_symbol_account_name" not in state["constraints"]
        assert rows[archived_id] == {
            "id": archived_id,
            "symbol": "SPY",
            "name": "Archived SPDR S&P 500 ETF",
            "account_name": "Brokerage",
            "is_active": False,
        }
        assert rows[recreated_id] == {
            "id": recreated_id,
            "symbol": "SPY",
            "name": "Recreated SPDR S&P 500 ETF",
            "account_name": "Brokerage",
            "is_active": True,
        }
    finally:
        await _run_alembic_upgrade("head")


async def test_downgrade_0003_restores_global_identity_constraint_for_compatible_data(
    _reset_database,
) -> None:
    async with MigrationSessionFactory() as session:
        asset_class = AssetClass(
            name="Equity",
            target_weight=Decimal("1"),
            display_order=1,
        )
        archived = Holding(
            asset_class=asset_class,
            symbol="SPY-OLD",
            name="Archived SPDR S&P 500 ETF",
            market="NYSEARCA",
            account_name="Brokerage",
            trade_currency="USD",
            quantity=Decimal("0"),
            average_cost_price=Decimal("500"),
            cost_fx_to_cny=Decimal("7.2"),
            baseline_fx_to_cny=Decimal("7.2"),
            lot_size=Decimal("1"),
            quantity_precision=0,
            is_rebalance_preferred=False,
            is_active=False,
        )
        active = Holding(
            asset_class=asset_class,
            symbol="SPY",
            name="Active SPDR S&P 500 ETF",
            market="NYSEARCA",
            account_name="Brokerage",
            trade_currency="USD",
            quantity=Decimal("10"),
            average_cost_price=Decimal("510"),
            cost_fx_to_cny=Decimal("7.1"),
            baseline_fx_to_cny=Decimal("7.2"),
            lot_size=Decimal("1"),
            quantity_precision=0,
            is_rebalance_preferred=True,
        )
        session.add_all([archived, active])
        await session.commit()
        archived_id = archived.id
        active_id = active.id

    try:
        await _run_alembic_downgrade("20260713_0002")

        state = await _holding_migration_state()
        rows = {row["id"]: row for row in state["rows"]}

        assert state["revision"] == "20260713_0002"
        assert "uq_holdings_active_symbol_account_name" not in state["indexes"]
        assert "uq_holdings_symbol_account_name" in state["indexes"]
        assert "uq_holdings_symbol_account_name" in state["constraints"]
        assert rows[archived_id] == {
            "id": archived_id,
            "symbol": "SPY-OLD",
            "name": "Archived SPDR S&P 500 ETF",
            "account_name": "Brokerage",
            "is_active": False,
        }
        assert rows[active_id] == {
            "id": active_id,
            "symbol": "SPY",
            "name": "Active SPDR S&P 500 ETF",
            "account_name": "Brokerage",
            "is_active": True,
        }
    finally:
        await _run_alembic_upgrade("head")

    restored_state = await _holding_migration_state()
    assert restored_state["revision"] == "20260713_0003"
