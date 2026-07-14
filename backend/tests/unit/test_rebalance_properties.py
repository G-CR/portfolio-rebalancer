from decimal import Decimal, localcontext

from hypothesis import given, settings, strategies as st

from app.domain.rebalance import AssetInput, CashInput, RebalanceOptions, rebalance


money = st.decimals(
    min_value="0",
    max_value="1000000",
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
positive_price = st.decimals(
    min_value="0.01",
    max_value="10000",
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
cash_value = st.decimals(
    min_value="0",
    max_value="100000",
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def portfolios(draw: st.DrawFn) -> tuple[tuple[AssetInput, ...], CashInput]:
    first_value = draw(money)
    second_value = draw(money)
    first_price = draw(positive_price)
    second_price = draw(positive_price)
    cash = CashInput(
        draw(cash_value),
        draw(cash_value) / Decimal("7.2"),
        Decimal("7.2"),
    )
    assets = (
        AssetInput(
            "a", "AAA", "CNY", first_value, Decimal("0.5"), first_price, Decimal("1")
        ),
        AssetInput(
            "b", "BBB", "USD", second_value, Decimal("0.5"), second_price, Decimal("1")
        ),
    )
    return assets, cash


@given(portfolios())
@settings(max_examples=80)
def test_disabled_actions_never_appear(
    value: tuple[tuple[AssetInput, ...], CashInput],
) -> None:
    assets, cash = value
    no_actions = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0.02"), Decimal("0"), False, False),
    )
    no_sells = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0.02"), Decimal("0"), False, True),
    )
    no_fx = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0.02"), Decimal("0"), True, False),
    )

    assert all(trade.action != "sell" for trade in no_actions.trades)
    assert no_actions.fx_required_cny == 0
    assert all(trade.action != "sell" for trade in no_sells.trades)
    assert no_fx.fx_required_cny == 0


@given(portfolios())
@settings(max_examples=80)
def test_spending_is_bounded_lots_are_exact_and_outputs_nonnegative(
    value: tuple[tuple[AssetInput, ...], CashInput],
) -> None:
    assets, cash = value
    result = rebalance(
        assets,
        cash,
        RebalanceOptions(Decimal("0.02"), Decimal("0"), True, True),
    )
    by_symbol = {asset.symbol: asset for asset in assets}
    buy_cny = sum(
        (trade.amount_cny for trade in result.trades if trade.action == "buy"),
        Decimal("0"),
    )
    sale_cny = sum(
        (trade.amount_cny for trade in result.trades if trade.action == "sell"),
        Decimal("0"),
    )
    starting_cny = cash.cny + cash.usd * cash.usd_cny

    assert buy_cny <= starting_cny + sale_cny
    assert result.fx_required_cny <= cash.cny + sum(
        (
            trade.amount_cny
            for trade in result.trades
            if trade.action == "sell"
            and by_symbol[trade.symbol].currency == "CNY"
        ),
        Decimal("0"),
    )
    assert result.remaining_cny >= 0
    assert result.remaining_usd >= 0
    assert result.max_drift_before >= 0
    assert result.max_drift_after >= 0
    for weight in result.projected_weights:
        assert weight.before >= 0
        assert weight.after >= 0
        assert weight.target >= 0
    for trade in result.trades:
        asset = by_symbol[trade.symbol]
        assert trade.quantity >= 0
        assert trade.amount_cny >= 0
        assert trade.amount_trade_currency >= 0
        assert trade.quantity % asset.lot_size == 0


@given(portfolios())
@settings(max_examples=60)
def test_result_is_deterministic_context_independent_and_inputs_are_unchanged(
    value: tuple[tuple[AssetInput, ...], CashInput],
) -> None:
    assets, cash = value
    before = tuple(assets)
    options = RebalanceOptions(Decimal("0.02"), Decimal("10"), True, True)
    expected = rebalance(assets, cash, options)

    with localcontext() as context:
        context.prec = 3
        actual = rebalance(tuple(assets), cash, options)

    assert actual == expected
    assert assets == before
    assert len(actual.trades) == len(
        {(trade.symbol, trade.action) for trade in actual.trades}
    )


def test_pnl_fields_cannot_influence_the_engine_contract() -> None:
    fields = set(AssetInput.__dataclass_fields__)

    assert fields == {
        "asset_class_id",
        "symbol",
        "currency",
        "current_value_cny",
        "target_weight",
        "unit_price_cny",
        "lot_size",
    }
