from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from app.domain.rebalance import AssetInput, CashInput, RebalanceOptions, rebalance
from app.schemas.rebalance import RebalancePreviewRequest, RebalanceResultResponse


def _asset(
    asset_class_id: str,
    symbol: str,
    currency: str,
    current_value_cny: str,
    target_weight: str,
    unit_price_cny: str,
    lot_size: str = "1",
) -> AssetInput:
    return AssetInput(
        asset_class_id=asset_class_id,
        symbol=symbol,
        currency=currency,
        current_value_cny=Decimal(current_value_cny),
        target_weight=Decimal(target_weight),
        unit_price_cny=Decimal(unit_price_cny),
        lot_size=Decimal(lot_size),
    )


def test_cash_is_used_before_any_sell() -> None:
    assets = [
        _asset("low-vol", "510880", "CNY", "180000", "0.20", "3", "100"),
        _asset("quality", "159758", "CNY", "210000", "0.20", "1.2", "100"),
        _asset("sp500", "SPY", "USD", "310000", "0.30", "4687.20"),
        _asset("nasdaq", "QQQ", "USD", "200000", "0.20", "3950.64"),
        _asset("gold", "518880", "CNY", "100000", "0.10", "5.8", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(cny=Decimal("20000"), usd=Decimal("0"), usd_cny=Decimal("7.20")),
        RebalanceOptions(
            tolerance=Decimal("0.02"),
            minimum_trade_cny=Decimal("500"),
            allow_sell=True,
            allow_fx=True,
        ),
    )

    assert result.trades
    assert all(item.action == "buy" for item in result.trades)
    assert sum(
        (item.amount_cny for item in result.trades), Decimal("0")
    ) <= Decimal("20000")


def test_cash_buys_are_ordered_by_largest_deficit_then_symbol() -> None:
    assets = [
        _asset("a", "ZZZ", "CNY", "100", "0.4", "10"),
        _asset("b", "BBB", "CNY", "200", "0.3", "10"),
        _asset("c", "AAA", "CNY", "200", "0.3", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("300"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.50"), Decimal("0"), False, False),
    )

    assert [trade.symbol for trade in result.trades] == ["ZZZ", "AAA", "BBB"]
    assert all(
        trade.reason_code == "UNDERWEIGHT_WITH_CASH" for trade in result.trades
    )


def test_cash_buy_order_is_global_across_currencies() -> None:
    assets = [
        _asset("cny", "ZZZ", "CNY", "100", "0.5", "10"),
        _asset("usd", "AAA", "USD", "100", "0.5", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("100"), Decimal("300"), Decimal("1")),
        RebalanceOptions(Decimal("0.50"), Decimal("0"), False, False),
    )

    assert [trade.symbol for trade in result.trades] == ["AAA", "ZZZ"]


def test_fx_converts_only_executable_usd_deficit() -> None:
    assets = [
        _asset("cny", "CNY-FUND", "CNY", "600", "0.4", "10"),
        _asset("usd", "USD-FUND", "USD", "400", "0.6", "72"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("200"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.01"), Decimal("0"), False, True),
    )

    assert result.fx_required_cny == Decimal("144")
    assert result.remaining_cny == Decimal("56")
    assert result.remaining_usd == Decimal("0")
    assert result.trades[0].symbol == "USD-FUND"
    assert result.trades[0].quantity == Decimal("2")
    assert result.trades[0].amount_trade_currency == Decimal("20")
    assert result.trades[0].reason_code == "UNDERWEIGHT_AFTER_FX"


def test_full_target_asset_consumes_same_currency_and_convertible_cash() -> None:
    assets = [
        _asset("all", "ALL", "USD", "100", "1", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("25"), Decimal("25"), Decimal("1")),
        RebalanceOptions(Decimal("0"), Decimal("0"), False, True),
    )

    assert [(trade.symbol, trade.action, trade.quantity) for trade in result.trades] == [
        ("ALL", "buy", Decimal("4"))
    ]
    assert result.trades[0].reason_code == "UNDERWEIGHT_WITH_CASH_AND_FX"
    assert result.remaining_cny == Decimal("5")
    assert result.remaining_usd == Decimal("5")


def test_mixed_full_and_zero_targets_rebalance_without_division_by_zero() -> None:
    assets = [
        _asset("all", "ALL", "USD", "0", "1", "10"),
        _asset("zero", "ZERO", "CNY", "100", "0", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("100"), Decimal("0"), Decimal("1")),
        RebalanceOptions(Decimal("0"), Decimal("0"), True, True),
    )

    assert [(trade.symbol, trade.action, trade.quantity) for trade in result.trades] == [
        ("ALL", "buy", Decimal("20")),
        ("ZERO", "sell", Decimal("10")),
    ]
    assert result.feasible is True
    assert [weight.after for weight in result.projected_weights] == [
        Decimal("1"),
        Decimal("0"),
    ]


def test_reviewer_scenario_does_not_buy_currently_overweight_usd_class() -> None:
    assets = [
        _asset("usd", "USD-FUND", "USD", "130", "0.5", "20"),
        _asset("cny", "CNY-FUND", "CNY", "70", "0.5", "50"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("100"), Decimal("0"), Decimal("1")),
        RebalanceOptions(Decimal("0.02"), Decimal("0"), False, True),
    )

    assert [(trade.symbol, trade.action, trade.quantity) for trade in result.trades] == [
        ("CNY-FUND", "buy", Decimal("1"))
    ]
    assert result.max_drift_after == Decimal("0.02")


def test_sell_gate_uses_current_invested_upper_bound_after_filtered_buy() -> None:
    assets = [
        _asset("over", "OVER", "CNY", "600", "0.5", "100"),
        _asset("under", "UNDER", "CNY", "400", "0.5", "200"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("100"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.05"), Decimal("0"), True, False),
    )

    assert [(trade.symbol, trade.action, trade.quantity) for trade in result.trades] == [
        ("OVER", "sell", Decimal("1"))
    ]
    assert result.max_drift_after < result.max_drift_before


def test_merged_existing_usd_and_fx_buy_has_combined_reason() -> None:
    assets = [
        _asset("cny", "CNY-FUND", "CNY", "700", "0.4", "100"),
        _asset("usd", "USD-FUND", "USD", "300", "0.6", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("300"), Decimal("10"), Decimal("10")),
        RebalanceOptions(Decimal("0.02"), Decimal("0"), False, True),
    )

    assert len(result.trades) == 1
    assert result.trades[0].symbol == "USD-FUND"
    assert result.trades[0].quantity == Decimal("4")
    assert result.trades[0].reason_code == "UNDERWEIGHT_WITH_CASH_AND_FX"


def test_sell_proceeds_are_reused_before_fx_and_restore_target() -> None:
    assets = [
        _asset("cny", "CNY-FUND", "CNY", "800", "0.5", "100"),
        _asset("usd", "USD-FUND", "USD", "200", "0.5", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("5")),
        RebalanceOptions(Decimal("0.05"), Decimal("0"), True, True),
    )

    assert [(trade.symbol, trade.action, trade.quantity) for trade in result.trades] == [
        ("CNY-FUND", "sell", Decimal("3")),
        ("USD-FUND", "buy", Decimal("3")),
    ]
    assert result.trades[0].reason_code == "OVERWEIGHT_AFTER_CASH"
    assert result.fx_required_cny == Decimal("300")
    assert result.feasible is True
    assert result.max_drift_after == Decimal("0.0")


def test_usd_sale_proceeds_fund_usd_buys_without_fx() -> None:
    assets = [
        _asset("cny", "CNY-FUND", "CNY", "200", "0.2", "100"),
        _asset("usd-over", "USD-OVER", "USD", "700", "0.4", "100"),
        _asset("usd-under", "USD-UNDER", "USD", "100", "0.4", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("5")),
        RebalanceOptions(Decimal("0.05"), Decimal("0"), True, True),
    )

    assert [(trade.symbol, trade.action) for trade in result.trades] == [
        ("USD-OVER", "sell"),
        ("USD-UNDER", "buy"),
    ]
    assert result.fx_required_cny == 0
    assert result.remaining_usd == 0
    assert result.feasible is True


def test_repeated_buys_are_merged_and_sales_do_not_cross_below_target() -> None:
    assets = [
        _asset("under", "UNDER", "CNY", "200", "0.5", "100"),
        _asset("over", "OVER", "CNY", "800", "0.5", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("100"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.05"), Decimal("0"), True, False),
    )

    under_buys = [trade for trade in result.trades if trade.symbol == "UNDER"]
    over_sell = next(trade for trade in result.trades if trade.symbol == "OVER")
    assert len(under_buys) == 1
    assert under_buys[0].quantity == Decimal("3")
    assert (
        under_buys[0].reason_code
        == "UNDERWEIGHT_WITH_CASH_AND_SELL_PROCEEDS"
    )
    assert over_sell.quantity == Decimal("2")
    projected_over = next(
        weight for weight in result.projected_weights if weight.asset_class_id == "over"
    )
    assert projected_over.after > projected_over.target


def test_merged_buy_preserves_cash_fx_and_sell_proceeds_components() -> None:
    assets = [
        _asset("cny", "CNY-FUND", "CNY", "200", "0.2", "100"),
        _asset("usd-under", "USD-UNDER", "USD", "100", "0.4", "100"),
        _asset("usd-over", "USD-OVER", "USD", "700", "0.4", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("100"), Decimal("10"), Decimal("10")),
        RebalanceOptions(Decimal("0.05"), Decimal("0"), True, True),
    )

    under_buy = next(
        trade for trade in result.trades if trade.symbol == "USD-UNDER"
    )
    assert under_buy.reason_code == (
        "UNDERWEIGHT_WITH_CASH_SELL_PROCEEDS_AND_FX"
    )


def test_reviewer_round_trip_is_removed_from_executable_trades() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "0", "0.5", "200"),
        _asset("b", "BBB", "CNY", "50", "0.5", "50"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("150"), Decimal("0"), Decimal("1")),
        RebalanceOptions(Decimal("0.02"), Decimal("0"), True, False),
    )

    assert result.trades == ()
    assert result.remaining_cny == Decimal("150")
    assert [weight.after for weight in result.projected_weights] == [
        Decimal("0"),
        Decimal("1"),
    ]


def test_cash_that_restores_tolerance_prevents_sells() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "600", "0.5", "10"),
        _asset("b", "BBB", "CNY", "400", "0.5", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("200"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.01"), Decimal("0"), True, True),
    )

    assert [
        (trade.symbol, trade.action, trade.amount_cny) for trade in result.trades
    ] == [("BBB", "buy", Decimal("200"))]
    assert result.feasible is True


def test_before_metrics_use_original_holdings_with_temporary_cash() -> None:
    assets = [
        _asset("over", "OVER", "CNY", "600", "0.5", "10"),
        _asset("under", "UNDER", "CNY", "400", "0.5", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("200"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), Decimal("0"), True, True),
    )

    assert [weight.before for weight in result.projected_weights] == [
        Decimal("0.6"),
        Decimal("0.4"),
    ]
    assert result.max_drift_before == Decimal("0.1")
    assert [weight.after for weight in result.projected_weights] == [
        Decimal("0.5"),
        Decimal("0.5"),
    ]


def test_minimum_trade_filters_lots_without_spending_cash() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "0", "0.5", "40"),
        _asset("b", "BBB", "CNY", "100", "0.5", "100"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("20"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.01"), Decimal("50"), False, False),
    )

    assert result.trades == ()
    assert result.remaining_cny == Decimal("20")


def test_final_weights_exclude_uninvested_temporary_cash() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "100", "0.5", "60"),
        _asset("b", "BBB", "CNY", "100", "0.5", "60"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("50"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), Decimal("0"), False, False),
    )

    assert result.trades == ()
    assert [weight.after for weight in result.projected_weights] == [
        Decimal("0.5"),
        Decimal("0.5"),
    ]


def test_projected_weights_are_sorted_by_asset_class_id() -> None:
    assets = [
        _asset("z-class", "AAA", "CNY", "40", "0.4", "10"),
        _asset("a-class", "ZZZ", "CNY", "60", "0.6", "10"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("1")),
        RebalanceOptions(Decimal("0.02"), Decimal("0"), False, False),
    )

    assert [weight.asset_class_id for weight in result.projected_weights] == [
        "a-class",
        "z-class",
    ]


def test_zero_portfolio_returns_a_stable_infeasible_result() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "0", "0.5", "10"),
        _asset("b", "BBB", "USD", "0", "0.5", "72"),
    ]

    result = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), Decimal("500"), True, True),
    )

    assert result.trades == ()
    assert result.remaining_cny == 0
    assert result.remaining_usd == 0
    assert result.max_drift_before == Decimal("0.5")
    assert result.max_drift_after == Decimal("0.5")
    assert result.feasible is False


def test_types_are_immutable_and_rebalance_does_not_mutate_inputs() -> None:
    assets = [
        _asset("a", "AAA", "CNY", "40", "0.5", "10"),
        _asset("b", "BBB", "CNY", "60", "0.5", "10"),
    ]
    original = list(assets)
    cash = CashInput(Decimal("20"), Decimal("0"), Decimal("7.2"))
    options = RebalanceOptions(Decimal("0.01"), Decimal("0"), False, False)

    rebalance(assets, cash, options)

    assert assets == original
    with pytest.raises(FrozenInstanceError):
        assets[0].symbol = "CHANGED"  # type: ignore[misc]


def test_result_is_independent_of_ambient_decimal_precision() -> None:
    assets = [
        _asset(
            "a",
            "AAA",
            "CNY",
            "1234567890123456.123456789012",
            "0.5",
            "0.000000000123",
            "100",
        ),
        _asset(
            "b",
            "BBB",
            "USD",
            "1234567890123455.123456789012",
            "0.5",
            "987654321.123456789012",
        ),
    ]
    cash = CashInput(
        Decimal("999999999999.999999999999"),
        Decimal("1.234567890123"),
        Decimal("7.123456789012"),
    )
    options = RebalanceOptions(Decimal("0.02"), Decimal("0.01"), True, True)
    expected = rebalance(assets, cash, options)

    with localcontext() as context:
        context.prec = 4
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
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        AssetInput(**values)


@pytest.mark.parametrize(
    ("constructor", "match"),
    [
        (lambda: CashInput(Decimal("-1"), Decimal("0"), Decimal("7.2")), "cny"),
        (lambda: CashInput(Decimal("0"), Decimal("NaN"), Decimal("7.2")), "usd"),
        (lambda: CashInput(Decimal("0"), Decimal("0"), Decimal("0")), "usd_cny"),
        (
            lambda: RebalanceOptions(
                Decimal("-0.1"), Decimal("0"), False, False
            ),
            "tolerance",
        ),
        (
            lambda: RebalanceOptions(
                Decimal("0.1"), Decimal("Infinity"), False, False
            ),
            "minimum_trade_cny",
        ),
    ],
)
def test_cash_and_options_reject_invalid_decimals(constructor, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        constructor()


def test_rebalance_rejects_duplicate_classes_symbols_and_invalid_weights() -> None:
    valid_cash = CashInput(Decimal("0"), Decimal("0"), Decimal("7.2"))
    options = RebalanceOptions(Decimal("0.02"), Decimal("0"), False, False)

    with pytest.raises(ValueError, match="duplicate asset_class_id"):
        rebalance(
            [
                _asset("a", "AAA", "CNY", "1", "0.5", "1"),
                _asset("a", "BBB", "CNY", "1", "0.5", "1"),
            ],
            valid_cash,
            options,
        )
    with pytest.raises(ValueError, match="duplicate symbol"):
        rebalance(
            [
                _asset("a", "AAA", "CNY", "1", "0.5", "1"),
                _asset("b", "AAA", "USD", "1", "0.5", "1"),
            ],
            valid_cash,
            options,
        )
    with pytest.raises(ValueError, match="target weights must sum to 1"):
        rebalance(
            [_asset("a", "AAA", "CNY", "1", "0.9", "1")],
            valid_cash,
            options,
        )


def test_rebalance_schema_serializes_domain_result_as_decimal_strings() -> None:
    result = rebalance(
        [_asset("a", "AAA", "CNY", "100", "1", "10", "3")],
        CashInput(Decimal("20"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0.02"), Decimal("0"), False, False),
    )

    payload = RebalanceResultResponse.model_validate(result).model_dump(mode="json")

    assert payload["remaining_cny"] == "20"
    assert payload["projected_weights"][0] == {
        "asset_class_id": "a",
        "before": "1",
        "after": "1",
        "target": "1",
    }


def test_rebalance_preview_request_is_frozen_normalized_and_validated() -> None:
    request = RebalancePreviewRequest(
        session_token="browser-session-1",
        request_token="preview-request-1",
        available_cny="20000",
        available_usd="0",
        valuation_basis="actual",
        allow_sell=True,
        allow_fx=True,
        tolerance="0.02",
        minimum_trade_cny="500",
    )

    assert request.available_cny == Decimal("20000")
    with pytest.raises(ValidationError):
        request.available_cny = Decimal("1")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RebalancePreviewRequest(
            session_token="browser-session-1",
            request_token="preview-request-2",
            available_cny="NaN",
            available_usd="0",
            valuation_basis="actual",
            allow_sell=False,
            allow_fx=False,
            tolerance="0.02",
            minimum_trade_cny="500",
        )
