from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domain.rebalance_optimizer import CandidatePlan, score_candidate


def _candidate(
    *, max_drift: str, total_drift: str, sale: str = "0", fx: str = "0"
) -> CandidatePlan:
    return CandidatePlan.for_test(
        lot_counts=(0, 0),
        final_values=(Decimal("50"), Decimal("50")),
        max_drift=Decimal(max_drift),
        total_drift=Decimal(total_drift),
        total_sale_cny=Decimal(sale),
        net_fx_cny=Decimal(fx),
    )


def test_score_uses_one_basis_point_buckets_before_activity() -> None:
    quiet = _candidate(max_drift="0.020001", total_drift="0.030001")
    noisy = _candidate(
        max_drift="0.020099", total_drift="0.030099", sale="100"
    )

    assert score_candidate(quiet) < score_candidate(noisy)


def test_score_never_trades_a_full_basis_point_for_lower_activity() -> None:
    better = _candidate(max_drift="0.0201", total_drift="0.04", sale="1000")
    worse = _candidate(max_drift="0.0202", total_drift="0.02")

    assert score_candidate(better) < score_candidate(worse)


def test_candidate_test_factory_uses_deterministic_activity_defaults() -> None:
    candidate = _candidate(max_drift="0.02", total_drift="0.03")

    assert candidate.total_traded_cny == 0
    assert candidate.trade_count == 0
    assert candidate.remaining_cny == 0
    assert candidate.remaining_usd == 0
    assert candidate.stable_trade_key == ()
    with pytest.raises(FrozenInstanceError):
        candidate.trade_count = 1  # type: ignore[misc]
