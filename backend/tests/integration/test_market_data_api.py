from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select, update

from app.db.models import Holding, MarketData, MarketDataOverride
from app.providers.base import MarketQuote
from app.services import market_data as market_data_service


def _holding_payload(
    asset_class_id: str,
    *,
    symbol: str,
    account_name: str,
    market: str = "US",
    trade_currency: str = "USD",
) -> dict[str, object]:
    return {
        "asset_class_id": asset_class_id,
        "symbol": symbol,
        "name": symbol,
        "market": market,
        "account_name": account_name,
        "trade_currency": trade_currency,
        "quantity": "10",
        "average_cost_price": "500",
        "cost_fx_to_cny": "7.20",
        "baseline_fx_to_cny": "7.20",
        "lot_size": "1",
        "quantity_precision": 0,
        "is_rebalance_preferred": True,
    }


class _FakeRegistry:
    def __init__(self) -> None:
        self.price_calls: list[tuple[str, str, str | None]] = []
        self.fx_calls: list[tuple[str, str, str | None]] = []

    async def fetch_price(
        self,
        symbol: str,
        *,
        market: str,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        self.price_calls.append((symbol, market, preferred_source))
        if symbol == "SPY":
            return MarketQuote(
                key="price:SPY",
                symbol="SPY",
                value=Decimal("652.10"),
                currency="USD",
                source="yahoo",
                as_of=datetime(2026, 7, 14, 20, 0, tzinfo=UTC),
                fetched_at=datetime(2026, 7, 14, 20, 5, tzinfo=UTC),
            )
        if symbol == "510300":
            return MarketQuote(
                key="price:510300",
                symbol="510300",
                value=Decimal("3.455"),
                currency="CNY",
                source="akshare",
                as_of=datetime(2026, 7, 14, 7, 0, tzinfo=UTC),
                fetched_at=datetime(2026, 7, 14, 7, 5, tzinfo=UTC),
            )
        raise AssertionError(f"unexpected price symbol {symbol}")

    async def fetch_fx(
        self,
        base: str,
        quote: str,
        *,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        self.fx_calls.append((base, quote, preferred_source))
        raise RuntimeError("timeout while refreshing USD/CNY\ntraceback hidden")


class _FailingRegistry:
    async def fetch_price(
        self,
        symbol: str,
        *,
        market: str,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        raise RuntimeError(f"timeout while refreshing {symbol}\nsecret detail")

    async def fetch_fx(
        self,
        base: str,
        quote: str,
        *,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        raise RuntimeError(f"timeout while refreshing {base}/{quote}\nsecret detail")


class _ProviderSelectionFailingRegistry:
    async def fetch_price(
        self,
        symbol: str,
        *,
        market: str,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        raise market_data_service.ProviderSelectionError(
            [
                market_data_service.ProviderAttempt(
                    "akshare", "provider_request_failed"
                ),
                market_data_service.ProviderAttempt(
                    "tushare", "provider_not_configured"
                ),
            ]
        )

    async def fetch_fx(
        self,
        base: str,
        quote: str,
        *,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        raise AssertionError("CNY holdings do not require an external FX quote")


class _OversizedQuoteRegistry(_FakeRegistry):
    async def fetch_price(
        self,
        symbol: str,
        *,
        market: str,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ):
        return SimpleNamespace(
            source="yahoo",
            value=Decimal("10000000000000000"),
            as_of=datetime(2026, 7, 14, 20, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 14, 20, 5, tzinfo=UTC),
        )

    async def fetch_fx(
        self,
        base: str,
        quote: str,
        *,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        return MarketQuote(
            key=f"fx:{base}/{quote}",
            symbol=f"{base}/{quote}",
            value=Decimal("7.20"),
            currency=quote,
            source="yahoo",
            as_of=datetime(2026, 7, 14, 20, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 14, 20, 5, tzinfo=UTC),
        )


class _DatabaseFailingRegistry(_OversizedQuoteRegistry):
    async def fetch_price(
        self,
        symbol: str,
        *,
        market: str,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        return MarketQuote(
            key=f"price:{symbol}",
            symbol=symbol,
            value=Decimal("650.25"),
            currency="USD",
            source="x" * 65,
            as_of=datetime(2026, 7, 14, 20, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 14, 20, 5, tzinfo=UTC),
        )


async def test_get_market_data_reports_legacy_invalid_holding_configuration(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    created = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    await db_session.execute(
        update(Holding)
        .where(Holding.id == created.json()["id"])
        .values(market="MOON", trade_currency="USDT")
    )
    await db_session.commit()

    response = await api_client.get("/api/market-data")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["diagnostics"] == [
        {
            "code": "HOLDING_MARKET_DATA_CONFIG_INVALID",
            "message": "Holding market-data configuration is invalid.",
            "holding_id": created.json()["id"],
            "symbol": "SPY",
            "fields": ["market", "trade_currency"],
        }
    ]


async def test_first_refresh_failure_is_reported_without_an_effective_value(
    api_client,
    monkeypatch,
    caplog,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    monkeypatch.setattr(
        market_data_service,
        "get_provider_registry",
        lambda: _FailingRegistry(),
    )

    refresh_response = await api_client.post("/api/market-data/refresh")
    assert refresh_response.status_code == 200

    response = await api_client.get("/api/market-data")
    assert response.status_code == 200
    item = {item["key"]: item for item in response.json()["items"]}["price:SPY"]
    assert item["effective_value"] is None
    assert item["status"] == "failed"
    assert item["source"] == "yahoo"
    assert item["market_time"] is None
    assert item["fetched_at"] is not None
    assert item["error_summary"] == (
        "provider_internal_error: Market-data provider failed unexpectedly."
    )
    assert "secret detail" not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_provider_attempt_diagnostics_survive_storage_round_trip(
    api_client,
    monkeypatch,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            symbol="563020",
            account_name="Broker 1",
            market="SH",
            trade_currency="CNY",
        ),
    )
    monkeypatch.setattr(
        market_data_service,
        "get_provider_registry",
        lambda: _ProviderSelectionFailingRegistry(),
    )

    refresh_response = await api_client.post("/api/market-data/refresh")
    assert refresh_response.status_code == 200

    response = await api_client.get("/api/market-data")
    item = {item["key"]: item for item in response.json()["items"]}["price:563020"]
    assert item["source"] == "akshare"
    assert item["status"] == "failed"
    assert item["error_summary"] == (
        "akshare: provider_request_failed; tushare: provider_not_configured"
    )
    assert "SECRET" not in response.text
    assert "http" not in item["error_summary"]


async def test_active_override_takes_precedence_over_failed_only_state(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    now = datetime.now(UTC)
    db_session.add(
        MarketData(
            data_type="price",
            symbol="SPY",
            source="yahoo",
            value=None,
            market_time=None,
            fetched_at=now - timedelta(minutes=5),
            status="failed",
            error_summary="https://provider.invalid/path?token=LEGACY-SECRET",
        )
    )
    await db_session.commit()

    override_response = await api_client.post(
        "/api/market-data/price:SPY/override",
        json={
            "value": "649.90",
            "note": "broker close",
            "effective_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        },
    )
    assert override_response.status_code == 200

    response = await api_client.get("/api/market-data")
    item = {item["key"]: item for item in response.json()["items"]}["price:SPY"]
    assert item["effective_value"] == "649.90"
    assert item["status"] == "manual"
    assert item["source"] == "manual"
    assert item["error_summary"] is None


async def test_expired_override_reveals_failed_only_state(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    now = datetime.now(UTC)
    failed_at = now - timedelta(minutes=5)
    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="SPY",
                source="yahoo",
                value=None,
                market_time=None,
                fetched_at=failed_at,
                status="failed",
                error_summary="https://provider.invalid/path?token=LEGACY-SECRET",
            ),
            MarketDataOverride(
                data_type="price",
                symbol="SPY",
                value=Decimal("649.90"),
                note="expired broker close",
                effective_at=now - timedelta(hours=1),
                expires_at=now - timedelta(minutes=1),
            ),
        ]
    )
    await db_session.commit()

    response = await api_client.get("/api/market-data")
    item = {item["key"]: item for item in response.json()["items"]}["price:SPY"]
    assert item["effective_value"] is None
    assert item["status"] == "failed"
    assert item["source"] == "yahoo"
    assert item["market_time"] is None
    assert item["fetched_at"] == failed_at.isoformat().replace("+00:00", "Z")
    assert item["error_summary"] == (
        "legacy_refresh_error: Previous market-data refresh failed."
    )
    assert "LEGACY-SECRET" not in item["error_summary"]


async def test_get_market_data_resolves_manual_override_and_stale_fallback(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="QQQ", account_name="Broker 2"),
    )

    now = datetime.now(UTC)
    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="SPY",
                source="yahoo",
                value=Decimal("651.28"),
                market_time=now - timedelta(hours=12),
                fetched_at=now - timedelta(hours=2),
                status="valid",
            ),
            MarketData(
                data_type="price",
                symbol="QQQ",
                source="yahoo",
                value=Decimal("530.25"),
                market_time=now - timedelta(days=1),
                fetched_at=now - timedelta(days=1, minutes=5),
                status="valid",
            ),
            MarketData(
                data_type="price",
                symbol="QQQ",
                source="yahoo",
                value=None,
                market_time=None,
                fetched_at=now - timedelta(minutes=15),
                status="failed",
                error_summary="https://provider.invalid/path?token=LEGACY-SECRET",
            ),
            MarketData(
                data_type="fx",
                symbol="USD/CNY",
                source="yahoo",
                value=Decimal("7.19"),
                market_time=now - timedelta(hours=12),
                fetched_at=now - timedelta(hours=2),
                status="valid",
            ),
            MarketDataOverride(
                data_type="price",
                symbol="SPY",
                value=Decimal("650.10"),
                note="券商结算参考",
                effective_at=now - timedelta(hours=1),
                expires_at=None,
            ),
        ]
    )
    await db_session.commit()

    response = await api_client.get("/api/market-data")

    assert response.status_code == 200
    items = {item["key"]: item for item in response.json()["items"]}
    assert items["price:SPY"]["effective_value"] == "650.10"
    assert items["price:SPY"]["status"] == "manual"
    assert items["price:SPY"]["source"] == "manual"
    assert items["price:QQQ"]["effective_value"] == "530.25"
    assert items["price:QQQ"]["status"] == "stale"
    assert items["price:QQQ"]["error_summary"] == (
        "legacy_refresh_error: Previous market-data refresh failed."
    )
    assert items["fx:USD/CNY"]["effective_value"] == "7.19"
    assert items["fx:USD/CNY"]["status"] == "valid"


async def test_late_backfill_does_not_replace_newer_market_time(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    now = datetime.now(UTC)
    newest_market_time = now - timedelta(hours=1)
    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="SPY",
                source="yahoo",
                value=Decimal("652.10"),
                market_time=newest_market_time,
                fetched_at=now - timedelta(hours=3),
                status="valid",
            ),
            MarketData(
                data_type="price",
                symbol="SPY",
                source="alpha_vantage",
                value=Decimal("640.00"),
                market_time=now - timedelta(days=2),
                fetched_at=now - timedelta(minutes=30),
                status="valid",
            ),
        ]
    )
    await db_session.commit()

    response = await api_client.get("/api/market-data")

    item = {item["key"]: item for item in response.json()["items"]}["price:SPY"]
    assert item["effective_value"] == "652.10"
    assert item["source"] == "yahoo"
    assert item["status"] == "valid"
    assert item["market_time"] == newest_market_time.isoformat().replace("+00:00", "Z")


async def test_later_failure_marks_newest_market_time_quote_stale(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    now = datetime.now(UTC)
    newest_market_time = now - timedelta(hours=1)
    failed_at = now - timedelta(minutes=5)
    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="SPY",
                source="yahoo",
                value=Decimal("652.10"),
                market_time=newest_market_time,
                fetched_at=now - timedelta(hours=3),
                status="valid",
            ),
            MarketData(
                data_type="price",
                symbol="SPY",
                source="alpha_vantage",
                value=Decimal("640.00"),
                market_time=now - timedelta(days=2),
                fetched_at=now - timedelta(minutes=30),
                status="valid",
            ),
            MarketData(
                data_type="price",
                symbol="SPY",
                source="alpha_vantage",
                value=None,
                market_time=None,
                fetched_at=failed_at,
                status="failed",
                error_summary=(
                    "provider_request_failed: Market-data provider request failed."
                ),
            ),
        ]
    )
    await db_session.commit()

    response = await api_client.get("/api/market-data")

    item = {item["key"]: item for item in response.json()["items"]}["price:SPY"]
    assert item["effective_value"] == "652.10"
    assert item["source"] == "yahoo"
    assert item["status"] == "stale"
    assert item["market_time"] == newest_market_time.isoformat().replace("+00:00", "Z")
    assert item["fetched_at"] == failed_at.isoformat().replace("+00:00", "Z")
    assert item["error_summary"] == (
        "provider_request_failed: Market-data provider request failed."
    )


async def test_refresh_deduplicates_required_keys_and_preserves_last_valid_value(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 2"),
    )
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            symbol="510300",
            account_name="Broker CN",
            market="SH",
            trade_currency="CNY",
        ),
    )

    db_session.add(
        MarketData(
            data_type="fx",
            symbol="USD/CNY",
            source="yahoo",
            value=Decimal("7.17"),
            market_time=datetime.now(UTC) - timedelta(days=1),
            fetched_at=datetime.now(UTC) - timedelta(days=1, minutes=-5),
            status="valid",
        )
    )
    await db_session.commit()

    registry = _FakeRegistry()
    monkeypatch.setattr(market_data_service, "get_provider_registry", lambda: registry)

    response = await api_client.post("/api/market-data/refresh")

    assert response.status_code == 200
    assert registry.price_calls == [
        ("510300", "SH", None),
        ("SPY", "US", None),
    ]
    assert registry.fx_calls == [("USD", "CNY", None)]

    items = {item["key"]: item for item in response.json()["items"]}
    assert items["price:SPY"]["effective_value"] == "652.10"
    assert items["price:510300"]["effective_value"] == "3.455"
    assert items["fx:USD/CNY"]["effective_value"] == "7.17"
    assert items["fx:USD/CNY"]["status"] == "stale"
    assert items["fx:USD/CNY"]["error_summary"] == (
        "provider_internal_error: Market-data provider failed unexpectedly."
    )

    failure_row = await db_session.scalar(
        select(MarketData)
        .where(
            MarketData.data_type == "fx",
            MarketData.symbol == "USD/CNY",
            MarketData.status == "failed",
        )
        .order_by(MarketData.fetched_at.desc())
    )
    assert failure_row is not None
    assert failure_row.value is None
    assert failure_row.error_summary == (
        "provider_internal_error: Market-data provider failed unexpectedly."
    )
    assert "timeout while refreshing" not in failure_row.error_summary


async def test_refresh_rejects_oversized_provider_quote_before_postgres_write(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    monkeypatch.setattr(
        market_data_service,
        "get_provider_registry",
        lambda: _OversizedQuoteRegistry(),
    )

    response = await api_client.post("/api/market-data/refresh")

    assert response.status_code == 200
    item = {item["key"]: item for item in response.json()["items"]}["price:SPY"]
    assert item["status"] == "failed"
    assert item["effective_value"] is None
    assert item["error_summary"] == (
        "provider_payload_invalid: Market-data provider returned invalid data."
    )
    rows = list(
        await db_session.scalars(
            select(MarketData).where(MarketData.symbol == "SPY")
        )
    )
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].value is None


async def test_refresh_database_error_rolls_back_without_failure_row_fallback(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )
    monkeypatch.setattr(
        market_data_service,
        "get_provider_registry",
        lambda: _DatabaseFailingRegistry(),
    )

    response = await api_client.post("/api/market-data/refresh")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "MARKET_DATA_STORAGE_ERROR",
        "message": "Market-data storage operation failed.",
    }
    assert list(await db_session.scalars(select(MarketData))) == []


async def test_override_routes_apply_validate_and_delete(api_client) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )

    invalid_response = await api_client.post(
        "/api/market-data/price:SPY/override",
        json={
            "value": "0",
            "note": "",
            "effective_at": (datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        },
    )
    assert invalid_response.status_code == 422

    create_response = await api_client.post(
        "/api/market-data/price:SPY/override",
        json={
            "value": "649.90",
            "note": "券商结算价",
            "effective_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["key"] == "price:SPY"
    assert created["effective_value"] == "649.90"
    assert created["status"] == "manual"

    delete_response = await api_client.delete("/api/market-data/price:SPY/override")
    assert delete_response.status_code == 204

    listed = await api_client.get("/api/market-data")
    items = {item["key"]: item for item in listed.json()["items"]}
    assert items["price:SPY"]["status"] == "missing"


async def test_override_rejects_non_ascii_fx_currency_key(api_client) -> None:
    response = await api_client.post(
        "/api/market-data/fx:人民币/CNY/override",
        json={"value": "7.20", "note": "invalid key"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MARKET_DATA_KEY_INVALID"


async def test_override_rejects_value_outside_numeric_storage_bounds(
    api_client,
    db_session,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, symbol="SPY", account_name="Broker 1"),
    )

    response = await api_client.post(
        "/api/market-data/price:SPY/override",
        json={"value": "10000000000000000", "note": "oversized"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "MARKET_DATA_NUMERIC_OUT_OF_RANGE",
        "message": "Market-data values must fit NUMERIC(28,12).",
        "field": "value",
    }
    assert list(await db_session.scalars(select(MarketDataOverride))) == []
