from decimal import ROUND_DOWN, Decimal, localcontext
from itertools import permutations

from app.domain.rebalance import AssetInput, CashInput, RebalanceOptions, rebalance
from hypothesis import given, settings
from hypothesis import strategies as st


def _ratio(value: Decimal, total: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        return value / total if total else Decimal("0")


def _absolute_difference(value: Decimal, target: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        return abs(value - target)


@st.composite
def bounded_portfolios(
    draw: st.DrawFn,
) -> tuple[tuple[AssetInput, ...], CashInput]:
    first_lot_size = Decimal(draw(st.sampled_from((1, 2, 5))))
    second_lot_size = Decimal(draw(st.sampled_from((1, 2, 5))))
    first_inventory_lots = draw(st.integers(min_value=0, max_value=8))
    second_inventory_lots = draw(st.integers(min_value=0, max_value=8))
    first_value = Decimal(draw(st.integers(min_value=0, max_value=80))) * Decimal("10")
    second_value = Decimal(draw(st.integers(min_value=0, max_value=80))) * Decimal("10")
    cny_cash = Decimal(draw(st.integers(min_value=0, max_value=8))) * Decimal("10")
    usd_cash = Decimal(draw(st.integers(min_value=0, max_value=8)))
    assets = (
        AssetInput(
            "a",
            "AAA",
            "CNY",
            first_value,
            Decimal("0.5"),
            Decimal("10") / first_lot_size,
            first_lot_size,
            Decimal(first_inventory_lots) * first_lot_size,
        ),
        AssetInput(
            "b",
            "BBB",
            "USD",
            second_value,
            Decimal("0.5"),
            Decimal("10") / second_lot_size,
            second_lot_size,
            Decimal(second_inventory_lots) * second_lot_size,
        ),
    )
    return assets, CashInput(cny_cash, usd_cash, Decimal("10"))


@given(bounded_portfolios(), st.booleans(), st.booleans())
@settings(max_examples=80, deadline=None)
def test_lots_inventory_cash_fx_and_disabled_actions_are_exact(
    value: tuple[tuple[AssetInput, ...], CashInput],
    allow_sell: bool,
    allow_fx: bool,
) -> None:
    assets, cash = value
    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0.02"), allow_sell, allow_fx),
    )
    by_symbol = {asset.symbol: asset for asset in assets}

    assert result.remaining_cny >= 0
    assert result.remaining_usd >= 0
    assert result.net_fx_direction in {"cny_to_usd", "usd_to_cny", "none"}
    assert result.net_fx_amount_cny >= 0
    assert result.fx_required_cny == (
        result.net_fx_amount_cny
        if result.net_fx_direction == "cny_to_usd"
        else Decimal("0")
    )
    if not allow_sell:
        assert all(trade.action != "sell" for trade in result.trades)
        assert not result.sell_phase_used
    if not allow_fx:
        assert result.net_fx_direction == "none"
        assert result.net_fx_amount_cny == 0

    sold_by_symbol: dict[str, Decimal] = {}
    for trade in result.trades:
        asset = by_symbol[trade.symbol]
        assert trade.quantity > 0
        assert trade.quantity % asset.lot_size == 0
        assert trade.amount_cny == trade.quantity * asset.unit_price_cny
        assert trade.amount_trade_currency == (
            trade.amount_cny
            if asset.currency == "CNY"
            else trade.amount_cny / cash.usd_cny
        )
        if trade.action == "sell":
            sold_by_symbol[trade.symbol] = trade.quantity
            assert trade.reason_code == "REALLOCATE_OUTSIDE_TOLERANCE"
    for symbol, quantity in sold_by_symbol.items():
        assert quantity <= by_symbol[symbol].max_sell_quantity

    signed_cny = sum(
        (
            trade.amount_cny if trade.action == "sell" else -trade.amount_cny
            for trade in result.trades
            if by_symbol[trade.symbol].currency == "CNY"
        ),
        Decimal("0"),
    )
    signed_usd = sum(
        (
            trade.amount_trade_currency
            if trade.action == "sell"
            else -trade.amount_trade_currency
            for trade in result.trades
            if by_symbol[trade.symbol].currency == "USD"
        ),
        Decimal("0"),
    )
    fx_cny = (
        -result.net_fx_amount_cny
        if result.net_fx_direction == "cny_to_usd"
        else result.net_fx_amount_cny
        if result.net_fx_direction == "usd_to_cny"
        else Decimal("0")
    )
    fx_usd = -fx_cny / cash.usd_cny
    assert result.remaining_cny == cash.cny + signed_cny + fx_cny
    assert result.remaining_usd == cash.usd + signed_usd + fx_usd


@given(usd_cny=st.sampled_from((Decimal("3"), Decimal("7"))))
@settings(max_examples=2, deadline=None)
def test_multiple_usd_orders_conserve_repeating_currency_conversions(
    usd_cny: Decimal,
) -> None:
    assets = (
        AssetInput(
            "a",
            "A",
            "CNY",
            Decimal("2"),
            Decimal("0.5"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
        AssetInput(
            "b",
            "B",
            "USD",
            Decimal("0"),
            Decimal("0.25"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
        AssetInput(
            "c",
            "C",
            "USD",
            Decimal("0"),
            Decimal("0.25"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
        ),
    )
    cash = CashInput(Decimal("0"), Decimal("1"), usd_cny)
    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0"), False, False),
    )
    usd_trades = tuple(trade for trade in result.trades if trade.symbol in {"B", "C"})

    assert len(usd_trades) == 2
    with localcontext() as context:
        context.prec = 100
        context.rounding = ROUND_DOWN
        assert all(
            trade.amount_trade_currency == trade.amount_cny / cash.usd_cny
            for trade in usd_trades
        )
    with localcontext() as context:
        context.prec = 250
        assert result.remaining_usd == cash.usd - sum(
            (trade.amount_trade_currency for trade in usd_trades), Decimal("0")
        )


@given(bounded_portfolios(), st.booleans(), st.booleans())
@settings(max_examples=60, deadline=None)
def test_projected_state_is_conserved_and_metrics_are_exact(
    value: tuple[tuple[AssetInput, ...], CashInput],
    allow_sell: bool,
    allow_fx: bool,
) -> None:
    assets, cash = value
    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0.02"), allow_sell, allow_fx),
    )
    by_symbol = {asset.symbol: asset for asset in assets}
    final_values = {asset.asset_class_id: asset.current_value_cny for asset in assets}
    for trade in result.trades:
        asset = by_symbol[trade.symbol]
        direction = Decimal("1") if trade.action == "buy" else Decimal("-1")
        final_values[asset.asset_class_id] += direction * trade.amount_cny

    original_total = sum((asset.current_value_cny for asset in assets), Decimal("0"))
    final_total = sum(final_values.values(), Decimal("0"))
    projected = {weight.asset_class_id: weight for weight in result.projected_weights}
    expected_before_drifts = []
    expected_after_drifts = []
    for asset in assets:
        expected_before = _ratio(asset.current_value_cny, original_total)
        expected_after = _ratio(final_values[asset.asset_class_id], final_total)
        assert projected[asset.asset_class_id].before == expected_before
        assert projected[asset.asset_class_id].after == expected_after
        assert projected[asset.asset_class_id].target == asset.target_weight
        expected_before_drifts.append(
            _absolute_difference(expected_before, asset.target_weight)
        )
        expected_after_drifts.append(
            _absolute_difference(expected_after, asset.target_weight)
        )

    assert result.max_drift_before == max(expected_before_drifts)
    assert result.max_drift_after == max(expected_after_drifts)
    assert result.feasible == (result.max_drift_after <= Decimal("0.02"))


@given(bounded_portfolios(), st.booleans(), st.booleans())
@settings(max_examples=50, deadline=None)
def test_results_are_permutation_stable_immutable_and_precision_independent(
    value: tuple[tuple[AssetInput, ...], CashInput],
    allow_sell: bool,
    allow_fx: bool,
) -> None:
    assets, cash = value
    before = tuple(assets)
    options = RebalanceOptions(Decimal("0.02"), allow_sell, allow_fx)
    expected = rebalance(assets, cash, options)

    for permuted in permutations(assets):
        assert rebalance(permuted, cash, options) == expected
    with localcontext() as context:
        context.prec = 3
        assert rebalance(assets, cash, options) == expected
    assert assets == before
    result_symbols = [trade.symbol for trade in expected.trades]
    assert len(result_symbols) == len(set(result_symbols))


@given(
    preferred_lots=st.integers(min_value=0, max_value=5),
    extra_class_lots=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=40, deadline=None)
def test_sales_never_exceed_exact_preferred_inventory_cap(
    preferred_lots: int,
    extra_class_lots: int,
) -> None:
    lot_size = Decimal("2")
    price = Decimal("10")
    capped_quantity = Decimal(preferred_lots) * lot_size
    over_value = (capped_quantity + Decimal(extra_class_lots) * lot_size) * price
    assets = (
        AssetInput(
            "over",
            "OVER",
            "CNY",
            over_value,
            Decimal("0.1"),
            price,
            lot_size,
            capped_quantity,
        ),
        AssetInput(
            "under",
            "UNDER",
            "CNY",
            Decimal("10"),
            Decimal("0.9"),
            price,
            lot_size,
            Decimal("0"),
        ),
    )

    result = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("7.2")),
        RebalanceOptions(Decimal("0"), True, False),
    )

    sold = sum(
        (
            trade.quantity
            for trade in result.trades
            if trade.symbol == "OVER" and trade.action == "sell"
        ),
        Decimal("0"),
    )
    assert sold <= capped_quantity
