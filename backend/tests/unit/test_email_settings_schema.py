import pytest
from pydantic import ValidationError

from app.schemas.email_settings import EmailSettingsUpdate


def test_email_settings_update_accepts_valid_payload() -> None:
    payload = EmailSettingsUpdate(
        enabled=True,
        recipient="owner@example.com",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_security="ssl",
        smtp_username="owner@example.com",
        from_address=None,
        password="auth-code",
    )

    assert payload.recipient == "owner@example.com"
    assert payload.smtp_port == 465


def test_email_settings_update_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        EmailSettingsUpdate(
            enabled=False,
            recipient="not-an-email",
            smtp_host="",
            smtp_port=465,
            smtp_security="ssl",
            smtp_username="",
        )


def test_email_settings_update_requires_complete_config_when_enabled() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EmailSettingsUpdate(
            enabled=True,
            recipient="",
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_security="ssl",
            smtp_username="owner@example.com",
        )

    assert exc_info.value.errors()[0]["ctx"]["field"] == "recipient"


def test_email_settings_update_rejects_bad_port_and_security() -> None:
    with pytest.raises(ValidationError):
        EmailSettingsUpdate(
            enabled=False,
            recipient="owner@example.com",
            smtp_host="smtp.qq.com",
            smtp_port=0,
            smtp_security="ssl",
            smtp_username="owner@example.com",
        )
    with pytest.raises(ValidationError):
        EmailSettingsUpdate(
            enabled=False,
            recipient="owner@example.com",
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_security="plain",
            smtp_username="owner@example.com",
        )
