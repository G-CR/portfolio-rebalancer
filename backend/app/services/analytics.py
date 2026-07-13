from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetClass, Holding, MarketData, MarketDataOverride, Setting
from app.domain.analytics import PositionInput, analyze_position
from app.schemas.analytics import (
    AssetClassAnalyticsResponse,
    HoldingAnalyticsResponse,
    PortfolioAnalyticsResponse,
    PortfolioDataInputResponse,
    PortfolioDecisionResponse,
)
from app.services.errors import ServiceError
from app.services.market_data import (
    EffectiveValue,
    ManualOverride,
    _resolve_automated_value,
    resolve_effective_value,
)

_ONE = Decimal("1")
_ZERO = Decimal("0")
_WEIGHT_QUANTUM = Decimal("0.000000000001")
_DECISION_QUANTUM = Decimal("0.00000001")


async def get_portfolio_analytics(session: AsyncSession) -> PortfolioAnalyticsResponse:
    rows = (
        await session.execute(
            select(AssetClass, Holding)
            .outerjoin(
                Holding,
                and_(
                    Holding.asset_class_id == AssetClass.id,
                    Holding.is_active.is_(True),
                ),
            )
            .where(AssetClass.is_active.is_(True))
            .order_by(
                AssetClass.display_order.asc(),
                AssetClass.id.asc(),
                Holding.created_at.asc(),
                Holding.id.asc(),
            )
        )
    ).all()
    asset_classes: list[AssetClass] = []
    holdings: list[Holding] = []
    seen_asset_classes = set()
    for asset_class, holding in rows:
        if asset_class.id not in seen_asset_classes:
            seen_asset_classes.add(asset_class.id)
            asset_classes.append(asset_class)
        if holding is not None:
            holdings.append(holding)

    tolerance = await session.scalar(select(Setting.default_tolerance).limit(1))
    tolerance = tolerance if tolerance is not None else Decimal("0.02")
    if not holdings:
        return _setup_response(tolerance)

    required_keys = _required_keys(holdings)
    automated_rows = await _load_market_rows(session, required_keys)
    override_rows = await _load_override_rows(session, required_keys)
    effective_values = _resolve_effective_values(
        required_keys,
        automated_rows=automated_rows,
        override_rows=override_rows,
    )

    incomplete = _incomplete_items(holdings, effective_values)
    if incomplete:
        raise ServiceError(
            409,
            "PORTFOLIO_DATA_INCOMPLETE",
            "Required portfolio market data is incomplete.",
            {"items": incomplete},
        )

    with localcontext() as context:
        context.prec = 200
        holding_responses: list[HoldingAnalyticsResponse] = []
        aggregate = defaultdict(lambda: defaultdict(Decimal))
        totals = defaultdict(Decimal)
        overseas_market_value = Decimal("0")

        for holding in holdings:
            price = effective_values[f"price:{holding.symbol}"]
            fx = effective_values[_fx_key(holding)]
            analysis = analyze_position(
                PositionInput(
                    quantity=holding.quantity,
                    cost_price=holding.average_cost_price,
                    current_price=price.value,
                    cost_fx=holding.cost_fx_to_cny,
                    current_fx=fx.value,
                    baseline_fx=holding.baseline_fx_to_cny,
                )
            )
            values = {
                "cost_cny": analysis.cost_cny,
                "market_value_cny": analysis.market_value_cny,
                "fx_neutral_value_cny": analysis.fx_neutral_value_cny,
                "unrealized_pnl": analysis.unrealized_pnl,
                "price_effect": analysis.price_effect,
                "fx_effect": analysis.fx_effect,
            }
            for name, value in values.items():
                aggregate[holding.asset_class_id][name] += value
                totals[name] += value
            if holding.trade_currency != "CNY":
                overseas_market_value += analysis.market_value_cny

            holding_responses.append(
                HoldingAnalyticsResponse(
                    holding_id=holding.id,
                    asset_class_id=holding.asset_class_id,
                    symbol=holding.symbol,
                    name=holding.name,
                    trade_currency=holding.trade_currency,
                    current_price=price.value,
                    current_fx_to_cny=fx.value,
                    price_status=price.status,
                    fx_status=fx.status,
                    cost_trade_currency=holding.quantity * holding.average_cost_price,
                    market_value_trade_currency=holding.quantity * price.value,
                    unrealized_pnl_trade_currency=(
                        holding.quantity * (price.value - holding.average_cost_price)
                    ),
                    **values,
                    unrealized_return=(
                        analysis.unrealized_pnl / analysis.cost_cny
                        if analysis.cost_cny
                        else _ZERO
                    ),
                )
            )

        actual_weights = _exact_weights(
            [aggregate[item.id]["market_value_cny"] for item in asset_classes],
            totals["market_value_cny"],
        )
        fx_neutral_weights = _exact_weights(
            [aggregate[item.id]["fx_neutral_value_cny"] for item in asset_classes],
            totals["fx_neutral_value_cny"],
        )
        class_responses = []
        for asset_class, actual_weight, fx_neutral_weight in zip(
            asset_classes,
            actual_weights,
            fx_neutral_weights,
            strict=True,
        ):
            values = aggregate[asset_class.id]
            class_responses.append(
                AssetClassAnalyticsResponse(
                    id=asset_class.id,
                    name=asset_class.name,
                    target_weight=asset_class.target_weight,
                    display_order=asset_class.display_order,
                    actual_weight=actual_weight,
                    fx_neutral_weight=fx_neutral_weight,
                    drift=actual_weight - asset_class.target_weight,
                    fx_weight_contribution=actual_weight - fx_neutral_weight,
                    cost_cny=values["cost_cny"],
                    market_value_cny=values["market_value_cny"],
                    fx_neutral_value_cny=values["fx_neutral_value_cny"],
                    unrealized_pnl=values["unrealized_pnl"],
                    price_effect=values["price_effect"],
                    fx_effect=values["fx_effect"],
                )
            )

        statuses = {value.status for value in effective_values.values()}
        as_of_values = [
            value.as_of or value.fetched_at
            for value in effective_values.values()
            if value.as_of is not None or value.fetched_at is not None
        ]
        return PortfolioAnalyticsResponse(
            as_of=max(as_of_values) if as_of_values else None,
            data_status="stale" if "stale" in statuses else "manual" if "manual" in statuses else "valid",
            has_stale_data="stale" in statuses,
            has_manual_data="manual" in statuses,
            tolerance=tolerance,
            cost_cny=totals["cost_cny"],
            market_value_cny=totals["market_value_cny"],
            fx_neutral_value_cny=totals["fx_neutral_value_cny"],
            unrealized_pnl=totals["unrealized_pnl"],
            unrealized_return=(
                totals["unrealized_pnl"] / totals["cost_cny"]
                if totals["cost_cny"]
                else _ZERO
            ),
            price_effect=totals["price_effect"],
            fx_effect=totals["fx_effect"],
            overseas_weight=(
                overseas_market_value / totals["market_value_cny"]
                if totals["market_value_cny"]
                else _ZERO
            ),
            decision=_decision(class_responses, tolerance),
            asset_classes=class_responses,
            holdings=holding_responses,
            data_inputs=_data_input_responses(effective_values),
        )


def _setup_response(tolerance: Decimal) -> PortfolioAnalyticsResponse:
    return PortfolioAnalyticsResponse(
        as_of=None,
        data_status="setup",
        has_stale_data=False,
        has_manual_data=False,
        tolerance=tolerance,
        cost_cny=_ZERO,
        market_value_cny=_ZERO,
        fx_neutral_value_cny=_ZERO,
        unrealized_pnl=_ZERO,
        unrealized_return=_ZERO,
        price_effect=_ZERO,
        fx_effect=_ZERO,
        overseas_weight=_ZERO,
        decision=PortfolioDecisionResponse(
            status="setup",
            title="开始建立组合",
            reason="添加第一个持仓后即可查看配置偏离与盈亏拆分。",
            max_drift=_ZERO,
            fx_contribution=_ZERO,
            primary_action="add_holding",
        ),
        asset_classes=[],
        holdings=[],
        data_inputs=[],
    )


def _required_keys(holdings: list[Holding]) -> set[tuple[str, str]]:
    keys = {("price", holding.symbol) for holding in holdings}
    keys.update(("fx", _fx_symbol(holding)) for holding in holdings if holding.trade_currency != "CNY")
    return keys


async def _load_market_rows(
    session: AsyncSession,
    required_keys: set[tuple[str, str]],
) -> list[MarketData]:
    conditions = [
        and_(MarketData.data_type == data_type, MarketData.symbol == symbol)
        for data_type, symbol in required_keys
    ]
    if not conditions:
        return []
    return list(await session.scalars(select(MarketData).where(or_(*conditions))))


async def _load_override_rows(
    session: AsyncSession,
    required_keys: set[tuple[str, str]],
) -> list[MarketDataOverride]:
    conditions = [
        and_(MarketDataOverride.data_type == data_type, MarketDataOverride.symbol == symbol)
        for data_type, symbol in required_keys
    ]
    if not conditions:
        return []
    return list(await session.scalars(select(MarketDataOverride).where(or_(*conditions))))


def _resolve_effective_values(required_keys, *, automated_rows, override_rows):
    automated_by_key = defaultdict(list)
    for row in automated_rows:
        automated_by_key[(row.data_type, row.symbol)].append(row)
    override_by_key = {}
    for row in sorted(override_rows, key=lambda item: (item.updated_at, item.created_at)):
        override_by_key[(row.data_type, row.symbol)] = row

    now = datetime.now(UTC)
    effective = {}
    for data_type, symbol in required_keys:
        key = f"{data_type}:{symbol}"
        override_row = override_by_key.get((data_type, symbol))
        override = (
            ManualOverride(
                value=override_row.value,
                note=override_row.note,
                starts_at=override_row.effective_at,
                expires_at=override_row.expires_at,
            )
            if override_row is not None
            else None
        )
        effective[key] = resolve_effective_value(
            automated=_resolve_automated_value(automated_by_key[(data_type, symbol)]),
            override=override,
            now=now,
        )
    effective["fx:CNY/CNY"] = EffectiveValue(
        value=_ONE,
        source="local",
        status="valid",
        as_of=None,
        fetched_at=None,
        note=None,
        currency="CNY",
    )
    return effective


def _incomplete_items(holdings, effective_values) -> list[dict[str, object]]:
    items = []
    for holding in holdings:
        for input_name, key in (("price", f"price:{holding.symbol}"), ("fx", _fx_key(holding))):
            value = effective_values[key]
            if value.value is not None and value.status in {"valid", "stale", "manual"}:
                continue
            items.append(
                {
                    "holding_id": str(holding.id),
                    "symbol": holding.symbol,
                    "input": input_name,
                    "key": key,
                    "status": value.status,
                    "value": None,
                    "market_time": value.as_of.isoformat().replace("+00:00", "Z") if value.as_of else None,
                    "source": value.source,
                    "error_summary": value.error_summary,
                }
            )
    return items


def _data_input_responses(effective_values) -> list[PortfolioDataInputResponse]:
    return [
        PortfolioDataInputResponse(
            key=key,
            input="price" if key.startswith("price:") else "fx",
            value=value.value,
            status=value.status,
            source=value.source,
            market_time=value.as_of,
            fetched_at=value.fetched_at,
            error_summary=value.error_summary,
            note=value.note,
        )
        for key, value in sorted(effective_values.items())
    ]


def _exact_weights(values: list[Decimal], denominator: Decimal) -> list[Decimal]:
    if not values or denominator == 0:
        return [_ZERO.quantize(_WEIGHT_QUANTUM) for _ in values]
    rounded = [
        (value / denominator).quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
        for value in values[:-1]
    ]
    return [*rounded, (_ONE - sum(rounded, _ZERO)).quantize(_WEIGHT_QUANTUM)]


def _decision(
    asset_classes: list[AssetClassAnalyticsResponse],
    tolerance: Decimal,
) -> PortfolioDecisionResponse:
    drifts = [Decimal(item.actual_weight) - Decimal(item.target_weight) for item in asset_classes]
    fx_contributions = [
        Decimal(item.actual_weight) - Decimal(item.fx_neutral_weight)
        for item in asset_classes
    ]
    max_drift = max((abs(value) for value in drifts), default=_ZERO)
    max_overweight = max(drifts, default=_ZERO)
    fx_contribution = max((abs(value) for value in fx_contributions), default=_ZERO)
    tolerance_pp = (tolerance * Decimal("100")).quantize(Decimal("0.1"))

    if max_drift <= tolerance:
        status = "hold"
        title = "保持现状"
        reason = f"全部资产仍在 ±{tolerance_pp} 个百分点策略区间内。"
        primary_action = "simulate_contribution"
    elif max_overweight <= tolerance:
        status = "contribute"
        title = "建议补仓"
        reason = "存在低配资产，可先测算新增资金对配置偏离的改善。"
        primary_action = "simulate_contribution"
    else:
        status = "rebalance"
        title = "建议再平衡"
        reason = "至少一个资产类别超出策略区间，建议查看再平衡方案。"
        primary_action = "view_rebalance"

    return PortfolioDecisionResponse(
        status=status,
        title=title,
        reason=reason,
        max_drift=max_drift.quantize(_DECISION_QUANTUM, rounding=ROUND_HALF_UP),
        fx_contribution=fx_contribution.quantize(_DECISION_QUANTUM, rounding=ROUND_HALF_UP),
        primary_action=primary_action,
    )


def _fx_symbol(holding: Holding) -> str:
    return f"{holding.trade_currency}/CNY"


def _fx_key(holding: Holding) -> str:
    return "fx:CNY/CNY" if holding.trade_currency == "CNY" else f"fx:{_fx_symbol(holding)}"
