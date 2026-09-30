from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.ledger import Entry, replay, select_reference


def entry(kind, sequence=1, **kwargs):
    return Entry(kind=kind, occurred_on=date(2026, 10, 1), sequence=sequence, **kwargs)


def test_purchase_fee_and_partial_sale_average_cost():
    result = replay(D(10), D(50), [entry('purchase', quantity=D(2), price=D(10), fee=D(1)), entry('sale', 2, quantity=D(3), price=D(12), fee=D(2))])
    assert result.quantity == 9
    assert result.cost == D('53.25')
    assert result.realized == D('16.25')


def test_split_preserves_cost_and_dividend_does_not_change_position():
    result = replay(D(10), D(50), [entry('split', ratio=D(2)), entry('dividend', 2, amount=D(7))])
    assert result.quantity == 20
    assert result.cost == 50
    assert result.dividends == 7


def test_historical_oversell_is_rejected():
    with pytest.raises(ValueError, match='负份额'):
        replay(D(2), D(10), [entry('sale', quantity=D(3), price=D(8))])


def test_correction_is_not_profit_and_marks_incomplete():
    result = replay(D(10), D(50), [entry('manual_correction', quantity=D(20), amount=D(80))])
    assert result.realized == 0
    assert result.cost == 80
    assert result.reasons


def test_reference_never_uses_future_and_seven_day_limit():
    rates = [(date(2026, 9, 24), D('7')), (date(2026, 10, 2), D('8'))]
    assert select_reference(date(2026, 10, 1), rates) == (date(2026, 9, 24), D('7'))
    assert select_reference(date(2026, 10, 2), rates[:1]) is None
