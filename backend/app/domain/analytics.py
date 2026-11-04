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
        value.current_fx,
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
    current_fx: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative("quantity", self.quantity)
        _require_nonnegative("cost_price", self.cost_price)
        _require_nonnegative("current_price", self.current_price)
        _require_positive("current_fx", self.current_fx)


@dataclass(frozen=True)
class PositionAnalysis:
    cost_trade_currency: Decimal
    market_value_trade_currency: Decimal
    unrealized_pnl_trade_currency: Decimal
    cost_cny: Decimal
    market_value_cny: Decimal
    unrealized_pnl: Decimal
    unrealized_return: Decimal


def analyze_position(value: PositionInput) -> PositionAnalysis:
    """Value a position in its trade currency and convert to CNY at the current rate.

    The holding's own average cost is authoritative. The CNY cost and PnL are
    reference values derived with the current exchange rate; no historical FX
    cost is inferred or attributed.
    """
    with localcontext() as context:
        context.prec = _analysis_precision(value)

        cost_trade_currency = value.quantity * value.cost_price
        market_value_trade_currency = value.quantity * value.current_price
        unrealized_pnl_trade_currency = (
            market_value_trade_currency - cost_trade_currency
        )

        cost_cny = cost_trade_currency * value.current_fx
        market_value_cny = market_value_trade_currency * value.current_fx
        unrealized_pnl = market_value_cny - cost_cny
        unrealized_return = unrealized_pnl / cost_cny if cost_cny else Decimal("0")

        return PositionAnalysis(
            cost_trade_currency=cost_trade_currency,
            market_value_trade_currency=market_value_trade_currency,
            unrealized_pnl_trade_currency=unrealized_pnl_trade_currency,
            cost_cny=cost_cny,
            market_value_cny=market_value_cny,
            unrealized_pnl=unrealized_pnl,
            unrealized_return=unrealized_return,
        )
