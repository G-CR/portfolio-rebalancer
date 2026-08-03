from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage
import logging
import smtplib
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmailConfig:
    host: str
    port: int
    security: Literal["ssl", "starttls"]
    username: str
    password: str
    from_address: str
    recipient: str


def _send_smtp_sync(config: EmailConfig, message: EmailMessage) -> None:
    if config.security == "ssl":
        with smtplib.SMTP_SSL(config.host, config.port, timeout=30) as server:
            server.login(config.username, config.password)
            server.send_message(message, from_addr=config.from_address, to_addrs=[config.recipient])
        return
    with smtplib.SMTP(config.host, config.port, timeout=30) as server:
        server.starttls()
        server.login(config.username, config.password)
        server.send_message(message, from_addr=config.from_address, to_addrs=[config.recipient])


async def send_email(config: EmailConfig, *, subject: str, html: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = config.recipient
    message.set_content("请使用支持 HTML 的邮件客户端查看本邮件。")
    message.add_alternative(html, subtype="html")
    await asyncio.to_thread(_send_smtp_sync, config, message)


def classify_smtp_error(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "smtp_auth_failed"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "smtp_recipient_rejected"
    if isinstance(exc, TimeoutError):
        return "smtp_timeout"
    if isinstance(exc, smtplib.SMTPException):
        return "smtp_send_failed"
    if isinstance(exc, (ConnectionError, OSError)):
        return "smtp_connect_failed"
    return "smtp_send_failed"
