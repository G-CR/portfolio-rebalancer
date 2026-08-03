import smtplib
from unittest.mock import MagicMock, Mock

import pytest

from app.services.email_sender import (
    EmailConfig,
    classify_smtp_error,
    send_email,
)


def _config(**overrides: object) -> EmailConfig:
    values: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 465,
        "security": "ssl",
        "username": "owner@example.com",
        "password": "secret-auth-code",
        "from_address": "owner@example.com",
        "recipient": "receiver@example.com",
    }
    values.update(overrides)
    return EmailConfig(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_send_email_ssl_branch(monkeypatch) -> None:
    server = MagicMock()
    server.__enter__.return_value = server
    smtp_ssl = Mock(return_value=server)
    monkeypatch.setattr("app.services.email_sender.smtplib.SMTP_SSL", smtp_ssl)

    await send_email(_config(), subject="投资组合日报 2026-08-03", html="<p>内容</p>")

    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)
    server.login.assert_called_once_with("owner@example.com", "secret-auth-code")
    sent = server.send_message.call_args.args[0]
    assert "投资组合日报" in str(sent["Subject"])
    assert sent["To"] == "receiver@example.com"
    assert "<p>内容</p>" in sent.get_payload()[1].get_payload()
    server.__enter__.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_starttls_branch(monkeypatch) -> None:
    server = MagicMock()
    server.__enter__.return_value = server
    monkeypatch.setattr("app.services.email_sender.smtplib.SMTP", Mock(return_value=server))

    await send_email(
        _config(port=587, security="starttls"),
        subject="test",
        html="<p>内容</p>",
    )

    server.starttls.assert_called_once()
    server.login.assert_called_once()


def test_classify_smtp_errors() -> None:
    assert classify_smtp_error(smtplib.SMTPAuthenticationError(535, b"auth")) == "smtp_auth_failed"
    assert classify_smtp_error(smtplib.SMTPRecipientsRefused({})) == "smtp_recipient_rejected"
    assert classify_smtp_error(ConnectionError("boom")) == "smtp_connect_failed"
    assert classify_smtp_error(TimeoutError("slow")) == "smtp_timeout"
    assert classify_smtp_error(smtplib.SMTPException("other")) == "smtp_send_failed"
