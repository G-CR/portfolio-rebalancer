from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, localcontext
from typing import Literal, Sequence


Currency = Literal["CNY", "USD"]
TradeAction = Literal["buy", "sell"]


def _require_finite(name: str, value: Decimal) -> None:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def _require_nonnegative(name: str, value: Decimal) -> None:
    _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _require_positive(name: str, value: Decimal) -> None:
    _require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _digit_counts(value: Decimal) -> tuple[int, int]:
    exponent = value.as_tuple().exponent
    fractional_digits = max(-exponent, 0)
    integer_digits = max(len(value.as_tuple().digits) - fractional_digits, 1)
    return integer_digits, fractional_digits


def _calculation_precision(values: Sequence[Decimal]) -> int:
    integer_digits = 0
    fractional_digits = 0
    for value in values:
        current_integer, current_fractional = _digit_counts(value)
        integer_digits += current_integer
        fractional_digits += current_fractional
    return max(100, integer_digits + fractional_digits + 30)


@dataclass(frozen=True)
class AssetInput:
    asset_class_id: str
    symbol: str
    currency: Currency
    current_value_cny: Decimal
    target_weight: Decimal
    unit_price_cny: Decimal
    lot_size: Decimal

    def __post_init__(self) -> None:
        if not self.asset_class_id:
            raise ValueError("asset_class_id must not be empty")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.currency not in ("CNY", "USD"):
            raise ValueError("currency must be CNY or USD")
        _require_nonnegative("current_value_cny", self.current_value_cny)
        _require_nonnegative("target_weight", self.target_weight)
        if self.target_weight > 1:
            raise ValueError("target_weight must not exceed 1")
        _require_positive("unit_price_cny", self.unit_price_cny)
        _require_positive("lot_size", self.lot_size)


@dataclass(frozen=True)
class CashInput:
    cny: Decimal
    usd: Decimal
    usd_cny: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative("cny", self.cny)
        _require_nonnegative("usd", self.usd)
        _require_positive("usd_cny", self.usd_cny)


@dataclass(frozen=True)
class RebalanceOptions:
    tolerance: Decimal
    minimum_trade_cny: Decimal
    allow_sell: bool
    allow_fx: bool

    def __post_init__(self) -> None:
        _require_nonnegative("tolerance", self.tolerance)
        if self.tolerance > 1:
            raise ValueError("tolerance must not exceed 1")
        _require_nonnegative("minimum_trade_cny", self.minimum_trade_cny)


@dataclass(frozen=True)
class TradeSuggestion:
    symbol: str
    action: TradeAction
    quantity: Decimal
    amount_cny: Decimal
    amount_trade_currency: Decimal
    reason_code: str


@dataclass(frozen=True)
class ProjectedWeight:
    asset_class_id: str
    before: Decimal
    after: Decimal
    target: Decimal


@dataclass(frozen=True)
class RebalanceResult:
    feasible: bool
    max_drift_before: Decimal
    max_drift_after: Decimal
    fx_required_cny: Decimal
    remaining_cny: Decimal
    remaining_usd: Decimal
    projected_weights: tuple[ProjectedWeight, ...]
    trades: tuple[TradeSuggestion, ...]


@dataclass
class _TradeTotal:
    symbol: str
    action: TradeAction
    quantity: Decimal
    amount_cny: Decimal
    amount_trade_currency: Decimal
    reason_code: str


def _floor_lots(amount_cny: Decimal, asset: AssetInput) -> Decimal:
    lot_value_cny = asset.unit_price_cny * asset.lot_size
    lot_count = (amount_cny / lot_value_cny).to_integral_value(rounding=ROUND_FLOOR)
    return lot_count * asset.lot_size


def _weight(value: Decimal, total: Decimal) -> Decimal:
    return value / total if total else Decimal("0")


def _max_drift(
    assets: Sequence[AssetInput], values: dict[str, Decimal], total: Decimal
) -> Decimal:
    if not assets:
        return Decimal("0")
    return max(
        abs(_weight(values[item.asset_class_id], total) - item.target_weight)
        for item in assets
    )


def rebalance(
    assets: Sequence[AssetInput],
    cash: CashInput,
    options: RebalanceOptions,
) -> RebalanceResult:
    asset_list = tuple(assets)
    class_ids = [item.asset_class_id for item in asset_list]
    symbols = [item.symbol for item in asset_list]
    if len(class_ids) != len(set(class_ids)):
        raise ValueError("duplicate asset_class_id")
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate symbol")

    decimal_values = [
        cash.cny,
        cash.usd,
        cash.usd_cny,
        options.tolerance,
        options.minimum_trade_cny,
    ]
    for item in asset_list:
        decimal_values.extend(
            (
                item.current_value_cny,
                item.target_weight,
                item.unit_price_cny,
                item.lot_size,
            )
        )

    with localcontext() as context:
        context.prec = _calculation_precision(decimal_values)
        if asset_list and sum(
            (item.target_weight for item in asset_list), Decimal("0")
        ) != Decimal("1"):
            raise ValueError("target weights must sum to 1")

        values = {
            item.asset_class_id: item.current_value_cny for item in asset_list
        }
        current_total = sum(values.values(), Decimal("0"))
        investable_total = current_total + cash.cny + cash.usd * cash.usd_cny
        targets = {
            item.asset_class_id: investable_total * item.target_weight
            for item in asset_list
        }
        cny_balance = cash.cny
        usd_balance = cash.usd
        fx_required_cny = Decimal("0")
        trade_totals: dict[tuple[str, TradeAction], _TradeTotal] = {}

        def add_trade(
            asset: AssetInput,
            action: TradeAction,
            quantity: Decimal,
            reason_code: str,
        ) -> None:
            amount_cny = quantity * asset.unit_price_cny
            amount_trade_currency = (
                amount_cny if asset.currency == "CNY" else amount_cny / cash.usd_cny
            )
            key = (asset.symbol, action)
            existing = trade_totals.get(key)
            if existing is None:
                trade_totals[key] = _TradeTotal(
                    symbol=asset.symbol,
                    action=action,
                    quantity=quantity,
                    amount_cny=amount_cny,
                    amount_trade_currency=amount_trade_currency,
                    reason_code=reason_code,
                )
                return
            existing.quantity += quantity
            existing.amount_cny += amount_cny
            existing.amount_trade_currency += amount_trade_currency

        def deficits(
            currency: Currency | None = None,
        ) -> list[tuple[Decimal, AssetInput]]:
            candidates = []
            for item in asset_list:
                deficit = targets[item.asset_class_id] - values[item.asset_class_id]
                if (currency is None or item.currency == currency) and deficit > 0:
                    candidates.append((deficit, item))
            return sorted(candidates, key=lambda row: (-row[0], row[1].symbol))

        def buy_with_same_currency() -> None:
            nonlocal cny_balance, usd_balance
            for deficit, item in deficits():
                available_cny = (
                    cny_balance
                    if item.currency == "CNY"
                    else usd_balance * cash.usd_cny
                )
                quantity = _floor_lots(min(deficit, available_cny), item)
                amount_cny = quantity * item.unit_price_cny
                if quantity <= 0 or amount_cny < options.minimum_trade_cny:
                    continue
                values[item.asset_class_id] += amount_cny
                if item.currency == "CNY":
                    cny_balance -= amount_cny
                else:
                    usd_balance -= amount_cny / cash.usd_cny
                add_trade(item, "buy", quantity, "UNDERWEIGHT_WITH_CASH")

        def buy_usd_with_fx() -> None:
            nonlocal cny_balance, usd_balance, fx_required_cny
            if not options.allow_fx or cny_balance <= 0:
                return
            for deficit, item in deficits("USD"):
                quantity = _floor_lots(min(deficit, cny_balance), item)
                amount_cny = quantity * item.unit_price_cny
                if quantity <= 0 or amount_cny < options.minimum_trade_cny:
                    continue
                converted_usd = amount_cny / cash.usd_cny
                cny_balance -= amount_cny
                usd_balance += converted_usd
                fx_required_cny += amount_cny
                values[item.asset_class_id] += amount_cny
                usd_balance -= converted_usd
                add_trade(item, "buy", quantity, "UNDERWEIGHT_AFTER_FX")

        # Passes 1-3: fixed targets, same-currency cash, then minimal executable FX.
        buy_with_same_currency()
        buy_usd_with_fx()

        # Pass 4: only residual upper-bound breaches can create sale proceeds.
        if options.allow_sell and investable_total > 0:
            upper_candidates = []
            for item in asset_list:
                upper_value = investable_total * (
                    item.target_weight + options.tolerance
                )
                excess_to_target = (
                    values[item.asset_class_id] - targets[item.asset_class_id]
                )
                if values[item.asset_class_id] > upper_value and excess_to_target > 0:
                    upper_candidates.append((excess_to_target, item))

            for excess, item in sorted(
                upper_candidates, key=lambda row: (-row[0], row[1].symbol)
            ):
                available_quantity = _floor_lots(
                    values[item.asset_class_id], item
                )
                quantity = min(_floor_lots(excess, item), available_quantity)
                amount_cny = quantity * item.unit_price_cny
                if quantity <= 0 or amount_cny < options.minimum_trade_cny:
                    continue
                values[item.asset_class_id] -= amount_cny
                if item.currency == "CNY":
                    cny_balance += amount_cny
                else:
                    usd_balance += amount_cny / cash.usd_cny
                add_trade(item, "sell", quantity, "OVERWEIGHT_AFTER_CASH")

            buy_with_same_currency()
            buy_usd_with_fx()

        final_total = sum(values.values(), Decimal("0"))
        before_values = {
            item.asset_class_id: item.current_value_cny for item in asset_list
        }
        max_drift_before = _max_drift(asset_list, before_values, current_total)
        max_drift_after = _max_drift(asset_list, values, final_total)
        projected_weights = tuple(
            ProjectedWeight(
                asset_class_id=item.asset_class_id,
                before=_weight(item.current_value_cny, current_total),
                after=_weight(values[item.asset_class_id], final_total),
                target=item.target_weight,
            )
            for item in asset_list
        )
        trades = tuple(
            TradeSuggestion(
                symbol=item.symbol,
                action=item.action,
                quantity=item.quantity,
                amount_cny=item.amount_cny,
                amount_trade_currency=item.amount_trade_currency,
                reason_code=item.reason_code,
            )
            for item in trade_totals.values()
        )

        return RebalanceResult(
            feasible=max_drift_after <= options.tolerance,
            max_drift_before=max_drift_before,
            max_drift_after=max_drift_after,
            fx_required_cny=fx_required_cny,
            remaining_cny=cny_balance,
            remaining_usd=usd_balance,
            projected_weights=projected_weights,
            trades=trades,
        )
