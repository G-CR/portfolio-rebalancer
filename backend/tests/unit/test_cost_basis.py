from decimal import Decimal

import pytest

from app.domain.cost_basis import CostBasis, FeeRule, Purchase, add_purchase, resolve_fee, sell_quantity


def test_add_purchase_with_trade_currency_fee() -> None:
    result = add_purchase(
        CostBasis(
            quantity=Decimal("100"),
            average_price=Decimal("100"),
            cost_fx=Decimal("7.00"),
        ),
        Purchase(
            quantity=Decimal("50"),
            price=Decimal("120"),
            fx=Decimal("7.20"),
            fee_trade_currency=Decimal("2"),
            fee_cny=Decimal("0"),
        ),
    )

    assert result.quantity == Decimal("150")
    assert result.average_price == Decimal("106.68")
    assert result.total_cost_cny == Decimal("113214.40")
    assert (
        result.quantity * result.average_price * result.cost_fx
    ).quantize(Decimal("0.01")) == result.total_cost_cny.quantize(Decimal("0.01"))


def test_add_purchase_with_cny_fee() -> None:
    result = add_purchase(
        CostBasis(
            quantity=Decimal("10"),
            average_price=Decimal("500"),
            cost_fx=Decimal("7.20"),
        ),
        Purchase(
            quantity=Decimal("5"),
            price=Decimal("650.20"),
            fx=Decimal("7.1850"),
            fee_trade_currency=Decimal("0"),
            fee_cny=Decimal("18"),
        ),
    )

    assert result.quantity == Decimal("15")
    assert result.average_price.quantize(Decimal("0.0001")) == Decimal("550.2337")
    assert result.total_cost_cny.quantize(Decimal("0.01")) == Decimal("59376.44")


def test_actual_fee_overrides_estimated_fee() -> None:
    fee = resolve_fee(
        trade_value=Decimal("3251"),
        quantity=Decimal("5"),
        rule=FeeRule(
            commission_rate=Decimal("0"),
            minimum_commission=Decimal("0"),
            per_share_fee=Decimal("0.01"),
            fixed_fee=Decimal("2"),
        ),
        actual_fee=Decimal("2.30"),
    )

    assert fee == Decimal("2.30")


def test_resolve_fee_uses_estimated_formula_when_actual_fee_missing() -> None:
    fee = resolve_fee(
        trade_value=Decimal("3251"),
        quantity=Decimal("5"),
        rule=FeeRule(
            commission_rate=Decimal("0.001"),
            minimum_commission=Decimal("4"),
            per_share_fee=Decimal("0.01"),
            fixed_fee=Decimal("2"),
        ),
        actual_fee=None,
    )

    assert fee == Decimal("6.05")


def test_partial_sale_preserves_average_cost() -> None:
    result = sell_quantity(
        CostBasis(
            quantity=Decimal("100"),
            average_price=Decimal("50"),
            cost_fx=Decimal("7.10"),
        ),
        Decimal("25"),
    )

    assert result == CostBasis(
        quantity=Decimal("75"),
        average_price=Decimal("50"),
        cost_fx=Decimal("7.10"),
    )


def test_full_sale_zeros_out_cost_fields() -> None:
    result = sell_quantity(
        CostBasis(
            quantity=Decimal("25"),
            average_price=Decimal("50"),
            cost_fx=Decimal("7.10"),
        ),
        Decimal("25"),
    )

    assert result == CostBasis(
        quantity=Decimal("0"),
        average_price=Decimal("0"),
        cost_fx=Decimal("0"),
    )


def test_sell_quantity_rejects_sale_above_current_quantity() -> None:
    with pytest.raises(ValueError, match="sell quantity"):
        sell_quantity(
            CostBasis(
                quantity=Decimal("10"),
                average_price=Decimal("50"),
                cost_fx=Decimal("7.10"),
            ),
            Decimal("10.000001"),
        )
