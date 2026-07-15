from decimal import Decimal

from sqlalchemy import select

from app.db.models import EncryptedSecret, Setting


async def test_provider_key_is_never_returned(api_client, db_session) -> None:
    response = await api_client.put(
        "/api/settings/providers/alpha_vantage",
        json={"api_key": "alpha-secret-value", "priority": 1, "enabled": True},
    )
    listed = await api_client.get("/api/settings/providers")
    item = next(value for value in listed.json() if value["provider"] == "alpha_vantage")
    db_session.expire_all()
    stored = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "alpha_vantage")
    )

    assert response.status_code == 200, response.text
    assert listed.status_code == 200, listed.text
    assert item["key_status"] == "configured"
    assert item["masked_key"].endswith("alue")
    assert "alpha-secret-value" not in response.text
    assert "alpha-secret-value" not in listed.text
    assert "alpha-secret-value" not in stored.encrypted_value


async def test_general_settings_round_trip_decimal_strings(api_client, db_session) -> None:
    response = await api_client.put(
        "/api/settings/general",
        json={
            "refresh_time": "09:15",
            "provider_priority": [
                "akshare",
                "yahoo",
                "sina",
                "tushare",
                "alpha_vantage",
            ],
            "default_tolerance": "0.025",
            "minimum_trade_amount_cny": "800",
            "allow_sell": False,
            "allow_fx": True,
        },
    )
    fetched = await api_client.get("/api/settings/general")
    db_session.expire_all()
    stored = await db_session.scalar(select(Setting).limit(1))

    assert response.status_code == 200, response.text
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == response.json()
    assert response.json()["refresh_time"] == "09:15"
    assert response.json()["default_tolerance"] == "0.025"
    assert response.json()["minimum_trade_amount_cny"] == "800"
    assert stored.refresh_hour == 9
    assert stored.refresh_minute == 15
    assert stored.default_tolerance == Decimal("0.025")


async def test_legacy_provider_priority_inserts_sina_after_yahoo(
    api_client,
    db_session,
) -> None:
    setting = await db_session.scalar(select(Setting).limit(1))
    setting.provider_priority = ["akshare", "yahoo", "tushare", "alpha_vantage"]
    await db_session.commit()

    response = await api_client.get("/api/settings/general")

    assert response.status_code == 200
    assert response.json()["provider_priority"] == [
        "akshare",
        "yahoo",
        "sina",
        "tushare",
        "alpha_vantage",
    ]


async def test_provider_validation_updates_only_safe_status(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await api_client.put(
        "/api/settings/providers/tushare",
        json={"api_key": "tushare-sensitive-token", "priority": 2, "enabled": True},
    )

    async def _successful_validation(provider: str, api_key: str) -> None:
        assert provider == "tushare"
        assert api_key == "tushare-sensitive-token"

    monkeypatch.setattr(
        "app.services.settings.validate_provider_credential",
        _successful_validation,
    )
    response = await api_client.post("/api/settings/providers/tushare/test")
    db_session.expire_all()
    stored = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "tushare")
    )

    assert response.status_code == 200, response.text
    assert response.json()["validation_status"] == "valid"
    assert response.json()["last_validated_at"] is not None
    assert "tushare-sensitive-token" not in response.text
    assert stored.validation_message == "Credential validation succeeded."


async def test_disabling_keyed_provider_removes_usable_credential(api_client, db_session) -> None:
    await api_client.put(
        "/api/settings/providers/alpha_vantage",
        json={"api_key": "temporary-secret", "priority": 1, "enabled": True},
    )
    response = await api_client.put(
        "/api/settings/providers/alpha_vantage",
        json={"api_key": None, "priority": 4, "enabled": False},
    )
    db_session.expire_all()
    stored = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "alpha_vantage")
    )

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert response.json()["key_status"] == "not_configured"
    assert stored is None
