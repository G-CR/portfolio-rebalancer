from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    Decimal,
    getcontext,
    localcontext,
)
from heapq import heappop, heappush
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.rebalance import AssetInput, CashInput


OPTIMIZATION_EPSILON = Decimal("0.0001")
NODE_BUDGET = 250_000


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    lot_counts: tuple[int, ...]
    final_values: tuple[Decimal, ...]
    max_drift: Decimal
    total_drift: Decimal
    total_sale_cny: Decimal
    net_fx_cny: Decimal
    total_traded_cny: Decimal
    trade_count: int
    remaining_cny: Decimal
    remaining_usd: Decimal
    stable_trade_key: tuple[tuple[str, str, Decimal], ...]

    @classmethod
    def for_test(
        cls,
        *,
        lot_counts: tuple[int, ...],
        final_values: tuple[Decimal, ...],
        max_drift: Decimal,
        total_drift: Decimal,
        total_sale_cny: Decimal = Decimal("0"),
        net_fx_cny: Decimal = Decimal("0"),
    ) -> CandidatePlan:
        return cls(
            lot_counts=lot_counts,
            final_values=final_values,
            max_drift=max_drift,
            total_drift=total_drift,
            total_sale_cny=total_sale_cny,
            net_fx_cny=net_fx_cny,
            total_traded_cny=Decimal("0"),
            trade_count=0,
            remaining_cny=Decimal("0"),
            remaining_usd=Decimal("0"),
            stable_trade_key=(),
        )


@dataclass(frozen=True, slots=True)
class ContinuousBound:
    max_drift: Decimal
    total_drift: Decimal
    guide_values: tuple[Decimal, ...]
    lot_bounds: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class CashLedgerResult:
    feasible: bool
    net_fx_cny: Decimal
    remaining_cny: Decimal
    remaining_usd: Decimal


@dataclass(frozen=True, slots=True)
class CertifiedPlan:
    candidate: CandidatePlan
    best_open_lower_bound: Decimal
    optimality_gap: Decimal
    explored_nodes: int


class OptimizationFailure(RuntimeError):
    def __init__(self, code: str, explored_nodes: int, gap: Decimal) -> None:
        super().__init__(code)
        self.code = code
        self.explored_nodes = explored_nodes
        self.gap = gap


def _bucket(value: Decimal) -> int:
    return int((value / OPTIMIZATION_EPSILON).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True, order=True, slots=True)
class PlanScore:
    max_drift_bucket: int
    total_drift_bucket: int
    total_sale_cny: Decimal
    absolute_net_fx_cny: Decimal
    total_traded_cny: Decimal
    trade_count: int
    stable_trade_key: tuple[tuple[str, str, Decimal], ...]


def score_candidate(candidate: CandidatePlan) -> PlanScore:
    return PlanScore(
        _bucket(candidate.max_drift),
        _bucket(candidate.total_drift),
        candidate.total_sale_cny,
        abs(candidate.net_fx_cny),
        candidate.total_traded_cny,
        candidate.trade_count,
        candidate.stable_trade_key,
    )


def _digit_counts(value: Decimal) -> tuple[int, int]:
    exponent = value.as_tuple().exponent
    fractional_digits = max(-exponent, 0)
    integer_digits = max(len(value.as_tuple().digits) - fractional_digits, 1)
    return integer_digits, fractional_digits


def _calculation_precision(values: Sequence[Decimal]) -> int:
    integer_digits = 0
    fractional_digits = 0
    for value in values:
        current_integer, current_fractional = _digit_counts(value)
        integer_digits += current_integer
        fractional_digits += current_fractional
    return max(100, integer_digits + fractional_digits + 30)


def _asset_key(asset: AssetInput) -> tuple[str, str]:
    return asset.asset_class_id, asset.symbol


def _lot_value(asset: AssetInput) -> Decimal:
    return asset.unit_price_cny * asset.lot_size


def evaluate_cash_ledger(
    assets: Sequence[AssetInput],
    lot_counts: Sequence[int],
    cash: CashInput,
    *,
    allow_fx: bool,
) -> CashLedgerResult:
    """Evaluate a complete signed lot vector using at most one net FX leg."""
    if len(assets) != len(lot_counts):
        raise ValueError("lot_counts must match assets")

    cny_before_fx = cash.cny
    usd_cny_before_fx = cash.usd * cash.usd_cny
    for asset, lot_count in zip(assets, lot_counts, strict=True):
        trade_value_cny = Decimal(lot_count) * _lot_value(asset)
        if asset.currency == "CNY":
            cny_before_fx -= trade_value_cny
        else:
            usd_cny_before_fx -= trade_value_cny

    feasible = True
    if not allow_fx:
        feasible = cny_before_fx >= 0 and usd_cny_before_fx >= 0
        net_fx_cny = Decimal("0")
    elif cny_before_fx < 0:
        # Negative means the USD balance funds CNY purchases.
        net_fx_cny = cny_before_fx
    elif usd_cny_before_fx < 0:
        # Positive means the CNY balance funds USD purchases.
        net_fx_cny = -usd_cny_before_fx
    else:
        net_fx_cny = Decimal("0")

    remaining_cny = cny_before_fx - net_fx_cny
    remaining_usd_cny = usd_cny_before_fx + net_fx_cny
    feasible = feasible and remaining_cny >= 0 and remaining_usd_cny >= 0
    return CashLedgerResult(
        feasible=feasible,
        net_fx_cny=net_fx_cny,
        remaining_cny=remaining_cny,
        remaining_usd=remaining_usd_cny / cash.usd_cny,
    )


def _full_lot_bounds(
    assets: tuple[AssetInput, ...],
    cash: CashInput,
    *,
    allow_sell: bool,
    allow_fx: bool,
) -> tuple[tuple[int, int], ...]:
    lot_values = tuple(_lot_value(asset) for asset in assets)
    lower_bounds: list[int] = []
    for asset, lot_value in zip(assets, lot_values, strict=True):
        if not allow_sell:
            lower_bounds.append(0)
            continue
        inventory_lots = int(
            (asset.max_sell_quantity / asset.lot_size).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        class_value_lots = int(
            (asset.current_value_cny / lot_value).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        lower_bounds.append(-min(inventory_lots, class_value_lots))

    sale_capacities = tuple(
        Decimal(-lower_bound) * lot_value
        for lower_bound, lot_value in zip(lower_bounds, lot_values, strict=True)
    )
    combined_cash = cash.cny + cash.usd * cash.usd_cny
    upper_bounds: list[int] = []
    for index, (asset, lot_value) in enumerate(zip(assets, lot_values, strict=True)):
        if allow_fx:
            available = combined_cash + sum(
                (
                    sale_value
                    for other_index, sale_value in enumerate(sale_capacities)
                    if other_index != index
                ),
                Decimal("0"),
            )
        else:
            available = cash.cny if asset.currency == "CNY" else cash.usd * cash.usd_cny
            available += sum(
                (
                    sale_value
                    for other_index, (other, sale_value) in enumerate(
                        zip(assets, sale_capacities, strict=True)
                    )
                    if other_index != index and other.currency == asset.currency
                ),
                Decimal("0"),
            )
        upper_bounds.append(
            int((available / lot_value).to_integral_value(rounding=ROUND_FLOOR))
        )

    return tuple(zip(lower_bounds, upper_bounds, strict=True))


def _minimum_invested_total(
    minimum_values: tuple[Decimal, ...],
    target_weights: tuple[Decimal, ...],
    drift: Decimal,
) -> Decimal | None:
    """Solve V = sum(max(minimum_i, (target_i - drift) * V))."""
    lower_slopes = tuple(max(Decimal("0"), target - drift) for target in target_weights)
    active: set[int] = set()
    while True:
        fixed_total = sum(
            (
                minimum
                for index, minimum in enumerate(minimum_values)
                if index not in active
            ),
            Decimal("0"),
        )
        active_slope = sum((lower_slopes[index] for index in active), Decimal("0"))
        denominator = Decimal("1") - active_slope
        if denominator == 0:
            if fixed_total > 0:
                return None
            invested_total = Decimal("0")
        else:
            invested_total = fixed_total / denominator

        newly_active = {
            index
            for index, (minimum, slope) in enumerate(
                zip(minimum_values, lower_slopes, strict=True)
            )
            if index not in active and slope * invested_total > minimum
        }
        if not newly_active:
            return invested_total
        active.update(newly_active)


def _trial_intervals(
    minimum_values: tuple[Decimal, ...],
    maximum_values: tuple[Decimal, ...],
    target_weights: tuple[Decimal, ...],
    drift: Decimal,
    invested_total: Decimal,
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
    rounding_margin = Decimal("1").scaleb(
        invested_total.adjusted() - getcontext().prec + 4
    )
    lower_values = tuple(
        max(
            minimum,
            (target - drift) * invested_total - rounding_margin,
        )
        for minimum, target in zip(minimum_values, target_weights, strict=True)
    )
    upper_values = tuple(
        min(
            maximum,
            (target + drift) * invested_total + rounding_margin,
        )
        for maximum, target in zip(maximum_values, target_weights, strict=True)
    )
    return lower_values, upper_values


def _has_interval_capacity(
    assets: tuple[AssetInput, ...],
    lower_values: tuple[Decimal, ...],
    upper_values: tuple[Decimal, ...],
    invested_total: Decimal,
    currency_caps: dict[str, Decimal],
    *,
    allow_fx: bool,
) -> bool:
    if any(
        lower > upper for lower, upper in zip(lower_values, upper_values, strict=True)
    ):
        return False
    if sum(lower_values, Decimal("0")) > invested_total:
        return False
    if allow_fx:
        return invested_total <= sum(upper_values, Decimal("0"))

    upper_capacity = Decimal("0")
    for currency in ("CNY", "USD"):
        currency_lower = sum(
            (
                value
                for asset, value in zip(assets, lower_values, strict=True)
                if asset.currency == currency
            ),
            Decimal("0"),
        )
        if currency_lower > currency_caps[currency]:
            return False
        currency_upper = sum(
            (
                value
                for asset, value in zip(assets, upper_values, strict=True)
                if asset.currency == currency
            ),
            Decimal("0"),
        )
        upper_capacity += min(currency_upper, currency_caps[currency])
    return invested_total <= upper_capacity


def _positive_zero_minimum_trial(
    assets: tuple[AssetInput, ...],
    maximum_values: tuple[Decimal, ...],
    target_weights: tuple[Decimal, ...],
    drift: Decimal,
    maximum_invested_total: Decimal,
    currency_caps: dict[str, Decimal],
    *,
    allow_fx: bool,
) -> Decimal | None:
    """Choose a positive V below the first upper-bound breakpoint."""
    upper_slopes = tuple(target + drift for target in target_weights)
    effective_slope = sum(
        (
            slope
            for asset, maximum, slope in zip(
                assets, maximum_values, upper_slopes, strict=True
            )
            if maximum > 0 and (allow_fx or currency_caps[asset.currency] > 0)
        ),
        Decimal("0"),
    )
    if effective_slope < 1 or maximum_invested_total <= 0:
        return None

    breakpoints = [maximum_invested_total]
    breakpoints.extend(
        maximum / slope
        for maximum, slope in zip(maximum_values, upper_slopes, strict=True)
        if maximum > 0 and slope > 0
    )
    if not allow_fx:
        for currency in ("CNY", "USD"):
            currency_slope = sum(
                (
                    slope
                    for asset, maximum, slope in zip(
                        assets, maximum_values, upper_slopes, strict=True
                    )
                    if asset.currency == currency and maximum > 0
                ),
                Decimal("0"),
            )
            if currency_caps[currency] > 0 and currency_slope > 0:
                breakpoints.append(currency_caps[currency] / currency_slope)
    positive_breakpoints = [value for value in breakpoints if value > 0]
    if not positive_breakpoints:
        return None
    return min(positive_breakpoints) / Decimal("2")


def _water_fill_guide(
    assets: tuple[AssetInput, ...],
    lower_values: tuple[Decimal, ...],
    upper_values: tuple[Decimal, ...],
    target_weights: tuple[Decimal, ...],
    invested_total: Decimal,
    currency_caps: dict[str, Decimal],
    *,
    allow_fx: bool,
) -> tuple[Decimal, ...]:
    values = list(lower_values)
    remaining = invested_total - sum(values, Decimal("0"))
    currency_totals = {
        currency: sum(
            (
                value
                for asset, value in zip(assets, values, strict=True)
                if asset.currency == currency
            ),
            Decimal("0"),
        )
        for currency in ("CNY", "USD")
    }
    target_ceilings = tuple(
        min(upper, max(lower, target * invested_total))
        for lower, upper, target in zip(
            lower_values, upper_values, target_weights, strict=True
        )
    )

    for ceilings in (target_ceilings, upper_values):
        for index, (asset, ceiling) in enumerate(zip(assets, ceilings, strict=True)):
            if remaining <= 0:
                break
            room = ceiling - values[index]
            if not allow_fx:
                room = min(
                    room,
                    currency_caps[asset.currency] - currency_totals[asset.currency],
                )
            addition = min(remaining, room)
            if addition <= 0:
                continue
            values[index] += addition
            currency_totals[asset.currency] += addition
            remaining -= addition

    if remaining != 0:
        raise RuntimeError("continuous guide could not be water-filled")
    return tuple(values)


def _infeasible_continuous_bound(
    guide_values: tuple[Decimal, ...],
    lot_bounds: tuple[tuple[int, int], ...],
) -> ContinuousBound:
    return ContinuousBound(
        max_drift=Decimal("Infinity"),
        total_drift=Decimal("Infinity"),
        guide_values=guide_values,
        lot_bounds=lot_bounds,
    )


def continuous_relaxation(
    assets: Sequence[AssetInput],
    cash: CashInput,
    *,
    allow_sell: bool,
    allow_fx: bool,
    lot_bounds: tuple[tuple[int, int], ...] | None = None,
) -> ContinuousBound:
    """Return a conservative minimax bound and a deterministic relaxed guide."""
    asset_tuple = tuple(assets)
    if lot_bounds is not None and len(lot_bounds) != len(asset_tuple):
        raise ValueError("lot_bounds must match assets")

    if lot_bounds is None:
        ordered_assets = tuple(sorted(asset_tuple, key=_asset_key))
        ordered_explicit_bounds = None
    else:
        ordered_entries = sorted(
            zip(asset_tuple, lot_bounds, strict=True),
            key=lambda entry: _asset_key(entry[0]),
        )
        ordered_assets = tuple(entry[0] for entry in ordered_entries)
        ordered_explicit_bounds = tuple(entry[1] for entry in ordered_entries)

    decimal_inputs = [cash.cny, cash.usd, cash.usd_cny]
    for asset in ordered_assets:
        decimal_inputs.extend(
            (
                asset.current_value_cny,
                asset.target_weight,
                asset.unit_price_cny,
                asset.lot_size,
                asset.max_sell_quantity,
            )
        )

    with localcontext() as context:
        context.prec = _calculation_precision(decimal_inputs)
        executable_bounds = _full_lot_bounds(
            ordered_assets,
            cash,
            allow_sell=allow_sell,
            allow_fx=allow_fx,
        )
        if ordered_explicit_bounds is None:
            resolved_bounds = executable_bounds
        else:
            for explicit, executable in zip(
                ordered_explicit_bounds, executable_bounds, strict=True
            ):
                if (
                    len(explicit) != 2
                    or explicit[0] > explicit[1]
                    or explicit[0] < executable[0]
                    or explicit[1] > executable[1]
                ):
                    raise ValueError(
                        "lot_bounds must be inclusive executable subranges"
                    )
            resolved_bounds = ordered_explicit_bounds

        if not ordered_assets:
            return ContinuousBound(
                max_drift=Decimal("0"),
                total_drift=Decimal("0"),
                guide_values=(),
                lot_bounds=resolved_bounds,
            )

        target_weights = tuple(asset.target_weight for asset in ordered_assets)
        if sum(target_weights, Decimal("0")) != 1:
            raise ValueError("target weights must sum to 1")

        lot_values = tuple(_lot_value(asset) for asset in ordered_assets)
        minimum_values = tuple(
            asset.current_value_cny + Decimal(lower) * lot_value
            for asset, (lower, _), lot_value in zip(
                ordered_assets, resolved_bounds, lot_values, strict=True
            )
        )
        maximum_values = tuple(
            asset.current_value_cny + Decimal(upper) * lot_value
            for asset, (_, upper), lot_value in zip(
                ordered_assets, resolved_bounds, lot_values, strict=True
            )
        )
        current_by_currency = {
            currency: sum(
                (
                    asset.current_value_cny
                    for asset in ordered_assets
                    if asset.currency == currency
                ),
                Decimal("0"),
            )
            for currency in ("CNY", "USD")
        }
        currency_caps = {
            "CNY": current_by_currency["CNY"] + cash.cny,
            "USD": current_by_currency["USD"] + cash.usd * cash.usd_cny,
        }
        if allow_fx:
            maximum_invested_total = min(
                sum(maximum_values, Decimal("0")),
                sum(currency_caps.values(), Decimal("0")),
            )
        else:
            maximum_invested_total = sum(
                (
                    min(
                        sum(
                            (
                                maximum
                                for asset, maximum in zip(
                                    ordered_assets,
                                    maximum_values,
                                    strict=True,
                                )
                                if asset.currency == currency
                            ),
                            Decimal("0"),
                        ),
                        currency_caps[currency],
                    )
                    for currency in ("CNY", "USD")
                ),
                Decimal("0"),
            )
        minimum_invested_total = sum(minimum_values, Decimal("0"))

        if minimum_invested_total > maximum_invested_total:
            return _infeasible_continuous_bound(minimum_values, resolved_bounds)
        if maximum_invested_total == 0:
            return ContinuousBound(
                max_drift=max(target_weights),
                total_drift=sum(target_weights, Decimal("0")),
                guide_values=minimum_values,
                lot_bounds=resolved_bounds,
            )

        def trial(
            drift: Decimal,
        ) -> tuple[Decimal, tuple[Decimal, ...], tuple[Decimal, ...]] | None:
            invested_total = _minimum_invested_total(
                minimum_values, target_weights, drift
            )
            if invested_total is None:
                return None
            if invested_total == 0:
                invested_total = _positive_zero_minimum_trial(
                    ordered_assets,
                    maximum_values,
                    target_weights,
                    drift,
                    maximum_invested_total,
                    currency_caps,
                    allow_fx=allow_fx,
                )
                if invested_total is None:
                    return None
            if not (minimum_invested_total <= invested_total <= maximum_invested_total):
                return None
            lower_values, upper_values = _trial_intervals(
                minimum_values,
                maximum_values,
                target_weights,
                drift,
                invested_total,
            )
            if not _has_interval_capacity(
                ordered_assets,
                lower_values,
                upper_values,
                invested_total,
                currency_caps,
                allow_fx=allow_fx,
            ):
                return None
            return invested_total, lower_values, upper_values

        zero_trial = trial(Decimal("0"))
        if zero_trial is not None:
            lower_bound = Decimal("0")
            feasible_trial = zero_trial
        else:
            lower_bound = Decimal("0")
            upper_bound = Decimal("1")
            feasible_trial = trial(upper_bound)
            if feasible_trial is None:
                return _infeasible_continuous_bound(minimum_values, resolved_bounds)

            tolerance = OPTIMIZATION_EPSILON / Decimal("16")
            while upper_bound - lower_bound > tolerance:
                midpoint = (lower_bound + upper_bound) / Decimal("2")
                midpoint_trial = trial(midpoint)
                if midpoint_trial is None:
                    lower_bound = midpoint
                else:
                    upper_bound = midpoint
                    feasible_trial = midpoint_trial

        invested_total, lower_values, upper_values = feasible_trial
        guide_values = _water_fill_guide(
            ordered_assets,
            lower_values,
            upper_values,
            target_weights,
            invested_total,
            currency_caps,
            allow_fx=allow_fx,
        )
        guide_drifts = tuple(
            abs(value / invested_total - target)
            for value, target in zip(guide_values, target_weights, strict=True)
        )
        return ContinuousBound(
            # The last infeasible bisection endpoint is conservative for branch
            # pruning; its distance from the relaxed optimum is < epsilon / 16.
            max_drift=lower_bound,
            total_drift=sum(guide_drifts, Decimal("0")),
            guide_values=guide_values,
            lot_bounds=resolved_bounds,
        )


@dataclass(frozen=True, slots=True)
class _SearchNode:
    lot_bounds: tuple[tuple[int, int], ...]
    bound: ContinuousBound

    @property
    def is_singleton(self) -> bool:
        return all(lower == upper for lower, upper in self.lot_bounds)


def _candidate_from_lots(
    assets: tuple[AssetInput, ...],
    cash: CashInput,
    lot_counts: tuple[int, ...],
    *,
    allow_fx: bool,
) -> CandidatePlan | None:
    ledger = evaluate_cash_ledger(assets, lot_counts, cash, allow_fx=allow_fx)
    lot_values = tuple(_lot_value(asset) for asset in assets)
    final_values = tuple(
        asset.current_value_cny + Decimal(lot_count) * lot_value
        for asset, lot_count, lot_value in zip(
            assets, lot_counts, lot_values, strict=True
        )
    )
    if not ledger.feasible or any(value < 0 for value in final_values):
        return None

    invested_total = sum(final_values, Decimal("0"))
    if invested_total == 0:
        drifts = tuple(asset.target_weight for asset in assets)
    else:
        drifts = tuple(
            abs(value / invested_total - asset.target_weight)
            for asset, value in zip(assets, final_values, strict=True)
        )
    trade_values = tuple(
        Decimal(lot_count) * lot_value
        for lot_count, lot_value in zip(lot_counts, lot_values, strict=True)
    )
    return CandidatePlan(
        lot_counts=lot_counts,
        final_values=final_values,
        max_drift=max(drifts, default=Decimal("0")),
        total_drift=sum(drifts, Decimal("0")),
        total_sale_cny=sum(
            (-value for value in trade_values if value < 0), Decimal("0")
        ),
        net_fx_cny=ledger.net_fx_cny,
        total_traded_cny=sum((abs(value) for value in trade_values), Decimal("0")),
        trade_count=sum(lot_count != 0 for lot_count in lot_counts),
        remaining_cny=ledger.remaining_cny,
        remaining_usd=ledger.remaining_usd,
        stable_trade_key=tuple(
            (
                asset.asset_class_id,
                asset.symbol,
                Decimal(lot_count) * asset.lot_size,
            )
            for asset, lot_count in zip(assets, lot_counts, strict=True)
            if lot_count != 0
        ),
    )


def _optimistic_score(bound: ContinuousBound) -> PlanScore:
    # Every executable total drift is at least its maximum component drift.
    # Activity is left at zero because a partial interval has not fixed trades.
    drift_bucket_lower_bound = _bucket(bound.max_drift)
    return PlanScore(
        drift_bucket_lower_bound,
        drift_bucket_lower_bound,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        0,
        (),
    )


def _guide_lot_roundings(
    asset: AssetInput,
    guide_value: Decimal,
    lot_bound: tuple[int, int],
) -> tuple[int, int, int]:
    guide_lots = (guide_value - asset.current_value_cny) / _lot_value(asset)
    lower, upper = lot_bound

    def bounded_lots(lot_count: int) -> int:
        return min(upper, max(lower, lot_count))

    return (
        bounded_lots(int(guide_lots.to_integral_value(rounding=ROUND_DOWN))),
        bounded_lots(int(guide_lots.to_integral_value(rounding=ROUND_FLOOR))),
        bounded_lots(int(guide_lots.to_integral_value(rounding=ROUND_CEILING))),
    )


def _seed_incumbent(
    assets: tuple[AssetInput, ...],
    cash: CashInput,
    root_bound: ContinuousBound,
    *,
    allow_fx: bool,
) -> CandidatePlan:
    roundings = tuple(
        _guide_lot_roundings(asset, guide_value, lot_bound)
        for asset, guide_value, lot_bound in zip(
            assets,
            root_bound.guide_values,
            root_bound.lot_bounds,
            strict=True,
        )
    )
    guide_vector = tuple(toward_zero for toward_zero, _, _ in roundings)
    lot_vectors: list[tuple[int, ...]] = []
    seen_vectors: set[tuple[int, ...]] = set()

    def add_seed(lot_counts: tuple[int, ...]) -> None:
        if lot_counts not in seen_vectors:
            seen_vectors.add(lot_counts)
            lot_vectors.append(lot_counts)

    add_seed(tuple(0 for _ in assets))
    add_seed(guide_vector)
    for index, (_, floor_lots, ceiling_lots) in enumerate(roundings):
        for neighboring_lots in (floor_lots, ceiling_lots):
            neighboring_vector = list(guide_vector)
            neighboring_vector[index] = neighboring_lots
            add_seed(tuple(neighboring_vector))

    incumbent: CandidatePlan | None = None
    for lot_counts in lot_vectors:
        candidate = _candidate_from_lots(assets, cash, lot_counts, allow_fx=allow_fx)
        if candidate is not None and (
            incumbent is None or score_candidate(candidate) < score_candidate(incumbent)
        ):
            incumbent = candidate
    if incumbent is None:
        raise RuntimeError("the no-trade rebalance candidate must be feasible")
    return incumbent


def _split_node(
    node: _SearchNode,
    assets: tuple[AssetInput, ...],
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    splittable = [
        index for index, (lower, upper) in enumerate(node.lot_bounds) if lower < upper
    ]
    split_index = max(
        splittable,
        key=lambda index: (
            Decimal(node.lot_bounds[index][1] - node.lot_bounds[index][0])
            * _lot_value(assets[index]),
            -index,
        ),
    )
    lower, upper = node.lot_bounds[split_index]
    guide_lots = (
        node.bound.guide_values[split_index] - assets[split_index].current_value_cny
    ) / _lot_value(assets[split_index])
    split_at = int(guide_lots.to_integral_value(rounding=ROUND_FLOOR))
    split_at = min(upper - 1, max(lower, split_at))

    left = list(node.lot_bounds)
    right = list(node.lot_bounds)
    left[split_index] = (lower, split_at)
    right[split_index] = (split_at + 1, upper)
    return tuple(left), tuple(right)


def optimize_discrete(
    assets: Sequence[AssetInput],
    cash: CashInput,
    *,
    allow_sell: bool,
    allow_fx: bool,
) -> CertifiedPlan:
    """Return a deterministic executable plan with a certified drift gap."""
    ordered_assets = tuple(sorted(assets, key=_asset_key))
    decimal_inputs = [cash.cny, cash.usd, cash.usd_cny]
    for asset in ordered_assets:
        decimal_inputs.extend(
            (
                asset.current_value_cny,
                asset.target_weight,
                asset.unit_price_cny,
                asset.lot_size,
                asset.max_sell_quantity,
            )
        )

    with localcontext() as context:
        context.prec = _calculation_precision(decimal_inputs)
        root_bound = continuous_relaxation(
            ordered_assets,
            cash,
            allow_sell=allow_sell,
            allow_fx=allow_fx,
        )
        incumbent = _seed_incumbent(ordered_assets, cash, root_bound, allow_fx=allow_fx)
        heap: list[
            tuple[
                PlanScore,
                tuple[tuple[int, int], ...],
                _SearchNode,
            ]
        ] = []

        def push_node(lot_bounds: tuple[tuple[int, int], ...]) -> None:
            bound = continuous_relaxation(
                ordered_assets,
                cash,
                allow_sell=allow_sell,
                allow_fx=allow_fx,
                lot_bounds=lot_bounds,
            )
            if bound.max_drift.is_infinite():
                return
            node = _SearchNode(lot_bounds, bound)
            heappush(heap, (_optimistic_score(bound), lot_bounds, node))

        push_node(root_bound.lot_bounds)
        explored_nodes = 0
        while heap:
            if explored_nodes == NODE_BUDGET:
                best_open_bound = min(node.bound.max_drift for _, _, node in heap)
                gap = max(Decimal("0"), incumbent.max_drift - best_open_bound)
                raise OptimizationFailure(
                    "REBALANCE_OPTIMIZATION_UNCERTIFIED", explored_nodes, gap
                )

            optimistic_score, _, node = heappop(heap)
            explored_nodes += 1
            if optimistic_score >= score_candidate(incumbent):
                continue
            if node.is_singleton:
                lot_counts = tuple(lower for lower, _ in node.lot_bounds)
                candidate = _candidate_from_lots(
                    ordered_assets, cash, lot_counts, allow_fx=allow_fx
                )
                if candidate is not None and score_candidate(
                    candidate
                ) < score_candidate(incumbent):
                    incumbent = candidate
            else:
                left, right = _split_node(node, ordered_assets)
                push_node(left)
                push_node(right)

            if not heap:
                return CertifiedPlan(
                    incumbent,
                    incumbent.max_drift,
                    Decimal("0"),
                    explored_nodes,
                )

        return CertifiedPlan(
            incumbent,
            incumbent.max_drift,
            Decimal("0"),
            explored_nodes,
        )
