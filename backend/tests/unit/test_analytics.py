from decimal import Decimal

import pytest

from app.domain.analytics import PositionInput, analyze_position


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

    assert result.cost_cny == Decimal("113200.000000000354")
    assert result.market_value_cny == Decimal("129600.00")
    assert result.fx_neutral_value_cny == Decimal("126000.00")
    assert result.price_effect + result.fx_effect == result.unrealized_pnl


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("quantity", Decimal("0")),
        ("cost_price", Decimal("-0.01")),
        ("current_price", Decimal("0")),
        ("cost_fx", Decimal("-1")),
        ("current_fx", Decimal("0")),
        ("baseline_fx", Decimal("-7.00")),
    ),
)
def test_position_input_rejects_nonpositive_values(
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
