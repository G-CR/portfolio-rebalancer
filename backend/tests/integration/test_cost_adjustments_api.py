from decimal import Decimal
from uuid import UUID

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
            "commission_rate": "0.0010",
            "minimum_commission": "5",
            "per_share_fee": "0.02",
            "fixed_fee": "3",
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
                "commission_rate": "0.0010",
                "minimum_commission": "5",
                "per_share_fee": "0.02",
                "fixed_fee": "3",
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
                "save_fee_defaults": True,
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_COST_PREVIEW"

    rows = list(await db_session.scalars(select(CostAdjustment)))
    assert rows == []


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
