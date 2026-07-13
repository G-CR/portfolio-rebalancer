from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetClass, Holding
from app.schemas.holding import HoldingCreate, HoldingUpdate
from app.services.errors import ServiceError

_ONE = Decimal("1")


async def list_holdings(session: AsyncSession) -> list[Holding]:
    result = await session.scalars(
        select(Holding)
        .join(AssetClass, Holding.asset_class_id == AssetClass.id)
        .where(Holding.is_active.is_(True), AssetClass.is_active.is_(True))
        .order_by(AssetClass.display_order.asc(), Holding.created_at.asc())
    )
    return list(result)


async def create_holding(session: AsyncSession, payload: HoldingCreate) -> Holding:
    await _get_active_asset_class(session, payload.asset_class_id)
    existing_holdings = await _get_active_holdings_for_asset_class(
        session,
        payload.asset_class_id,
        lock=True,
    )
    cost_fx_to_cny, baseline_fx_to_cny = _normalized_fx_values(
        payload.trade_currency,
        payload.cost_fx_to_cny,
        payload.baseline_fx_to_cny,
    )
    should_prefer = payload.is_rebalance_preferred or not existing_holdings
    if should_prefer:
        for item in existing_holdings:
            item.is_rebalance_preferred = False

    holding = Holding(
        asset_class_id=payload.asset_class_id,
        symbol=payload.symbol,
        name=payload.name,
        market=payload.market,
        account_name=payload.account_name,
        trade_currency=payload.trade_currency,
        quantity=payload.quantity,
        average_cost_price=payload.average_cost_price,
        cost_fx_to_cny=cost_fx_to_cny,
        baseline_fx_to_cny=baseline_fx_to_cny,
        lot_size=payload.lot_size,
        quantity_precision=payload.quantity_precision,
        is_rebalance_preferred=should_prefer,
    )
    session.add(holding)
    await session.flush()
    return holding


async def update_holding(
    session: AsyncSession, holding_id: UUID, payload: HoldingUpdate
) -> Holding:
    holding = await _get_active_holding(session, holding_id, lock=True)
    previous_asset_class_id = holding.asset_class_id
    updates = {
        field_name: getattr(payload, field_name) for field_name in payload.model_fields_set
    }

    if "asset_class_id" in updates:
        await _get_active_asset_class(session, updates["asset_class_id"])
        holding.asset_class_id = updates["asset_class_id"]
    if "symbol" in updates:
        holding.symbol = updates["symbol"]
    if "name" in updates:
        holding.name = updates["name"]
    if "market" in updates:
        holding.market = updates["market"]
    if "account_name" in updates:
        holding.account_name = updates["account_name"]
    if "trade_currency" in updates:
        holding.trade_currency = updates["trade_currency"]
    if "quantity" in updates:
        holding.quantity = updates["quantity"]
    if "average_cost_price" in updates:
        holding.average_cost_price = updates["average_cost_price"]
    if "lot_size" in updates:
        holding.lot_size = updates["lot_size"]
    if "quantity_precision" in updates:
        holding.quantity_precision = updates["quantity_precision"]
    if "is_rebalance_preferred" in updates:
        holding.is_rebalance_preferred = updates["is_rebalance_preferred"]

    cost_fx_to_cny, baseline_fx_to_cny = _normalized_fx_values(
        holding.trade_currency,
        updates.get("cost_fx_to_cny", holding.cost_fx_to_cny),
        updates.get("baseline_fx_to_cny", holding.baseline_fx_to_cny),
    )
    holding.cost_fx_to_cny = cost_fx_to_cny
    holding.baseline_fx_to_cny = baseline_fx_to_cny

    await session.flush()

    if previous_asset_class_id != holding.asset_class_id:
        await _enforce_preferred_holding(session, previous_asset_class_id)

    await _enforce_preferred_holding(
        session,
        asset_class_id=holding.asset_class_id,
        preferred_holding=holding if holding.is_rebalance_preferred else None,
    )
    await session.flush()
    return holding


async def archive_holding(session: AsyncSession, holding_id: UUID) -> Holding:
    holding = await _get_active_holding(session, holding_id, lock=True)
    if holding.quantity != 0:
        raise ServiceError(
            409,
            "HOLDING_NOT_EMPTY",
            "Archive is only allowed when quantity is zero.",
        )

    holding.is_active = False
    holding.is_rebalance_preferred = False
    await session.flush()
    await _enforce_preferred_holding(session, holding.asset_class_id)
    await session.flush()
    return holding


async def _get_active_asset_class(
    session: AsyncSession, asset_class_id: UUID
) -> AssetClass:
    asset_class = await session.scalar(
        select(AssetClass).where(
            AssetClass.id == asset_class_id,
            AssetClass.is_active.is_(True),
        )
    )
    if asset_class is None:
        raise ServiceError(
            404,
            "ASSET_CLASS_NOT_FOUND",
            "Active asset class was not found.",
        )
    return asset_class


async def _get_active_holding(
    session: AsyncSession, holding_id: UUID, *, lock: bool = False
) -> Holding:
    statement = select(Holding).where(
        Holding.id == holding_id,
        Holding.is_active.is_(True),
    )
    if lock:
        statement = statement.with_for_update()
    holding = await session.scalar(statement)
    if holding is None:
        raise ServiceError(404, "HOLDING_NOT_FOUND", "Active holding was not found.")
    return holding


async def _get_active_holdings_for_asset_class(
    session: AsyncSession,
    asset_class_id: UUID,
    *,
    lock: bool = False,
) -> list[Holding]:
    statement = (
        select(Holding)
        .where(
            Holding.asset_class_id == asset_class_id,
            Holding.is_active.is_(True),
        )
        .order_by(Holding.created_at.asc(), Holding.id.asc())
    )
    if lock:
        statement = statement.with_for_update()
    return list(await session.scalars(statement))


def _normalized_fx_values(
    trade_currency: str,
    cost_fx_to_cny: Decimal,
    baseline_fx_to_cny: Decimal,
) -> tuple[Decimal, Decimal]:
    if trade_currency == "CNY":
        return (_ONE, _ONE)
    if cost_fx_to_cny <= 0 or baseline_fx_to_cny <= 0:
        raise ServiceError(
            422,
            "FX_MUST_BE_POSITIVE",
            "Non-CNY holdings require positive cost and baseline FX values.",
        )
    return (cost_fx_to_cny, baseline_fx_to_cny)


async def _enforce_preferred_holding(
    session: AsyncSession,
    asset_class_id: UUID,
    preferred_holding: Holding | None = None,
) -> None:
    active_holdings = await _get_active_holdings_for_asset_class(
        session,
        asset_class_id,
        lock=True,
    )
    if not active_holdings:
        return

    chosen_id = preferred_holding.id if preferred_holding is not None else None
    if chosen_id is None:
        chosen = next(
            (item for item in active_holdings if item.is_rebalance_preferred),
            active_holdings[0],
        )
        chosen_id = chosen.id

    for item in active_holdings:
        item.is_rebalance_preferred = item.id == chosen_id
