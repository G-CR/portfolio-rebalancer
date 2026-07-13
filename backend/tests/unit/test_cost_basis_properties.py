from decimal import Decimal, localcontext

from hypothesis import given, strategies as st

from app.domain.cost_basis import CostBasis, Purchase, add_purchase

current_quantity = st.decimals(min_value="0.000001", max_value="100000", places=6)
current_price = st.decimals(min_value="0.000001", max_value="100000", places=6)
purchase_quantity = st.decimals(min_value="0.000001", max_value="100000", places=6)
purchase_price = st.decimals(min_value="0.000001", max_value="100000", places=6)
fx_value = st.decimals(min_value="0.000001", max_value="20", places=6)
fee_value = st.decimals(min_value="0", max_value="1000", places=6)


@st.composite
def purchase_inputs(draw: st.DrawFn) -> tuple[CostBasis, Purchase]:
    fee_currency = draw(st.sampled_from(("trade", "cny")))
    trade_fee = draw(fee_value) if fee_currency == "trade" else Decimal("0")
    cny_fee = draw(fee_value) if fee_currency == "cny" else Decimal("0")

    return (
        CostBasis(
            quantity=draw(current_quantity),
            average_price=draw(current_price),
            cost_fx=draw(fx_value),
        ),
        Purchase(
            quantity=draw(purchase_quantity),
            price=draw(purchase_price),
            fx=draw(fx_value),
            fee_trade_currency=trade_fee,
            fee_cny=cny_fee,
        ),
    )


@given(purchase_inputs())
def test_purchase_identity_holds_after_cent_quantization(
    value: tuple[CostBasis, Purchase],
) -> None:
    with localcontext() as context:
        context.prec = 80
        current, purchase = value
        result = add_purchase(
            CostBasis(
                quantity=Decimal(current.quantity),
                average_price=Decimal(current.average_price),
                cost_fx=Decimal(current.cost_fx),
            ),
            Purchase(
                quantity=Decimal(purchase.quantity),
                price=Decimal(purchase.price),
                fx=Decimal(purchase.fx),
                fee_trade_currency=Decimal(purchase.fee_trade_currency),
                fee_cny=Decimal(purchase.fee_cny),
            ),
        )
        left = (result.quantity * result.average_price * result.cost_fx).quantize(
            Decimal("0.01")
        )
        right = result.total_cost_cny.quantize(Decimal("0.01"))

        assert left == right
