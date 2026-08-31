from dataclasses import FrozenInstanceError
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, localcontext

import pytest
from app.domain.rebalance import (
    AssetInput,
    CashInput,
    RebalanceOptions,
    RebalanceResult,
    rebalance,
)
from app.domain.rebalance_optimizer import OPTIMIZATION_EPSILON


def _asset(
    asset_class_id: str,
    symbol: str,
    currency: str,
    current_value_cny: str,
    target_weight: str,
    unit_price_cny: str,
    lot_size: str = "1",
    max_sell_quantity: str | None = None,
) -> AssetInput:
    return AssetInput(
        asset_class_id=asset_class_id,
        symbol=symbol,
        currency=currency,  # type: ignore[arg-type]
        current_value_cny=Decimal(current_value_cny),
        target_weight=Decimal(target_weight),
        unit_price_cny=Decimal(unit_price_cny),
        lot_size=Decimal(lot_size),
        max_sell_quantity=(
            Decimal(current_value_cny) / Decimal(unit_price_cny)
            if max_sell_quantity is None
            else Decimal(max_sell_quantity)
        ),
    )


GOLD_STARVATION_ASSETS = (
    AssetInput(
        "sp500",
        "VOO",
        "USD",
        Decimal("31300"),
        Decimal("0.30"),
        Decimal("4869"),
        Decimal("0.01"),
        Decimal("6.43"),
    ),
    AssetInput(
        "nasdaq",
        "QQQ",
        "USD",
        Decimal("20500"),
        Decimal("0.20"),
        Decimal("3575"),
        Decimal("0.01"),
        Decimal("5.73"),
    ),
    AssetInput(
        "dividend",
        "159209",
        "CNY",
        Decimal("20200"),
        Decimal("0.20"),
        Decimal("1.145"),
        Decimal("100"),
        Decimal("17600"),
    ),
    AssetInput(
        "quality",
        "563020",
        "CNY",
        Decimal("19300"),
        Decimal("0.20"),
        Decimal("1.184"),
        Decimal("100"),
        Decimal("16300"),
    ),
    AssetInput(
        "gold",
        "518880",
        "CNY",
        Decimal("8700"),
        Decimal("0.10"),
        Decimal("20"),
        Decimal("100"),
        Decimal("400"),
    ),
)
GOLD_STARVATION_CASH = CashInput(Decimal("10000"), Decimal("1500"), Decimal("7.2"))


def test_minimax_contribution_does_not_starve_underweight_gold() -> None:
    result = rebalance(
        GOLD_STARVATION_ASSETS,
        GOLD_STARVATION_CASH,
        RebalanceOptions(Decimal("0.04"), True, True),
    )

    gold = next(
        weight for weight in result.projected_weights if weight.asset_class_id == "gold"
    )
    assert any(
        trade.symbol == "518880" and trade.action == "buy" for trade in result.trades
    )
    assert gold.after > gold.before
    assert result.max_drift_after < Decimal("0.01")


def test_buy_only_within_tolerance_never_uses_sell_phase() -> None:
    assets = (
        _asset("a", "AAA", "CNY", "51", "0.5", "1"),
        _asset("b", "BBB", "CNY", "49", "0.5", "1"),
    )

    result = rebalance(
        assets,
        CashInput(Decimal("2"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), True, True),
    )

    assert result.buy_only_max_drift <= Decimal("0.02")
    assert not result.sell_phase_used
    assert all(trade.action == "buy" for trade in result.trades)


def test_sell_phase_runs_only_after_buy_only_plan_remains_outside_tolerance() -> None:
    assets = (
        _asset("over", "OVER", "CNY", "80", "0.5", "10", max_sell_quantity="8"),
        _asset("under", "UNDER", "CNY", "20", "0.5", "10", max_sell_quantity="2"),
    )

    result = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.05"), True, False),
    )

    assert result.buy_only_max_drift > Decimal("0.05")
    assert result.sell_phase_used
    assert any(trade.action == "sell" for trade in result.trades)
    assert result.max_drift_after <= Decimal("0.05")


def test_one_lot_is_the_only_minimum_trade() -> None:
    assets = (
        _asset("under", "UNDER", "CNY", "0", "0.5", "0.01", "100", "0"),
        _asset("other", "OTHER", "CNY", "1", "0.5", "1", "1", "1"),
    )

    result = rebalance(
        assets,
        CashInput(Decimal("1"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), False, False),
    )

    trade = next(trade for trade in result.trades if trade.symbol == "UNDER")
    assert trade.action == "buy"
    assert trade.quantity == Decimal("100")
    assert trade.amount_cny == Decimal("1")


def test_sub_one_basis_point_improvement_does_not_create_an_order() -> None:
    assets = (
        _asset("a", "AAA", "CNY", "5000.5", "0.5", "0.1", "1", "0"),
        _asset("b", "BBB", "CNY", "4999.5", "0.5", "0.1", "1", "0"),
    )

    result = rebalance(
        assets,
        CashInput(Decimal("0.1"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), False, False),
    )

    assert result.trades == ()
    assert result.remaining_cny == Decimal("0.1")


def test_buy_order_reason_describes_optimizer_intent() -> None:
    result = rebalance(
        (
            _asset("a", "AAA", "CNY", "40", "0.5", "10"),
            _asset("b", "BBB", "CNY", "60", "0.5", "10"),
        ),
        CashInput(Decimal("20"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), False, False),
    )

    assert len(result.trades) == 1
    assert result.trades[0].reason_code == "REDUCE_MAX_DRIFT"


def test_sell_order_reason_describes_phase_two_reallocation() -> None:
    result = rebalance(
        (
            _asset("over", "OVER", "CNY", "80", "0.5", "10", max_sell_quantity="8"),
            _asset("under", "UNDER", "CNY", "20", "0.5", "10", max_sell_quantity="2"),
        ),
        CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.05"), True, False),
    )

    sell = next(trade for trade in result.trades if trade.action == "sell")
    assert sell.reason_code == "REALLOCATE_OUTSIDE_TOLERANCE"


def test_cash_feasible_sell_still_describes_phase_two_reallocation() -> None:
    result = rebalance(
        (
            _asset("over", "OVER", "CNY", "90", "0.5", "10", max_sell_quantity="9"),
            _asset("under", "UNDER", "CNY", "10", "0.5", "10", max_sell_quantity="1"),
        ),
        CashInput(Decimal("70"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.01"), True, False),
    )

    sell = next(trade for trade in result.trades if trade.action == "sell")
    assert result.sell_phase_used
    assert sell.reason_code == "REALLOCATE_OUTSIDE_TOLERANCE"


def test_trade_reason_describes_max_drift_reduction_for_the_certified_plan() -> None:
    result = rebalance(
        (
            _asset("a", "A", "CNY", "40", "0.4", "20"),
            _asset("b", "B", "CNY", "20", "0.3", "20"),
            _asset("c", "C", "CNY", "60", "0.2", "20"),
            _asset("d", "D", "CNY", "0", "0.1", "20", max_sell_quantity="0"),
        ),
        CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), True, False),
    )

    buy = next(trade for trade in result.trades if trade.symbol == "D")
    assert buy.action == "buy"
    assert buy.reason_code == "REDUCE_MAX_DRIFT"


@pytest.mark.parametrize(
    ("assets", "cash", "direction", "amount", "compatibility_amount"),
    [
        (
            (
                _asset("cny", "CNY", "CNY", "100", "0.5", "10", max_sell_quantity="0"),
                _asset("usd", "USD", "USD", "0", "0.5", "10", max_sell_quantity="0"),
            ),
            CashInput(Decimal("0"), Decimal("10"), Decimal("10")),
            "none",
            Decimal("0"),
            Decimal("0"),
        ),
        (
            (
                _asset("cny", "CNY", "CNY", "100", "0.5", "10", max_sell_quantity="0"),
                _asset("usd", "USD", "USD", "0", "0.5", "10", max_sell_quantity="0"),
            ),
            CashInput(Decimal("100"), Decimal("0"), Decimal("10")),
            "cny_to_usd",
            Decimal("100"),
            Decimal("100"),
        ),
        (
            (
                _asset("cny", "CNY", "CNY", "0", "0.5", "10", max_sell_quantity="0"),
                _asset("usd", "USD", "USD", "100", "0.5", "10", max_sell_quantity="0"),
            ),
            CashInput(Decimal("0"), Decimal("10"), Decimal("10")),
            "usd_to_cny",
            Decimal("100"),
            Decimal("0"),
        ),
    ],
)
def test_net_fx_metadata_and_compatibility_alias(
    assets: tuple[AssetInput, ...],
    cash: CashInput,
    direction: str,
    amount: Decimal,
    compatibility_amount: Decimal,
) -> None:
    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0"), False, True),
    )

    assert result.net_fx_direction == direction
    assert result.net_fx_amount_cny == amount
    assert result.fx_required_cny == compatibility_amount


def test_multiple_usd_orders_exactly_conserve_reported_currency() -> None:
    cash = CashInput(Decimal("0"), Decimal("1"), Decimal("3"))
    assets = (
        _asset("a", "A", "CNY", "2", "0.5", "1", max_sell_quantity="0"),
        _asset("b", "B", "USD", "0", "0.25", "1", max_sell_quantity="0"),
        _asset("c", "C", "USD", "0", "0.25", "1", max_sell_quantity="0"),
    )

    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0"), False, False),
    )

    usd_buys = tuple(
        trade
        for trade in result.trades
        if trade.symbol in {"B", "C"} and trade.action == "buy"
    )
    assert len(usd_buys) == 2
    with localcontext() as context:
        context.prec = 100
        context.rounding = ROUND_DOWN
        assert all(
            trade.amount_trade_currency == trade.amount_cny / cash.usd_cny
            for trade in usd_buys
        )
    with localcontext() as context:
        context.prec = 250
        assert result.remaining_usd == cash.usd - sum(
            (trade.amount_trade_currency for trade in usd_buys), Decimal("0")
        )


def test_fully_spent_repeating_usd_orders_preserve_canonical_amounts() -> None:
    cash = CashInput(Decimal("0"), Decimal("3"), Decimal("3"))
    assets = (
        _asset("a", "A", "CNY", "1", "0.1", "1", max_sell_quantity="0"),
        _asset("b", "B", "USD", "0", "0.2", "2", max_sell_quantity="0"),
        _asset("c", "C", "USD", "0", "0.5", "5", max_sell_quantity="0"),
        _asset("d", "D", "USD", "0", "0.2", "2", max_sell_quantity="0"),
    )

    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0"), False, False),
    )

    usd_buys = tuple(trade for trade in result.trades if trade.symbol != "A")
    assert len(usd_buys) == 3
    with localcontext() as context:
        context.prec = 100
        context.rounding = ROUND_DOWN
        assert all(
            trade.amount_trade_currency == trade.amount_cny / cash.usd_cny
            for trade in usd_buys
        )
    with localcontext() as context:
        context.prec = 250
        assert result.remaining_usd >= 0
        assert result.remaining_usd == cash.usd - sum(
            (trade.amount_trade_currency for trade in usd_buys), Decimal("0")
        )


@pytest.mark.parametrize("cash_usd", ("1E+120", "1E+150", "1E+200"))
def test_large_positive_exponent_cash_preserves_a_small_usd_order(
    cash_usd: str,
) -> None:
    cash = CashInput(Decimal("0"), Decimal(cash_usd), Decimal("3"))
    assets = (
        _asset("a", "A", "CNY", "1", "0.5", "1", max_sell_quantity="0"),
        _asset("b", "B", "USD", "0", "0.5", "1", max_sell_quantity="0"),
    )

    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0"), False, False),
    )

    usd_buy = next(trade for trade in result.trades if trade.symbol == "B")
    assert usd_buy.amount_trade_currency > 0
    with localcontext() as context:
        context.prec = 600
        assert result.remaining_usd == cash.usd - usd_buy.amount_trade_currency


def test_large_cash_and_fx_operands_preserve_exact_trade_currency() -> None:
    usd_cash = Decimal("9" * 100)
    usd_cny = Decimal("7" * 100)
    cash = CashInput(Decimal("0"), usd_cash, usd_cny)
    assets = (
        AssetInput(
            "a",
            "A",
            "CNY",
            usd_cny,
            Decimal("0.5"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
        AssetInput(
            "b",
            "B",
            "USD",
            Decimal("0"),
            Decimal("0.5"),
            usd_cny,
            Decimal("1"),
            Decimal("0"),
        ),
    )

    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0"), False, False),
    )

    usd_buy = next(trade for trade in result.trades if trade.symbol == "B")
    assert usd_buy.amount_trade_currency == Decimal("1")
    with localcontext() as context:
        context.prec = 250
        assert result.remaining_usd == usd_cash - Decimal("1")


def test_result_metadata_and_weights_come_from_the_certified_candidate() -> None:
    result = rebalance(
        (
            _asset("b", "BBB", "CNY", "60", "0.5", "10"),
            _asset("a", "AAA", "CNY", "40", "0.5", "10"),
        ),
        CashInput(Decimal("20"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), False, False),
    )

    assert result.feasible
    assert result.max_drift_before == Decimal("0.1")
    assert result.max_drift_after == 0
    assert result.buy_only_max_drift == result.max_drift_after
    assert result.optimization_precision == OPTIMIZATION_EPSILON
    assert result.optimization_certified
    assert result.optimality_gap == 0
    assert not result.sell_phase_used
    assert [weight.asset_class_id for weight in result.projected_weights] == ["a", "b"]
    assert result.projected_weights[0].before == Decimal("0.4")
    assert result.projected_weights[0].after == Decimal("0.5")


def test_zero_portfolio_returns_a_stable_certified_best_effort() -> None:
    result = rebalance(
        (
            _asset("a", "AAA", "CNY", "0", "0.5", "10", max_sell_quantity="0"),
            _asset("b", "BBB", "USD", "0", "0.5", "10", max_sell_quantity="0"),
        ),
        CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), True, True),
    )

    assert not result.feasible
    assert result.max_drift_before == Decimal("0.5")
    assert result.max_drift_after == Decimal("0.5")
    assert result.trades == ()
    assert result.net_fx_direction == "none"


def test_public_types_are_immutable_and_rebalance_does_not_mutate_inputs() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "40", "0.5", "10"),
        _asset("b", "BBB", "CNY", "60", "0.5", "10"),
    ]
    original = list(assets)
    cash = CashInput(Decimal("20"), Decimal("0"), Decimal("7.2"))
    options = RebalanceOptions(Decimal("0.01"), False, False)

    result = rebalance(assets, cash, options)

    assert assets == original
    with pytest.raises(FrozenInstanceError):
        assets[0].symbol = "CHANGED"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.remaining_cny = Decimal("0")  # type: ignore[misc]


def test_result_is_independent_of_ambient_decimal_precision() -> None:
    assets = (
        _asset("a", "AAA", "CNY", "123456789.123456", "0.5", "0.001", "100", "0"),
        _asset("b", "BBB", "USD", "123456788.123456", "0.5", "98765.4321", "0.01", "0"),
    )
    cash = CashInput(Decimal("999.999999"), Decimal("1.234567"), Decimal("7.123456"))
    options = RebalanceOptions(Decimal("0.02"), False, True)
    expected = rebalance(assets, cash, options)

    with localcontext() as context:
        context.prec = 4
        actual = rebalance(assets, cash, options)

    assert actual == expected


def test_result_is_independent_of_ambient_decimal_rounding() -> None:
    assets = (
        _asset("a", "A", "CNY", "2", "0.5", "1", max_sell_quantity="0"),
        _asset("b", "B", "USD", "0", "0.25", "1", max_sell_quantity="0"),
        _asset("c", "C", "USD", "0", "0.25", "1", max_sell_quantity="0"),
    )
    cash = CashInput(Decimal("0"), Decimal("1"), Decimal("3"))
    options = RebalanceOptions(Decimal("0"), False, False)

    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        expected = rebalance(assets, cash, options)
    with localcontext() as context:
        context.rounding = ROUND_DOWN
        actual = rebalance(assets, cash, options)

    assert actual == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_value_cny", Decimal("-1")),
        ("current_value_cny", Decimal("NaN")),
        ("target_weight", Decimal("-0.1")),
        ("target_weight", Decimal("Infinity")),
        ("unit_price_cny", Decimal("0")),
        ("unit_price_cny", Decimal("-1")),
        ("lot_size", Decimal("0")),
        ("lot_size", Decimal("NaN")),
        ("max_sell_quantity", Decimal("-1")),
        ("max_sell_quantity", Decimal("Infinity")),
    ],
)
def test_asset_input_rejects_invalid_decimals(field: str, value: Decimal) -> None:
    values = {
        "asset_class_id": "a",
        "symbol": "AAA",
        "currency": "CNY",
        "current_value_cny": Decimal("100"),
        "target_weight": Decimal("1"),
        "unit_price_cny": Decimal("10"),
        "lot_size": Decimal("1"),
        "max_sell_quantity": Decimal("10"),
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        AssetInput(**values)  # type: ignore[arg-type]


def test_asset_input_accepts_fractional_preferred_inventory() -> None:
    asset = _asset(
        "a",
        "AAA",
        "CNY",
        "100",
        "1",
        "10",
        lot_size="2",
        max_sell_quantity="3.5",
    )

    assert asset.max_sell_quantity == Decimal("3.5")


def test_rebalance_options_and_result_expose_the_minimax_contract() -> None:
    assert set(RebalanceOptions.__dataclass_fields__) == {
        "tolerance",
        "allow_sell",
        "allow_fx",
    }
    assert set(RebalanceResult.__dataclass_fields__) == {
        "feasible",
        "max_drift_before",
        "max_drift_after",
        "buy_only_max_drift",
        "optimization_precision",
        "optimization_certified",
        "optimality_gap",
        "sell_phase_used",
        "net_fx_direction",
        "net_fx_amount_cny",
        "fx_required_cny",
        "remaining_cny",
        "remaining_usd",
        "projected_weights",
        "trades",
    }


@pytest.mark.parametrize(
    ("constructor", "match"),
    [
        (lambda: CashInput(Decimal("-1"), Decimal("0"), Decimal("7.2")), "cny"),
        (lambda: CashInput(Decimal("0"), Decimal("NaN"), Decimal("7.2")), "usd"),
        (lambda: CashInput(Decimal("0"), Decimal("0"), Decimal("0")), "usd_cny"),
        (lambda: RebalanceOptions(Decimal("-0.1"), False, False), "tolerance"),
        (lambda: RebalanceOptions(Decimal("Infinity"), False, False), "tolerance"),
    ],
)
def test_cash_and_options_reject_invalid_decimals(constructor, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        constructor()


def test_rebalance_rejects_duplicate_classes_symbols_and_invalid_weights() -> None:
    valid_cash = CashInput(Decimal("0"), Decimal("0"), Decimal("7.2"))
    options = RebalanceOptions(Decimal("0.02"), False, False)

    with pytest.raises(ValueError, match="duplicate asset_class_id"):
        rebalance(
            (
                _asset("a", "AAA", "CNY", "1", "0.5", "1"),
                _asset("a", "BBB", "CNY", "1", "0.5", "1"),
            ),
            valid_cash,
            options,
        )
    with pytest.raises(ValueError, match="duplicate symbol"):
        rebalance(
            (
                _asset("a", "AAA", "CNY", "1", "0.5", "1"),
                _asset("b", "AAA", "USD", "1", "0.5", "1"),
            ),
            valid_cash,
            options,
        )
    with pytest.raises(ValueError, match="target weights must sum to 1"):
        rebalance(
            (_asset("a", "AAA", "CNY", "1", "0.9", "1"),),
            valid_cash,
            options,
        )
