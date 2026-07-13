from decimal import Decimal, localcontext

from hypothesis import given, strategies as st

from app.domain.analytics import PositionInput, analyze_position

quantity = st.decimals(min_value="0.000001", max_value="10000", places=12)
base_price = st.decimals(min_value="0.01", max_value="10000", places=12)
base_fx = st.decimals(min_value="0.1", max_value="20", places=12)
ratio = st.decimals(min_value="0.5", max_value="1.5", places=12)


@st.composite
def position_inputs(draw: st.DrawFn) -> PositionInput:
    price_basis = draw(base_price)
    fx_basis = draw(base_fx)
    return PositionInput(
        quantity=draw(quantity),
        cost_price=price_basis * draw(ratio),
        current_price=price_basis * draw(ratio),
        cost_fx=fx_basis * draw(ratio),
        current_fx=fx_basis * draw(ratio),
        baseline_fx=fx_basis * draw(ratio),
    )


@given(position_inputs())
def test_pnl_decomposition_identity(value: PositionInput) -> None:
    with localcontext() as context:
        context.prec = 80
        result = analyze_position(
            PositionInput(
                quantity=Decimal(value.quantity),
                cost_price=Decimal(value.cost_price),
                current_price=Decimal(value.current_price),
                cost_fx=Decimal(value.cost_fx),
                current_fx=Decimal(value.current_fx),
                baseline_fx=Decimal(value.baseline_fx),
            )
        )
        assert result.price_effect + result.fx_effect == result.unrealized_pnl
