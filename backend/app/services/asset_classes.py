from __future__ import annotations

from decimal import Decimal

from sqlalchemy import event
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
STRATEGY_QUANTUM = Decimal("0.00000000")


def _quantize_strategy_decimal(value: Decimal) -> Decimal:
    return value.quantize(STRATEGY_QUANTUM)


def _normalize_asset_class(asset_class: AssetClass) -> None:
    asset_class.target_weight = _quantize_strategy_decimal(asset_class.target_weight)


def _normalize_setting(setting: Setting) -> None:
    setting.default_tolerance = _quantize_strategy_decimal(setting.default_tolerance)
    setting.minimum_trade_amount_cny = _quantize_strategy_decimal(
        setting.minimum_trade_amount_cny
    )


@event.listens_for(AssetClass, "load")
def _asset_class_on_load(asset_class: AssetClass, _: object) -> None:
    _normalize_asset_class(asset_class)


@event.listens_for(AssetClass, "refresh")
def _asset_class_on_refresh(asset_class: AssetClass, _: object, __: object) -> None:
    _normalize_asset_class(asset_class)


@event.listens_for(Setting, "load")
def _setting_on_load(setting: Setting, _: object) -> None:
    _normalize_setting(setting)


@event.listens_for(Setting, "refresh")
def _setting_on_refresh(setting: Setting, _: object, __: object) -> None:
    _normalize_setting(setting)


async def list_asset_classes(session: AsyncSession) -> list[AssetClass]:
    result = await session.scalars(
        select(AssetClass)
        .where(AssetClass.is_active.is_(True))
        .order_by(AssetClass.display_order.asc(), AssetClass.created_at.asc())
    )
    items = list(result)
    for item in items:
        _normalize_asset_class(item)
    return items


async def seed_default_strategy(session: AsyncSession) -> None:
    asset_class_exists = (
        await session.scalar(select(AssetClass.id).limit(1))
    ) is not None
    settings_exists = (await session.scalar(select(Setting.id).limit(1))) is not None

    if not asset_class_exists:
        asset_classes = [
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
        for asset_class in asset_classes:
            _normalize_asset_class(asset_class)
        session.add_all(asset_classes)

    if not settings_exists:
        setting = Setting(
            refresh_hour=8,
            refresh_minute=0,
            provider_priority=[],
            default_tolerance=Decimal("0.02000000"),
            minimum_trade_amount_cny=Decimal("500.00000000"),
            allow_sell=True,
            allow_fx=True,
        )
        _normalize_setting(setting)
        session.add(setting)

    if not asset_class_exists or not settings_exists:
        await session.commit()
