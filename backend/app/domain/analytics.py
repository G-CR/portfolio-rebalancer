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


def _analysis_precision(value: "PositionInput") -> int:
    total_integer_digits = 0
    total_fractional_digits = 0

    for component in (
        value.quantity,
        value.cost_price,
        value.current_price,
        value.cost_fx,
        value.current_fx,
        value.baseline_fx,
    ):
        integer_digits, fractional_digits = _digit_counts(component)
        total_integer_digits += integer_digits
        total_fractional_digits += fractional_digits

    return max(100, total_integer_digits + total_fractional_digits + 20)


@dataclass(frozen=True)
class PositionInput:
    quantity: Decimal
    cost_price: Decimal
    current_price: Decimal
    cost_fx: Decimal
    current_fx: Decimal
    baseline_fx: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative("quantity", self.quantity)
        _require_nonnegative("cost_price", self.cost_price)
        _require_nonnegative("current_price", self.current_price)
        _require_positive("cost_fx", self.cost_fx)
        _require_positive("current_fx", self.current_fx)
        _require_positive("baseline_fx", self.baseline_fx)


@dataclass(frozen=True)
class PositionAnalysis:
    cost_cny: Decimal
    market_value_cny: Decimal
    fx_neutral_value_cny: Decimal
    unrealized_pnl: Decimal
    unrealized_return: Decimal
    price_effect: Decimal
    fx_effect: Decimal


def analyze_position(value: PositionInput) -> PositionAnalysis:
    with localcontext() as context:
        context.prec = _analysis_precision(value)

        cost_cny = value.quantity * value.cost_price * value.cost_fx
        market_value_cny = value.quantity * value.current_price * value.current_fx
        fx_neutral_value_cny = value.quantity * value.current_price * value.baseline_fx
        current_at_cost_cny = value.quantity * value.current_price * value.cost_fx
        price_effect = current_at_cost_cny - cost_cny
        fx_effect = market_value_cny - current_at_cost_cny
        unrealized_pnl = market_value_cny - cost_cny
        unrealized_return = unrealized_pnl / cost_cny if cost_cny else Decimal("0")

        return PositionAnalysis(
            cost_cny=cost_cny,
            market_value_cny=market_value_cny,
            fx_neutral_value_cny=fx_neutral_value_cny,
            unrealized_pnl=unrealized_pnl,
            unrealized_return=unrealized_return,
            price_effect=price_effect,
            fx_effect=fx_effect,
        )
