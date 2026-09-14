from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.backups.archive import inspect_archive, iter_current_rows
from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.db.models import AssetClass, Holding, MarketData, RebalancePlan
from app.db.session import SessionFactory
from app.domain.rebalance_optimizer import OptimizationFailure
from app.main import app
from app.services import rebalancing as rebalancing_service
from app.services.backup_export import export_database_backup
from app.services.backup_restore import restore_validated_backup
from app.services.backup_storage import BackupStorage
from app.services.backup_validation import validate_backup
import app.worker as worker_module

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
    is_rebalance_preferred: bool = True,
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
        "is_rebalance_preferred": is_rebalance_preferred,
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
        "acknowledge_stale_data": acknowledge_stale_data,
    }


async def test_preview_job_creation_returns_queued_status_without_running_preview(
    api_client,
) -> None:
    response = await api_client.post("/api/rebalance/preview-jobs", json=_preview_payload())

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["result"] is None
    assert payload["error"] is None


async def test_worker_completes_a_queued_preview_job(api_client, db_session, monkeypatch) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def no_refresh(_session) -> None:
        return None

    monkeypatch.setattr(worker_module, "refresh_all_required_data", no_refresh)
    created = await api_client.post(
        "/api/rebalance/preview-jobs",
        json=_preview_payload(request_token="worker-preview-job"),
    )
    assert created.status_code == 202, created.text

    assert await worker_module.run_preview_job_once() is True

    status = await api_client.get(f"/api/rebalance/preview-jobs/{created.json()['id']}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "succeeded"
    assert status.json()["result"]["status"] == "ok"


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

    first = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(session_token="refresh-once-session"),
    )
    second = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(
            session_token="refresh-once-session",
            request_token="preview-request-2",
        ),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(refresh_calls) == 1

    payload = first.json()
    assert payload["session_token"] == "refresh-once-session"
    assert payload["request_token"] == "preview-request-1"
    assert payload["status"] == "ok"
    assert payload["data_status"] == "valid"
    assert payload["refresh_attempted"] is True
    assert payload["valuation_basis"] == "actual"
    trades_by_symbol = {trade["symbol"]: trade for trade in payload["result"]["trades"]}
    cny_trade = trades_by_symbol["CNY-FUND"]
    usd_trade = trades_by_symbol["USD-FUND"]
    assert cny_trade["action"] == "sell"
    assert Decimal(cny_trade["quantity"]) == Decimal("3")
    assert Decimal(cny_trade["amount_cny"]) == Decimal("300")
    assert cny_trade["reason_code"] == "REALLOCATE_OUTSIDE_TOLERANCE"
    assert cny_trade["reason"] == "仅靠买入仍无法进入容差范围，建议卖出并重新配置。"
    assert usd_trade["action"] == "buy"
    assert Decimal(usd_trade["quantity"]) == Decimal("3")
    assert Decimal(usd_trade["amount_trade_currency"]) == Decimal("60")
    assert usd_trade["reason_code"] == "REDUCE_MAX_DRIFT"
    assert usd_trade["reason"] == "该交易用于降低投资组合的最大配置偏离。"
    assert payload["result"]["optimization_precision"] == "0.0001"
    assert payload["result"]["optimization_certified"] is True
    assert Decimal(payload["result"]["optimality_gap"]) <= Decimal("0.0001")
    assert Decimal(payload["result"]["buy_only_max_drift"]) == Decimal("0.3")
    assert payload["result"]["sell_phase_used"] is True
    assert payload["result"]["net_fx_direction"] == "cny_to_usd"
    assert Decimal(payload["result"]["net_fx_amount_cny"]) == Decimal("300")
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


async def test_preview_schema_and_buy_only_result_expose_the_active_optimizer_contract(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)
    request = {**_preview_payload(session_token="buy-only-session"), "available_cny": "600"}

    response = await api_client.post("/api/rebalance/preview", json=request)
    openapi = (await api_client.get("/openapi.json")).json()

    assert response.status_code == 200, response.text
    assert "minimum_trade_cny" not in request
    assert (
        "minimum_trade_cny"
        not in openapi["components"]["schemas"]["RebalancePreviewRequest"]["properties"]
    )
    payload = response.json()
    assert payload["result"]["optimization_precision"] == "0.0001"
    assert payload["result"]["optimization_certified"] is True
    assert Decimal(payload["result"]["optimality_gap"]) <= Decimal("0.0001")
    assert payload["result"]["net_fx_direction"] in {
        "cny_to_usd",
        "usd_to_cny",
        "none",
    }
    assert payload["result"]["sell_phase_used"] is False


async def test_preview_caps_sell_inventory_at_the_preferred_holding_quantity(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    secondary = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            configured["cny_asset_class_id"],
            symbol="CNY-SECONDARY",
            name="CNY Secondary",
            market="SH",
            trade_currency="CNY",
            quantity="20",
            average_cost_price="100",
            cost_fx_to_cny="1",
            baseline_fx_to_cny="1",
            lot_size="1",
            account_name="Broker CNY Secondary",
            is_rebalance_preferred=False,
        ),
    )
    assert secondary.status_code == 201, secondary.text
    db_session.add(
        MarketData(
            data_type="price",
            symbol="CNY-SECONDARY",
            source="seed",
            value=Decimal("100.000000000000"),
            market_time=NOW,
            fetched_at=NOW,
            status="valid",
        )
    )
    await db_session.commit()

    captured: list[tuple[Decimal, Decimal]] = []
    run_optimizer = rebalancing_service.rebalance

    def _capture_inventory(assets, cash, options, **kwargs):
        cny_asset = next(item for item in assets if item.symbol == "CNY-FUND")
        captured.append((cny_asset.current_value_cny, cny_asset.max_sell_quantity))
        return run_optimizer(assets, cash, options, **kwargs)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr(rebalancing_service, "rebalance", _capture_inventory)
    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)

    response = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(session_token="preferred-inventory-session"),
    )

    assert response.status_code == 200, response.text
    assert captured == [
        (Decimal("2800.000000000000"), Decimal("8.000000000000")),
        (Decimal("2800.000000000000"), Decimal("8.000000000000")),
    ]


async def test_preview_rejects_active_class_without_a_preferred_holding(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    configured = await _configure_two_class_portfolio(api_client, db_session)
    cny_holding = await db_session.get(Holding, UUID(configured["cny_holding_id"]))
    assert cny_holding is not None
    cny_holding.is_rebalance_preferred = False
    await db_session.commit()

    optimizer_calls: list[object] = []
    run_optimizer = rebalancing_service.rebalance

    def _capture_optimizer(*args, **kwargs):
        optimizer_calls.append((args, kwargs))
        return run_optimizer(*args, **kwargs)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr(rebalancing_service, "rebalance", _capture_optimizer)
    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)

    response = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(session_token="missing-preferred-session"),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "REBALANCE_DATA_INCOMPLETE",
        "message": "Active rebalance asset class is missing a preferred holding.",
        "status": "incomplete",
        "items": [f"preferred:{configured['cny_asset_class_id']}"],
    }
    assert optimizer_calls == []


async def test_preview_maps_optimizer_certification_failure_to_typed_service_error(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    def _fail_optimization(*_args, **_kwargs):
        raise OptimizationFailure(
            "REBALANCE_OPTIMIZATION_UNCERTIFIED",
            explored_nodes=250_000,
            gap=Decimal("0.0002"),
        )

    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)
    monkeypatch.setattr(rebalancing_service, "rebalance", _fail_optimization)

    response = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(session_token="uncertified-session"),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "code": "REBALANCE_OPTIMIZATION_UNCERTIFIED",
        "message": "无法在 1bp 精度内生成可认证的再平衡方案。",
        "explored_nodes": 250_000,
        "optimality_gap": "0.0002",
    }


async def test_preview_maps_optimizer_timeout_to_a_distinct_typed_service_error(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    def _timeout_optimization(*_args, **_kwargs):
        raise OptimizationFailure(
            "REBALANCE_OPTIMIZATION_TIMEOUT",
            explored_nodes=42,
            gap=Decimal("0.001"),
        )

    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)
    monkeypatch.setattr(rebalancing_service, "rebalance", _timeout_optimization)

    response = await api_client.post(
        "/api/rebalance/preview",
        json=_preview_payload(session_token="timeout-session"),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "code": "REBALANCE_OPTIMIZATION_TIMEOUT",
        "message": "再平衡计算超出时间预算。",
        "explored_nodes": 42,
        "optimality_gap": "0.001",
    }


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
    tmp_path: Path,
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
    assert created["available_cny"] == "0"
    assert created["available_usd"] == "0"
    assert created["minimum_trade_cny"] is None
    assert created["allow_sell"] is True
    assert created["allow_fx"] is True
    assert created["acknowledge_stale_data"] is False
    assert created["tolerance"] == "0.05"
    assert created["market_data_record_ids"]["price:CNY-FUND"]
    assert created["market_data_record_ids"]["price:USD-FUND"]
    assert created["market_data_record_ids"]["fx:USD/CNY"]
    assert created["holding_versions"][configured["cny_holding_id"]] == 1
    assert created["holding_versions"][configured["usd_holding_id"]] == 1
    assert created["result"]["trades"][0]["reason_code"] in {
        "REDUCE_MAX_DRIFT",
        "REDUCE_TOTAL_DRIFT",
        "REALLOCATE_OUTSIDE_TOLERANCE",
    }

    listed = await api_client.get("/api/rebalance/plans")
    detail = await api_client.get(f"/api/rebalance/plans/{created['id']}")

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    assert listed.json()["items"] == [detail.json()]
    assert detail.json() == created

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
        "minimum_trade_cny": None,
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
        },
    }
    assert plan.suggested_actions == created["result"]["trades"]
    assert plan.projected_result == {
        "valuation_basis": "actual",
        "result": created["result"],
        "fx_comparison": created["fx_comparison"],
        "data_status": "valid",
    }

    legacy_input_summary = dict(plan.input_summary)
    legacy_input_summary.pop("resolved_constraints")
    legacy_input_summary.pop("asset_class_targets")
    legacy_input_summary["minimum_trade_cny"] = "275"
    plan.input_summary = legacy_input_summary
    legacy_projected = dict(plan.projected_result)
    legacy_result = dict(legacy_projected["result"])
    legacy_comparison = dict(legacy_projected["fx_comparison"])
    legacy_comparison_result = dict(legacy_comparison["result"])
    for field in (
        "buy_only_max_drift",
        "optimization_precision",
        "optimization_certified",
        "optimality_gap",
        "sell_phase_used",
        "net_fx_direction",
        "net_fx_amount_cny",
    ):
        legacy_result.pop(field)
        legacy_comparison_result.pop(field)
    legacy_result["trades"] = [
        {
            **legacy_result["trades"][0],
            "action": "sell",
            "reason_code": "OVERWEIGHT_AFTER_CASH",
            "reason": "当前实际占比在投入现有现金后仍高于上限，需要卖出以回到目标附近。",
        },
        *legacy_result["trades"][1:],
    ]
    legacy_result["fx_required_cny"] = "70"
    legacy_comparison_result["trades"] = []
    legacy_comparison_result["fx_required_cny"] = "0"
    legacy_comparison["result"] = legacy_comparison_result
    legacy_projected["result"] = legacy_result
    legacy_projected["fx_comparison"] = legacy_comparison
    plan.projected_result = legacy_projected
    plan.suggested_actions = legacy_result["trades"]
    plan.data_version = "legacy-opaque-version"
    await db_session.commit()

    archive = tmp_path / "legacy-rebalance.portfolio-backup"
    await export_database_backup(archive)
    validate_backup(archive, path_id="upload:test", workspace_root=tmp_path)
    with inspect_archive(archive) as inspected:
        [archived_plan] = list(iter_current_rows(inspected, "data/rebalance_plans.json"))
    assert "resolved_constraints" not in archived_plan["input_summary"]
    assert "asset_class_targets" not in archived_plan["input_summary"]
    assert archived_plan["data_version"] == "legacy-opaque-version"

    legacy_listed = await api_client.get("/api/rebalance/plans")
    legacy_detail = await api_client.get(f"/api/rebalance/plans/{created['id']}")

    assert legacy_listed.status_code == 200, legacy_listed.text
    assert legacy_detail.status_code == 200, legacy_detail.text
    assert legacy_listed.json()["items"] == [legacy_detail.json()]
    assert legacy_detail.json()["allow_sell"] is True
    assert legacy_detail.json()["allow_fx"] is True
    assert legacy_detail.json()["tolerance"] == "0.05"
    assert legacy_detail.json()["minimum_trade_cny"] == "275"
    assert legacy_detail.json()["asset_class_targets"] == {}
    assert legacy_detail.json()["data_version"] == "legacy-opaque-version"
    assert legacy_detail.json()["result"]["trades"][0]["reason_code"] == "OVERWEIGHT_AFTER_CASH"
    assert legacy_detail.json()["result"]["optimization_certified"] is False
    assert legacy_detail.json()["result"]["optimization_precision"] == "0.0001"
    assert legacy_detail.json()["result"]["buy_only_max_drift"] == legacy_result["max_drift_after"]
    assert legacy_detail.json()["result"]["sell_phase_used"] is True
    assert legacy_detail.json()["result"]["net_fx_direction"] == "cny_to_usd"
    assert legacy_detail.json()["result"]["net_fx_amount_cny"] == "70"
    assert legacy_detail.json()["fx_comparison"]["result"]["buy_only_max_drift"] == legacy_comparison_result["max_drift_after"]
    assert legacy_detail.json()["fx_comparison"]["result"]["sell_phase_used"] is False
    assert legacy_detail.json()["fx_comparison"]["result"]["net_fx_direction"] == "none"
    assert legacy_detail.json()["fx_comparison"]["result"]["net_fx_amount_cny"] == "0"


async def test_current_task5_plan_backup_validates_and_restores_without_legacy_mutation(
    api_client,
    db_session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    await _configure_two_class_portfolio(api_client, db_session)

    async def _record_refresh(_session) -> None:
        return None

    monkeypatch.setattr(rebalancing_service, "refresh_all_required_data", _record_refresh)
    created_response = await api_client.post(
        "/api/rebalance/plans",
        json={**_preview_payload(), "idempotency_key": "current-task5-backup"},
    )

    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    archive = tmp_path / "current-task5-rebalance.portfolio-backup"
    await export_database_backup(archive)
    storage = BackupStorage(tmp_path / "backup-storage")
    storage.initialize()
    validated = validate_backup(
        archive,
        path_id="upload:current-task5",
        workspace_root=storage.tmp_dir,
    )
    with inspect_archive(archive) as inspected:
        [archived_plan] = list(iter_current_rows(inspected, "data/rebalance_plans.json"))
    assert archived_plan["input_summary"]["minimum_trade_cny"] is None
    assert set(archived_plan["input_summary"]["resolved_constraints"]) == {
        "allow_sell",
        "allow_fx",
        "tolerance",
    }
    assert archived_plan["projected_result"]["result"]["optimization_certified"] is True

    class _Progress:
        async def set_stage(self, _stage) -> None:
            return None

    await db_session.commit()
    async with db_session.begin():
        restored = await restore_validated_backup(
            db_session,
            validated,
            storage=storage,
            secret_store=SecretStore(Path(get_settings().secret_key_path)),
            progress=_Progress(),
        )

    restored_plan = await db_session.get(RebalancePlan, UUID(created["id"]))
    assert restored.record_counts["data/rebalance_plans.json"] == 1
    assert restored_plan is not None
    assert restored_plan.input_summary["minimum_trade_cny"] is None
    assert set(restored_plan.input_summary["resolved_constraints"]) == {
        "allow_sell",
        "allow_fx",
        "tolerance",
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
    cny_trade = next(
        trade
        for trade in next_preview.json()["result"]["trades"]
        if trade["symbol"] == "CNY-FUND"
    )
    assert Decimal(cny_trade["amount_cny"]) == Decimal(cny_trade["quantity"]) * Decimal("125")


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
