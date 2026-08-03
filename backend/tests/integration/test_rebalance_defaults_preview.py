from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update

from app.db.models import MarketData, Setting
from app.services.rebalancing import preview_rebalance_with_defaults


def _holding_payload(asset_class_id: str, *, symbol: str, quantity: str) -> dict[str, object]:
    return {
        "asset_class_id": asset_class_id,
        "symbol": symbol,
        "name": symbol,
        "market": "SH",
        "account_name": symbol,
        "trade_currency": "CNY",
        "quantity": quantity,
        "average_cost_price": "1",
        "cost_fx_to_cny": "1",
        "baseline_fx_to_cny": "1",
        "lot_size": "1",
        "quantity_precision": 12,
        "is_rebalance_preferred": True,
    }


async def test_preview_with_defaults_uses_persisted_constraints(api_client, db_session) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    quantities = ("20", "20", "30", "20", "10")
    for index, (asset_class, quantity) in enumerate(zip(asset_classes, quantities, strict=True)):
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                asset_class["id"],
                symbol=f"51010{index}",
                quantity=quantity,
            ),
        )
    now = datetime.now(UTC)
    for index in range(5):
        db_session.add(
            MarketData(
                data_type="price",
                symbol=f"51010{index}",
                source="test-provider",
                value=Decimal("1"),
                market_time=now,
                fetched_at=now,
                status="valid",
            )
        )
    await db_session.execute(
        update(Setting).values(
            rebalance_available_cny=Decimal("10000"),
            default_tolerance=Decimal("0.01"),
            allow_sell=True,
            allow_fx=False,
        )
    )
    await db_session.commit()

    preview = await preview_rebalance_with_defaults(db_session)

    assert preview.status == "ok"
    assert preview.valuation_basis == "actual"
    assert len(preview.result.projected_weights) == 5
    assert preview.result.feasible is True
    assert any(trade.action == "buy" for trade in preview.result.trades)
