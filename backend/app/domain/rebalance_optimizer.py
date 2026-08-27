from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal


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
    return int(
        (value / OPTIMIZATION_EPSILON).to_integral_value(rounding=ROUND_CEILING)
    )


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
