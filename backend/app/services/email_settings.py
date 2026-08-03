from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.db.models import EncryptedSecret, Setting
from app.schemas.email_settings import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
)
from app.services.errors import ServiceError


def _secret_store() -> SecretStore:
    return SecretStore(Path(get_settings().secret_key_path))


def _mask_secret(value: str) -> str:
    suffix = value[-4:] if len(value) >= 4 else value
    return f"****{suffix}"


async def _get_setting(session: AsyncSession, *, lock: bool = False) -> Setting:
    statement = select(Setting).limit(1)
    if lock:
        statement = statement.with_for_update()
    setting = await session.scalar(statement)
    if setting is None:
        raise RuntimeError("Default settings row is missing.")
    return setting


async def _smtp_secret(session: AsyncSession) -> EncryptedSecret | None:
    return await session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )


async def get_email_settings(session: AsyncSession) -> EmailSettingsResponse:
    setting = await _get_setting(session)
    secret = await _smtp_secret(session)
    return EmailSettingsResponse(
        enabled=setting.email_enabled,
        recipient=setting.email_recipient,
        smtp_host=setting.email_smtp_host,
        smtp_port=setting.email_smtp_port,
        smtp_security=setting.email_smtp_security,  # type: ignore[arg-type]
        smtp_username=setting.email_smtp_username,
        from_address=setting.email_from,
        password_masked=secret.masked_value if secret is not None else None,
        updated_at=setting.updated_at,
    )


async def update_email_settings(
    session: AsyncSession,
    payload: EmailSettingsUpdate,
) -> EmailSettingsResponse:
    setting = await _get_setting(session, lock=True)
    setting.email_enabled = payload.enabled
    setting.email_recipient = payload.recipient
    setting.email_smtp_host = payload.smtp_host
    setting.email_smtp_port = payload.smtp_port
    setting.email_smtp_security = payload.smtp_security
    setting.email_smtp_username = payload.smtp_username
    setting.email_from = payload.from_address
    setting.updated_at = datetime.now(UTC)

    secret = await _smtp_secret(session)
    if payload.password:
        encrypted = _secret_store().encrypt(payload.password).decode("ascii")
        if secret is None:
            session.add(
                EncryptedSecret(
                    provider="smtp",
                    encrypted_value=encrypted,
                    masked_value=_mask_secret(payload.password),
                )
            )
        else:
            secret.encrypted_value = encrypted
            secret.masked_value = _mask_secret(payload.password)
            secret.validation_status = None
            secret.validation_message = None
            secret.last_validated_at = None
    await session.flush()
    return await get_email_settings(session)


async def require_email_configured(session: AsyncSession) -> EncryptedSecret:
    secret = await _smtp_secret(session)
    if secret is None:
        raise ServiceError(409, "EMAIL_NOT_CONFIGURED", "SMTP authorization code is not configured.")
    return secret
