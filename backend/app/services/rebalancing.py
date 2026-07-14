from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import logging
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetClass, Holding, MarketData, MarketDataOverride, RebalancePlan
from app.domain.rebalance import AssetInput, CashInput, RebalanceOptions, RebalanceResult, rebalance
from app.schemas.rebalance import (
    ProjectedWeightResponse,
    RebalanceComparisonResponse,
    RebalancePlanCreateRequest,
    RebalancePlanResponse,
    RebalancePreviewRequest,
    RebalancePreviewResponse,
    RebalanceResultResponse,
    TradeSuggestionResponse,
)
from app.services.baseline import reset_baseline_fx
from app.services.errors import ServiceError
from app.services.market_data import refresh_all_required_data
from app.services.snapshots import create_event_snapshot

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_SESSION_REFRESH_LOCK = asyncio.Lock()
_REFRESHED_PREVIEW_SESSIONS: set[str] = set()
_REASON_TEXT = {
    "UNDERWEIGHT_WITH_CASH": "当前低配，可直接使用同币种现金补足目标仓位。",
    "UNDERWEIGHT_AFTER_FX": "同币种现金不足，建议先换汇后买入低配资产。",
    "UNDERWEIGHT_WITH_SELL_PROCEEDS": "可优先使用同币种卖出回笼资金补足低配资产。",
    "UNDERWEIGHT_WITH_CASH_AND_FX": "建议先用现有现金，不足部分再换汇后买入低配资产。",
    "UNDERWEIGHT_WITH_CASH_AND_SELL_PROCEEDS": "建议先用现有现金，再配合卖出回笼资金补足低配资产。",
    "UNDERWEIGHT_AFTER_SELL_AND_FX": "同币种现金不足，建议优先使用卖出所得并补充换汇后买入低配资产。",
    "UNDERWEIGHT_WITH_CASH_SELL_PROCEEDS_AND_FX": "建议依次使用现有现金、卖出所得和换汇资金补足低配资产。",
    "OVERWEIGHT_AFTER_CASH": "当前实际占比在投入现有现金后仍高于上限，需要卖出以回到目标附近。",
}


class _EffectiveInput:
    def __init__(
        self,
        *,
        key: str,
        value: Decimal | None,
        status: str,
        source_id: str | None,
        currency: str,
    ) -> None:
        self.key = key
        self.value = value
        self.status = status
        self.source_id = source_id
        self.currency = currency


class _PreparedRebalance:
    def __init__(
        self,
        *,
        data_status: Literal["valid", "stale", "manual"],
        market_data_record_ids: dict[str, str],
        holding_versions: dict[str, int],
        asset_class_targets: dict[str, str],
        result: RebalanceResult,
        comparison: RebalanceComparisonResponse,
        effective_fx: dict[str, Decimal],
    ) -> None:
        self.data_status = data_status
        self.market_data_record_ids = market_data_record_ids
        self.holding_versions = holding_versions
        self.asset_class_targets = asset_class_targets
        self.result = result
        self.comparison = comparison
        self.effective_fx = effective_fx


async def preview_rebalance(
    session: AsyncSession,
    payload: RebalancePreviewRequest,
) -> RebalancePreviewResponse:
    refresh_attempted = await _refresh_before_first_preview(session, payload.session_token)
    prepared = await _prepare_rebalance(
        session,
        payload=payload,
        allow_stale=payload.acknowledge_stale_data,
    )
    return RebalancePreviewResponse(
        session_token=payload.session_token,
        request_token=payload.request_token,
        status="ok",
        data_status=prepared.data_status,
        acknowledge_stale_data=payload.acknowledge_stale_data,
        refresh_attempted=refresh_attempted,
        valuation_basis=payload.valuation_basis,
        result=_serialize_result(prepared.result),
        fx_comparison=prepared.comparison,
    )


async def create_rebalance_plan(
    session: AsyncSession,
    payload: RebalancePlanCreateRequest,
) -> tuple[RebalancePlanResponse, bool]:
    existing = await session.scalar(
        select(RebalancePlan).where(RebalancePlan.create_idempotency_key == payload.idempotency_key)
    )
    if existing is not None:
        return (_plan_response(existing), False)

    preview = await preview_rebalance(
        session,
        RebalancePreviewRequest(**payload.model_dump(exclude={"idempotency_key"})),
    )
    prepared = await _prepare_rebalance(
        session,
        payload=RebalancePreviewRequest(**payload.model_dump(exclude={"idempotency_key"})),
        allow_stale=payload.acknowledge_stale_data,
    )
    data_version = _data_version(
        market_data_record_ids=prepared.market_data_record_ids,
        holding_versions=prepared.holding_versions,
        asset_class_targets=prepared.asset_class_targets,
    )
    plan = RebalancePlan(
        strategy_mode=payload.valuation_basis,
        status="draft",
        data_version=data_version,
        create_idempotency_key=payload.idempotency_key,
        input_summary={
            **payload.model_dump(exclude={"idempotency_key"}),
            "holding_versions": prepared.holding_versions,
            "market_data_record_ids": prepared.market_data_record_ids,
            "asset_class_targets": prepared.asset_class_targets,
        },
        suggested_actions=preview.result.model_dump(mode="json")["trades"],
        projected_result={
            "valuation_basis": payload.valuation_basis,
            "result": preview.result.model_dump(mode="json"),
            "fx_comparison": preview.fx_comparison.model_dump(mode="json"),
            "data_status": preview.data_status,
        },
    )
    session.add(plan)
    await session.flush()
    return (_plan_response(plan), True)


async def list_rebalance_plans(session: AsyncSession) -> list[RebalancePlanResponse]:
    rows = await session.scalars(
        select(RebalancePlan).order_by(RebalancePlan.created_at.desc(), RebalancePlan.id.desc())
    )
    return [_plan_response(plan) for plan in rows]


async def get_rebalance_plan(session: AsyncSession, plan_id: UUID) -> RebalancePlanResponse:
    plan = await session.scalar(select(RebalancePlan).where(RebalancePlan.id == plan_id))
    if plan is None:
        raise ServiceError(404, "REBALANCE_PLAN_NOT_FOUND", "Rebalance plan was not found.")
    return _plan_response(plan)


async def start_rebalance_plan(
    session: AsyncSession,
    *,
    plan_id: UUID,
    idempotency_key: str,
) -> RebalancePlanResponse:
    plan = await _get_locked_plan(session, plan_id)
    if plan.status == "in_progress" and plan.start_idempotency_key == idempotency_key:
        return _plan_response(plan)
    if plan.status != "draft":
        raise ServiceError(
            409,
            "REBALANCE_PLAN_STATE_CONFLICT",
            "Rebalance plan is not in a startable state.",
        )

    current = await _capture_current_assumptions(session)
    if plan.data_version != _data_version(**current):
        raise ServiceError(
            409,
            "REBALANCE_PLAN_CONFLICT",
            "The saved rebalance plan no longer matches current holdings or market data.",
            {"status": "stale_inputs"},
        )

    before_snapshot = await create_event_snapshot(
        session,
        snapshot_type="rebalance_before",
        note=f"rebalance-plan:{plan.id}",
    )
    plan.status = "in_progress"
    plan.started_at = datetime.now(UTC)
    plan.before_snapshot_id = before_snapshot.id
    plan.start_market_data_record_ids = current["market_data_record_ids"]
    plan.start_idempotency_key = idempotency_key
    await session.flush()
    return _plan_response(plan)


async def cancel_rebalance_plan(
    session: AsyncSession,
    *,
    plan_id: UUID,
    idempotency_key: str,
) -> RebalancePlanResponse:
    plan = await _get_locked_plan(session, plan_id)
    if plan.status == "cancelled" and plan.cancel_idempotency_key == idempotency_key:
        return _plan_response(plan)
    if plan.status == "completed":
        raise ServiceError(
            409,
            "REBALANCE_PLAN_STATE_CONFLICT",
            "Completed rebalance plans cannot be cancelled.",
        )
    if plan.status not in {"draft", "in_progress"}:
        raise ServiceError(
            409,
            "REBALANCE_PLAN_STATE_CONFLICT",
            "Rebalance plan is not cancellable.",
        )
    plan.status = "cancelled"
    plan.cancelled_at = datetime.now(UTC)
    plan.cancel_idempotency_key = idempotency_key
    await session.flush()
    return _plan_response(plan)


async def complete_rebalance_plan(
    session: AsyncSession,
    *,
    plan_id: UUID,
    idempotency_key: str,
) -> RebalancePlanResponse:
    plan = await _get_locked_plan(session, plan_id)
    if plan.status == "completed" and plan.complete_idempotency_key == idempotency_key:
        return _plan_response(plan)
    if plan.status != "in_progress":
        raise ServiceError(
            409,
            "REBALANCE_PLAN_STATE_CONFLICT",
            "Only in-progress rebalance plans can be completed.",
        )

    current = await _capture_current_assumptions(session)
    after_snapshot = await create_event_snapshot(
        session,
        snapshot_type="rebalance_after",
        note=f"rebalance-plan:{plan.id}",
    )
    await reset_baseline_fx(session, current["effective_fx"])
    now = datetime.now(UTC)
    plan.status = "completed"
    plan.completed_at = now
    plan.after_snapshot_id = after_snapshot.id
    plan.baseline_reset_at = now
    plan.completion_market_data_record_ids = current["market_data_record_ids"]
    plan.complete_idempotency_key = idempotency_key
    await session.flush()
    return _plan_response(plan)


async def _refresh_before_first_preview(session: AsyncSession, session_token: str) -> bool:
    async with _SESSION_REFRESH_LOCK:
        if session_token in _REFRESHED_PREVIEW_SESSIONS:
            return False
        _REFRESHED_PREVIEW_SESSIONS.add(session_token)
    try:
        await refresh_all_required_data(session)
    except Exception:
        logger.warning("Rebalance preview refresh failed session_token=%s", session_token, exc_info=True)
    return True


async def _prepare_rebalance(
    session: AsyncSession,
    *,
    payload: RebalancePreviewRequest,
    allow_stale: bool,
) -> _PreparedRebalance:
    context = await _load_rebalance_context(session)
    statuses = {item.status for item in context["effective_inputs"].values()}
    if context["incomplete_items"]:
        raise ServiceError(
            409,
            "REBALANCE_DATA_INCOMPLETE",
            "Required rebalance market data is incomplete.",
            {"status": "incomplete", "items": context["incomplete_items"]},
        )
    if "stale" in statuses and not allow_stale:
        stale_items = sorted(key for key, item in context["effective_inputs"].items() if item.status == "stale")
        raise ServiceError(
            409,
            "REBALANCE_STALE_DATA_ACK_REQUIRED",
            "Stale market data requires explicit acknowledgement before previewing a rebalance plan.",
            {"status": "stale", "items": stale_items},
        )
    data_status: Literal["valid", "stale", "manual"]
    if "stale" in statuses:
        data_status = "stale"
    elif "manual" in statuses:
        data_status = "manual"
    else:
        data_status = "valid"

    requested_result = _run_engine(
        valuation_basis=payload.valuation_basis,
        asset_classes=context["asset_classes"],
        holdings=context["holdings"],
        effective_inputs=context["effective_inputs"],
        available_cny=payload.available_cny,
        available_usd=payload.available_usd,
        tolerance=payload.tolerance,
        minimum_trade_cny=payload.minimum_trade_cny,
        allow_sell=payload.allow_sell,
        allow_fx=payload.allow_fx,
    )
    alternate_basis: Literal["actual", "fx_neutral"] = (
        "fx_neutral" if payload.valuation_basis == "actual" else "actual"
    )
    alternate_result = _run_engine(
        valuation_basis=alternate_basis,
        asset_classes=context["asset_classes"],
        holdings=context["holdings"],
        effective_inputs=context["effective_inputs"],
        available_cny=payload.available_cny,
        available_usd=payload.available_usd,
        tolerance=payload.tolerance,
        minimum_trade_cny=payload.minimum_trade_cny,
        allow_sell=payload.allow_sell,
        allow_fx=payload.allow_fx,
    )
    return _PreparedRebalance(
        data_status=data_status,
        market_data_record_ids=context["market_data_record_ids"],
        holding_versions=context["holding_versions"],
        asset_class_targets=context["asset_class_targets"],
        result=requested_result,
        comparison=RebalanceComparisonResponse(
            valuation_basis=alternate_basis,
            result=_serialize_result(alternate_result),
        ),
        effective_fx=context["effective_fx"],
    )


async def _capture_current_assumptions(session: AsyncSession) -> dict[str, object]:
    context = await _load_rebalance_context(session, lock=True)
    if context["incomplete_items"]:
        raise ServiceError(
            409,
            "REBALANCE_DATA_INCOMPLETE",
            "Required rebalance market data is incomplete.",
            {"status": "incomplete", "items": context["incomplete_items"]},
        )
    return {
        "market_data_record_ids": context["market_data_record_ids"],
        "holding_versions": context["holding_versions"],
        "asset_class_targets": context["asset_class_targets"],
        "effective_fx": context["effective_fx"],
    }


async def _load_rebalance_context(session: AsyncSession, *, lock: bool = False) -> dict[str, object]:
    asset_statement = (
        select(AssetClass)
        .where(AssetClass.is_active.is_(True))
        .order_by(AssetClass.display_order.asc(), AssetClass.id.asc())
    )
    if lock:
        asset_statement = asset_statement.with_for_update()
    asset_classes = list(await session.scalars(asset_statement))

    holding_statement = (
        select(Holding)
        .join(AssetClass, Holding.asset_class_id == AssetClass.id)
        .where(Holding.is_active.is_(True), AssetClass.is_active.is_(True))
        .order_by(Holding.asset_class_id.asc(), Holding.created_at.asc(), Holding.id.asc())
    )
    if lock:
        holding_statement = holding_statement.with_for_update()
    holdings = list(await session.scalars(holding_statement))

    effective_inputs, incomplete_items = await _effective_inputs_for_holdings(session, holdings)
    holding_versions = {str(holding.id): holding.version for holding in holdings}
    asset_class_targets = {str(asset_class.id): format(asset_class.target_weight, "f") for asset_class in asset_classes}
    market_data_record_ids = {
        key: item.source_id
        for key, item in effective_inputs.items()
        if item.source_id is not None
    }
    effective_fx = {
        "CNY": Decimal("1"),
        **{
            holding.trade_currency: effective_inputs[f"fx:{holding.trade_currency}/CNY"].value
            for holding in holdings
            if holding.trade_currency != "CNY"
        },
    }
    return {
        "asset_classes": asset_classes,
        "holdings": holdings,
        "effective_inputs": effective_inputs,
        "incomplete_items": incomplete_items,
        "holding_versions": holding_versions,
        "asset_class_targets": asset_class_targets,
        "market_data_record_ids": market_data_record_ids,
        "effective_fx": effective_fx,
    }


async def _effective_inputs_for_holdings(
    session: AsyncSession,
    holdings: list[Holding],
) -> tuple[dict[str, _EffectiveInput], list[str]]:
    keys = {f"price:{holding.symbol}" for holding in holdings}
    keys.update(
        f"fx:{holding.trade_currency}/CNY" for holding in holdings if holding.trade_currency != "CNY"
    )
    required: dict[str, tuple[str, str, str]] = {}
    for holding in holdings:
        required[f"price:{holding.symbol}"] = ("price", holding.symbol, holding.trade_currency)
        if holding.trade_currency != "CNY":
            required[f"fx:{holding.trade_currency}/CNY"] = ("fx", f"{holding.trade_currency}/CNY", "CNY")

    automated_rows = (
        await session.execute(
            select(MarketData)
            .where(
                or_(*[
                    and_(MarketData.data_type == data_type, MarketData.symbol == symbol)
                    for data_type, symbol, _currency in required.values()
                ])
            )
            .order_by(MarketData.fetched_at.desc(), MarketData.created_at.desc())
        )
    ).scalars().all() if required else []
    override_rows = (
        await session.execute(
            select(MarketDataOverride)
            .where(
                or_(*[
                    and_(MarketDataOverride.data_type == data_type, MarketDataOverride.symbol == symbol)
                    for data_type, symbol, _currency in required.values()
                ])
            )
            .order_by(MarketDataOverride.updated_at.desc(), MarketDataOverride.created_at.desc())
        )
    ).scalars().all() if required else []

    rows_by_key: dict[str, list[MarketData]] = defaultdict(list)
    for row in automated_rows:
        rows_by_key[f"{row.data_type}:{row.symbol}"].append(row)
    overrides_by_key: dict[str, MarketDataOverride] = {}
    for row in override_rows:
        overrides_by_key.setdefault(f"{row.data_type}:{row.symbol}", row)

    effective_inputs: dict[str, _EffectiveInput] = {}
    incomplete_items: list[str] = []
    for key, (_data_type, _symbol, currency) in required.items():
        effective = _resolve_effective_input(key, rows_by_key.get(key, []), overrides_by_key.get(key), currency)
        effective_inputs[key] = effective
        if effective.value is None:
            incomplete_items.append(key)
    return effective_inputs, sorted(incomplete_items)


def _resolve_effective_input(
    key: str,
    automated_rows: list[MarketData],
    override_row: MarketDataOverride | None,
    currency: str,
) -> _EffectiveInput:
    now = datetime.now(UTC)
    if override_row is not None and override_row.effective_at <= now and (
        override_row.expires_at is None or override_row.expires_at > now
    ):
        return _EffectiveInput(
            key=key,
            value=override_row.value,
            status="manual",
            source_id=str(override_row.id),
            currency=currency,
        )

    latest_attempt = max(
        automated_rows,
        key=lambda row: (row.fetched_at, row.created_at),
        default=None,
    )
    latest_valid = max(
        (row for row in automated_rows if row.status == "valid" and row.value is not None),
        key=lambda row: (row.market_time or row.fetched_at, row.fetched_at, row.created_at),
        default=None,
    )
    if latest_valid is None:
        if latest_attempt is None:
            return _EffectiveInput(key=key, value=None, status="missing", source_id=None, currency=currency)
        return _EffectiveInput(
            key=key,
            value=None,
            status=latest_attempt.status,
            source_id=str(latest_attempt.id),
            currency=currency,
        )
    status = "valid"
    if latest_attempt is not None and latest_attempt.status != "valid":
        status = "stale"
    return _EffectiveInput(
        key=key,
        value=latest_valid.value,
        status=status,
        source_id=str(latest_valid.id),
        currency=currency,
    )


def _run_engine(
    *,
    valuation_basis: Literal["actual", "fx_neutral"],
    asset_classes: list[AssetClass],
    holdings: list[Holding],
    effective_inputs: dict[str, _EffectiveInput],
    available_cny: Decimal,
    available_usd: Decimal,
    tolerance: Decimal,
    minimum_trade_cny: Decimal,
    allow_sell: bool,
    allow_fx: bool,
) -> RebalanceResult:
    holdings_by_class: dict[UUID, list[Holding]] = defaultdict(list)
    for holding in holdings:
        holdings_by_class[holding.asset_class_id].append(holding)

    assets: list[AssetInput] = []
    for asset_class in asset_classes:
        class_holdings = holdings_by_class.get(asset_class.id, [])
        if not class_holdings:
            raise ServiceError(
                409,
                "REBALANCE_DATA_INCOMPLETE",
                "Active rebalance asset class is missing a preferred holding.",
                {"status": "incomplete", "items": [f"preferred:{asset_class.id}"]},
            )
        preferred = next((holding for holding in class_holdings if holding.is_rebalance_preferred), class_holdings[0])
        total_value = _ZERO
        for holding in class_holdings:
            price = effective_inputs[f"price:{holding.symbol}"].value
            fx = Decimal("1") if holding.trade_currency == "CNY" else effective_inputs[f"fx:{holding.trade_currency}/CNY"].value
            basis_fx = fx if valuation_basis == "actual" else holding.baseline_fx_to_cny
            total_value += holding.quantity * price * basis_fx
        preferred_price = effective_inputs[f"price:{preferred.symbol}"].value
        preferred_fx = Decimal("1") if preferred.trade_currency == "CNY" else effective_inputs[f"fx:{preferred.trade_currency}/CNY"].value
        unit_price_cny = preferred_price * (preferred_fx if preferred.trade_currency != "CNY" else Decimal("1"))
        assets.append(
            AssetInput(
                asset_class_id=str(asset_class.id),
                symbol=preferred.symbol,
                currency=preferred.trade_currency,
                current_value_cny=total_value,
                target_weight=asset_class.target_weight,
                unit_price_cny=unit_price_cny,
                lot_size=preferred.lot_size,
            )
        )

    usd_fx = effective_inputs.get("fx:USD/CNY")
    usd_cny = usd_fx.value if usd_fx is not None and usd_fx.value is not None else Decimal("1")
    return rebalance(
        assets,
        CashInput(cny=available_cny, usd=available_usd, usd_cny=usd_cny),
        RebalanceOptions(
            tolerance=tolerance,
            minimum_trade_cny=minimum_trade_cny,
            allow_sell=allow_sell,
            allow_fx=allow_fx,
        ),
    )


def _serialize_result(result: RebalanceResult) -> RebalanceResultResponse:
    return RebalanceResultResponse(
        feasible=result.feasible,
        max_drift_before=result.max_drift_before,
        max_drift_after=result.max_drift_after,
        fx_required_cny=result.fx_required_cny,
        remaining_cny=result.remaining_cny,
        remaining_usd=result.remaining_usd,
        projected_weights=tuple(
            ProjectedWeightResponse(
                asset_class_id=item.asset_class_id,
                before=item.before,
                after=item.after,
                target=item.target,
            )
            for item in result.projected_weights
        ),
        trades=tuple(
            TradeSuggestionResponse(
                symbol=item.symbol,
                action=item.action,
                quantity=item.quantity,
                amount_cny=item.amount_cny,
                amount_trade_currency=item.amount_trade_currency,
                reason_code=item.reason_code,
                reason=_REASON_TEXT[item.reason_code],
            )
            for item in result.trades
        ),
    )


def _data_version(
    *,
    market_data_record_ids: dict[str, str],
    holding_versions: dict[str, int],
    asset_class_targets: dict[str, str],
    **_ignored,
) -> str:
    payload = {
        "market_data_record_ids": market_data_record_ids,
        "holding_versions": holding_versions,
        "asset_class_targets": asset_class_targets,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _get_locked_plan(session: AsyncSession, plan_id: UUID) -> RebalancePlan:
    plan = await session.scalar(
        select(RebalancePlan).where(RebalancePlan.id == plan_id).with_for_update()
    )
    if plan is None:
        raise ServiceError(404, "REBALANCE_PLAN_NOT_FOUND", "Rebalance plan was not found.")
    return plan


def _plan_response(plan: RebalancePlan) -> RebalancePlanResponse:
    projected = plan.projected_result
    return RebalancePlanResponse(
        id=str(plan.id),
        status=plan.status,
        valuation_basis=plan.strategy_mode,
        data_version=plan.data_version,
        data_status=projected["data_status"],
        market_data_record_ids=plan.input_summary["market_data_record_ids"],
        holding_versions=plan.input_summary["holding_versions"],
        asset_class_targets=plan.input_summary.get("asset_class_targets", {}),
        result=RebalanceResultResponse.model_validate(projected["result"]),
        fx_comparison=RebalanceComparisonResponse.model_validate(projected["fx_comparison"]),
        before_snapshot_id=str(plan.before_snapshot_id) if plan.before_snapshot_id is not None else None,
        after_snapshot_id=str(plan.after_snapshot_id) if plan.after_snapshot_id is not None else None,
        baseline_reset_at=plan.baseline_reset_at.isoformat() if plan.baseline_reset_at is not None else None,
        created_at=plan.created_at.isoformat(),
        updated_at=plan.updated_at.isoformat(),
    )
