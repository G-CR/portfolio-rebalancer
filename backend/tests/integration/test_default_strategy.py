from sqlalchemy import select

from app.db.models import Setting
from app.services.asset_classes import list_asset_classes, seed_default_strategy


async def test_default_strategy_is_seeded_once(db_session) -> None:
    await seed_default_strategy(db_session)
    await seed_default_strategy(db_session)
    items = await list_asset_classes(db_session)

    assert [(item.name, format(item.target_weight, "f")) for item in items] == [
        ("红利低波", "0.20000000"),
        ("红利质量", "0.20000000"),
        ("标普 500", "0.30000000"),
        ("纳斯达克 100", "0.20000000"),
        ("黄金", "0.10000000"),
    ]


async def test_default_strategy_seeds_default_settings(db_session) -> None:
    await seed_default_strategy(db_session)

    setting = await db_session.scalar(select(Setting))

    assert setting is not None
    assert (setting.refresh_hour, setting.refresh_minute) == (8, 0)
    assert format(setting.default_tolerance, "f") == "0.02000000"
    assert format(setting.minimum_trade_amount_cny, "f") == "500.00000000"
    assert setting.allow_sell is True
    assert setting.allow_fx is True
