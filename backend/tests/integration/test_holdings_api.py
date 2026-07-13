import pytest


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
