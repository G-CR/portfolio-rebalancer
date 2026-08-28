from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domain.rebalance import AssetInput, CashInput
from app.domain.rebalance_optimizer import (
    CandidatePlan,
    continuous_relaxation,
    evaluate_cash_ledger,
    score_candidate,
)


def asset(asset_class_id: str, currency: str, current: str, target: str) -> AssetInput:
    return AssetInput(
        asset_class_id=asset_class_id,
        symbol=asset_class_id.upper(),
        currency=currency,  # type: ignore[arg-type]
        current_value_cny=Decimal(current),
        target_weight=Decimal(target),
        unit_price_cny=Decimal("10"),
        lot_size=Decimal("1"),
        max_sell_quantity=Decimal(current) / Decimal("10"),
    )


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
    noisy = _candidate(max_drift="0.020099", total_drift="0.030099", sale="100")

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


def test_continuous_relaxation_returns_exact_two_class_lower_bound() -> None:
    bound = continuous_relaxation(
        assets=(
            asset("a", "CNY", "80", "0.5"),
            asset("b", "CNY", "20", "0.5"),
        ),
        cash=CashInput(Decimal("60"), Decimal("0"), Decimal("7.2")),
        allow_sell=False,
        allow_fx=False,
    )

    assert bound.max_drift == 0
    assert bound.guide_values == (Decimal("80"), Decimal("80"))
    assert bound.lot_bounds == ((0, 6), (0, 6))


def test_continuous_relaxation_honors_explicit_node_lot_bounds() -> None:
    bound = continuous_relaxation(
        assets=(
            asset("a", "CNY", "80", "0.5"),
            asset("b", "CNY", "20", "0.5"),
        ),
        cash=CashInput(Decimal("60"), Decimal("0"), Decimal("7.2")),
        allow_sell=False,
        allow_fx=False,
        lot_bounds=((0, 0), (0, 6)),
    )

    assert bound.max_drift == 0
    assert bound.guide_values == (Decimal("80"), Decimal("80"))
    assert bound.lot_bounds == ((0, 0), (0, 6))


def test_continuous_relaxation_derives_preferred_inventory_sell_bound() -> None:
    limited = AssetInput(
        asset_class_id="a",
        symbol="A",
        currency="CNY",
        current_value_cny=Decimal("100"),
        target_weight=Decimal("1"),
        unit_price_cny=Decimal("10"),
        lot_size=Decimal("1"),
        max_sell_quantity=Decimal("2.5"),
    )

    bound = continuous_relaxation(
        assets=(limited,),
        cash=CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        allow_sell=True,
        allow_fx=False,
    )

    assert bound.lot_bounds == ((-2, 0),)


def test_continuous_relaxation_never_exceeds_an_executable_plan() -> None:
    assets = (
        asset("a", "USD", "10", "0.6"),
        asset("b", "USD", "50", "0.4"),
    )

    bound = continuous_relaxation(
        assets=assets,
        cash=CashInput(Decimal("50"), Decimal("2"), Decimal("5")),
        allow_sell=False,
        allow_fx=True,
    )
    executable_values = (Decimal("70"), Decimal("50"))
    executable_total = sum(executable_values)
    executable_drift = max(
        abs(value / executable_total - item.target_weight)
        for item, value in zip(assets, executable_values, strict=True)
    )

    assert bound.max_drift <= executable_drift


def test_cash_ledger_uses_one_net_usd_to_cny_direction() -> None:
    ledger = evaluate_cash_ledger(
        assets=(
            asset("cn", "CNY", "50", "0.5"),
            asset("us", "USD", "50", "0.5"),
        ),
        lot_counts=(5, 0),
        cash=CashInput(Decimal("0"), Decimal("10"), Decimal("7")),
        allow_fx=True,
    )

    assert ledger.feasible
    assert ledger.net_fx_cny == Decimal("-50")
    assert ledger.remaining_cny == 0
    assert ledger.remaining_usd == Decimal("20") / Decimal("7")


def test_cash_ledger_uses_one_net_cny_to_usd_direction() -> None:
    ledger = evaluate_cash_ledger(
        assets=(
            asset("cn", "CNY", "50", "0.5"),
            asset("us", "USD", "50", "0.5"),
        ),
        lot_counts=(0, 5),
        cash=CashInput(Decimal("50"), Decimal("0"), Decimal("7")),
        allow_fx=True,
    )

    assert ledger.feasible
    assert ledger.net_fx_cny == Decimal("50")
    assert ledger.remaining_cny == 0
    assert ledger.remaining_usd == 0


def test_cash_ledger_rejects_cross_currency_funding_when_fx_is_disabled() -> None:
    ledger = evaluate_cash_ledger(
        assets=(
            asset("cn", "CNY", "50", "0.5"),
            asset("us", "USD", "50", "0.5"),
        ),
        lot_counts=(0, 5),
        cash=CashInput(Decimal("50"), Decimal("0"), Decimal("7")),
        allow_fx=False,
    )

    assert not ledger.feasible
    assert ledger.net_fx_cny == 0
    assert ledger.remaining_cny == Decimal("50")
    assert ledger.remaining_usd == Decimal("-50") / Decimal("7")


def test_cash_ledger_makes_sale_proceeds_available_to_buys() -> None:
    ledger = evaluate_cash_ledger(
        assets=(
            asset("a", "CNY", "50", "0.5"),
            asset("b", "CNY", "50", "0.5"),
        ),
        lot_counts=(-2, 1),
        cash=CashInput(Decimal("0"), Decimal("0"), Decimal("7")),
        allow_fx=False,
    )

    assert ledger.feasible
    assert ledger.net_fx_cny == 0
    assert ledger.remaining_cny == Decimal("10")
    assert ledger.remaining_usd == 0


def test_cash_ledger_does_not_create_an_fx_round_trip() -> None:
    ledger = evaluate_cash_ledger(
        assets=(
            asset("cn", "CNY", "50", "0.5"),
            asset("us", "USD", "50", "0.5"),
        ),
        lot_counts=(1, 1),
        cash=CashInput(Decimal("20"), Decimal("20") / Decimal("7"), Decimal("7")),
        allow_fx=True,
    )

    assert ledger.feasible
    assert ledger.net_fx_cny == 0
    assert ledger.remaining_cny == Decimal("10")
    assert ledger.remaining_usd == Decimal("10") / Decimal("7")
