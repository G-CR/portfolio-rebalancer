from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal

from app.domain.rebalance_optimizer import (
    OPTIMIZATION_EPSILON,
    CandidatePlan,
    optimize_discrete,
    score_candidate,
)

Currency = Literal["CNY", "USD"]
TradeAction = Literal["buy", "sell"]
ReasonCode = Literal[
    "REDUCE_MAX_DRIFT",
    "REDUCE_TOTAL_DRIFT",
    "REALLOCATE_OUTSIDE_TOLERANCE",
]
NetFxDirection = Literal["cny_to_usd", "usd_to_cny", "none"]


def _require_finite(name: str, value: Decimal) -> None:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def _require_nonnegative(name: str, value: Decimal) -> None:
    _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _require_positive(name: str, value: Decimal) -> None:
    _require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _digit_counts(value: Decimal) -> tuple[int, int]:
    exponent = value.as_tuple().exponent
    fractional_digits = max(-exponent, 0)
    integer_digits = max(
        len(value.as_tuple().digits) - fractional_digits + max(exponent, 0),
        1,
    )
    return integer_digits, fractional_digits


def _calculation_precision(values: Sequence[Decimal]) -> int:
    integer_digits = 0
    fractional_digits = 0
    for value in values:
        current_integer, current_fractional = _digit_counts(value)
        integer_digits += current_integer
        fractional_digits += current_fractional
    return max(100, integer_digits + fractional_digits + 30)


def _exact_sum_precision(values: Sequence[Decimal]) -> int:
    if not values:
        return 100
    lowest_exponent = min(value.as_tuple().exponent for value in values)
    highest_adjusted = max((value.adjusted() if value else 0) for value in values)
    carry_digits = len(str(len(values)))
    return max(100, highest_adjusted - lowest_exponent + carry_digits + 2)


def _public_usd_amount(
    amount_cny: Decimal,
    usd_cny: Decimal,
    *,
    precision: int,
) -> Decimal:
    """Convert the authoritative CNY ledger amount for public USD display."""
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_DOWN
        return amount_cny / usd_cny


@dataclass(frozen=True)
class AssetInput:
    asset_class_id: str
    symbol: str
    currency: Currency
    current_value_cny: Decimal
    target_weight: Decimal
    unit_price_cny: Decimal
    lot_size: Decimal
    max_sell_quantity: Decimal

    def __post_init__(self) -> None:
        if not self.asset_class_id:
            raise ValueError("asset_class_id must not be empty")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.currency not in ("CNY", "USD"):
            raise ValueError("currency must be CNY or USD")
        _require_nonnegative("current_value_cny", self.current_value_cny)
        _require_nonnegative("target_weight", self.target_weight)
        if self.target_weight > 1:
            raise ValueError("target_weight must not exceed 1")
        _require_positive("unit_price_cny", self.unit_price_cny)
        _require_positive("lot_size", self.lot_size)
        _require_nonnegative("max_sell_quantity", self.max_sell_quantity)


@dataclass(frozen=True)
class CashInput:
    cny: Decimal
    usd: Decimal
    usd_cny: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative("cny", self.cny)
        _require_nonnegative("usd", self.usd)
        _require_positive("usd_cny", self.usd_cny)


@dataclass(frozen=True)
class RebalanceOptions:
    tolerance: Decimal
    allow_sell: bool
    allow_fx: bool

    def __post_init__(self) -> None:
        _require_nonnegative("tolerance", self.tolerance)
        if self.tolerance > 1:
            raise ValueError("tolerance must not exceed 1")


@dataclass(frozen=True)
class TradeSuggestion:
    symbol: str
    action: TradeAction
    quantity: Decimal
    amount_cny: Decimal
    amount_trade_currency: Decimal
    reason_code: ReasonCode


@dataclass(frozen=True)
class ProjectedWeight:
    asset_class_id: str
    before: Decimal
    after: Decimal
    target: Decimal


@dataclass(frozen=True)
class RebalanceResult:
    feasible: bool
    max_drift_before: Decimal
    max_drift_after: Decimal
    buy_only_max_drift: Decimal
    optimization_precision: Decimal
    optimization_certified: bool
    optimality_gap: Decimal
    sell_phase_used: bool
    net_fx_direction: NetFxDirection
    net_fx_amount_cny: Decimal
    fx_required_cny: Decimal
    remaining_cny: Decimal
    remaining_usd: Decimal
    projected_weights: tuple[ProjectedWeight, ...]
    trades: tuple[TradeSuggestion, ...]


def _weight(value: Decimal, total: Decimal) -> Decimal:
    return value / total if total else Decimal("0")


def _drifts(
    assets: Sequence[AssetInput], values: Sequence[Decimal]
) -> tuple[Decimal, ...]:
    invested_total = sum(values, Decimal("0"))
    if invested_total == 0:
        return tuple(asset.target_weight for asset in assets)
    return tuple(
        abs(value / invested_total - asset.target_weight)
        for asset, value in zip(assets, values, strict=True)
    )


def _candidate_without_order(
    assets: tuple[AssetInput, ...],
    candidate: CandidatePlan,
    order_index: int,
) -> CandidatePlan:
    lot_counts = list(candidate.lot_counts)
    lot_counts[order_index] = 0
    final_values = tuple(
        asset.current_value_cny
        + Decimal(lot_count) * asset.unit_price_cny * asset.lot_size
        for asset, lot_count in zip(assets, lot_counts, strict=True)
    )
    drifts = _drifts(assets, final_values)
    return CandidatePlan.for_test(
        lot_counts=tuple(lot_counts),
        final_values=final_values,
        max_drift=max(drifts, default=Decimal("0")),
        total_drift=sum(drifts, Decimal("0")),
    )


def _reason_code(
    assets: tuple[AssetInput, ...],
    candidate: CandidatePlan,
    order_index: int,
    *,
    sell_phase_used: bool,
) -> ReasonCode:
    if sell_phase_used and candidate.lot_counts[order_index] < 0:
        return "REALLOCATE_OUTSIDE_TOLERANCE"

    removed = _candidate_without_order(assets, candidate, order_index)
    selected_score = score_candidate(candidate)
    removed_score = score_candidate(removed)
    if removed_score.max_drift_bucket > selected_score.max_drift_bucket:
        return "REDUCE_MAX_DRIFT"
    if removed_score.total_drift_bucket > selected_score.total_drift_bucket:
        return "REDUCE_TOTAL_DRIFT"
    if sell_phase_used:
        return "REALLOCATE_OUTSIDE_TOLERANCE"
    return "REDUCE_TOTAL_DRIFT"


def _net_fx(net_fx_cny: Decimal) -> tuple[NetFxDirection, Decimal]:
    if net_fx_cny > 0:
        return "cny_to_usd", net_fx_cny
    if net_fx_cny < 0:
        return "usd_to_cny", -net_fx_cny
    return "none", Decimal("0")


def rebalance(
    assets: Sequence[AssetInput],
    cash: CashInput,
    options: RebalanceOptions,
    *,
    deadline: float | None = None,
) -> RebalanceResult:
    asset_list = tuple(
        sorted(assets, key=lambda item: (item.asset_class_id, item.symbol))
    )
    class_ids = [item.asset_class_id for item in asset_list]
    symbols = [item.symbol for item in asset_list]
    if len(class_ids) != len(set(class_ids)):
        raise ValueError("duplicate asset_class_id")
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate symbol")

    decimal_values = [cash.cny, cash.usd, cash.usd_cny, options.tolerance]
    for item in asset_list:
        decimal_values.extend(
            (
                item.current_value_cny,
                item.target_weight,
                item.unit_price_cny,
                item.lot_size,
                item.max_sell_quantity,
            )
        )

    calculation_precision = _calculation_precision(decimal_values)
    with localcontext() as context:
        context.prec = calculation_precision
        # Nested optimizer contexts inherit this explicit mode, preserving the
        # approved half-even score semantics independently of the caller.
        context.rounding = ROUND_HALF_EVEN
        if asset_list and sum(
            (item.target_weight for item in asset_list), Decimal("0")
        ) != Decimal("1"):
            raise ValueError("target weights must sum to 1")

        original_values = tuple(item.current_value_cny for item in asset_list)
        original_total = sum(original_values, Decimal("0"))
        original_drifts = _drifts(asset_list, original_values)

        buy_only = optimize_discrete(
            asset_list,
            cash,
            allow_sell=False,
            allow_fx=options.allow_fx,
            deadline=deadline,
        )
        selected = buy_only
        sell_phase_used = False
        if options.allow_sell and buy_only.candidate.max_drift > options.tolerance:
            selected = optimize_discrete(
                asset_list,
                cash,
                allow_sell=True,
                allow_fx=options.allow_fx,
                deadline=deadline,
            )
            sell_phase_used = True

        candidate = selected.candidate
        final_total = sum(candidate.final_values, Decimal("0"))
        projected_weights = tuple(
            ProjectedWeight(
                asset_class_id=asset.asset_class_id,
                before=_weight(original, original_total),
                after=_weight(final, final_total),
                target=asset.target_weight,
            )
            for asset, original, final in zip(
                asset_list,
                original_values,
                candidate.final_values,
                strict=True,
            )
        )
        trade_suggestions = []
        signed_cny_amounts: list[Decimal] = []
        signed_usd_amounts: list[Decimal] = []
        for index, (asset, lot_count) in enumerate(
            zip(asset_list, candidate.lot_counts, strict=True)
        ):
            if lot_count == 0:
                continue
            quantity = abs(Decimal(lot_count)) * asset.lot_size
            amount_cny = quantity * asset.unit_price_cny
            # This is the canonical public order conversion. Remaining cash is
            # derived from it; the order amount is never reconciled or adjusted.
            amount_trade_currency = (
                amount_cny
                if asset.currency == "CNY"
                else _public_usd_amount(
                    amount_cny,
                    cash.usd_cny,
                    precision=calculation_precision,
                )
            )
            signed_amount = Decimal("1") if lot_count < 0 else Decimal("-1")
            if asset.currency == "CNY":
                signed_cny_amounts.append(signed_amount * amount_cny)
            else:
                signed_usd_amounts.append(signed_amount * amount_trade_currency)
            trade_suggestions.append(
                TradeSuggestion(
                    symbol=asset.symbol,
                    action="buy" if lot_count > 0 else "sell",
                    quantity=quantity,
                    amount_cny=amount_cny,
                    amount_trade_currency=amount_trade_currency,
                    reason_code=_reason_code(
                        asset_list,
                        candidate,
                        index,
                        sell_phase_used=sell_phase_used,
                    ),
                )
            )
        net_fx_direction, net_fx_amount_cny = _net_fx(candidate.net_fx_cny)
        fx_usd = _public_usd_amount(
            candidate.net_fx_cny,
            cash.usd_cny,
            precision=calculation_precision,
        )
        balance_values = [
            cash.cny,
            cash.usd,
            candidate.net_fx_cny,
            fx_usd,
            *signed_cny_amounts,
            *signed_usd_amounts,
        ]
        with localcontext() as balance_context:
            balance_context.prec = _exact_sum_precision(balance_values)
            balance_context.rounding = ROUND_HALF_EVEN
            remaining_cny = (
                cash.cny + sum(signed_cny_amounts, Decimal("0")) - candidate.net_fx_cny
            )
            remaining_usd = cash.usd + sum(signed_usd_amounts, Decimal("0")) + fx_usd
        trades = tuple(trade_suggestions)

        return RebalanceResult(
            feasible=candidate.max_drift <= options.tolerance,
            max_drift_before=max(original_drifts, default=Decimal("0")),
            max_drift_after=candidate.max_drift,
            buy_only_max_drift=buy_only.candidate.max_drift,
            optimization_precision=OPTIMIZATION_EPSILON,
            optimization_certified=True,
            optimality_gap=selected.optimality_gap,
            sell_phase_used=sell_phase_used,
            net_fx_direction=net_fx_direction,
            net_fx_amount_cny=net_fx_amount_cny,
            fx_required_cny=(
                net_fx_amount_cny if net_fx_direction == "cny_to_usd" else Decimal("0")
            ),
            remaining_cny=remaining_cny,
            remaining_usd=remaining_usd,
            projected_weights=projected_weights,
            trades=trades,
        )
