from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetClass, Setting

DEFAULT_ASSET_CLASSES: tuple[tuple[str, Decimal], ...] = (
    ("红利低波", Decimal("0.20000000")),
    ("红利质量", Decimal("0.20000000")),
    ("标普 500", Decimal("0.30000000")),
    ("纳斯达克 100", Decimal("0.20000000")),
    ("黄金", Decimal("0.10000000")),
)


async def list_asset_classes(session: AsyncSession) -> list[AssetClass]:
    result = await session.scalars(
        select(AssetClass)
        .where(AssetClass.is_active.is_(True))
        .order_by(AssetClass.display_order.asc(), AssetClass.created_at.asc())
    )
    return list(result)


async def seed_default_strategy(session: AsyncSession) -> None:
    asset_class_exists = (
        await session.scalar(select(AssetClass.id).limit(1))
    ) is not None
    settings_exists = (await session.scalar(select(Setting.id).limit(1))) is not None

    if not asset_class_exists:
        session.add_all(
            [
            AssetClass(
                name=name,
                target_weight=target_weight,
                display_order=index,
            )
            for index, (name, target_weight) in enumerate(
                DEFAULT_ASSET_CLASSES,
                start=1,
            )
            ]
        )

    if not settings_exists:
        session.add(
            Setting(
                refresh_hour=8,
                refresh_minute=0,
                provider_priority=[],
                default_tolerance=Decimal("0.02000000"),
                minimum_trade_amount_cny=Decimal("500.00000000"),
                allow_sell=True,
                allow_fx=True,
            )
        )

    if not asset_class_exists or not settings_exists:
        await session.commit()
