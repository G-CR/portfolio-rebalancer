from decimal import Decimal

from hypothesis import given, strategies as st

from app.domain.analytics import PositionInput, analyze_position

positive = st.decimals(min_value="0.0001", max_value="100000", places=4)


@given(positive, positive, positive, positive, positive, positive)
def test_pnl_decomposition_identity(
    qty: Decimal,
    cost: Decimal,
    current: Decimal,
    cost_fx: Decimal,
    current_fx: Decimal,
    baseline_fx: Decimal,
) -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal(qty),
            cost_price=Decimal(cost),
            current_price=Decimal(current),
            cost_fx=Decimal(cost_fx),
            current_fx=Decimal(current_fx),
            baseline_fx=Decimal(baseline_fx),
        )
    )

    assert result.price_effect + result.fx_effect == result.unrealized_pnl
