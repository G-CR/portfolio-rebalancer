import asyncio

from httpx import Response
import pytest
from sqlalchemy import select

from app.db.models import Holding
from app.services import holdings as holdings_service


@pytest.fixture
async def asset_class_id(api_client) -> str:
    return (await api_client.get("/api/asset-classes")).json()[0]["id"]


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


async def test_list_holdings_returns_empty_when_none_created(api_client) -> None:
    response = await api_client.get("/api/holdings")

    assert response.status_code == 200
    assert response.json() == []


async def test_create_usd_holding_requires_positive_fx_values(
    api_client, asset_class_id
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, cost_fx_to_cny="0"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "FX_MUST_BE_POSITIVE"


async def test_create_cny_holding_normalizes_fx_and_sets_first_holding_preferred(
    api_client, asset_class_id
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            symbol="510300",
            name="沪深 300 ETF",
            market="SH",
            trade_currency="CNY",
            quantity="100",
            average_cost_price="3.4567",
            cost_fx_to_cny="7.20",
            baseline_fx_to_cny="6.80",
            is_rebalance_preferred=False,
        ),
    )

    assert response.status_code == 201
    assert response.json()["trade_currency"] == "CNY"
    assert response.json()["cost_fx_to_cny"] == "1"
    assert response.json()["baseline_fx_to_cny"] == "1"
    assert response.json()["is_rebalance_preferred"] is True
    assert response.json()["version"] == 1


async def test_create_holding_normalizes_supported_market_and_currency(
    api_client, asset_class_id
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            market="sse",
            trade_currency="cny",
        ),
    )

    assert response.status_code == 201
    assert response.json()["market"] == "SH"
    assert response.json()["trade_currency"] == "CNY"


async def test_create_holding_rejects_non_iso_trade_currency(
    api_client, asset_class_id
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, trade_currency="USDT"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "HOLDING_TRADE_CURRENCY_INVALID",
        "message": "Trade currency must be exactly three ASCII letters.",
        "field": "trade_currency",
    }


async def test_patch_holding_updates_values_and_increments_version(
    api_client, asset_class_id
) -> None:
    created = await api_client.post("/api/holdings", json=_holding_payload(asset_class_id))
    holding_id = created.json()["id"]

    response = await api_client.patch(
        f"/api/holdings/{holding_id}",
        json={
            "quantity": "12",
            "average_cost_price": "510.50",
            "baseline_fx_to_cny": "7.15",
        },
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == "12"
    assert response.json()["average_cost_price"] == "510.50"
    assert response.json()["baseline_fx_to_cny"] == "7.15"
    assert response.json()["version"] == 2

    listed = (await api_client.get("/api/holdings")).json()
    assert listed == [response.json()]


async def test_patch_holding_rejects_unsupported_market(
    api_client, asset_class_id
) -> None:
    created = await api_client.post("/api/holdings", json=_holding_payload(asset_class_id))

    response = await api_client.patch(
        f"/api/holdings/{created.json()['id']}",
        json={"market": "MOON"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "HOLDING_MARKET_INVALID",
        "message": "Market must be one of US, SH, or SZ.",
        "field": "market",
    }


async def test_patch_holding_switches_preferred_within_asset_class(api_client) -> None:
    asset_class_id = (await api_client.get("/api/asset-classes")).json()[0]["id"]
    first = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(asset_class_id, symbol="SPY"),
        )
    ).json()
    second = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                asset_class_id,
                symbol="VOO",
                name="Vanguard S&P 500 ETF",
                account_name="美股账户 2",
                is_rebalance_preferred=False,
            ),
        )
    ).json()

    response = await api_client.patch(
        f"/api/holdings/{second['id']}",
        json={"is_rebalance_preferred": True},
    )

    assert response.status_code == 200
    holdings = (await api_client.get("/api/holdings")).json()
    first_after = next(item for item in holdings if item["id"] == first["id"])
    second_after = next(item for item in holdings if item["id"] == second["id"])
    assert first_after["is_rebalance_preferred"] is False
    assert second_after["is_rebalance_preferred"] is True


async def test_patch_holding_move_preferred_between_asset_classes(api_client) -> None:
    classes = (await api_client.get("/api/asset-classes")).json()
    source_asset_class_id = classes[0]["id"]
    target_asset_class_id = classes[1]["id"]
    source_preferred = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(source_asset_class_id, symbol="SPY"),
        )
    ).json()
    source_other = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                source_asset_class_id,
                symbol="SCHD",
                name="Schwab US Dividend Equity ETF",
                account_name="分红账户",
                is_rebalance_preferred=False,
            ),
        )
    ).json()
    target_preferred = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                target_asset_class_id,
                symbol="QQQ",
                name="Invesco QQQ Trust",
                account_name="纳指账户",
            ),
        )
    ).json()

    response = await api_client.patch(
        f"/api/holdings/{source_preferred['id']}",
        json={"asset_class_id": target_asset_class_id},
    )

    assert response.status_code == 200
    holdings = (await api_client.get("/api/holdings")).json()
    moved = next(item for item in holdings if item["id"] == source_preferred["id"])
    source_other_after = next(item for item in holdings if item["id"] == source_other["id"])
    target_preferred_after = next(
        item for item in holdings if item["id"] == target_preferred["id"]
    )
    assert moved["asset_class_id"] == target_asset_class_id
    assert moved["is_rebalance_preferred"] is True
    assert source_other_after["is_rebalance_preferred"] is True
    assert target_preferred_after["is_rebalance_preferred"] is False


async def test_concurrent_opposite_preferred_moves_do_not_deadlock(
    api_client, monkeypatch
) -> None:
    classes = (await api_client.get("/api/asset-classes")).json()
    first_class_id = classes[0]["id"]
    second_class_id = classes[1]["id"]
    first = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(first_class_id, symbol="SPY"),
        )
    ).json()
    second = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                second_class_id,
                symbol="QQQ",
                name="Invesco QQQ Trust",
                account_name="纳指账户",
            ),
        )
    ).json()

    original_get_active_holding = holdings_service._get_active_holding
    both_source_rows_locked = asyncio.Event()
    counter_lock = asyncio.Lock()
    locked_source_count = 0

    async def synchronize_after_source_lock(*args, **kwargs):
        nonlocal locked_source_count
        holding = await original_get_active_holding(*args, **kwargs)
        async with counter_lock:
            locked_source_count += 1
            if locked_source_count == 2:
                both_source_rows_locked.set()
        try:
            await asyncio.wait_for(both_source_rows_locked.wait(), timeout=1)
        except TimeoutError:
            pass
        return holding

    monkeypatch.setattr(
        holdings_service,
        "_get_active_holding",
        synchronize_after_source_lock,
    )

    results = await asyncio.gather(
        api_client.patch(
            f"/api/holdings/{first['id']}",
            json={"asset_class_id": second_class_id},
        ),
        api_client.patch(
            f"/api/holdings/{second['id']}",
            json={"asset_class_id": first_class_id},
        ),
        return_exceptions=True,
    )

    assert all(isinstance(result, Response) for result in results)
    assert [result.status_code for result in results if isinstance(result, Response)] == [
        200,
        200,
    ]

    holdings = (await api_client.get("/api/holdings")).json()
    for asset_class_id in (first_class_id, second_class_id):
        class_holdings = [
            item for item in holdings if item["asset_class_id"] == asset_class_id
        ]
        assert sum(item["is_rebalance_preferred"] for item in class_holdings) == 1


async def test_create_holding_rejects_negative_numeric_fields_with_structured_error(
    api_client, asset_class_id
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, quantity="-1"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NEGATIVE_NUMERIC_FIELD"
    assert response.json()["detail"]["field"] == "quantity"


async def test_patch_holding_rejects_negative_numeric_fields_with_structured_error(
    api_client, asset_class_id
) -> None:
    created = await api_client.post("/api/holdings", json=_holding_payload(asset_class_id))

    response = await api_client.patch(
        f"/api/holdings/{created.json()['id']}",
        json={"quantity_precision": -1},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NEGATIVE_NUMERIC_FIELD"
    assert response.json()["detail"]["field"] == "quantity_precision"


async def test_archive_holding_rejects_non_zero_quantity(api_client, asset_class_id) -> None:
    created = await api_client.post("/api/holdings", json=_holding_payload(asset_class_id))
    holding_id = created.json()["id"]

    response = await api_client.post(f"/api/holdings/{holding_id}/archive")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "HOLDING_NOT_EMPTY"
    assert (await api_client.get("/api/holdings")).json()[0]["id"] == holding_id


async def test_archive_zero_quantity_hiding_from_active_list(
    api_client, asset_class_id
) -> None:
    created = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, quantity="0"),
    )
    holding_id = created.json()["id"]

    response = await api_client.post(f"/api/holdings/{holding_id}/archive")

    assert response.status_code == 200
    assert response.json()["id"] == holding_id
    assert response.json()["is_active"] is False
    assert (await api_client.get("/api/holdings")).json() == []


async def test_list_holdings_can_include_archived_without_changing_default_order(
    api_client, asset_class_id
) -> None:
    archived = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                asset_class_id,
                symbol="ZERO",
                account_name="归档账户",
                quantity="0",
            ),
        )
    ).json()
    active = (
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                asset_class_id,
                symbol="SPY",
                account_name="长期账户",
            ),
        )
    ).json()
    archived_response = await api_client.post(f"/api/holdings/{archived['id']}/archive")
    assert archived_response.status_code == 200

    default_response = await api_client.get("/api/holdings")
    include_archived_response = await api_client.get(
        "/api/holdings", params={"include_archived": "true"}
    )

    assert [item["id"] for item in default_response.json()] == [active["id"]]
    assert [item["id"] for item in include_archived_response.json()] == [
        archived["id"],
        active["id"],
    ]
    assert include_archived_response.json()[0]["is_active"] is False
    assert include_archived_response.json()[1]["is_active"] is True


async def test_archive_then_recreate_same_symbol_and_account(
    api_client, asset_class_id, db_session
) -> None:
    payload = _holding_payload(asset_class_id, quantity="0")
    archived = await api_client.post("/api/holdings", json=payload)
    archived_id = archived.json()["id"]
    archive_response = await api_client.post(
        f"/api/holdings/{archived_id}/archive"
    )

    recreated = await api_client.post("/api/holdings", json=payload)

    assert archive_response.status_code == 200
    assert recreated.status_code == 201
    assert recreated.json()["id"] != archived_id

    rows = list(
        await db_session.scalars(
            select(Holding)
            .where(
                Holding.symbol == payload["symbol"],
                Holding.account_name == payload["account_name"],
            )
            .order_by(Holding.created_at.asc())
        )
    )
    assert [(str(row.id), row.is_active) for row in rows] == [
        (archived_id, False),
        (recreated.json()["id"], True),
    ]


async def test_duplicate_active_symbol_and_account_returns_structured_conflict(
    api_client, asset_class_id
) -> None:
    payload = _holding_payload(asset_class_id)
    first = await api_client.post("/api/holdings", json=payload)

    duplicate = await api_client.post("/api/holdings", json=payload)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "HOLDING_ALREADY_EXISTS"
    assert len((await api_client.get("/api/holdings")).json()) == 1


async def test_create_holding_missing_field_uses_fastapi_validation_detail(
    api_client, asset_class_id
) -> None:
    payload = _holding_payload(asset_class_id)
    del payload["symbol"]

    response = await api_client.post("/api/holdings", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.json()["detail"][0]["type"] == "missing"
    assert response.json()["detail"][0]["loc"] == ["body", "symbol"]
