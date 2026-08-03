from smtplib import SMTPAuthenticationError
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.db.models import EncryptedSecret, Setting


def _email_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": True,
        "recipient": "owner@example.com",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "smtp_username": "owner@qq.com",
        "from_address": None,
        "password": "smtp-auth-code",
    }
    payload.update(overrides)
    return payload


async def test_email_settings_round_trip_and_encrypted_password(api_client, db_session) -> None:
    initial = await api_client.get("/api/settings/email")
    assert initial.status_code == 200, initial.text
    assert initial.json()["enabled"] is False
    assert initial.json()["smtp_port"] == 465
    assert initial.json()["smtp_security"] == "ssl"
    assert initial.json()["password_masked"] is None

    saved = await api_client.put("/api/settings/email", json=_email_payload())
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is True
    assert saved.json()["recipient"] == "owner@example.com"
    assert saved.json()["password_masked"] == "****code"
    assert "smtp-auth-code" not in saved.text

    fetched = await api_client.get("/api/settings/email")
    db_session.expire_all()
    stored = await db_session.scalar(select(Setting).limit(1))
    secret = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["password_masked"] == "****code"
    assert stored.email_enabled is True
    assert stored.email_recipient == "owner@example.com"
    assert stored.email_smtp_host == "smtp.qq.com"
    assert stored.email_smtp_port == 465
    assert stored.email_smtp_security == "ssl"
    assert stored.email_smtp_username == "owner@qq.com"
    assert secret is not None
    assert secret.masked_value == "****code"
    assert "smtp-auth-code" not in secret.encrypted_value

    kept = await api_client.put(
        "/api/settings/email",
        json=_email_payload(password="", recipient="other@example.com"),
    )
    db_session.expire_all()
    secret_after = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )

    assert kept.status_code == 200, kept.text
    assert kept.json()["recipient"] == "other@example.com"
    assert kept.json()["password_masked"] == "****code"
    assert secret_after is not None
    assert secret_after.masked_value == "****code"


async def test_email_settings_validation_errors(api_client) -> None:
    bad_email = await api_client.put(
        "/api/settings/email",
        json=_email_payload(recipient="not-an-email"),
    )
    incomplete = await api_client.put(
        "/api/settings/email",
        json=_email_payload(enabled=True, recipient="", smtp_host="", smtp_username=""),
    )
    bad_port = await api_client.put(
        "/api/settings/email",
        json=_email_payload(smtp_port=0),
    )

    assert bad_email.status_code == 422
    assert incomplete.status_code == 422
    assert bad_port.status_code == 422


async def test_email_test_endpoint_returns_ok(api_client, db_session, monkeypatch) -> None:
    await api_client.put("/api/settings/email", json=_email_payload())
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_settings.send_email", send)

    response = await api_client.post("/api/settings/email/test")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "error_category": None}
    send.assert_awaited_once()


async def test_email_test_endpoint_reports_failure_category(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await api_client.put("/api/settings/email", json=_email_payload())

    async def _fail(*args, **kwargs):
        raise SMTPAuthenticationError(535, b"auth")

    monkeypatch.setattr("app.services.email_settings.send_email", _fail)

    response = await api_client.post("/api/settings/email/test")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "failed", "error_category": "smtp_auth_failed"}


async def test_email_test_endpoint_not_configured(api_client) -> None:
    response = await api_client.post("/api/settings/email/test")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "failed", "error_category": "not_configured"}
