from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetClass, DEFAULT_SETTINGS_ID, Setting
from app.schemas.asset_class import AssetClassUpdate
from app.services.errors import ServiceError

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


async def replace_asset_classes(
    session: AsyncSession, updates: list[AssetClassUpdate]
) -> list[AssetClass]:
    active_rows = list(
        await session.scalars(
            select(AssetClass)
            .where(AssetClass.is_active.is_(True))
            .order_by(AssetClass.display_order.asc(), AssetClass.created_at.asc())
            .with_for_update()
        )
    )

    if len(active_rows) != len(updates) or {
        item.id for item in active_rows
    } != {item.id for item in updates}:
        raise ServiceError(
            422,
            "ASSET_CLASS_SET_MISMATCH",
            "Payload must include every active asset class exactly once.",
        )

    actual_total = sum((item.target_weight for item in updates), start=Decimal("0"))
    if actual_total != Decimal("1"):
        raise ServiceError(
            422,
            "TARGET_WEIGHT_TOTAL_INVALID",
            "Active target weights must total exactly 1.",
            {"actual_total": format(actual_total, "f")},
        )

    updates_by_id = {item.id: item for item in updates}
    for row in active_rows:
        payload = updates_by_id[row.id]
        row.name = payload.name
        row.target_weight = payload.target_weight
        row.display_order = payload.display_order
        row.notes = payload.notes

    await session.flush()
    return await list_asset_classes(session)


async def seed_default_strategy(session: AsyncSession) -> None:
    await session.execute(
        insert(AssetClass)
        .values(
            [
                {
                    "name": name,
                    "target_weight": target_weight,
                    "display_order": index,
                }
                for index, (name, target_weight) in enumerate(
                    DEFAULT_ASSET_CLASSES,
                    start=1,
                )
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[AssetClass.name],
            index_where=text("is_active"),
        )
    )

    await session.execute(
        insert(Setting)
        .values(
            id=DEFAULT_SETTINGS_ID,
            refresh_hour=8,
            refresh_minute=0,
            provider_priority=[],
            default_tolerance=Decimal("0.02000000"),
            minimum_trade_amount_cny=Decimal("500.00000000"),
            allow_sell=True,
            allow_fx=True,
        )
        .on_conflict_do_nothing(index_elements=[Setting.id])
    )
