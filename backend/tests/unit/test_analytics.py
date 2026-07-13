from decimal import Decimal, localcontext

import pytest

from app.domain.analytics import PositionInput, analyze_position
from app.schemas.analytics import PositionAnalysisResponse


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


def test_pnl_decomposition_identity_survives_low_precision_context() -> None:
    with localcontext() as context:
        context.prec = 4
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

        assert result.price_effect + result.fx_effect == result.unrealized_pnl


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
        "unrealized_return": "0.1448763250883356448763250884",
        "price_effect": "14149.999999999646250",
        "fx_effect": "2250.000",
    }
