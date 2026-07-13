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


async def list_asset_classes(
    session: AsyncSession, *, include_inactive: bool = False
) -> list[AssetClass]:
    statement = select(AssetClass)
    if not include_inactive:
        statement = statement.where(AssetClass.is_active.is_(True))
    result = await session.scalars(
        statement.order_by(
            AssetClass.display_order.asc(),
            AssetClass.created_at.asc(),
            AssetClass.id.asc(),
        )
    )
    return list(result)


async def replace_asset_classes(
    session: AsyncSession, updates: list[AssetClassUpdate]
) -> list[AssetClass]:
    all_rows = list(
        await session.scalars(
            select(AssetClass)
            .order_by(AssetClass.id.asc())
            .with_for_update()
        )
    )
    active_rows = [item for item in all_rows if item.is_active]
    update_ids = {item.id for item in updates}
    is_full_set = len(all_rows) == len(updates) and update_ids == {
        item.id for item in all_rows
    }
    is_legacy_active_set = len(active_rows) == len(updates) and update_ids == {
        item.id for item in active_rows
    }

    if not is_full_set and not is_legacy_active_set:
        raise ServiceError(
            422,
            "ASSET_CLASS_SET_MISMATCH",
            "Payload must include either every active asset class or the full asset class set exactly once.",
        )

    names = [item.name for item in updates if item.is_active]
    if len(names) != len(set(names)):
        raise ServiceError(
            409,
            "ASSET_CLASS_NAME_CONFLICT",
            "Active asset class names must be unique.",
        )

    for item in updates:
        if item.target_weight < 0 or item.target_weight > 1:
            raise ServiceError(
                422,
                "TARGET_WEIGHT_OUT_OF_RANGE",
                "Each target weight must be between 0 and 1 inclusive.",
                {
                    "asset_class_id": str(item.id),
                    "target_weight": format(item.target_weight, "f"),
                },
            )

    actual_total = sum(
        (item.target_weight for item in updates if item.is_active),
        start=Decimal("0"),
    )
    if actual_total != Decimal("1"):
        raise ServiceError(
            422,
            "TARGET_WEIGHT_TOTAL_INVALID",
            "Active target weights must total exactly 1.",
            {"actual_total": format(actual_total, "f")},
        )

    updates_by_id = {item.id: item for item in updates}
    rows_to_update = all_rows if is_full_set else active_rows
    for row in rows_to_update:
        payload = updates_by_id[row.id]
        row.name = payload.name
        row.target_weight = payload.target_weight
        row.display_order = payload.display_order
        row.notes = payload.notes
        if is_full_set:
            row.is_active = payload.is_active

    await session.flush()
    return await list_asset_classes(session, include_inactive=is_full_set)


async def seed_default_strategy(session: AsyncSession) -> None:
    existing_asset_class_id = await session.scalar(select(AssetClass.id).limit(1))
    if existing_asset_class_id is None:
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
