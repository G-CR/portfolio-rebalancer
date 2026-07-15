from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.models import AssetClass, Holding, MarketData, RebalancePlan
from app.db.session import SessionFactory
from app.main import app
from app.services import rebalancing as rebalancing_service

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


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
        "cny_asset_class_id": str(cny_class.id),
        "usd_asset_class_id": str(usd_class.id),
        "cny_holding_id": cny_holding.json()["id"],
        "usd_holding_id": usd_holding.json()["id"],
    }


def _preview_payload(
    *,
    session_token: str = "browser-session-1",
    request_token: str = "preview-request-1",
    acknowledge_stale_data: bool = False,
) -> dict[str, object]:
    return {
        "session_token": session_token,
        "request_token": request_token,
        "available_cny": "0",
        "available_usd": "0",
        "valuation_basis": "actual",
        "allow_sell": True,
        "allow_fx": True,
        "tolerance": "0.05",
        "minimum_trade_cny": "0",
        "acknowledge_stale_data": acknowledge_stale_data,
    }


async def test_preview_refreshes_once_per_browser_session_and_includes_basis_comparison(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)
    refresh_calls: list[str] = []

    async def _record_refresh(session) -> None:
        refresh_calls.append(str(id(session)))

    monkeypatch.setattr(
        "app.services.rebalancing.refresh_all_required_data",
        _record_refresh,
    )

    first = await api_client.post("/api/rebalance/preview", json=_preview_payload())
    second = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(request_token="preview-request-2"),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(refresh_calls) == 1

    payload = first.json()
    assert payload["session_token"] == "browser-session-1"
    assert payload["request_token"] == "preview-request-1"
    assert payload["status"] == "ok"
    assert payload["data_status"] == "valid"
    assert payload["refresh_attempted"] is True
    assert payload["valuation_basis"] == "actual"
    assert payload["result"]["trades"][0]["symbol"] == "CNY-FUND"
    assert payload["result"]["trades"][0]["action"] == "sell"
    assert Decimal(payload["result"]["trades"][0]["quantity"]) == Decimal("3")
    assert Decimal(payload["result"]["trades"][0]["amount_cny"]) == Decimal("300")
    assert payload["result"]["trades"][0]["reason_code"] == "OVERWEIGHT_AFTER_CASH"
    assert payload["result"]["trades"][0]["reason"] == "当前实际占比在投入现有现金后仍高于上限，需要卖出以回到目标附近。"
    assert payload["result"]["trades"][1]["symbol"] == "USD-FUND"
    assert payload["result"]["trades"][1]["action"] == "buy"
    assert Decimal(payload["result"]["trades"][1]["quantity"]) == Decimal("3")
    assert Decimal(payload["result"]["trades"][1]["amount_trade_currency"]) == Decimal("60")
    assert payload["result"]["trades"][1]["reason_code"] == "UNDERWEIGHT_AFTER_SELL_AND_FX"
    assert payload["result"]["trades"][1]["reason"] == "同币种现金不足，建议优先使用卖出所得并补充换汇后买入低配资产。"
    assert payload["fx_comparison"]["valuation_basis"] == "fx_neutral"
    assert [item["asset_class_id"] for item in payload["fx_comparison"]["result"]["projected_weights"]] == [
        payload["result"]["projected_weights"][0]["asset_class_id"],
        payload["result"]["projected_weights"][1]["asset_class_id"],
    ]
    assert [Decimal(item["after"]) for item in payload["fx_comparison"]["result"]["projected_weights"]] != [
        Decimal("0.5"),
        Decimal("0.5"),
    ]
    assert payload["fx_comparison"]["result"]["feasible"] is True

    second_payload = second.json()
    assert second_payload["refresh_attempted"] is False


async def test_preview_uses_existing_values_when_initial_refresh_times_out(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _slow_refresh(_session) -> None:
        await asyncio.sleep(0.1)

    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _slow_refresh)
    monkeypatch.setattr(rebalancing_service, "_PREVIEW_REFRESH_TIMEOUT_SECONDS", 0.01)

    response = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(session_token="refresh-timeout-session"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["refresh_attempted"] is True
    assert response.json()["data_status"] == "valid"


async def test_preview_requires_acknowledgement_before_using_stale_market_data(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)
    stale_attempt_at = NOW + timedelta(minutes=5)
    db_session.add_all(
        [
            MarketData(
                data_type="price",
                symbol="USD-FUND",
                source="seed",
                value=None,
                market_time=None,
                fetched_at=stale_attempt_at,
                status="failed",
                error_summary="provider_internal_error: fallback to last valid quote",
            ),
            MarketData(
                data_type="fx",
                symbol="USD/CNY",
                source="seed",
                value=None,
                market_time=None,
                fetched_at=stale_attempt_at,
                status="failed",
                error_summary="provider_internal_error: fallback to last valid fx",
            ),
        ]
    )
    await db_session.commit()

    async def _refresh_failure(_session) -> None:
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(
        "app.services.rebalancing.refresh_all_required_data",
        _refresh_failure,
    )

    rejected = await api_client.post("/api/rebalance/preview", json=_preview_payload())
    accepted = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(
            request_token="preview-request-2",
            acknowledge_stale_data=True,
        ),
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == {
        "code": "REBALANCE_STALE_DATA_ACK_REQUIRED",
        "message": "Stale market data requires explicit acknowledgement before previewing a rebalance plan.",
        "status": "stale",
        "items": ["fx:USD/CNY", "price:USD-FUND"],
    }

    assert accepted.status_code == 200, accepted.text
    accepted_payload = accepted.json()
    assert accepted_payload["data_status"] == "stale"
    assert accepted_payload["status"] == "ok"
    assert accepted_payload["acknowledge_stale_data"] is True


async def test_create_plan_persists_exact_preview_contract_and_supports_list_detail(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr(
        "app.services.rebalancing.refresh_all_required_data",
        _record_refresh,
    )

    create_response = await api_client.post(
        "/api/rebalance/plans",
        json={**_preview_payload(), "idempotency_key": "plan-create-1"},
    )

    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["status"] == "draft"
    assert created["valuation_basis"] == "actual"
    assert created["market_data_record_ids"]["price:CNY-FUND"]
    assert created["market_data_record_ids"]["price:USD-FUND"]
    assert created["market_data_record_ids"]["fx:USD/CNY"]
    assert created["holding_versions"][configured["cny_holding_id"]] == 1
    assert created["holding_versions"][configured["usd_holding_id"]] == 1
    assert created["result"]["trades"][0]["reason"].startswith("当前实际占比")

    listed = await api_client.get("/api/rebalance/plans")
    detail = await api_client.get(f"/api/rebalance/plans/{created['id']}")

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    assert listed.json()["items"] == [detail.json()]

    plan = await db_session.scalar(select(RebalancePlan).where(RebalancePlan.id == created["id"]))
    assert plan is not None
    assert plan.status == "draft"
    assert plan.strategy_mode == "actual"
    assert plan.input_summary == {
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
        "holding_versions": created["holding_versions"],
        "market_data_record_ids": created["market_data_record_ids"],
        "asset_class_targets": {
            configured["cny_asset_class_id"]: "0.500000000000",
            configured["usd_asset_class_id"]: "0.500000000000",
        },
        "resolved_constraints": {
            "allow_sell": True,
            "allow_fx": True,
            "tolerance": "0.05",
            "minimum_trade_cny": "0",
        },
    }
    assert plan.suggested_actions == created["result"]["trades"]
    assert plan.projected_result == {
        "valuation_basis": "actual",
        "result": created["result"],
        "fx_comparison": created["fx_comparison"],
        "data_status": "valid",
    }


async def test_create_plan_uses_one_capture_when_newer_price_is_appended_before_insert(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)
    captured_price = await db_session.scalar(
        select(MarketData).where(
            MarketData.data_type == "price",
            MarketData.symbol == "CNY-FUND",
        )
    )
    captured_price_id = str(captured_price.id)
    appended_ids: list[str] = []
    preparation_count = 0
    refresh_count = 0
    original_prepare = rebalancing_service._prepare_rebalance

    async def _prepare_then_append(*args, **kwargs):
        nonlocal preparation_count
        prepared = await original_prepare(*args, **kwargs)
        preparation_count += 1
        if preparation_count == 1:
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
        return prepared

    async def _record_refresh(_session) -> None:
        nonlocal refresh_count
        refresh_count += 1

    monkeypatch.setattr(rebalancing_service, "_prepare_rebalance", _prepare_then_append)
    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)

    created_response = await api_client.post(
        "/api/rebalance/plans",
        json={
            **_preview_payload(session_token="single-capture-browser-session"),
            "idempotency_key": "single-capture-create",
        },
    )
    created = created_response.json()
    plan = await db_session.scalar(
        select(RebalancePlan).where(
            RebalancePlan.create_idempotency_key == "single-capture-create"
        )
    )

    assert created_response.status_code == 201, created_response.text
    assert preparation_count == 1
    assert refresh_count == 1
    assert appended_ids
    assert created["market_data_record_ids"]["price:CNY-FUND"] == captured_price_id
    assert created["market_data_record_ids"]["price:CNY-FUND"] != appended_ids[0]
    assert Decimal(created["result"]["trades"][0]["quantity"]) == Decimal("3")
    assert Decimal(created["result"]["trades"][0]["amount_cny"]) == Decimal("300")
    assert plan.input_summary["market_data_record_ids"] == created["market_data_record_ids"]
    assert plan.projected_result["result"] == created["result"]

    next_preview = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(
            session_token="single-capture-browser-session",
            request_token="preview-after-concurrent-append",
        ),
    )

    assert next_preview.status_code == 200, next_preview.text
    assert Decimal(next_preview.json()["result"]["trades"][0]["amount_cny"]) == Decimal("375")


async def test_concurrent_plan_create_with_same_key_returns_one_persisted_plan(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr("app.services.rebalancing.refresh_all_required_data", _record_refresh)
    payload = {**_preview_payload(), "idempotency_key": "concurrent-plan-create"}

    async def _create() -> tuple[int, dict[str, object]]:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post("/api/rebalance/plans", json=payload)
            return response.status_code, response.json()

    responses = await asyncio.gather(*(_create() for _ in range(8)))
    plan_count = await db_session.scalar(
        select(func.count())
        .select_from(RebalancePlan)
        .where(RebalancePlan.create_idempotency_key == "concurrent-plan-create")
    )

    assert [status for status, _payload in responses].count(201) == 1
    assert [status for status, _payload in responses].count(200) == 7
    assert len({payload["id"] for _status, payload in responses}) == 1
    assert plan_count == 1


async def test_plan_create_same_key_with_different_payload_returns_original_plan(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr("app.services.rebalancing.refresh_all_required_data", _record_refresh)
    first_payload = {**_preview_payload(), "idempotency_key": "payload-stable-key"}
    second_payload = {
        **first_payload,
        "request_token": "materially-different-request",
        "available_cny": "50000",
        "valuation_basis": "fx_neutral",
    }

    first = await api_client.post("/api/rebalance/plans", json=first_payload)
    second = await api_client.post("/api/rebalance/plans", json=second_payload)
    plan_count = await db_session.scalar(
        select(func.count())
        .select_from(RebalancePlan)
        .where(RebalancePlan.create_idempotency_key == "payload-stable-key")
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert plan_count == 1
