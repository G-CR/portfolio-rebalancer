from decimal import Decimal, localcontext

import pytest

from app.domain.analytics import PositionInput, analyze_position
from app.schemas.analytics import PositionAnalysisResponse


def _expected_formulas(value: PositionInput) -> dict[str, Decimal]:
    with localcontext() as context:
        context.prec = 200
        cost_trade_currency = value.quantity * value.cost_price
        market_value_trade_currency = value.quantity * value.current_price
        unrealized_pnl_trade_currency = (
            market_value_trade_currency - cost_trade_currency
        )
        cost_cny = cost_trade_currency * value.current_fx
        market_value_cny = market_value_trade_currency * value.current_fx
        unrealized_pnl = market_value_cny - cost_cny
        return {
            "cost_trade_currency": cost_trade_currency,
            "market_value_trade_currency": market_value_trade_currency,
            "unrealized_pnl_trade_currency": unrealized_pnl_trade_currency,
            "cost_cny": cost_cny,
            "market_value_cny": market_value_cny,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_return": (
                unrealized_pnl / cost_cny if cost_cny else Decimal("0")
            ),
        }


def test_usd_position_uses_native_cost_and_current_fx_reference() -> None:
    value = PositionInput(
        quantity=Decimal("150"),
        cost_price=Decimal("106.666666666667"),
        current_price=Decimal("120"),
        current_fx=Decimal("7.20"),
    )
    result = analyze_position(value)
    expected = _expected_formulas(value)

    assert result.cost_trade_currency == Decimal("16000.00000000005")
    assert result.market_value_trade_currency == Decimal("18000")
    assert result.unrealized_pnl_trade_currency == Decimal("1999.99999999995")
    assert result.cost_cny == expected["cost_cny"]
    assert result.market_value_cny == Decimal("129600.00")
    assert result.unrealized_pnl == expected["unrealized_pnl"]
    assert result.unrealized_return.quantize(
        Decimal("0.000000000001")
    ) == expected["unrealized_return"].quantize(Decimal("0.000000000001"))


def test_zero_quantity_returns_zero_values() -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal("0"),
            cost_price=Decimal("106.666666666667"),
            current_price=Decimal("120"),
            current_fx=Decimal("7.20"),
        )
    )

    assert result.cost_trade_currency == Decimal("0")
    assert result.market_value_trade_currency == Decimal("0")
    assert result.unrealized_pnl_trade_currency == Decimal("0")
    assert result.cost_cny == Decimal("0.000")
    assert result.market_value_cny == Decimal("0.000")
    assert result.unrealized_pnl == Decimal("0.000")
    assert result.unrealized_return == Decimal("0")


def test_zero_cost_price_returns_zero_unrealized_return() -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal("150"),
            cost_price=Decimal("0"),
            current_price=Decimal("120"),
            current_fx=Decimal("7.20"),
        )
    )

    assert result.cost_cny == Decimal("0.00")
    assert result.market_value_cny == Decimal("129600.00")
    assert result.unrealized_pnl == Decimal("129600.00")
    assert result.unrealized_return == Decimal("0")


def test_results_are_identical_under_low_and_default_precision_contexts() -> None:
    value = PositionInput(
        quantity=Decimal("150"),
        cost_price=Decimal("106.666666666667"),
        current_price=Decimal("120"),
        current_fx=Decimal("7.20"),
    )
    default_result = analyze_position(value)

    with localcontext() as context:
        context.prec = 4
        low_precision_result = analyze_position(value)

    assert low_precision_result == default_result


def test_numeric_28_12_boundary_formulas_are_exact() -> None:
    value = PositionInput(
        quantity=Decimal("9999999999999999.999999999999"),
        cost_price=Decimal("9999999999999999.999999999999"),
        current_price=Decimal("8888888888888888.888888888888"),
        current_fx=Decimal("0.100000000001"),
    )

    result = analyze_position(value)
    expected = _expected_formulas(value)

    assert result.cost_trade_currency == expected["cost_trade_currency"]
    assert (
        result.market_value_trade_currency
        == expected["market_value_trade_currency"]
    )
    assert (
        result.unrealized_pnl_trade_currency
        == expected["unrealized_pnl_trade_currency"]
    )
    assert result.cost_cny == expected["cost_cny"]
    assert result.market_value_cny == expected["market_value_cny"]
    assert result.unrealized_pnl == expected["unrealized_pnl"]
    assert result.unrealized_return.quantize(
        Decimal("0.000000000001")
    ) == expected["unrealized_return"].quantize(Decimal("0.000000000001"))

    with localcontext() as context:
        context.prec = 200
        assert result.market_value_cny - result.cost_cny == result.unrealized_pnl


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("quantity", Decimal("-0.000000000001")),
        ("cost_price", Decimal("-0.000000000001")),
        ("current_price", Decimal("-0.000000000001")),
        ("current_fx", Decimal("0")),
        ("current_fx", Decimal("-0.000000000001")),
    ),
)
def test_position_input_rejects_invalid_values(
    field_name: str, field_value: Decimal
) -> None:
    valid = {
        "quantity": Decimal("150"),
        "cost_price": Decimal("106.666666666667"),
        "current_price": Decimal("120"),
        "current_fx": Decimal("7.20"),
    }
    valid[field_name] = field_value

    with pytest.raises(ValueError, match=field_name):
        PositionInput(**valid)


def test_position_analysis_response_validates_from_domain_result() -> None:
    domain_result = analyze_position(
        PositionInput(
            quantity=Decimal("150"),
            cost_price=Decimal("106.666666666667"),
            current_price=Decimal("120"),
            current_fx=Decimal("7.20"),
        )
    )

    payload = PositionAnalysisResponse.model_validate(domain_result)

    assert payload.model_dump(mode="json") == {
        "cost_trade_currency": format(domain_result.cost_trade_currency, "f"),
        "market_value_trade_currency": format(
            domain_result.market_value_trade_currency, "f"
        ),
        "unrealized_pnl_trade_currency": format(
            domain_result.unrealized_pnl_trade_currency, "f"
        ),
        "cost_cny": format(domain_result.cost_cny, "f"),
        "market_value_cny": format(domain_result.market_value_cny, "f"),
        "unrealized_pnl": format(domain_result.unrealized_pnl, "f"),
        "unrealized_return": format(domain_result.unrealized_return, "f"),
    }
