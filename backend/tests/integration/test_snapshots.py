from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.services.market_data as market_data_service
from app import worker
from app.db.models import MarketData, MarketDataOverride, Snapshot, SnapshotItem
from app.db.session import engine as app_engine
from app.providers.base import MarketQuote
from app.services.snapshots import create_daily_snapshot_if_complete


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def _holding_payload(
    asset_class_id: str,
    *,
    symbol: str = "SPY",
    account_name: str = "USD account",
) -> dict[str, object]:
    return {
        "asset_class_id": asset_class_id,
        "symbol": symbol,
        "name": "SPDR S&P 500 ETF Trust",
        "market": "US",
        "account_name": account_name,
        "trade_currency": "USD",
        "quantity": "3.000000000000",
        "average_cost_price": "90.000000000000",
        "cost_fx_to_cny": "7.000000000000",
        "baseline_fx_to_cny": "6.800000000000",
        "lot_size": "1.000000000000",
        "quantity_precision": 12,
        "is_rebalance_preferred": True,
    }


async def _seed_complete_portfolio(api_client, db_session) -> dict[str, object]:
    asset_class = (await api_client.get("/api/asset-classes")).json()[2]
    holding_response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class["id"]),
    )
    assert holding_response.status_code == 201, holding_response.text
    holding = holding_response.json()
    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="SPY",
                source="test-provider",
                value=Decimal("100.000000000000"),
                market_time=NOW,
                fetched_at=NOW,
                status="valid",
            ),
            MarketData(
                data_type="fx",
                symbol="USD/CNY",
                source="test-provider",
                value=Decimal("7.200000000000"),
                market_time=NOW,
                fetched_at=NOW,
                status="valid",
            ),
        ]
    )
    await db_session.commit()
    return {"asset_class": asset_class, "holding": holding}


async def test_daily_snapshot_is_upserted_for_same_configured_local_date(
    api_client,
    db_session,
) -> None:
    await _seed_complete_portfolio(api_client, db_session)
    timezone = ZoneInfo("Asia/Shanghai")

    first = await create_daily_snapshot_if_complete(
        db_session,
        now=datetime(2026, 7, 14, 8, 5, tzinfo=timezone),
    )
    await db_session.commit()
    first_id = first.id
    first_captured_at = first.captured_at

    second = await create_daily_snapshot_if_complete(
        db_session,
        now=datetime(2026, 7, 14, 9, 10, tzinfo=timezone),
    )
    await db_session.commit()

    assert second.id == first_id
    assert second.captured_at > first_captured_at
    assert len(list(await db_session.scalars(select(Snapshot)))) == 1
    assert len(list(await db_session.scalars(select(SnapshotItem)))) == 1


async def test_daily_snapshot_uses_configured_timezone_across_utc_date_boundary(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _seed_complete_portfolio(api_client, db_session)
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")

    first = await create_daily_snapshot_if_complete(
        db_session,
        now=datetime(2026, 7, 13, 16, 30, tzinfo=UTC),
    )
    await db_session.commit()
    second = await create_daily_snapshot_if_complete(
        db_session,
        now=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
    )
    await db_session.commit()

    assert first.id == second.id
    assert second.local_date.isoformat() == "2026-07-14"


async def test_concurrent_daily_snapshot_attempts_share_one_row(api_client, db_session) -> None:
    await _seed_complete_portfolio(api_client, db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def capture(captured_at: datetime):
        async with factory() as session:
            async with session.begin():
                snapshot = await create_daily_snapshot_if_complete(session, now=captured_at)
            return snapshot.id

    ids = await asyncio.gather(
        capture(datetime(2026, 7, 14, 8, 5, tzinfo=ZoneInfo("Asia/Shanghai"))),
        capture(datetime(2026, 7, 14, 8, 6, tzinfo=ZoneInfo("Asia/Shanghai"))),
    )

    assert ids[0] == ids[1]
    assert len(list(await db_session.scalars(select(Snapshot)))) == 1
    assert len(list(await db_session.scalars(select(SnapshotItem)))) == 1


async def test_incomplete_market_data_skips_automatic_snapshot(api_client, db_session) -> None:
    asset_class = (await api_client.get("/api/asset-classes")).json()[2]
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class["id"]),
    )
    assert response.status_code == 201
    db_session.add(
        MarketData(
            data_type="price",
            symbol="SPY",
            source="test-provider",
            value=Decimal("100"),
            market_time=NOW,
            fetched_at=NOW,
            status="valid",
        )
    )
    await db_session.commit()

    result = await create_daily_snapshot_if_complete(db_session, now=NOW)

    assert result is None
    assert list(await db_session.scalars(select(Snapshot))) == []


async def test_worker_refresh_creates_daily_snapshot_with_refreshed_values(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    asset_class = (await api_client.get("/api/asset-classes")).json()[2]
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class["id"]),
    )
    assert response.status_code == 201

    class _Registry:
        async def fetch_price(self, symbol: str, **_kwargs) -> MarketQuote:
            return MarketQuote(
                key=f"price:{symbol}",
                symbol=symbol,
                value=Decimal("101.25"),
                currency="USD",
                source="smoke-provider",
                as_of=NOW,
                fetched_at=NOW,
            )

        async def fetch_fx(self, base: str, quote: str, **_kwargs) -> MarketQuote:
            return MarketQuote(
                key=f"fx:{base}/{quote}",
                symbol=f"{base}/{quote}",
                value=Decimal("7.22"),
                currency=quote,
                source="smoke-provider",
                as_of=NOW,
                fetched_at=NOW,
            )

    monkeypatch.setattr(market_data_service, "get_provider_registry", _Registry)

    await worker.scheduled_refresh()
    db_session.expire_all()

    snapshot = await db_session.scalar(select(Snapshot).where(Snapshot.snapshot_type == "daily"))
    item = await db_session.scalar(select(SnapshotItem).where(SnapshotItem.snapshot_id == snapshot.id))
    quotes = list(await db_session.scalars(select(MarketData).order_by(MarketData.data_type)))
    assert [(quote.data_type, quote.value, quote.status) for quote in quotes] == [
        ("fx", Decimal("7.220000000000"), "valid"),
        ("price", Decimal("101.250000000000"), "valid"),
    ]
    assert item.market_price == Decimal("101.250000000000")
    assert item.current_fx_to_cny == Decimal("7.220000000000")


async def test_snapshot_copies_complete_immutable_holding_payload(api_client, db_session) -> None:
    seeded = await _seed_complete_portfolio(api_client, db_session)

    response = await api_client.post("/api/snapshots/manual", json={"note": None})

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["snapshot_type"] == "manual"
    assert payload["data_complete"] is True
    assert payload["has_stale_data"] is False
    assert payload["has_manual_data"] is False
    assert payload["total_market_value_cny"] == "2160.000000000000"
    assert payload["total_cost_value_cny"] == "1890.000000000000"
    assert payload["total_unrealized_pnl_cny"] == "270.000000000000"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item == {
        "id": item["id"],
        "holding_id": seeded["holding"]["id"],
        "asset_class_name": seeded["asset_class"]["name"],
        "holding_name": "SPDR S&P 500 ETF Trust",
        "symbol": "SPY",
        "account_name": "USD account",
        "trade_currency": "USD",
        "quantity": "3.000000000000",
        "market_price": "100.000000000000",
        "current_fx_to_cny": "7.200000000000",
        "baseline_fx_to_cny": "6.800000000000",
        "average_cost_price": "90.000000000000",
        "cost_fx_to_cny": "7.000000000000",
        "target_weight": "0.300000000000",
        "market_value_cny": "2160.000000000000",
        "fx_neutral_value_cny": "2040.000000000000",
        "cost_value_cny": "1890.000000000000",
        "unrealized_pnl_amount_cny": "270.000000000000",
        "unrealized_pnl_rate": "0.142857142857",
        "price_effect_cny": "210.000000000000",
        "fx_effect_cny": "60.000000000000",
        "actual_weight": "1.000000000000",
        "fx_neutral_weight": "1.000000000000",
        "price_status": "valid",
        "fx_status": "valid",
    }

    holding_response = await api_client.patch(
        f"/api/holdings/{seeded['holding']['id']}",
        json={"name": "Renamed", "quantity": "4"},
    )
    assert holding_response.status_code == 200
    detail = await api_client.get(f"/api/snapshots/{payload['id']}")
    assert detail.json()["items"][0]["holding_name"] == "SPDR S&P 500 ETF Trust"
    assert detail.json()["items"][0]["quantity"] == "3.000000000000"


async def test_manual_snapshots_are_append_only(api_client, db_session) -> None:
    await _seed_complete_portfolio(api_client, db_session)

    first = await api_client.post("/api/snapshots/manual", json={"note": "first"})
    second = await api_client.post("/api/snapshots/manual", json={"note": "second"})

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(list(await db_session.scalars(select(Snapshot)))) == 2


async def test_manual_snapshot_requires_note_for_stale_or_manual_inputs(
    api_client,
    db_session,
) -> None:
    seeded = await _seed_complete_portfolio(api_client, db_session)
    db_session.add(
        MarketDataOverride(
            data_type="fx",
            symbol="USD/CNY",
            value=Decimal("7.25"),
            note="broker settlement rate",
            effective_at=datetime.now(UTC) - timedelta(minutes=5),
            expires_at=None,
        )
    )
    await db_session.commit()

    missing_note = await api_client.post("/api/snapshots/manual", json={"note": "  "})
    assert missing_note.status_code == 422
    assert missing_note.json()["detail"] == {
        "code": "SNAPSHOT_NOTE_REQUIRED",
        "message": "A note is required when snapshot inputs are stale or manually overridden.",
        "has_stale_data": False,
        "has_manual_data": True,
        "items": [
            {
                "holding_id": seeded["holding"]["id"],
                "symbol": "SPY",
                "input": "fx",
                "status": "manual",
            }
        ],
    }

    created = await api_client.post(
        "/api/snapshots/manual",
        json={"note": "使用券商结算汇率"},
    )
    assert created.status_code == 201
    assert created.json()["has_manual_data"] is True
    assert created.json()["note"] == "使用券商结算汇率"


async def test_list_filters_orders_and_paginates_without_loading_items(
    api_client,
    db_session,
) -> None:
    await _seed_complete_portfolio(api_client, db_session)
    await api_client.post("/api/snapshots/manual", json={"note": "older"})
    await api_client.post("/api/snapshots/manual", json={"note": "newer"})
    await create_daily_snapshot_if_complete(
        db_session,
        now=datetime(2026, 7, 14, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    await db_session.commit()

    query_count = 0

    def count_queries(*_args) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(app_engine.sync_engine, "before_cursor_execute", count_queries)
    try:
        response = await api_client.get(
            "/api/snapshots",
            params={"snapshot_type": "manual", "page": 1, "page_size": 1},
        )
    finally:
        event.remove(app_engine.sync_engine, "before_cursor_execute", count_queries)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["total"] == 2
    assert payload["items"][0]["note"] == "newer"
    assert "items" not in payload["items"][0]
    assert query_count <= 2


async def test_detail_loads_items_in_one_bounded_query_set(api_client, db_session) -> None:
    await _seed_complete_portfolio(api_client, db_session)
    created = await api_client.post("/api/snapshots/manual", json={"note": "detail"})
    query_count = 0

    def count_queries(*_args) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(app_engine.sync_engine, "before_cursor_execute", count_queries)
    try:
        response = await api_client.get(f"/api/snapshots/{created.json()['id']}")
    finally:
        event.remove(app_engine.sync_engine, "before_cursor_execute", count_queries)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert query_count <= 2


async def test_snapshot_not_found_returns_structured_error(api_client) -> None:
    response = await api_client.get("/api/snapshots/00000000-0000-4000-8000-000000000099")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "SNAPSHOT_NOT_FOUND",
        "message": "Snapshot was not found.",
    }
