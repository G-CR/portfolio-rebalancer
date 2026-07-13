from decimal import Decimal, localcontext

import pytest

from app.domain.analytics import PositionInput, analyze_position
from app.schemas.analytics import PositionAnalysisResponse


def _expected_formulas(value: PositionInput) -> dict[str, Decimal]:
    with localcontext() as context:
        context.prec = 200
        current_at_cost_fx = value.quantity * value.current_price * value.cost_fx
        cost_cny = value.quantity * value.cost_price * value.cost_fx
        market_value_cny = value.quantity * value.current_price * value.current_fx
        fx_neutral_value_cny = value.quantity * value.current_price * value.baseline_fx
        price_effect = current_at_cost_fx - cost_cny
        fx_effect = market_value_cny - current_at_cost_fx
        unrealized_pnl = market_value_cny - cost_cny
        unrealized_return = unrealized_pnl / cost_cny if cost_cny else Decimal("0")
        return {
            "cost_cny": cost_cny,
            "market_value_cny": market_value_cny,
            "fx_neutral_value_cny": fx_neutral_value_cny,
            "price_effect": price_effect,
            "fx_effect": fx_effect,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_return": unrealized_return,
        }


def test_usd_position_decomposes_pnl_exactly() -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal("150"),
            cost_price=Decimal("106.666666666667"),
            current_price=Decimal("120"),
            cost_fx=Decimal("7.075"),
            current_fx=Decimal("7.20"),
            baseline_fx=Decimal("7.00"),
        )
    )

    assert result.cost_cny == Decimal("113200.000000000353750")
    assert result.market_value_cny == Decimal("129600.00")
    assert result.fx_neutral_value_cny == Decimal("126000.00")
    assert result.price_effect + result.fx_effect == result.unrealized_pnl


def test_zero_quantity_returns_zero_values() -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal("0"),
            cost_price=Decimal("106.666666666667"),
            current_price=Decimal("120"),
            cost_fx=Decimal("7.075"),
            current_fx=Decimal("7.20"),
            baseline_fx=Decimal("7.00"),
        )
    )

    assert result.cost_cny == Decimal("0E-15")
    assert result.market_value_cny == Decimal("0.00")
    assert result.fx_neutral_value_cny == Decimal("0.00")
    assert result.unrealized_pnl == Decimal("0E-15")
    assert result.unrealized_return == Decimal("0")
    assert result.price_effect == Decimal("0E-15")
    assert result.fx_effect == Decimal("0.000")


def test_zero_cost_price_returns_zero_unrealized_return() -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal("150"),
            cost_price=Decimal("0"),
            current_price=Decimal("120"),
            cost_fx=Decimal("7.075"),
            current_fx=Decimal("7.20"),
            baseline_fx=Decimal("7.00"),
        )
    )

    assert result.cost_cny == Decimal("0.000")
    assert result.market_value_cny == Decimal("129600.00")
    assert result.fx_neutral_value_cny == Decimal("126000.00")
    assert result.unrealized_pnl == Decimal("129600.000")
    assert result.unrealized_return == Decimal("0")
    assert result.price_effect == Decimal("127350.000")
    assert result.fx_effect == Decimal("2250.000")
    assert result.price_effect + result.fx_effect == result.unrealized_pnl


def test_results_are_identical_under_low_and_default_precision_contexts() -> None:
    value = PositionInput(
        quantity=Decimal("150"),
        cost_price=Decimal("106.666666666667"),
        current_price=Decimal("120"),
        cost_fx=Decimal("7.075"),
        current_fx=Decimal("7.20"),
        baseline_fx=Decimal("7.00"),
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
        cost_fx=Decimal("19.999999999999"),
        current_fx=Decimal("0.100000000001"),
        baseline_fx=Decimal("10.123456789012"),
    )

    result = analyze_position(value)
    expected = _expected_formulas(value)

    assert result.cost_cny == expected["cost_cny"]
    assert result.market_value_cny == expected["market_value_cny"]
    assert result.fx_neutral_value_cny == expected["fx_neutral_value_cny"]
    assert result.unrealized_pnl == expected["unrealized_pnl"]
    assert result.price_effect == expected["price_effect"]
    assert result.fx_effect == expected["fx_effect"]

    with localcontext() as context:
        context.prec = 200
        assert result.market_value_cny - result.cost_cny == expected["unrealized_pnl"]
        assert result.price_effect + result.fx_effect == expected["unrealized_pnl"]


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("quantity", Decimal("-0.000000000001")),
        ("cost_price", Decimal("-0.000000000001")),
        ("current_price", Decimal("-0.000000000001")),
        ("cost_fx", Decimal("0")),
        ("cost_fx", Decimal("-0.000000000001")),
        ("current_fx", Decimal("0")),
        ("current_fx", Decimal("-0.000000000001")),
        ("baseline_fx", Decimal("0")),
        ("baseline_fx", Decimal("-0.000000000001")),
    ),
)
def test_position_input_rejects_invalid_values(
    field_name: str, field_value: Decimal
) -> None:
    valid = {
        "quantity": Decimal("150"),
        "cost_price": Decimal("106.666666666667"),
        "current_price": Decimal("120"),
        "cost_fx": Decimal("7.075"),
        "current_fx": Decimal("7.20"),
        "baseline_fx": Decimal("7.00"),
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
            cost_fx=Decimal("7.075"),
            current_fx=Decimal("7.20"),
            baseline_fx=Decimal("7.00"),
        )
    )

    payload = PositionAnalysisResponse.model_validate(domain_result)

    assert payload.model_dump(mode="json") == {
        "cost_cny": "113200.000000000353750",
        "market_value_cny": "129600.00",
        "fx_neutral_value_cny": "126000.00",
        "unrealized_pnl": "16399.999999999646250",
        "unrealized_return": format(domain_result.unrealized_return, "f"),
        "price_effect": "14149.999999999646250",
        "fx_effect": "2250.000",
    }
