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
            ),
            Purchase(
                quantity=Decimal(purchase.quantity),
                price=Decimal(purchase.price),
                fx=Decimal(purchase.fx),
                fee_trade_currency=Decimal(purchase.fee_trade_currency),
                fee_cny=Decimal(purchase.fee_cny),
            ),
        )
        expected_total = (
            current.quantity * current.average_price
            + purchase.quantity * purchase.price
            + purchase.fee_trade_currency
            + purchase.fee_cny / purchase.fx
        )

        assert result.quantity == current.quantity + purchase.quantity
        assert result.total_cost_trade_currency.quantize(
            Decimal("0.01")
        ) == expected_total.quantize(Decimal("0.01"))


@given(
    current_quantity,
    current_price,
    purchase_quantity,
    purchase_price,
    fx_value,
    fx_value,
)
def test_trade_currency_fee_cost_is_independent_of_fx(
    current_quantity_value: Decimal,
    current_price_value: Decimal,
    purchase_quantity_value: Decimal,
    purchase_price_value: Decimal,
    first_fx: Decimal,
    second_fx: Decimal,
) -> None:
    with localcontext() as context:
        context.prec = 80
        current = CostBasis(
            quantity=current_quantity_value,
            average_price=current_price_value,
        )

        def buy(fx: Decimal) -> CostBasis:
            return add_purchase(
                current,
                Purchase(
                    quantity=purchase_quantity_value,
                    price=purchase_price_value,
                    fx=fx,
                    fee_trade_currency=Decimal("1"),
                    fee_cny=Decimal("0"),
                ),
            )

        assert buy(first_fx) == buy(second_fx)
