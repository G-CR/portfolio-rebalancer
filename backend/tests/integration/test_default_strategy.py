import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import AssetClass
from app.db.models import DEFAULT_SETTINGS_ID
from app.db.models import Setting
from app.db.session import SessionFactory
from app.services.asset_classes import list_asset_classes, seed_default_strategy


async def test_default_strategy_is_seeded_once(db_session) -> None:
    async with db_session.begin():
        await seed_default_strategy(db_session)
    async with db_session.begin():
        await seed_default_strategy(db_session)
    items = await list_asset_classes(db_session)

    assert [(item.name, item.target_weight) for item in items] == [
        ("红利低波", Decimal("0.20000000")),
        ("红利质量", Decimal("0.20000000")),
        ("标普 500", Decimal("0.30000000")),
        ("纳斯达克 100", Decimal("0.20000000")),
        ("黄金", Decimal("0.10000000")),
    ]


async def test_seed_preserves_intentionally_inactive_asset_classes(db_session) -> None:
    async with db_session.begin():
        await seed_default_strategy(db_session)
    first = await db_session.scalar(
        select(AssetClass).order_by(AssetClass.display_order.asc()).limit(1)
    )
    assert first is not None
    first.is_active = False
    await db_session.commit()

    async with db_session.begin():
        await seed_default_strategy(db_session)

    all_items = await list_asset_classes(db_session, include_inactive=True)
    assert len(all_items) == 5
    assert all_items[0].is_active is False


async def test_default_strategy_seeds_default_settings(db_session) -> None:
    async with db_session.begin():
        await seed_default_strategy(db_session)

    setting = await db_session.scalar(select(Setting))

    assert setting is not None
    assert setting.id == DEFAULT_SETTINGS_ID
    assert (setting.refresh_hour, setting.refresh_minute) == (8, 0)
    assert setting.default_tolerance == Decimal("0.02000000")
    assert setting.minimum_trade_amount_cny == Decimal("500.00000000")
    assert setting.allow_sell is True
    assert setting.allow_fx is True


async def test_non_default_12_decimal_values_are_not_truncated(db_session) -> None:
    asset_class = AssetClass(
        name="12-decimal",
        target_weight=Decimal("0.123456789012"),
        display_order=1,
    )
    setting = Setting(
        refresh_hour=9,
        refresh_minute=30,
        provider_priority=["manual"],
        default_tolerance=Decimal("0.123456789012"),
        minimum_trade_amount_cny=Decimal("500.123456789012"),
        allow_sell=False,
        allow_fx=False,
    )

    db_session.add_all([asset_class, setting])
    await db_session.commit()

    items = await list_asset_classes(db_session)
    await db_session.refresh(setting)

    assert [(item.name, format(item.target_weight, "f")) for item in items] == [
        ("12-decimal", "0.123456789012")
    ]
    assert format(setting.default_tolerance, "f") == "0.123456789012"
    assert format(setting.minimum_trade_amount_cny, "f") == "500.123456789012"


async def test_default_strategy_concurrent_seed_is_idempotent(db_session) -> None:
    start = asyncio.Event()

    async def seed_in_independent_session() -> None:
        async with SessionFactory() as session:
            await start.wait()
            async with session.begin():
                await seed_default_strategy(session)

    first = asyncio.create_task(seed_in_independent_session())
    second = asyncio.create_task(seed_in_independent_session())
    await asyncio.sleep(0)
    start.set()
    await asyncio.gather(first, second)

    asset_class_count = await db_session.scalar(
        select(func.count()).select_from(AssetClass)
    )
    settings_count = await db_session.scalar(select(func.count()).select_from(Setting))
    items = await list_asset_classes(db_session)

    assert asset_class_count == 5
    assert settings_count == 1
    assert [item.name for item in items] == [
        "红利低波",
        "红利质量",
        "标普 500",
        "纳斯达克 100",
        "黄金",
    ]


async def test_seed_default_strategy_respects_caller_rollback(db_session) -> None:
    with pytest.raises(RuntimeError, match="rollback"):
        async with db_session.begin():
            await seed_default_strategy(db_session)
            raise RuntimeError("rollback")

    asset_class_count = await db_session.scalar(
        select(func.count()).select_from(AssetClass)
    )
    settings_count = await db_session.scalar(select(func.count()).select_from(Setting))

    assert asset_class_count == 0
    assert settings_count == 0


async def test_settings_singleton_rejects_non_default_id(db_session) -> None:
    db_session.add(
        Setting(
            id=uuid4(),
            refresh_hour=8,
            refresh_minute=0,
            provider_priority=[],
            default_tolerance=Decimal("0.02000000"),
            minimum_trade_amount_cny=Decimal("500.00000000"),
            allow_sell=True,
            allow_fx=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
