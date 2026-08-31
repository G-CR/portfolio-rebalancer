import time
from dataclasses import FrozenInstanceError
from decimal import Decimal
from itertools import product

import pytest
from app.domain import rebalance_optimizer as optimizer
from app.domain.rebalance import AssetInput, CashInput, RebalanceOptions, rebalance
from app.domain.rebalance_optimizer import (
    OPTIMIZATION_EPSILON,
    CandidatePlan,
    OptimizationFailure,
    continuous_relaxation,
    evaluate_cash_ledger,
    optimize_discrete,
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


SMALL_ASSETS = (
    asset("a", "CNY", "40", "0.5"),
    asset("b", "USD", "60", "0.5"),
)
SMALL_CASH = CashInput(Decimal("30"), Decimal("20") / Decimal("7"), Decimal("7"))


def _representative_large_assets() -> tuple[AssetInput, ...]:
    return (
        AssetInput(
            asset_class_id="dividend",
            symbol="510880",
            currency="CNY",
            current_value_cny=Decimal("202000"),
            target_weight=Decimal("0.20"),
            unit_price_cny=Decimal("11.45"),
            lot_size=Decimal("100"),
            max_sell_quantity=Decimal("17600"),
        ),
        AssetInput(
            asset_class_id="quality",
            symbol="563020",
            currency="CNY",
            current_value_cny=Decimal("193000"),
            target_weight=Decimal("0.20"),
            unit_price_cny=Decimal("11.84"),
            lot_size=Decimal("100"),
            max_sell_quantity=Decimal("16300"),
        ),
        AssetInput(
            asset_class_id="sp500",
            symbol="VOO",
            currency="USD",
            current_value_cny=Decimal("313000"),
            target_weight=Decimal("0.30"),
            unit_price_cny=Decimal("48690"),
            lot_size=Decimal("0.01"),
            max_sell_quantity=Decimal("6.43"),
        ),
        AssetInput(
            asset_class_id="nasdaq",
            symbol="QQQ",
            currency="USD",
            current_value_cny=Decimal("205000"),
            target_weight=Decimal("0.20"),
            unit_price_cny=Decimal("35750"),
            lot_size=Decimal("0.01"),
            max_sell_quantity=Decimal("5.73"),
        ),
        AssetInput(
            asset_class_id="gold",
            symbol="518880",
            currency="CNY",
            current_value_cny=Decimal("87000"),
            target_weight=Decimal("0.10"),
            unit_price_cny=Decimal("200"),
            lot_size=Decimal("100"),
            max_sell_quantity=Decimal("400"),
        ),
    )


def test_rebalance_representative_fixture_is_certified_within_latency_budget() -> None:
    started_at = time.perf_counter()
    result = rebalance(
        _representative_large_assets(),
        CashInput(Decimal("100000"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), True, True),
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.5
    assert result.optimization_certified
    assert result.optimality_gap <= OPTIMIZATION_EPSILON
    assert not result.sell_phase_used
    assert result.net_fx_direction == "cny_to_usd"
    assert any(trade.symbol == "518880" and trade.quantity % Decimal("100") == 0 for trade in result.trades)
    assert any(trade.symbol in {"VOO", "QQQ"} and trade.quantity % Decimal("0.01") == 0 for trade in result.trades)


def test_rebalance_representative_fixture_uses_sell_phase_at_tight_tolerance() -> None:
    result = rebalance(
        _representative_large_assets(),
        CashInput(Decimal("100000"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.0001"), True, True),
    )

    assert result.optimization_certified
    assert result.sell_phase_used
    assert result.buy_only_max_drift > Decimal("0.0001")


def test_rebalance_representative_fixture_can_convert_usd_to_cny() -> None:
    result = rebalance(
        _representative_large_assets(),
        CashInput(Decimal("0"), Decimal("100000") / Decimal("7.2"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), True, True),
    )

    assert result.optimization_certified
    assert result.net_fx_direction == "usd_to_cny"


def _candidate_from_lots(
    assets: tuple[AssetInput, ...],
    cash: CashInput,
    lot_counts: tuple[int, ...],
    *,
    allow_fx: bool,
) -> CandidatePlan | None:
    ledger = evaluate_cash_ledger(assets, lot_counts, cash, allow_fx=allow_fx)
    lot_values = tuple(item.unit_price_cny * item.lot_size for item in assets)
    final_values = tuple(
        item.current_value_cny + Decimal(lots) * lot_value
        for item, lots, lot_value in zip(assets, lot_counts, lot_values, strict=True)
    )
    if not ledger.feasible or any(value < 0 for value in final_values):
        return None

    invested_total = sum(final_values, Decimal("0"))
    if invested_total == 0:
        drifts = tuple(item.target_weight for item in assets)
    else:
        drifts = tuple(
            abs(value / invested_total - item.target_weight)
            for item, value in zip(assets, final_values, strict=True)
        )
    trade_values = tuple(
        Decimal(lots) * lot_value
        for lots, lot_value in zip(lot_counts, lot_values, strict=True)
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
        trade_count=sum(lots != 0 for lots in lot_counts),
        remaining_cny=ledger.remaining_cny,
        remaining_usd=ledger.remaining_usd,
        stable_trade_key=tuple(
            (item.asset_class_id, item.symbol, Decimal(lots) * item.lot_size)
            for item, lots in zip(assets, lot_counts, strict=True)
            if lots != 0
        ),
    )


def _exhaustive_best(
    assets: tuple[AssetInput, ...],
    cash: CashInput,
    *,
    allow_sell: bool,
    allow_fx: bool,
) -> CandidatePlan:
    bounds = optimizer._full_lot_bounds(
        assets,
        cash,
        allow_sell=allow_sell,
        allow_fx=allow_fx,
    )
    ranges = [range(lower, upper + 1) for lower, upper in bounds]
    candidates = []
    for lots in product(*ranges):
        candidate = _candidate_from_lots(assets, cash, lots, allow_fx=allow_fx)
        if candidate is not None and (
            allow_sell or all(lot_count >= 0 for lot_count in lots)
        ):
            candidates.append(candidate)
    return min(candidates, key=score_candidate)


@pytest.mark.parametrize(
    ("allow_sell", "allow_fx"),
    ((False, False), (False, True), (True, False), (True, True)),
)
def test_search_matches_exhaustive_oracle(allow_sell: bool, allow_fx: bool) -> None:
    expected = _exhaustive_best(
        SMALL_ASSETS,
        SMALL_CASH,
        allow_sell=allow_sell,
        allow_fx=allow_fx,
    )

    actual = optimize_discrete(
        SMALL_ASSETS,
        SMALL_CASH,
        allow_sell=allow_sell,
        allow_fx=allow_fx,
    )

    assert score_candidate(actual.candidate) == score_candidate(expected)
    assert actual.optimality_gap <= OPTIMIZATION_EPSILON


def test_search_does_not_prune_higher_total_that_dilutes_an_overweight_asset() -> None:
    assets = (
        AssetInput(
            asset_class_id="a",
            symbol="A",
            currency="CNY",
            current_value_cny=Decimal("13"),
            target_weight=Decimal("0.03"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        ),
        AssetInput(
            asset_class_id="b",
            symbol="B",
            currency="CNY",
            current_value_cny=Decimal("26"),
            target_weight=Decimal("0.35"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        ),
        AssetInput(
            asset_class_id="c",
            symbol="C",
            currency="CNY",
            current_value_cny=Decimal("29"),
            target_weight=Decimal("0.62"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        ),
    )
    cash = CashInput(Decimal("18"), Decimal("0"), Decimal("1"))

    exhaustive = _exhaustive_best(
        assets, cash, allow_sell=False, allow_fx=False
    )
    bound = continuous_relaxation(
        assets, cash, allow_sell=False, allow_fx=False
    )
    actual = optimize_discrete(assets, cash, allow_sell=False, allow_fx=False)

    assert exhaustive.lot_counts == (0, 0, 18)
    assert bound.max_drift <= exhaustive.max_drift
    assert score_candidate(actual.candidate) == score_candidate(exhaustive)
    assert actual.optimality_gap == OPTIMIZATION_EPSILON


def _zero_total_liquidation_assets() -> tuple[AssetInput, ...]:
    return (
        AssetInput(
            asset_class_id="a",
            symbol="A",
            currency="CNY",
            current_value_cny=Decimal("3"),
            target_weight=Decimal("0.1"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("3"),
        ),
        AssetInput(
            asset_class_id="b",
            symbol="B",
            currency="CNY",
            current_value_cny=Decimal("0"),
            target_weight=Decimal("0.4"),
            unit_price_cny=Decimal("4"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        ),
        AssetInput(
            asset_class_id="c",
            symbol="C",
            currency="USD",
            current_value_cny=Decimal("0"),
            target_weight=Decimal("0.5"),
            unit_price_cny=Decimal("10"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        ),
    )


@pytest.mark.parametrize("allow_fx", (False, True))
def test_zero_total_liquidation_endpoint_keeps_root_child_and_search_bounds_sound(
    allow_fx: bool,
) -> None:
    assets = _zero_total_liquidation_assets()
    cash = CashInput(Decimal("1"), Decimal("0"), Decimal("2"))
    exhaustive = _exhaustive_best(
        assets, cash, allow_sell=True, allow_fx=allow_fx
    )
    root_bound = continuous_relaxation(
        assets, cash, allow_sell=True, allow_fx=allow_fx
    )
    child_bound = continuous_relaxation(
        assets,
        cash,
        allow_sell=True,
        allow_fx=allow_fx,
        lot_bounds=((-3, -2), (0, 0), (0, 0)),
    )
    actual = optimize_discrete(assets, cash, allow_sell=True, allow_fx=allow_fx)

    assert exhaustive.lot_counts == (-3, 0, 0)
    assert exhaustive.max_drift == Decimal("0.5")
    assert root_bound.max_drift <= exhaustive.max_drift
    assert child_bound.max_drift == exhaustive.max_drift
    assert score_candidate(actual.candidate) == score_candidate(exhaustive)
    assert actual.candidate.lot_counts == exhaustive.lot_counts


def test_bucket_optimal_plan_reports_nonzero_raw_drift_certificate() -> None:
    assets = (
        AssetInput(
            "a",
            "A",
            "USD",
            Decimal("20"),
            Decimal("0.463"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
        AssetInput(
            "b",
            "B",
            "USD",
            Decimal("11"),
            Decimal("0.1883"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
        AssetInput(
            "c",
            "C",
            "CNY",
            Decimal("8"),
            Decimal("0.3487"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
    )
    cash = CashInput(Decimal("6"), Decimal("2"), Decimal("2"))
    raw_drift_best = _candidate_from_lots(
        assets, cash, (2, 0, 6), allow_fx=False
    )
    actual = optimize_discrete(assets, cash, allow_sell=False, allow_fx=False)

    assert raw_drift_best is not None
    assert actual.candidate.lot_counts == (1, 0, 6)
    assert raw_drift_best.max_drift < actual.candidate.max_drift
    assert score_candidate(actual.candidate) < score_candidate(raw_drift_best)
    assert 0 < actual.optimality_gap <= OPTIMIZATION_EPSILON


@pytest.mark.parametrize(
    ("values", "targets", "cash_cny"),
    (
        (("0", "1", "2"), ("0.1", "0.3", "0.6"), "4"),
        (("2", "0", "3"), ("0.2", "0.5", "0.3"), "3"),
        (("4", "1", "0"), ("0.6", "0.2", "0.2"), "5"),
        (("1", "3", "2"), ("0.15", "0.45", "0.40"), "2"),
    ),
)
def test_continuous_bound_is_sound_against_small_three_asset_oracles(
    values: tuple[str, str, str],
    targets: tuple[str, str, str],
    cash_cny: str,
) -> None:
    assets = tuple(
        AssetInput(
            asset_class_id=f"a{index}",
            symbol=f"A{index}",
            currency="CNY",
            current_value_cny=Decimal(value),
            target_weight=Decimal(target),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        )
        for index, (value, target) in enumerate(zip(values, targets, strict=True))
    )
    cash = CashInput(Decimal(cash_cny), Decimal("0"), Decimal("1"))

    exhaustive = _exhaustive_best(
        assets, cash, allow_sell=False, allow_fx=False
    )
    bound = continuous_relaxation(
        assets, cash, allow_sell=False, allow_fx=False
    )
    actual = optimize_discrete(assets, cash, allow_sell=False, allow_fx=False)

    assert bound.max_drift <= exhaustive.max_drift
    assert score_candidate(actual.candidate) == score_candidate(exhaustive)


def test_search_never_sells_more_than_preferred_holding_inventory() -> None:
    assets = (
        AssetInput(
            asset_class_id="a",
            symbol="A",
            currency="CNY",
            current_value_cny=Decimal("1000"),
            target_weight=Decimal("0.1"),
            unit_price_cny=Decimal("10"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("2.5"),
        ),
        asset("b", "CNY", "100", "0.9"),
    )

    plan = optimize_discrete(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("7")),
        allow_sell=True,
        allow_fx=False,
    )

    assert plan.candidate.lot_counts[0] == -2


def test_search_is_independent_of_input_order() -> None:
    canonical = optimize_discrete(
        SMALL_ASSETS,
        SMALL_CASH,
        allow_sell=True,
        allow_fx=True,
    )

    permuted = optimize_discrete(
        tuple(reversed(SMALL_ASSETS)),
        SMALL_CASH,
        allow_sell=True,
        allow_fx=True,
    )

    assert permuted == canonical


def _large_lot_assets() -> tuple[AssetInput, ...]:
    return (
        AssetInput(
            asset_class_id="a",
            symbol="A",
            currency="CNY",
            current_value_cny=Decimal("60"),
            target_weight=Decimal("0.5"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("100"),
            max_sell_quantity=Decimal("0"),
        ),
        AssetInput(
            asset_class_id="b",
            symbol="B",
            currency="CNY",
            current_value_cny=Decimal("40"),
            target_weight=Decimal("0.5"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("100"),
            max_sell_quantity=Decimal("0"),
        ),
    )


def test_search_exhaustion_certifies_a_large_integrality_gap() -> None:
    plan = optimize_discrete(
        _large_lot_assets(),
        CashInput(Decimal("100"), Decimal("0"), Decimal("7")),
        allow_sell=False,
        allow_fx=False,
    )

    assert plan.candidate.lot_counts == (0, 0)
    assert plan.candidate.max_drift == Decimal("0.1")
    assert plan.best_open_lower_bound == plan.candidate.max_drift
    assert plan.optimality_gap == OPTIMIZATION_EPSILON
    assert plan.explored_nodes > 1


def test_node_budget_raises_typed_uncertified_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(optimizer, "NODE_BUDGET", 1)
    result = None

    with pytest.raises(OptimizationFailure) as raised:
        result = optimize_discrete(
            _large_lot_assets(),
            CashInput(Decimal("100"), Decimal("0"), Decimal("7")),
            allow_sell=False,
            allow_fx=False,
        )

    assert result is None
    assert raised.value.code == "REBALANCE_OPTIMIZATION_UNCERTIFIED"
    assert raised.value.explored_nodes == 1
    assert raised.value.gap > 0
    assert not hasattr(raised.value, "candidate")


def test_seed_work_is_linear_before_node_budget_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_count = 16
    assets = tuple(
        AssetInput(
            asset_class_id=f"a{index:02d}",
            symbol=f"A{index:02d}",
            currency="CNY",
            current_value_cny=Decimal("0"),
            target_weight=Decimal("0.0625"),
            unit_price_cny=Decimal("1"),
            lot_size=Decimal("1"),
            max_sell_quantity=Decimal("0"),
        )
        for index in range(asset_count)
    )
    original_candidate_from_lots = optimizer._candidate_from_lots
    evaluated_candidates = 0
    maximum_linear_seeds = 2 + 2 * asset_count

    def counted_candidate_from_lots(
        candidate_assets: tuple[AssetInput, ...],
        candidate_cash: CashInput,
        lot_counts: tuple[int, ...],
        *,
        allow_fx: bool,
    ) -> CandidatePlan | None:
        nonlocal evaluated_candidates
        evaluated_candidates += 1
        if evaluated_candidates > maximum_linear_seeds:
            pytest.fail("seed evaluation exceeded the deterministic linear bound")
        return original_candidate_from_lots(
            candidate_assets,
            candidate_cash,
            lot_counts,
            allow_fx=allow_fx,
        )

    monkeypatch.setattr(optimizer, "_candidate_from_lots", counted_candidate_from_lots)
    monkeypatch.setattr(optimizer, "NODE_BUDGET", 1)

    with pytest.raises(OptimizationFailure) as raised:
        optimize_discrete(
            assets,
            CashInput(Decimal("8"), Decimal("0"), Decimal("7")),
            allow_sell=False,
            allow_fx=False,
        )

    assert evaluated_candidates <= maximum_linear_seeds
    assert raised.value.code == "REBALANCE_OPTIMIZATION_UNCERTIFIED"
    assert raised.value.explored_nodes == 1
    assert raised.value.gap > 0


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
