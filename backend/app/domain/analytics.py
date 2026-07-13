from dataclasses import dataclass
from decimal import Decimal


def _require_nonnegative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _require_positive(name: str, value: Decimal) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


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
    cost_cny = value.quantity * value.cost_price * value.cost_fx
    market_value_cny = value.quantity * value.current_price * value.current_fx
    fx_neutral_value_cny = value.quantity * value.current_price * value.baseline_fx
    price_effect = (value.quantity * value.current_price * value.cost_fx) - cost_cny
    fx_effect = market_value_cny - (
        value.quantity * value.current_price * value.cost_fx
    )
    unrealized_pnl = price_effect + fx_effect

    return PositionAnalysis(
        cost_cny=cost_cny,
        market_value_cny=market_value_cny,
        fx_neutral_value_cny=fx_neutral_value_cny,
        unrealized_pnl=unrealized_pnl,
        unrealized_return=unrealized_pnl / cost_cny if cost_cny else Decimal("0"),
        price_effect=price_effect,
        fx_effect=fx_effect,
    )
