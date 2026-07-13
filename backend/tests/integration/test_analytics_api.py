from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import event, select, update

from app.db.models import Holding, MarketData, MarketDataOverride, Setting
from app.db.session import engine as app_engine


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def _holding_payload(
    asset_class_id: str,
    *,
    symbol: str,
    account_name: str,
    market: str = "SH",
    trade_currency: str = "CNY",
    quantity: str = "10",
    average_cost_price: str = "1",
    cost_fx_to_cny: str = "1",
    baseline_fx_to_cny: str = "1",
) -> dict[str, object]:
    return {
        "asset_class_id": asset_class_id,
        "symbol": symbol,
        "name": symbol,
        "market": market,
        "account_name": account_name,
        "trade_currency": trade_currency,
        "quantity": quantity,
        "average_cost_price": average_cost_price,
        "cost_fx_to_cny": cost_fx_to_cny,
        "baseline_fx_to_cny": baseline_fx_to_cny,
        "lot_size": "1",
        "quantity_precision": 12,
        "is_rebalance_preferred": True,
    }


async def _create_holding(api_client, asset_class_id: str, **overrides: object) -> dict:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_quote(
    db_session,
    *,
    data_type: str,
    symbol: str,
    value: str | None,
    status: str = "valid",
    source: str = "test-provider",
    market_time: datetime | None = NOW,
    fetched_at: datetime = NOW,
    error_summary: str | None = None,
) -> None:
    db_session.add(
        MarketData(
            data_type=data_type,
            symbol=symbol,
            source=source,
            value=Decimal(value) if value is not None else None,
            market_time=market_time,
            fetched_at=fetched_at,
            status=status,
            error_summary=error_summary,
        )
    )


async def test_empty_portfolio_returns_setup_state(api_client) -> None:
    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"]["status"] == "setup"
    assert payload["market_value_cny"] == "0"
    assert payload["asset_classes"] == []
    assert payload["holdings"] == []
    assert payload["data_inputs"] == []


async def test_zero_quantity_holding_without_quote_returns_setup_but_remains_in_crud(
    api_client,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[2]["id"]
    holding = await _create_holding(
        api_client,
        asset_class_id,
        symbol="ZERO",
        account_name="zero account",
        market="US",
        trade_currency="USD",
        quantity="0",
    )

    response = await api_client.get("/api/analytics/portfolio")
    holdings_response = await api_client.get("/api/holdings")

    assert response.status_code == 200, response.text
    assert response.json()["decision"]["status"] == "setup"
    assert response.json()["holdings"] == []
    assert response.json()["data_inputs"] == []
    assert [item["id"] for item in holdings_response.json()] == [holding["id"]]


async def test_zero_quantity_holding_with_quote_still_returns_setup(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await _create_holding(
        api_client,
        asset_class_id,
        symbol="ZERO-CNY",
        account_name="zero quoted account",
        quantity="0",
    )
    await _add_quote(db_session, data_type="price", symbol="ZERO-CNY", value="10")
    await db_session.commit()

    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 200, response.text
    assert response.json()["decision"]["status"] == "setup"
    assert response.json()["holdings"] == []
    assert response.json()["data_inputs"] == []


async def test_positive_position_with_zero_total_market_value_returns_setup(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await _create_holding(
        api_client,
        asset_class_id,
        symbol="ZERO-VALUE",
        account_name="zero value account",
        quantity="2",
    )
    await _add_quote(db_session, data_type="price", symbol="ZERO-VALUE", value="0")
    await db_session.commit()

    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 200, response.text
    assert response.json()["decision"]["status"] == "setup"
    assert response.json()["asset_classes"] == []
    assert response.json()["holdings"] == []


async def test_mixed_portfolio_excludes_zero_quantity_holding_from_inputs_and_positions(
    api_client,
    db_session,
) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    zero_holding = await _create_holding(
        api_client,
        asset_classes[2]["id"],
        symbol="ZERO-USD",
        account_name="zero USD account",
        market="US",
        trade_currency="USD",
        quantity="0",
    )
    positive_holding = await _create_holding(
        api_client,
        asset_classes[0]["id"],
        symbol="POSITIVE",
        account_name="positive account",
        quantity="2",
    )
    await _add_quote(db_session, data_type="price", symbol="POSITIVE", value="5")
    await db_session.commit()

    response = await api_client.get("/api/analytics/portfolio")
    holdings_response = await api_client.get("/api/holdings")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["holding_id"] for item in payload["holdings"]] == [positive_holding["id"]]
    assert [item["key"] for item in payload["data_inputs"]] == ["fx:CNY/CNY", "price:POSITIVE"]
    assert {item["id"] for item in holdings_response.json()} == {
        zero_holding["id"],
        positive_holding["id"],
    }


async def test_portfolio_aggregates_positions_with_exact_weights_and_pnl_identity(
    api_client,
    db_session,
) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    domestic = await _create_holding(
        api_client,
        asset_classes[0]["id"],
        symbol="510100",
        account_name="CNY account",
        quantity="100",
        average_cost_price="0.8",
    )
    overseas = await _create_holding(
        api_client,
        asset_classes[2]["id"],
        symbol="SPY",
        account_name="USD account",
        market="US",
        trade_currency="USD",
        quantity="3",
        average_cost_price="90",
        cost_fx_to_cny="7.0",
        baseline_fx_to_cny="6.8",
    )
    await _add_quote(db_session, data_type="price", symbol="510100", value="1.25")
    await _add_quote(db_session, data_type="price", symbol="SPY", value="100")
    await _add_quote(db_session, data_type="fx", symbol="USD/CNY", value="7.2")
    await db_session.commit()

    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["asset_classes"]) == 5
    assert sum(Decimal(item["actual_weight"]) for item in payload["asset_classes"]) == Decimal("1")
    assert sum(Decimal(item["fx_neutral_weight"]) for item in payload["asset_classes"]) == Decimal("1")
    assert all(len(item["actual_weight"].partition(".")[2]) == 12 for item in payload["asset_classes"])
    assert all(len(item["fx_neutral_weight"].partition(".")[2]) == 12 for item in payload["asset_classes"])
    assert Decimal(payload["unrealized_pnl"]) == (
        Decimal(payload["price_effect"]) + Decimal(payload["fx_effect"])
    )
    assert payload["decision"]["status"] in {"hold", "contribute", "rebalance"}
    assert payload["decision"]["reason"]
    assert payload["decision"]["max_drift"]
    assert payload["decision"]["fx_contribution"]
    assert payload["decision"]["primary_action"]

    by_holding = {item["holding_id"]: item for item in payload["holdings"]}
    assert Decimal(by_holding[domestic["id"]]["current_price"]) == Decimal("1.25")
    assert Decimal(by_holding[domestic["id"]]["current_fx_to_cny"]) == Decimal("1")
    assert Decimal(by_holding[domestic["id"]]["market_value_cny"]) == Decimal("125")
    assert Decimal(by_holding[overseas["id"]]["current_price"]) == Decimal("100")
    assert Decimal(by_holding[overseas["id"]]["current_fx_to_cny"]) == Decimal("7.2")
    assert Decimal(by_holding[overseas["id"]]["market_value_cny"]) == Decimal("2160")
    assert Decimal(by_holding[overseas["id"]]["unrealized_pnl"]) == Decimal("270")
    assert Decimal(by_holding[overseas["id"]]["cost_trade_currency"]) == Decimal("270")
    assert Decimal(by_holding[overseas["id"]]["market_value_trade_currency"]) == Decimal("300")
    assert Decimal(by_holding[overseas["id"]]["unrealized_pnl_trade_currency"]) == Decimal("30")


async def test_stale_and_manual_values_remain_usable_and_are_reported(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[2]["id"]
    holding = await _create_holding(
        api_client,
        asset_class_id,
        symbol="SPY",
        account_name="USD account",
        market="US",
        trade_currency="USD",
        quantity="2",
        average_cost_price="90",
        cost_fx_to_cny="7.0",
        baseline_fx_to_cny="6.9",
    )
    await _add_quote(
        db_session,
        data_type="price",
        symbol="SPY",
        value="101.5",
        fetched_at=NOW - timedelta(days=1),
        market_time=NOW - timedelta(days=1),
    )
    await _add_quote(
        db_session,
        data_type="price",
        symbol="SPY",
        value=None,
        status="failed",
        fetched_at=NOW,
        market_time=None,
        error_summary="provider_request_failed: hidden",
    )
    effective_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(
        MarketDataOverride(
            data_type="fx",
            symbol="USD/CNY",
            value=Decimal("7.25"),
            note="Broker settlement rate",
            effective_at=effective_at,
            expires_at=None,
        )
    )
    await db_session.commit()

    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["has_stale_data"] is True
    assert payload["has_manual_data"] is True
    inputs = {item["key"]: item for item in payload["data_inputs"]}
    assert inputs["price:SPY"]["status"] == "stale"
    assert Decimal(inputs["price:SPY"]["value"]) == Decimal("101.5")
    assert inputs["fx:USD/CNY"]["status"] == "manual"
    assert Decimal(inputs["fx:USD/CNY"]["value"]) == Decimal("7.25")
    analytics = payload["holdings"][0]
    assert analytics["holding_id"] == holding["id"]
    assert analytics["price_status"] == "stale"
    assert analytics["fx_status"] == "manual"
    assert analytics["market_value_cny"] != "0"


async def test_missing_or_failed_required_value_returns_structured_conflict(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[2]["id"]
    holding = await _create_holding(
        api_client,
        asset_class_id,
        symbol="SPY",
        account_name="USD account",
        market="US",
        trade_currency="USD",
    )
    await _add_quote(
        db_session,
        data_type="price",
        symbol="SPY",
        value=None,
        status="failed",
        market_time=None,
        error_summary="provider_request_failed: hidden",
    )
    await db_session.commit()

    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "PORTFOLIO_DATA_INCOMPLETE",
        "message": "Required portfolio market data is incomplete.",
        "items": [
            {
                "holding_id": holding["id"],
                "symbol": "SPY",
                "input": "price",
                "key": "price:SPY",
                "status": "failed",
                "value": None,
                "market_time": None,
                "source": "test-provider",
                "error_summary": "provider_request_failed: Market-data provider request failed.",
            },
            {
                "holding_id": holding["id"],
                "symbol": "SPY",
                "input": "fx",
                "key": "fx:USD/CNY",
                "status": "missing",
                "value": None,
                "market_time": None,
                "source": None,
                "error_summary": None,
            },
        ],
    }


async def test_decision_uses_configured_tolerance_without_mutating_holdings(
    api_client,
    db_session,
) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    quantities = ("20", "20", "30", "20", "10")
    holding_ids = []
    for index, (asset_class, quantity) in enumerate(zip(asset_classes, quantities, strict=True)):
        holding = await _create_holding(
            api_client,
            asset_class["id"],
            symbol=f"51010{index}",
            account_name=f"account-{index}",
            quantity=quantity,
        )
        holding_ids.append(holding["id"])
        await _add_quote(db_session, data_type="price", symbol=holding["symbol"], value="1")
    await db_session.commit()

    hold_response = await api_client.get("/api/analytics/portfolio")
    assert hold_response.status_code == 200
    assert hold_response.json()["decision"]["status"] == "hold"
    assert hold_response.json()["decision"]["title"] == "保持现状"

    await db_session.execute(update(Setting).values(default_tolerance=Decimal("0.000000000001")))
    await db_session.execute(
        update(Holding).where(Holding.id == holding_ids[0]).values(quantity=Decimal("20.1"))
    )
    await db_session.commit()
    before = list(await db_session.scalars(select(Holding.quantity).order_by(Holding.id)))

    decision_response = await api_client.get("/api/analytics/portfolio")

    assert decision_response.status_code == 200
    assert decision_response.json()["decision"]["status"] in {"contribute", "rebalance"}
    after = list(await db_session.scalars(select(Holding.quantity).order_by(Holding.id)))
    assert after == before


async def test_portfolio_query_count_is_bounded_for_many_holdings(api_client, db_session) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    for index in range(12):
        holding = await _create_holding(
            api_client,
            asset_classes[index % len(asset_classes)]["id"],
            symbol=f"SYM{index}",
            account_name=f"account-{index}",
        )
        await _add_quote(db_session, data_type="price", symbol=holding["symbol"], value="1")
    await db_session.commit()

    selects = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    event.listen(app_engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        response = await api_client.get("/api/analytics/portfolio")
    finally:
        event.remove(app_engine.sync_engine, "before_cursor_execute", count_selects)

    assert response.status_code == 200, response.text
    assert selects <= 5
