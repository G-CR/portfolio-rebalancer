from decimal import Decimal

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
