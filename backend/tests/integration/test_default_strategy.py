from decimal import Decimal

from sqlalchemy import select

from app.db.models import AssetClass
from app.db.models import Setting
from app.services.asset_classes import list_asset_classes, seed_default_strategy


async def test_default_strategy_is_seeded_once(db_session) -> None:
    await seed_default_strategy(db_session)
    await seed_default_strategy(db_session)
    items = await list_asset_classes(db_session)

    assert [(item.name, item.target_weight) for item in items] == [
        ("红利低波", Decimal("0.20000000")),
        ("红利质量", Decimal("0.20000000")),
        ("标普 500", Decimal("0.30000000")),
        ("纳斯达克 100", Decimal("0.20000000")),
        ("黄金", Decimal("0.10000000")),
    ]


async def test_default_strategy_seeds_default_settings(db_session) -> None:
    await seed_default_strategy(db_session)

    setting = await db_session.scalar(select(Setting))

    assert setting is not None
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
