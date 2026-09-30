"""Original-currency average cost, independent of reference FX availability."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)


@dataclass(frozen=True)
class Entry:
    kind: str
    occurred_on: date
    sequence: int
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    fee: Decimal = ZERO
    amount: Decimal = ZERO
    ratio: Decimal = Decimal(1)
    incomplete_reason: str | None = None


@dataclass
class ReplayResult:
    quantity: Decimal
    cost: Decimal
    realized: Decimal = ZERO
    dividends: Decimal = ZERO
    reasons: list[str] = field(default_factory=list)

    @property
    def average_price(self) -> Decimal:
        return self.cost / self.quantity if self.quantity else ZERO


def replay(quantity: Decimal, cost: Decimal, entries: list[Entry]) -> ReplayResult:
    result = ReplayResult(quantity, cost)
    for item in sorted(entries, key=lambda value: (value.occurred_on, value.sequence)):
        if item.incomplete_reason:
            result.reasons.append(item.incomplete_reason)
        if item.kind in {'purchase', 'sale'}:
            if item.quantity <= 0 or item.price <= 0 or item.fee < 0:
                raise ValueError('交易份额及价格必须为正，费用不得为负。')
        if item.kind == 'purchase':
            result.quantity += item.quantity
            result.cost += item.quantity * item.price + item.fee
        elif item.kind == 'sale':
            if item.quantity > result.quantity:
                raise ValueError(f'{item.occurred_on} 交易重放产生负份额；请先修正冲突交易。')
            allocated = result.average_price * item.quantity
            result.realized += item.quantity * item.price - item.fee - allocated
            result.quantity -= item.quantity
            result.cost = result.cost - allocated if result.quantity else ZERO
        elif item.kind == 'dividend':
            if item.amount < 0:
                raise ValueError('分红净额不得为负。')
            result.dividends += item.amount
        elif item.kind == 'split':
            if item.ratio <= 0:
                raise ValueError('折算比例必须为正。')
            result.quantity *= item.ratio
        elif item.kind == 'manual_correction':
            if item.quantity < 0 or item.amount < 0:
                raise ValueError('修正份额及成本不得为负。')
            result.quantity, result.cost = item.quantity, item.amount
            result.reasons.append('人工修正改变成本链，期间损益记录不完整。')
        elif item.kind != 'reversal':
            raise ValueError('未知账本类型。')
    return result


def select_reference(day: date, rates: list[tuple[date, Decimal]]) -> tuple[date, Decimal] | None:
    candidates = [(on, rate) for on, rate in rates if 0 <= (day - on).days <= 7 and rate.is_finite() and rate > 0]
    return max(candidates, key=lambda item: item[0]) if candidates else None
