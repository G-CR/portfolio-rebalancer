from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.db.models import AssetClass, Holding, MarketData, RebalancePlan

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
    }
    assert plan.suggested_actions == created["result"]["trades"]
    assert plan.projected_result == {
        "valuation_basis": "actual",
        "result": created["result"],
        "fx_comparison": created["fx_comparison"],
        "data_status": "valid",
    }
