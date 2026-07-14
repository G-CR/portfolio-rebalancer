from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import itertools
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.models import AssetClass, Holding, MarketData, RebalancePlan, Snapshot, SnapshotItem
from app.db.session import SessionFactory
from app.main import app

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
_PLAN_COUNTER = itertools.count(1)


def _holding_payload(
    asset_class_id: str,
    *,
    symbol: str,
    name: str,
    market: str,
    trade_currency: str,
    quantity: str,
    average_cost_price: str,
    cost_fx_to_cny: str,
    baseline_fx_to_cny: str,
    lot_size: str,
    account_name: str,
) -> dict[str, object]:
    return {
        "asset_class_id": asset_class_id,
        "symbol": symbol,
        "name": name,
        "market": market,
        "account_name": account_name,
        "trade_currency": trade_currency,
        "quantity": quantity,
        "average_cost_price": average_cost_price,
        "cost_fx_to_cny": cost_fx_to_cny,
        "baseline_fx_to_cny": baseline_fx_to_cny,
        "lot_size": lot_size,
        "quantity_precision": 12,
        "is_rebalance_preferred": True,
    }


def _preview_payload() -> dict[str, object]:
    return {
        "session_token": "browser-session-1",
        "request_token": "preview-request-1",
        "available_cny": "0",
        "available_usd": "0",
        "valuation_basis": "actual",
        "allow_sell": True,
        "allow_fx": True,
        "tolerance": "0.05",
        "minimum_trade_cny": "0",
        "acknowledge_stale_data": False,
        "idempotency_key": "plan-create-1",
    }


async def _configure_two_class_portfolio(api_client, db_session) -> dict[str, object]:
    asset_classes = list(
        await db_session.scalars(select(AssetClass).order_by(AssetClass.display_order.asc(), AssetClass.id.asc()))
    )
    cny_class, usd_class = asset_classes[:2]
    cny_class.target_weight = Decimal("0.500000000000")
    usd_class.target_weight = Decimal("0.500000000000")
    for extra in asset_classes[2:]:
        extra.is_active = False
    await db_session.commit()

    cny_holding = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            str(cny_class.id),
            symbol="CNY-FUND",
            name="CNY Fund",
            market="SH",
            trade_currency="CNY",
            quantity="8",
            average_cost_price="90",
            cost_fx_to_cny="1",
            baseline_fx_to_cny="1",
            lot_size="1",
            account_name="Broker CNY",
        ),
    )
    assert cny_holding.status_code == 201, cny_holding.text
    usd_holding = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            str(usd_class.id),
            symbol="USD-FUND",
            name="USD Fund",
            market="US",
            trade_currency="USD",
            quantity="2",
            average_cost_price="18",
            cost_fx_to_cny="4.200000000000",
            baseline_fx_to_cny="4.000000000000",
            lot_size="1",
            account_name="Broker USD",
        ),
    )
    assert usd_holding.status_code == 201, usd_holding.text

    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="CNY-FUND",
                source="seed",
                value=Decimal("100.000000000000"),
                market_time=NOW,
                fetched_at=NOW,
                status="valid",
            ),
            MarketData(
                data_type="price",
                symbol="USD-FUND",
                source="seed",
                value=Decimal("20.000000000000"),
                market_time=NOW,
                fetched_at=NOW,
                status="valid",
            ),
            MarketData(
                data_type="fx",
                symbol="USD/CNY",
                source="seed",
                value=Decimal("5.000000000000"),
                market_time=NOW,
                fetched_at=NOW,
                status="valid",
            ),
        ]
    )
    await db_session.commit()

    return {
        "cny_holding_id": cny_holding.json()["id"],
        "usd_holding_id": usd_holding.json()["id"],
    }


async def _create_draft_plan(api_client, monkeypatch) -> dict[str, object]:
    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr(
        "app.services.rebalancing.refresh_all_required_data",
        _record_refresh,
    )

    counter = next(_PLAN_COUNTER)
    payload = _preview_payload()
    payload["request_token"] = f"preview-request-{counter}"
    payload["idempotency_key"] = f"plan-create-{counter}"
    response = await api_client.post("/api/rebalance/plans", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_start_rebalance_creates_before_snapshot_and_rejects_changed_inputs(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)

    first_start = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/start",
        json={"idempotency_key": "start-1"},
    )
    assert first_start.status_code == 200, first_start.text
    started = first_start.json()
    assert started["status"] == "in_progress"
    assert started["before_snapshot_id"] is not None
    assert started["after_snapshot_id"] is None

    before_snapshot = await db_session.scalar(
        select(Snapshot).where(Snapshot.id == started["before_snapshot_id"])
    )
    assert before_snapshot.snapshot_type == "rebalance_before"

    draft_two = await _create_draft_plan(api_client, monkeypatch)
    holding = await db_session.scalar(select(Holding).where(Holding.id == configured["usd_holding_id"]))
    holding.quantity = Decimal("3")
    await db_session.commit()

    rejected = await api_client.post(
        f"/api/rebalance/plans/{draft_two['id']}/start",
        json={"idempotency_key": "start-2"},
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == {
        "code": "REBALANCE_PLAN_CONFLICT",
        "message": "The saved rebalance plan no longer matches current holdings or market data.",
        "status": "stale_inputs",
    }


async def test_concurrent_start_attempts_create_only_one_before_snapshot(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)

    async def _start(idempotency_key: str) -> int:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/rebalance/plans/{draft['id']}/start",
                json={"idempotency_key": idempotency_key},
            )
            return response.status_code

    statuses = await asyncio.gather(_start("start-a"), _start("start-b"))
    plan = await db_session.scalar(select(RebalancePlan).where(RebalancePlan.id == draft["id"]))
    snapshot_count = await db_session.scalar(
        select(func.count())
        .select_from(Snapshot)
        .where(Snapshot.snapshot_type == "rebalance_before")
    )

    assert sorted(statuses) == [200, 409]
    assert plan.status == "in_progress"
    assert snapshot_count == 1


async def test_start_snapshot_uses_the_exact_price_row_captured_before_concurrent_append(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)
    captured_price = await db_session.scalar(
        select(MarketData).where(
            MarketData.data_type == "price",
            MarketData.symbol == "CNY-FUND",
        )
    )
    captured_price_id = str(captured_price.id)
    appended_ids: list[str] = []

    async def _append_newer_price(event: str, _capture) -> None:
        if event != "start":
            return
        async with SessionFactory() as concurrent_session:
            newer = MarketData(
                data_type="price",
                symbol="CNY-FUND",
                source="concurrent",
                value=Decimal("125.000000000000"),
                market_time=NOW + timedelta(minutes=1),
                fetched_at=NOW + timedelta(minutes=1),
                status="valid",
            )
            concurrent_session.add(newer)
            await concurrent_session.commit()
            appended_ids.append(str(newer.id))

    monkeypatch.setattr(
        "app.services.rebalancing._after_lifecycle_capture",
        _append_newer_price,
    )

    response = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/start",
        json={"idempotency_key": "start-captured-price"},
    )
    db_session.expire_all()
    plan = await db_session.scalar(select(RebalancePlan).where(RebalancePlan.id == draft["id"]))
    snapshot_item = await db_session.scalar(
        select(SnapshotItem).where(
            SnapshotItem.snapshot_id == plan.before_snapshot_id,
            SnapshotItem.symbol == "CNY-FUND",
        )
    )

    assert response.status_code == 200, response.text
    assert appended_ids
    assert plan.start_market_data_record_ids["price:CNY-FUND"] == captured_price_id
    assert plan.start_market_data_record_ids["price:CNY-FUND"] != appended_ids[0]
    assert snapshot_item.market_price == Decimal("100.000000000000")


async def test_cancel_never_modifies_holdings_or_baselines(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)
    before = {
        row.id: (row.quantity, row.average_cost_price, row.cost_fx_to_cny, row.baseline_fx_to_cny)
        for row in await db_session.scalars(select(Holding).where(Holding.is_active.is_(True)))
    }

    response = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/cancel",
        json={"idempotency_key": "cancel-1"},
    )
    db_session.expire_all()
    after = {
        row.id: (row.quantity, row.average_cost_price, row.cost_fx_to_cny, row.baseline_fx_to_cny)
        for row in await db_session.scalars(select(Holding).where(Holding.is_active.is_(True)))
    }

    assert configured["cny_holding_id"]
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert after == before
    assert await db_session.scalar(
        select(func.count()).select_from(Snapshot).where(Snapshot.snapshot_type == "rebalance_after")
    ) == 0


async def test_complete_rebalance_creates_after_snapshot_and_resets_baseline(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)
    started = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/start",
        json={"idempotency_key": "start-1"},
    )
    assert started.status_code == 200, started.text

    holdings = {
        row.id: row
        for row in await db_session.scalars(select(Holding).where(Holding.is_active.is_(True)))
    }
    holdings[UUID(configured["cny_holding_id"])].quantity = Decimal("5")
    holdings[UUID(configured["usd_holding_id"])].quantity = Decimal("5")
    before_cost_fx = {holding_id: row.cost_fx_to_cny for holding_id, row in holdings.items()}
    await db_session.commit()

    response = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/complete",
        json={"idempotency_key": "complete-1"},
    )
    db_session.expire_all()
    after = {
        row.id: row
        for row in await db_session.scalars(select(Holding).where(Holding.is_active.is_(True)))
    }

    assert response.status_code == 200, response.text
    completed = response.json()
    assert completed["status"] == "completed"
    assert completed["after_snapshot_id"] is not None
    assert completed["baseline_reset_at"] is not None

    after_snapshot = await db_session.scalar(
        select(Snapshot).where(Snapshot.id == completed["after_snapshot_id"])
    )
    assert after_snapshot.snapshot_type == "rebalance_after"
    assert after[UUID(configured["cny_holding_id"])].baseline_fx_to_cny == Decimal("1")
    assert after[UUID(configured["usd_holding_id"])].baseline_fx_to_cny == Decimal("5.000000000000")
    assert after[UUID(configured["cny_holding_id"])].cost_fx_to_cny == before_cost_fx[UUID(configured["cny_holding_id"])]
    assert after[UUID(configured["usd_holding_id"])].cost_fx_to_cny == before_cost_fx[UUID(configured["usd_holding_id"])]
    assert after[UUID(configured["cny_holding_id"])].quantity == Decimal("5")
    assert after[UUID(configured["usd_holding_id"])].quantity == Decimal("5")


async def test_complete_snapshot_and_baseline_use_the_exact_fx_row_captured_before_concurrent_append(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)
    started = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/start",
        json={"idempotency_key": "start-before-fx-race"},
    )
    assert started.status_code == 200, started.text
    captured_fx = await db_session.scalar(
        select(MarketData).where(
            MarketData.data_type == "fx",
            MarketData.symbol == "USD/CNY",
        )
    )
    captured_fx_id = str(captured_fx.id)
    appended_ids: list[str] = []

    async def _append_newer_fx(event: str, _capture) -> None:
        if event != "complete":
            return
        async with SessionFactory() as concurrent_session:
            newer = MarketData(
                data_type="fx",
                symbol="USD/CNY",
                source="concurrent",
                value=Decimal("6.250000000000"),
                market_time=NOW + timedelta(minutes=1),
                fetched_at=NOW + timedelta(minutes=1),
                status="valid",
            )
            concurrent_session.add(newer)
            await concurrent_session.commit()
            appended_ids.append(str(newer.id))

    monkeypatch.setattr(
        "app.services.rebalancing._after_lifecycle_capture",
        _append_newer_fx,
    )

    response = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/complete",
        json={"idempotency_key": "complete-captured-fx"},
    )
    db_session.expire_all()
    plan = await db_session.scalar(select(RebalancePlan).where(RebalancePlan.id == draft["id"]))
    snapshot_item = await db_session.scalar(
        select(SnapshotItem).where(
            SnapshotItem.snapshot_id == plan.after_snapshot_id,
            SnapshotItem.holding_id == configured["usd_holding_id"],
        )
    )
    usd_holding = await db_session.scalar(
        select(Holding).where(Holding.id == configured["usd_holding_id"])
    )

    assert response.status_code == 200, response.text
    assert appended_ids
    assert plan.completion_market_data_record_ids["fx:USD/CNY"] == captured_fx_id
    assert plan.completion_market_data_record_ids["fx:USD/CNY"] != appended_ids[0]
    assert snapshot_item.current_fx_to_cny == Decimal("5.000000000000")
    assert usd_holding.baseline_fx_to_cny == Decimal("5.000000000000")


async def test_complete_rolls_back_baseline_reset_and_after_snapshot_on_failure(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    draft = await _create_draft_plan(api_client, monkeypatch)
    started = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/start",
        json={"idempotency_key": "start-1"},
    )
    assert started.status_code == 200, started.text
    before = {
        row.id: row.baseline_fx_to_cny
        for row in await db_session.scalars(select(Holding).where(Holding.is_active.is_(True)))
    }

    async def _failing_reset(session, effective_fx) -> None:
        holding = await session.scalar(select(Holding).where(Holding.id == configured["usd_holding_id"]))
        holding.baseline_fx_to_cny = Decimal("9.990000000000")
        await session.flush()
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.services.rebalancing.reset_baseline_fx",
        _failing_reset,
    )

    response = await api_client.post(
        f"/api/rebalance/plans/{draft['id']}/complete",
        json={"idempotency_key": "complete-1"},
    )
    db_session.expire_all()
    after = {
        row.id: row.baseline_fx_to_cny
        for row in await db_session.scalars(select(Holding).where(Holding.is_active.is_(True)))
    }
    after_snapshot_count = await db_session.scalar(
        select(func.count())
        .select_from(Snapshot)
        .where(Snapshot.snapshot_type == "rebalance_after")
    )

    assert response.status_code == 500, response.text
    assert response.json()["detail"] == {
        "code": "REBALANCE_STORAGE_ERROR",
        "message": "Rebalance storage operation failed.",
    }
    assert after == before
    assert after_snapshot_count == 0
