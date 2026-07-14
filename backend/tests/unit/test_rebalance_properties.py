from decimal import Decimal, localcontext

from hypothesis import assume, given, settings, strategies as st

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


@given(
    usd_value=st.integers(min_value=1, max_value=500),
    cny_value=st.integers(min_value=0, max_value=500),
    cny_cash=st.integers(min_value=1, max_value=500),
    cny_lot_value=st.integers(min_value=1, max_value=200),
    usd_lot_value=st.integers(min_value=1, max_value=200),
)
@settings(max_examples=120)
def test_fx_pass_never_buys_a_class_overweight_after_same_currency_pass(
    usd_value: int,
    cny_value: int,
    cny_cash: int,
    cny_lot_value: int,
    usd_lot_value: int,
) -> None:
    assets = (
        AssetInput(
            "usd",
            "USD-FUND",
            "USD",
            Decimal(usd_value),
            Decimal("0.5"),
            Decimal(usd_lot_value),
            Decimal("1"),
        ),
        AssetInput(
            "cny",
            "CNY-FUND",
            "CNY",
            Decimal(cny_value),
            Decimal("0.5"),
            Decimal(cny_lot_value),
            Decimal("1"),
        ),
    )
    cash = CashInput(Decimal(cny_cash), Decimal("0"), Decimal("1"))
    options_without_fx = RebalanceOptions(
        Decimal("0.02"), Decimal("0"), False, False
    )
    options_with_fx = RebalanceOptions(
        Decimal("0.02"), Decimal("0"), False, True
    )
    without_fx = rebalance(assets, cash, options_without_fx)
    usd_after_same_currency = next(
        weight.after
        for weight in without_fx.projected_weights
        if weight.asset_class_id == "usd"
    )
    assume(usd_after_same_currency >= Decimal("0.5"))

    with_fx = rebalance(assets, cash, options_with_fx)

    assert all(
        not (trade.symbol == "USD-FUND" and trade.action == "buy")
        for trade in with_fx.trades
    )
    assert with_fx.max_drift_after <= without_fx.max_drift_after


@given(
    first_value=st.integers(min_value=1, max_value=999),
    cny_cash=st.integers(min_value=0, max_value=1000),
    usd_cash=st.integers(min_value=0, max_value=1000),
    tolerance=st.integers(min_value=0, max_value=50),
    minimum_trade=st.integers(min_value=0, max_value=100),
    allow_sell=st.booleans(),
    allow_fx=st.booleans(),
)
@settings(max_examples=100)
def test_before_metrics_match_original_weights_independent_of_cash_and_options(
    first_value: int,
    cny_cash: int,
    usd_cash: int,
    tolerance: int,
    minimum_trade: int,
    allow_sell: bool,
    allow_fx: bool,
) -> None:
    second_value = 1000 - first_value
    assets = (
        AssetInput(
            "first",
            "FIRST",
            "CNY",
            Decimal(first_value),
            Decimal("0.5"),
            Decimal("10"),
            Decimal("1"),
        ),
        AssetInput(
            "second",
            "SECOND",
            "USD",
            Decimal(second_value),
            Decimal("0.5"),
            Decimal("10"),
            Decimal("1"),
        ),
    )
    expected_weights = (
        Decimal(first_value) / Decimal("1000"),
        Decimal(second_value) / Decimal("1000"),
    )
    expected_drift = max(
        abs(expected_weights[0] - Decimal("0.5")),
        abs(expected_weights[1] - Decimal("0.5")),
    )
    baseline = rebalance(
        assets,
        CashInput(Decimal("0"), Decimal("0"), Decimal("1")),
        RebalanceOptions(Decimal("0"), Decimal("0"), False, False),
    )
    variant = rebalance(
        assets,
        CashInput(Decimal(cny_cash), Decimal(usd_cash), Decimal("1")),
        RebalanceOptions(
            Decimal(tolerance) / Decimal("100"),
            Decimal(minimum_trade),
            allow_sell,
            allow_fx,
        ),
    )

    assert tuple(
        weight.before for weight in baseline.projected_weights
    ) == expected_weights
    assert tuple(
        weight.before for weight in variant.projected_weights
    ) == expected_weights
    assert baseline.max_drift_before == expected_drift
    assert variant.max_drift_before == expected_drift
