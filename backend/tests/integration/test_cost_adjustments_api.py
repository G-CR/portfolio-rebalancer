from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models import CostAdjustment, Holding, HoldingDefault


def _holding_payload(asset_class_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "asset_class_id": asset_class_id,
        "symbol": "SPY",
        "name": "SPDR S&P 500 ETF Trust",
        "market": "US",
        "account_name": "港资券商",
        "trade_currency": "USD",
        "quantity": "10",
        "average_cost_price": "500",
        "cost_fx_to_cny": "7.20",
        "baseline_fx_to_cny": "7.20",
        "lot_size": "1",
        "quantity_precision": 0,
        "is_rebalance_preferred": True,
    }
    payload.update(overrides)
    return payload


async def _create_spy_holding(api_client) -> dict[str, object]:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[2]["id"]
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id),
    )
    assert response.status_code == 201
    return response.json()


async def test_purchase_confirm_updates_holding_persists_audit_and_fee_defaults(
    api_client, db_session
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "5",
            "price": "650.20",
            "fx": "7.1850",
            "fee_currency": "USD",
            "commission_rate": "0.0005",
            "minimum_commission": "1",
            "per_share_fee": "0.01",
            "fixed_fee": "2",
            "actual_fee": "2.30",
            "save_fee_defaults": True,
        },
    )

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["operation"] == "purchase"
    assert preview_body["holding_version"] == 1
    assert preview_body["after"]["quantity"] == "15"
    assert preview_body["fee"]["mode"] == "actual"
    assert preview_body["fee"]["amount"] == "2.30"
    assert preview_body["fee"]["currency"] == "USD"

    confirm = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": preview_body["holding_version"],
            "operation": "purchase",
            "payload": {
                "quantity": "5",
                "price": "650.20",
                "fx": "7.1850",
                "fee_currency": "USD",
                "commission_rate": "0.0005",
                "minimum_commission": "1",
                "per_share_fee": "0.01",
                "fixed_fee": "2",
                "actual_fee": "2.30",
                "save_fee_defaults": True,
            },
        },
    )

    assert confirm.status_code == 200
    confirmed = confirm.json()
    assert confirmed["holding_version"] == 2
    assert confirmed["after"] == preview_body["after"]

    holding = await db_session.scalar(select(Holding).where(Holding.id == UUID(spy_holding["id"])))
    assert holding is not None
    assert holding.version == 2
    assert holding.quantity == Decimal("15")
    assert holding.average_cost_price == Decimal(confirmed["after"]["average_cost_price"])
    assert holding.cost_fx_to_cny == Decimal(confirmed["after"]["cost_fx_to_cny"])
    assert holding.baseline_fx_to_cny == Decimal("7.20")

    defaults = await db_session.scalar(
        select(HoldingDefault).where(HoldingDefault.holding_id == holding.id)
    )
    assert defaults is not None
    assert defaults.fee_currency == "USD"
    assert defaults.commission_rate == Decimal("0.0005")
    assert defaults.minimum_commission == Decimal("1")
    assert defaults.per_share_fee == Decimal("0.01")
    assert defaults.fixed_fee == Decimal("2")

    adjustments = list(
        await db_session.scalars(
            select(CostAdjustment)
            .where(CostAdjustment.holding_id == holding.id)
            .order_by(CostAdjustment.created_at.asc(), CostAdjustment.id.asc())
        )
    )
    assert len(adjustments) == 1
    assert adjustments[0].operation_type == "PURCHASE"
    assert adjustments[0].input_summary["save_fee_defaults"] is True

    second_preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "1",
            "price": "600",
            "fx": "7.10",
            "fee_currency": "USD",
            "actual_fee": "3",
            "save_fee_defaults": False,
        },
    )
    assert second_preview.status_code == 200

    second_confirm = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": second_preview.json()["holding_version"],
            "operation": "purchase",
            "payload": {
                "quantity": "1",
                "price": "600",
                "fx": "7.10",
                "fee_currency": "USD",
                "actual_fee": "3",
                "save_fee_defaults": False,
            },
        },
    )
    assert second_confirm.status_code == 200

    await db_session.refresh(defaults)
    assert defaults.commission_rate == Decimal("0.0005")
    assert defaults.minimum_commission == Decimal("1")
    assert defaults.per_share_fee == Decimal("0.01")
    assert defaults.fixed_fee == Decimal("2")


@pytest.mark.parametrize(
    ("rule_fields", "missing_fields"),
    [
        ({}, {"commission_rate", "minimum_commission", "per_share_fee", "fixed_fee"}),
        (
            {"commission_rate": "0.001", "minimum_commission": "2"},
            {"per_share_fee", "fixed_fee"},
        ),
    ],
)
async def test_preview_rejects_incomplete_explicit_fee_default_save(
    api_client,
    db_session,
    rule_fields: dict[str, str],
    missing_fields: set[str],
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "1",
            "price": "500",
            "fx": "7.1",
            "actual_fee": "2",
            "save_fee_defaults": True,
            **rule_fields,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INCOMPLETE_FEE_DEFAULT_RULE"
    assert detail["message"] == "Saving fee defaults requires all four fee rule fields."
    assert set(detail["missing_fields"]) == missing_fields
    assert list(await db_session.scalars(select(HoldingDefault))) == []


async def test_confirm_rejects_actual_fee_only_default_save_atomically(
    api_client,
    db_session,
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": spy_holding["version"],
            "operation": "purchase",
            "payload": {
                "quantity": "1",
                "price": "500",
                "fx": "7.1",
                "actual_fee": "2",
                "save_fee_defaults": True,
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INCOMPLETE_FEE_DEFAULT_RULE"
    holding = await db_session.scalar(
        select(Holding).where(Holding.id == UUID(spy_holding["id"]))
    )
    assert holding is not None
    assert holding.version == 1
    assert holding.quantity == Decimal("10")
    assert list(await db_session.scalars(select(HoldingDefault))) == []
    assert list(await db_session.scalars(select(CostAdjustment))) == []


async def test_stale_cost_preview_is_rejected(api_client, db_session) -> None:
    spy_holding = await _create_spy_holding(api_client)
    preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "5",
            "price": "650.20",
            "fx": "7.1850",
            "actual_fee": "2.30",
            "fee_currency": "USD",
            "commission_rate": "0.0005",
            "minimum_commission": "1",
            "per_share_fee": "0.01",
            "fixed_fee": "2",
            "save_fee_defaults": True,
        },
    )

    assert preview.status_code == 200

    patch = await api_client.patch(
        f"/api/holdings/{spy_holding['id']}",
        json={"quantity": "87"},
    )
    assert patch.status_code == 200

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": preview.json()["holding_version"],
            "operation": "purchase",
            "payload": {
                "quantity": "5",
                "price": "650.20",
                "fx": "7.1850",
                "actual_fee": "2.30",
                "fee_currency": "USD",
                "commission_rate": "0.0005",
                "minimum_commission": "1",
                "per_share_fee": "0.01",
                "fixed_fee": "2",
                "save_fee_defaults": True,
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_COST_PREVIEW"

    rows = list(await db_session.scalars(select(CostAdjustment)))
    assert rows == []


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        (
            "preview-purchase",
            {"quantity": "1", "price": "10000000000000000", "fx": "7.1"},
            "price",
        ),
        ("preview-sell", {"quantity": "0.0000000000001"}, "quantity"),
        (
            "preview-correction",
            {
                "quantity": "10000000000000000",
                "average_cost_price": "480",
                "cost_fx_to_cny": "7.1",
                "note": "对齐券商月结单",
            },
            "quantity",
        ),
    ],
)
async def test_preview_rejects_decimal_values_outside_numeric_storage_bounds(
    api_client,
    path: str,
    payload: dict[str, str],
    field: str,
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/{path}",
        json=payload,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "COST_ADJUSTMENT_NUMERIC_OUT_OF_RANGE"
    assert detail["field"] == field


@pytest.mark.parametrize(
    ("operation", "payload", "field"),
    [
        (
            "purchase",
            {"quantity": "1", "price": "10000000000000000", "fx": "7.1"},
            "payload.price",
        ),
        ("sell", {"quantity": "0.0000000000001"}, "payload.quantity"),
        (
            "manual_correction",
            {
                "quantity": "10000000000000000",
                "average_cost_price": "480",
                "cost_fx_to_cny": "7.1",
                "note": "对齐券商月结单",
            },
            "payload.quantity",
        ),
    ],
)
async def test_confirm_rejects_out_of_range_decimal_atomically(
    api_client,
    db_session,
    operation: str,
    payload: dict[str, str],
    field: str,
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": spy_holding["version"],
            "operation": operation,
            "payload": payload,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "COST_ADJUSTMENT_NUMERIC_OUT_OF_RANGE"
    assert {error["field"] for error in detail["errors"]} == {field}
    holding = await db_session.scalar(
        select(Holding).where(Holding.id == UUID(spy_holding["id"]))
    )
    assert holding is not None
    assert holding.version == 1
    assert holding.quantity == Decimal("10")
    assert list(await db_session.scalars(select(CostAdjustment))) == []


async def test_preview_translates_decimal_arithmetic_overflow(api_client) -> None:
    spy_holding = await _create_spy_holding(api_client)

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "9999999999999999",
            "price": "9999999999999999",
            "fx": "9999999999999999",
            "actual_fee": "0",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "COST_ADJUSTMENT_NUMERIC_OUT_OF_RANGE"


@pytest.mark.parametrize(
    ("operation", "payload", "expected_fields"),
    [
        ("purchase", {"quantity": "1"}, {"payload.price", "payload.fx"}),
        (
            "sell",
            {"quantity": "1", "price": "500", "fx": "7.1"},
            {"payload.price", "payload.fx"},
        ),
        (
            "manual_correction",
            {
                "quantity": "not-a-number",
                "average_cost_price": "480",
                "cost_fx_to_cny": "7.10",
                "note": "对齐券商月结单",
            },
            {"payload.quantity"},
        ),
    ],
)
async def test_confirm_rejects_malformed_operation_payload_with_structured_errors(
    api_client,
    db_session,
    operation: str,
    payload: dict[str, object],
    expected_fields: set[str],
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": spy_holding["version"],
            "operation": operation,
            "payload": payload,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_COST_ADJUSTMENT_PAYLOAD"
    assert detail["message"] == "Cost adjustment payload is invalid for the operation."
    assert {error["field"] for error in detail["errors"]} == expected_fields

    holding = await db_session.scalar(
        select(Holding).where(Holding.id == UUID(spy_holding["id"]))
    )
    assert holding is not None
    assert holding.version == 1
    assert list(await db_session.scalars(select(CostAdjustment))) == []


async def test_stale_version_wins_over_malformed_confirm_payload(api_client, db_session) -> None:
    spy_holding = await _create_spy_holding(api_client)
    patch = await api_client.patch(
        f"/api/holdings/{spy_holding['id']}",
        json={"quantity": "11"},
    )
    assert patch.status_code == 200

    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": spy_holding["version"],
            "operation": "purchase",
            "payload": {"quantity": "not-a-number"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_COST_PREVIEW"
    assert list(await db_session.scalars(select(CostAdjustment))) == []


async def test_sell_confirm_preserves_average_cost_and_cost_fx(api_client, db_session) -> None:
    spy_holding = await _create_spy_holding(api_client)

    preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-sell",
        json={"quantity": "2", "note": "减仓，不计算已实现盈亏"},
    )

    assert preview.status_code == 200
    assert preview.json()["operation"] == "sell"
    assert preview.json()["after"]["quantity"] == "8"
    assert preview.json()["after"]["average_cost_price"] == "500.00"
    assert preview.json()["after"]["cost_fx_to_cny"] == "7.2"

    confirm = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": preview.json()["holding_version"],
            "operation": "sell",
            "payload": {
                "quantity": "2",
                "note": "减仓，不计算已实现盈亏",
            },
        },
    )

    assert confirm.status_code == 200
    assert confirm.json()["holding_version"] == 2
    assert confirm.json()["after"]["quantity"] == "8"

    holding = await db_session.scalar(select(Holding).where(Holding.id == UUID(spy_holding["id"])))
    assert holding is not None
    assert holding.quantity == Decimal("8")
    assert holding.average_cost_price == Decimal("500")
    assert holding.cost_fx_to_cny == Decimal("7.20")

    rows = list(await db_session.scalars(select(CostAdjustment)))
    assert len(rows) == 1
    assert rows[0].operation_type == "SELL"


async def test_zero_quantity_holding_defaults_can_preview_correction(api_client) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    holding_response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            symbol="ZERO",
            trade_currency="CNY",
            quantity="0",
            average_cost_price="0",
            cost_fx_to_cny="1",
            baseline_fx_to_cny="1",
        ),
    )
    assert holding_response.status_code == 201
    holding = holding_response.json()

    preview = await api_client.post(
        f"/api/cost-adjustments/{holding['id']}/preview-correction",
        json={
            "quantity": "0",
            "average_cost_price": "0",
            "cost_fx_to_cny": "1",
            "note": "确认空仓初始状态",
        },
    )

    assert preview.status_code == 200
    assert preview.json()["before"] == {
        "quantity": "0",
        "average_cost_price": "0.00",
        "cost_fx_to_cny": "0",
        "total_cost_cny": "0.00",
    }
    assert preview.json()["after"] == preview.json()["before"]


async def test_manual_correction_requires_reason_and_restore_creates_append_only_audit_row(
    api_client, db_session
) -> None:
    spy_holding = await _create_spy_holding(api_client)

    missing_note = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-correction",
        json={
            "quantity": "9",
            "average_cost_price": "480",
            "cost_fx_to_cny": "7.10",
        },
    )
    assert missing_note.status_code == 422
    assert missing_note.json()["detail"]["code"] == "MANUAL_CORRECTION_NOTE_REQUIRED"

    purchase_preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "5",
            "price": "650.20",
            "fx": "7.1850",
            "fee_currency": "USD",
            "actual_fee": "2.30",
        },
    )
    purchase_confirm = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": purchase_preview.json()["holding_version"],
            "operation": "purchase",
            "payload": {
                "quantity": "5",
                "price": "650.20",
                "fx": "7.1850",
                "fee_currency": "USD",
                "actual_fee": "2.30",
            },
        },
    )
    assert purchase_confirm.status_code == 200

    correction_preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-correction",
        json={
            "quantity": "9",
            "average_cost_price": "480",
            "cost_fx_to_cny": "7.10",
            "note": "对齐券商月结单",
        },
    )
    assert correction_preview.status_code == 200

    correction_confirm = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": correction_preview.json()["holding_version"],
            "operation": "manual_correction",
            "payload": {
                "quantity": "9",
                "average_cost_price": "480",
                "cost_fx_to_cny": "7.10",
                "note": "对齐券商月结单",
            },
        },
    )
    assert correction_confirm.status_code == 200

    history = await api_client.get(f"/api/cost-adjustments/{spy_holding['id']}")
    assert history.status_code == 200
    assert history.json()["defaults"] is None
    assert len(history.json()["items"]) == 2

    purchase_adjustment_id = history.json()["items"][0]["id"]
    restore_preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-restore/{purchase_adjustment_id}",
        json={"note": "恢复到买入后的基准"},
    )
    assert restore_preview.status_code == 200
    assert restore_preview.json()["operation"] == "restore"
    assert restore_preview.json()["after"] == history.json()["items"][0]["after"]

    restore_confirm = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": restore_preview.json()["holding_version"],
            "operation": "restore",
            "payload": {
                "adjustment_id": purchase_adjustment_id,
                "note": "恢复到买入后的基准",
            },
        },
    )
    assert restore_confirm.status_code == 200

    final_history = await api_client.get(f"/api/cost-adjustments/{spy_holding['id']}")
    assert final_history.status_code == 200
    assert len(final_history.json()["items"]) == 3
    assert final_history.json()["items"][-1]["operation_type"] == "MANUAL_CORRECTION"
    assert final_history.json()["items"][-1]["after"] == history.json()["items"][0]["after"]

    rows = list(
        await db_session.scalars(
            select(CostAdjustment)
            .where(CostAdjustment.holding_id == UUID(spy_holding["id"]))
            .order_by(CostAdjustment.created_at.asc(), CostAdjustment.id.asc())
        )
    )
    assert len(rows) == 3
    assert [row.operation_type for row in rows] == [
        "PURCHASE",
        "MANUAL_CORRECTION",
        "MANUAL_CORRECTION",
    ]

    holding = await db_session.scalar(select(Holding).where(Holding.id == UUID(spy_holding["id"])))
    assert holding is not None
    assert Decimal(final_history.json()["items"][-1]["after"]["quantity"]) == holding.quantity
    assert (
        Decimal(final_history.json()["items"][-1]["after"]["average_cost_price"])
        == holding.average_cost_price
    )


async def test_history_preserves_stored_decimals_after_quantity_precision_changes(
    api_client,
) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[2]["id"]
    create = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            quantity="10.1234",
            quantity_precision=4,
        ),
    )
    assert create.status_code == 201
    holding = create.json()

    preview = await api_client.post(
        f"/api/cost-adjustments/{holding['id']}/preview-sell",
        json={"quantity": "0.1001"},
    )
    assert preview.status_code == 200
    confirm = await api_client.post(
        f"/api/cost-adjustments/{holding['id']}/confirm",
        json={
            "expected_version": preview.json()["holding_version"],
            "operation": "sell",
            "payload": {"quantity": "0.1001"},
        },
    )
    assert confirm.status_code == 200

    history_before = await api_client.get(f"/api/cost-adjustments/{holding['id']}")
    assert history_before.status_code == 200
    stored_before = history_before.json()["items"][0]["before"]
    stored_after = history_before.json()["items"][0]["after"]
    assert stored_before["quantity"] == "10.1234"
    assert stored_after["quantity"] == "10.0233"

    precision_patch = await api_client.patch(
        f"/api/holdings/{holding['id']}",
        json={"quantity_precision": 0},
    )
    assert precision_patch.status_code == 200

    history_after = await api_client.get(f"/api/cost-adjustments/{holding['id']}")
    assert history_after.status_code == 200
    assert history_after.json()["items"][0]["before"] == stored_before
    assert history_after.json()["items"][0]["after"] == stored_after
