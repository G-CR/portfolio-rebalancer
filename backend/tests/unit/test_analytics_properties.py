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
        current_fx=fx_basis * draw(ratio),
    )


@given(position_inputs())
def test_reference_pnl_identity(value: PositionInput) -> None:
    with localcontext() as context:
        context.prec = 80
        result = analyze_position(
            PositionInput(
                quantity=Decimal(value.quantity),
                cost_price=Decimal(value.cost_price),
                current_price=Decimal(value.current_price),
                current_fx=Decimal(value.current_fx),
            )
        )
        assert result.market_value_cny - result.cost_cny == result.unrealized_pnl
        assert (
            result.market_value_trade_currency - result.cost_trade_currency
            == result.unrealized_pnl_trade_currency
        )


@given(position_inputs(), base_fx)
def test_native_pnl_does_not_depend_on_current_fx(
    value: PositionInput, other_fx: Decimal
) -> None:
    with localcontext() as context:
        context.prec = 80
        first = analyze_position(value)
        second = analyze_position(
            PositionInput(
                quantity=value.quantity,
                cost_price=value.cost_price,
                current_price=value.current_price,
                current_fx=other_fx,
            )
        )
        assert first.unrealized_pnl_trade_currency == second.unrealized_pnl_trade_currency
        assert first.unrealized_return.quantize(
            Decimal("0.000000000001")
        ) == second.unrealized_return.quantize(Decimal("0.000000000001"))
