from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import DB_QUANTUM


def _require_positive(name: str, value: Decimal) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _quantize_db(value: Decimal) -> Decimal:
    return value.quantize(DB_QUANTUM)


@dataclass(frozen=True)
class PositionInput:
    quantity: Decimal
    cost_price: Decimal
    current_price: Decimal
    cost_fx: Decimal
    current_fx: Decimal
    baseline_fx: Decimal

    def __post_init__(self) -> None:
        _require_positive("quantity", self.quantity)
        _require_positive("cost_price", self.cost_price)
        _require_positive("current_price", self.current_price)
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
    raw_cost_cny = value.quantity * value.cost_price * value.cost_fx
    raw_market_value_cny = value.quantity * value.current_price * value.current_fx
    raw_fx_neutral_value_cny = value.quantity * value.current_price * value.baseline_fx
    raw_price_effect = (value.quantity * value.current_price * value.cost_fx) - raw_cost_cny
    raw_fx_effect = raw_market_value_cny - (
        value.quantity * value.current_price * value.cost_fx
    )
    raw_unrealized_pnl = raw_market_value_cny - raw_cost_cny

    return PositionAnalysis(
        cost_cny=_quantize_db(raw_cost_cny),
        market_value_cny=_quantize_db(raw_market_value_cny),
        fx_neutral_value_cny=_quantize_db(raw_fx_neutral_value_cny),
        unrealized_pnl=_quantize_db(raw_unrealized_pnl),
        unrealized_return=_quantize_db(raw_unrealized_pnl / raw_cost_cny),
        price_effect=_quantize_db(raw_price_effect),
        fx_effect=_quantize_db(raw_fx_effect),
    )
