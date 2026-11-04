from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext


def _require_nonnegative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _require_positive(name: str, value: Decimal) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _digit_counts(value: Decimal) -> tuple[int, int]:
    exponent = value.as_tuple().exponent
    fractional_digits = max(-exponent, 0)
    integer_digits = max(len(value.as_tuple().digits) - fractional_digits, 1)
    return integer_digits, fractional_digits


def _calculation_precision(values: tuple[Decimal, ...]) -> int:
    total_integer_digits = 0
    total_fractional_digits = 0

    for value in values:
        integer_digits, fractional_digits = _digit_counts(value)
        total_integer_digits += integer_digits
        total_fractional_digits += fractional_digits

    return max(100, total_integer_digits + total_fractional_digits + 20)


@dataclass(frozen=True)
class CostBasis:
    quantity: Decimal
    average_price: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative("quantity", self.quantity)
        _require_nonnegative("average_price", self.average_price)

        if self.quantity == 0 and self.average_price != 0:
            raise ValueError("average price must be zero when quantity is zero")

    @property
    def total_cost_trade_currency(self) -> Decimal:
        return self.quantity * self.average_price


@dataclass(frozen=True)
class Purchase:
    quantity: Decimal
    price: Decimal
    fx: Decimal
    fee_trade_currency: Decimal
    fee_cny: Decimal

    def __post_init__(self) -> None:
        _require_positive("quantity", self.quantity)
        _require_nonnegative("price", self.price)
        _require_positive("fx", self.fx)
        _require_nonnegative("fee_trade_currency", self.fee_trade_currency)
        _require_nonnegative("fee_cny", self.fee_cny)


@dataclass(frozen=True)
class FeeRule:
    commission_rate: Decimal
    minimum_commission: Decimal
    per_share_fee: Decimal
    fixed_fee: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative("commission_rate", self.commission_rate)
        _require_nonnegative("minimum_commission", self.minimum_commission)
        _require_nonnegative("per_share_fee", self.per_share_fee)
        _require_nonnegative("fixed_fee", self.fixed_fee)


def add_purchase(current: CostBasis, purchase: Purchase) -> CostBasis:
    """Add a purchase to the trade-currency cost basis.

    ``purchase.fx`` is only used to translate a CNY-denominated fee into the
    holding's trade currency. The resulting cost basis never stores or depends
    on a historical CNY exchange rate.
    """
    values = (
        current.quantity,
        current.average_price,
        purchase.quantity,
        purchase.price,
        purchase.fx,
        purchase.fee_trade_currency,
        purchase.fee_cny,
    )
    with localcontext() as context:
        context.prec = _calculation_precision(values)

        original_trade_cost = current.quantity * current.average_price
        purchase_trade_cost = (
            purchase.quantity * purchase.price
            + purchase.fee_trade_currency
            + (purchase.fee_cny / purchase.fx)
        )

        new_quantity = current.quantity + purchase.quantity
        new_trade_cost = original_trade_cost + purchase_trade_cost

        if new_quantity == 0 or new_trade_cost == 0:
            return CostBasis(quantity=Decimal("0"), average_price=Decimal("0"))

        new_average_price = new_trade_cost / new_quantity

        return CostBasis(quantity=new_quantity, average_price=new_average_price)


def sell_quantity(current: CostBasis, quantity: Decimal) -> CostBasis:
    _require_positive("sell quantity", quantity)
    if quantity > current.quantity:
        raise ValueError("sell quantity cannot exceed current quantity")

    remaining_quantity = current.quantity - quantity
    if remaining_quantity == 0:
        return CostBasis(quantity=Decimal("0"), average_price=Decimal("0"))

    return CostBasis(
        quantity=remaining_quantity,
        average_price=current.average_price,
    )


def resolve_fee(
    *,
    trade_value: Decimal,
    quantity: Decimal,
    rule: FeeRule,
    actual_fee: Decimal | None,
) -> Decimal:
    _require_nonnegative("trade_value", trade_value)
    _require_nonnegative("quantity", quantity)
    if actual_fee is not None:
        _require_nonnegative("actual_fee", actual_fee)
        return actual_fee

    return (
        max(trade_value * rule.commission_rate, rule.minimum_commission)
        + (quantity * rule.per_share_fee)
        + rule.fixed_fee
    )
