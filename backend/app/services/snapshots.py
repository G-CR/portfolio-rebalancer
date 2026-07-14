from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import AssetClass, Holding, Snapshot, SnapshotItem
from app.schemas.analytics import PortfolioAnalyticsResponse
from app.schemas.snapshot import (
    SnapshotCollectionResponse,
    SnapshotDetailResponse,
    SnapshotSummaryResponse,
    SnapshotType,
)
from app.services.analytics import get_portfolio_analytics
from app.services.errors import ServiceError

_ZERO = Decimal("0")


async def create_daily_snapshot_if_complete(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> Snapshot | None:
    captured_at = _aware_now(now)
    try:
        analytics = await get_portfolio_analytics(session)
    except ServiceError as exc:
        if exc.code == "PORTFOLIO_DATA_INCOMPLETE":
            return None
        raise
    if analytics.data_status == "setup":
        return None

    local_date = captured_at.astimezone(ZoneInfo(get_settings().timezone)).date()
    statement = (
        insert(Snapshot)
        .values(
            snapshot_type="daily",
            local_date=local_date,
            captured_at=captured_at,
            note=None,
            data_complete=True,
            has_stale_data=analytics.has_stale_data,
            has_manual_data=analytics.has_manual_data,
            created_at=captured_at,
        )
        .on_conflict_do_update(
            index_elements=[Snapshot.local_date],
            index_where=Snapshot.snapshot_type == "daily",
            set_={
                "captured_at": captured_at,
                "note": None,
                "data_complete": True,
                "has_stale_data": analytics.has_stale_data,
                "has_manual_data": analytics.has_manual_data,
            },
        )
        .returning(Snapshot.id)
    )
    snapshot_id = (await session.execute(statement)).scalar_one()
    await session.execute(delete(SnapshotItem).where(SnapshotItem.snapshot_id == snapshot_id))
    await _persist_items(session, snapshot_id=snapshot_id, analytics=analytics, captured_at=captured_at)
    await session.flush()
    return await session.scalar(
        select(Snapshot)
        .where(Snapshot.id == snapshot_id)
        .execution_options(populate_existing=True)
    )


async def create_manual_snapshot(
    session: AsyncSession,
    *,
    note: str | None,
    now: datetime | None = None,
) -> SnapshotDetailResponse:
    captured_at = _aware_now(now)
    analytics = await get_portfolio_analytics(session)
    if analytics.data_status == "setup":
        raise ServiceError(
            409,
            "SNAPSHOT_PORTFOLIO_EMPTY",
            "A snapshot cannot be created before the portfolio has active holdings.",
        )
    if (analytics.has_stale_data or analytics.has_manual_data) and not note:
        raise ServiceError(
            422,
            "SNAPSHOT_NOTE_REQUIRED",
            "A note is required when snapshot inputs are stale or manually overridden.",
            {
                "has_stale_data": analytics.has_stale_data,
                "has_manual_data": analytics.has_manual_data,
                "items": _exceptional_inputs(analytics),
            },
        )

    snapshot = Snapshot(
        snapshot_type="manual",
        local_date=captured_at.astimezone(ZoneInfo(get_settings().timezone)).date(),
        captured_at=captured_at,
        note=note,
        data_complete=True,
        has_stale_data=analytics.has_stale_data,
        has_manual_data=analytics.has_manual_data,
        created_at=captured_at,
    )
    session.add(snapshot)
    await session.flush()
    await _persist_items(session, snapshot_id=snapshot.id, analytics=analytics, captured_at=captured_at)
    await session.flush()
    return await get_snapshot_detail(session, snapshot.id)


async def create_event_snapshot(
    session: AsyncSession,
    *,
    snapshot_type: str,
    note: str | None = None,
    now: datetime | None = None,
) -> Snapshot:
    captured_at = _aware_now(now)
    analytics = await get_portfolio_analytics(session)
    if analytics.data_status == "setup":
        raise ServiceError(
            409,
            "SNAPSHOT_PORTFOLIO_EMPTY",
            "A snapshot cannot be created before the portfolio has active holdings.",
        )

    snapshot = Snapshot(
        snapshot_type=snapshot_type,
        local_date=captured_at.astimezone(ZoneInfo(get_settings().timezone)).date(),
        captured_at=captured_at,
        note=note,
        data_complete=True,
        has_stale_data=analytics.has_stale_data,
        has_manual_data=analytics.has_manual_data,
        created_at=captured_at,
    )
    session.add(snapshot)
    await session.flush()
    await _persist_items(session, snapshot_id=snapshot.id, analytics=analytics, captured_at=captured_at)
    await session.flush()
    return snapshot


async def list_snapshots(
    session: AsyncSession,
    *,
    snapshot_type: SnapshotType | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    asset_class: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> SnapshotCollectionResponse:
    aggregate_filters = []
    if asset_class:
        aggregate_filters.append(SnapshotItem.asset_class_name == asset_class)
    aggregates = (
        select(
            SnapshotItem.snapshot_id.label("snapshot_id"),
            func.coalesce(func.sum(SnapshotItem.market_value_cny), _ZERO).label("market"),
            func.coalesce(func.sum(SnapshotItem.fx_neutral_value_cny), _ZERO).label("neutral"),
            func.coalesce(func.sum(SnapshotItem.cost_value_cny), _ZERO).label("cost"),
            func.coalesce(func.sum(SnapshotItem.unrealized_pnl_amount_cny), _ZERO).label("pnl"),
            func.coalesce(func.sum(SnapshotItem.price_effect_cny), _ZERO).label("price"),
            func.coalesce(func.sum(SnapshotItem.fx_effect_cny), _ZERO).label("fx"),
            func.coalesce(func.sum(SnapshotItem.actual_weight), _ZERO).label("actual"),
            func.coalesce(func.sum(SnapshotItem.fx_neutral_weight), _ZERO).label("neutral_weight"),
            func.max(SnapshotItem.target_weight).label("target"),
        )
        .where(*aggregate_filters)
        .group_by(SnapshotItem.snapshot_id)
        .subquery()
    )
    filters = []
    if snapshot_type:
        filters.append(Snapshot.snapshot_type == snapshot_type)
    if from_date:
        filters.append(Snapshot.local_date >= from_date)
    if to_date:
        filters.append(Snapshot.local_date <= to_date)

    count_statement = select(func.count()).select_from(Snapshot).where(*filters)
    if asset_class:
        count_statement = count_statement.join(aggregates, aggregates.c.snapshot_id == Snapshot.id)
    total = int((await session.scalar(count_statement)) or 0)

    statement = (
        select(Snapshot, aggregates)
        .join(aggregates, aggregates.c.snapshot_id == Snapshot.id)
        .where(*filters)
        .order_by(Snapshot.captured_at.desc(), Snapshot.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(statement)).all()
    return SnapshotCollectionResponse(
        items=[_summary(row[0], row, include_target=bool(asset_class)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_snapshot_detail(session: AsyncSession, snapshot_id: UUID) -> SnapshotDetailResponse:
    snapshot = await session.scalar(
        select(Snapshot)
        .where(Snapshot.id == snapshot_id)
        .options(selectinload(Snapshot.items))
    )
    if snapshot is None:
        raise ServiceError(404, "SNAPSHOT_NOT_FOUND", "Snapshot was not found.")
    ordered_items = sorted(snapshot.items, key=lambda item: (item.asset_class_name, item.symbol, str(item.id)))
    return SnapshotDetailResponse(
        **_summary_from_items(snapshot, ordered_items).model_dump(),
        items=ordered_items,
    )


async def _persist_items(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    analytics: PortfolioAnalyticsResponse,
    captured_at: datetime,
) -> None:
    holding_ids = [item.holding_id for item in analytics.holdings]
    rows = (
        await session.execute(
            select(Holding, AssetClass)
            .join(AssetClass, AssetClass.id == Holding.asset_class_id)
            .where(Holding.id.in_(holding_ids))
        )
    ).all()
    metadata = {holding.id: (holding, asset_class) for holding, asset_class in rows}
    session.add_all(
        [
            _snapshot_item(
                snapshot_id=snapshot_id,
                captured_at=captured_at,
                item=item,
                holding=metadata[item.holding_id][0],
                asset_class=metadata[item.holding_id][1],
                actual_weight=(
                    Decimal(item.market_value_cny) / Decimal(analytics.market_value_cny)
                    if Decimal(analytics.market_value_cny)
                    else _ZERO
                ),
                fx_neutral_weight=(
                    Decimal(item.fx_neutral_value_cny) / Decimal(analytics.fx_neutral_value_cny)
                    if Decimal(analytics.fx_neutral_value_cny)
                    else _ZERO
                ),
            )
            for item in analytics.holdings
        ]
    )


def _snapshot_item(*, snapshot_id, captured_at, item, holding, asset_class, actual_weight, fx_neutral_weight):
    return SnapshotItem(
        snapshot_id=snapshot_id,
        holding_id=holding.id,
        asset_class_name=asset_class.name,
        holding_name=holding.name,
        symbol=holding.symbol,
        account_name=holding.account_name,
        trade_currency=holding.trade_currency,
        quantity=holding.quantity,
        market_price=item.current_price,
        current_fx_to_cny=item.current_fx_to_cny,
        baseline_fx_to_cny=holding.baseline_fx_to_cny,
        average_cost_price=holding.average_cost_price,
        cost_fx_to_cny=holding.cost_fx_to_cny,
        target_weight=asset_class.target_weight,
        market_value_cny=item.market_value_cny,
        fx_neutral_value_cny=item.fx_neutral_value_cny,
        cost_value_cny=item.cost_cny,
        unrealized_pnl_amount_cny=item.unrealized_pnl,
        unrealized_pnl_rate=item.unrealized_return,
        price_effect_cny=item.price_effect,
        fx_effect_cny=item.fx_effect,
        actual_weight=actual_weight,
        fx_neutral_weight=fx_neutral_weight,
        price_status=item.price_status,
        fx_status=item.fx_status,
        created_at=captured_at,
    )


def _exceptional_inputs(analytics: PortfolioAnalyticsResponse) -> list[dict[str, object]]:
    statuses = {(item.key, item.status) for item in analytics.data_inputs if item.status in {"stale", "manual"}}
    result = []
    for holding in analytics.holdings:
        for input_name, key, status in (
            ("price", f"price:{holding.symbol}", holding.price_status),
            ("fx", "fx:CNY/CNY" if holding.trade_currency == "CNY" else f"fx:{holding.trade_currency}/CNY", holding.fx_status),
        ):
            if (key, status) in statuses:
                result.append(
                    {
                        "holding_id": str(holding.holding_id),
                        "symbol": holding.symbol,
                        "input": input_name,
                        "status": status,
                    }
                )
    return result


def _summary(snapshot: Snapshot, aggregate, *, include_target: bool) -> SnapshotSummaryResponse:
    return SnapshotSummaryResponse(
        id=snapshot.id,
        snapshot_type=snapshot.snapshot_type,
        local_date=snapshot.local_date,
        captured_at=snapshot.captured_at,
        note=snapshot.note,
        data_complete=snapshot.data_complete,
        has_stale_data=snapshot.has_stale_data,
        has_manual_data=snapshot.has_manual_data,
        total_market_value_cny=aggregate.market,
        total_fx_neutral_value_cny=aggregate.neutral,
        total_cost_value_cny=aggregate.cost,
        total_unrealized_pnl_cny=aggregate.pnl,
        total_price_effect_cny=aggregate.price,
        total_fx_effect_cny=aggregate.fx,
        actual_weight=aggregate.actual,
        fx_neutral_weight=aggregate.neutral_weight,
        target_weight=aggregate.target if include_target else None,
    )


def _summary_from_items(snapshot: Snapshot, items: list[SnapshotItem]) -> SnapshotSummaryResponse:
    def total(attribute: str) -> Decimal:
        return sum((getattr(item, attribute) or _ZERO for item in items), _ZERO)

    return SnapshotSummaryResponse(
        id=snapshot.id,
        snapshot_type=snapshot.snapshot_type,
        local_date=snapshot.local_date,
        captured_at=snapshot.captured_at,
        note=snapshot.note,
        data_complete=snapshot.data_complete,
        has_stale_data=snapshot.has_stale_data,
        has_manual_data=snapshot.has_manual_data,
        total_market_value_cny=total("market_value_cny"),
        total_fx_neutral_value_cny=total("fx_neutral_value_cny"),
        total_cost_value_cny=total("cost_value_cny"),
        total_unrealized_pnl_cny=total("unrealized_pnl_amount_cny"),
        total_price_effect_cny=total("price_effect_cny"),
        total_fx_effect_cny=total("fx_effect_cny"),
        actual_weight=total("actual_weight"),
        fx_neutral_weight=total("fx_neutral_weight"),
        target_weight=None,
    )


def _aware_now(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("Snapshot capture time must be timezone-aware.")
    return value
