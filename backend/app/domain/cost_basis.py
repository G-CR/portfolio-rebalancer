from __future__ import annotations

from dataclasses import dataclass, field
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
    cost_fx: Decimal
    _total_cost_cny: Decimal | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_nonnegative("quantity", self.quantity)
        _require_nonnegative("average_price", self.average_price)
        _require_nonnegative("cost_fx", self.cost_fx)

        if self.quantity == 0:
            if self.average_price != 0 or self.cost_fx != 0:
                raise ValueError(
                    "average price and cost fx must both be zero when quantity is zero"
                )
            return

        _require_positive("cost_fx", self.cost_fx)

    @property
    def total_cost_cny(self) -> Decimal:
        if self._total_cost_cny is not None:
            return self._total_cost_cny
        return self.quantity * self.average_price * self.cost_fx


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
    values = (
        current.quantity,
        current.average_price,
        current.cost_fx,
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

        original_cny_cost = current.total_cost_cny
        purchase_cny_cost = (
            purchase.quantity * purchase.price * purchase.fx
            + (purchase.fee_trade_currency * purchase.fx)
            + purchase.fee_cny
        )

        new_quantity = current.quantity + purchase.quantity
        new_trade_cost = original_trade_cost + purchase_trade_cost
        new_total_cost_cny = original_cny_cost + purchase_cny_cost

        if new_quantity == 0 or new_trade_cost == 0:
            return CostBasis(
                quantity=Decimal("0"),
                average_price=Decimal("0"),
                cost_fx=Decimal("0"),
                _total_cost_cny=Decimal("0"),
            )

        new_average_price = new_trade_cost / new_quantity
        new_cost_fx = new_total_cost_cny / new_trade_cost

        return CostBasis(
            quantity=new_quantity,
            average_price=new_average_price,
            cost_fx=new_cost_fx,
            _total_cost_cny=new_total_cost_cny,
        )


def sell_quantity(current: CostBasis, quantity: Decimal) -> CostBasis:
    _require_positive("sell quantity", quantity)
    if quantity > current.quantity:
        raise ValueError("sell quantity cannot exceed current quantity")

    remaining_quantity = current.quantity - quantity
    if remaining_quantity == 0:
        return CostBasis(
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            cost_fx=Decimal("0"),
            _total_cost_cny=Decimal("0"),
        )

    remaining_total_cost_cny = remaining_quantity * current.average_price * current.cost_fx
    return CostBasis(
        quantity=remaining_quantity,
        average_price=current.average_price,
        cost_fx=current.cost_fx,
        _total_cost_cny=remaining_total_cost_cny,
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
