from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.db.models import EncryptedSecret, Setting
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.tushare import TushareProvider
from app.schemas.settings import (
    GeneralSettingsResponse,
    GeneralSettingsUpdate,
    ProviderName,
    ProviderSettingResponse,
    ProviderSettingUpdate,
)
from app.services.errors import ServiceError

_PROVIDER_ORDER: tuple[ProviderName, ...] = (
    "akshare",
    "yahoo",
    "tushare",
    "alpha_vantage",
)
_PROVIDER_LABELS: dict[ProviderName, str] = {
    "akshare": "AKShare",
    "yahoo": "Yahoo Finance",
    "tushare": "Tushare",
    "alpha_vantage": "Alpha Vantage",
}
_KEYED_PROVIDERS = {"tushare", "alpha_vantage"}


@dataclass(frozen=True, slots=True)
class EncryptedProviderCredentialReader:
    credentials: dict[str, str]

    def get_api_key(self, provider: str) -> str | None:
        return self.credentials.get(provider)


def _secret_store() -> SecretStore:
    return SecretStore(Path(get_settings().secret_key_path))


async def load_provider_credential_reader(session: AsyncSession) -> EncryptedProviderCredentialReader:
    rows = list(await session.scalars(select(EncryptedSecret)))
    store = _secret_store()
    credentials: dict[str, str] = {}
    for row in rows:
        try:
            credentials[row.provider] = store.decrypt(row.encrypted_value.encode("ascii"))
        except Exception as exc:
            raise RuntimeError(f"Stored credential for provider {row.provider} cannot be decrypted.") from exc
    return EncryptedProviderCredentialReader(credentials)


async def list_provider_settings(session: AsyncSession) -> list[ProviderSettingResponse]:
    setting = await _get_setting(session)
    rows = {
        row.provider: row
        for row in await session.scalars(select(EncryptedSecret).order_by(EncryptedSecret.provider))
    }
    priority = _normalized_priority(setting.provider_priority)
    return [
        _provider_response(provider, priority.index(provider) + 1, rows.get(provider))
        for provider in priority
    ]


async def update_provider_setting(
    session: AsyncSession,
    *,
    provider: ProviderName,
    payload: ProviderSettingUpdate,
) -> ProviderSettingResponse:
    setting = await _get_setting(session, lock=True)
    priority = _normalized_priority(setting.provider_priority)
    priority.remove(provider)
    priority.insert(payload.priority - 1, provider)
    setting.provider_priority = priority

    row = await session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == provider).with_for_update()
    )
    if provider not in _KEYED_PROVIDERS:
        if payload.api_key:
            raise ServiceError(422, "PROVIDER_KEY_NOT_SUPPORTED", "This provider does not use an API key.")
        await session.flush()
        return _provider_response(provider, priority.index(provider) + 1, None)

    if not payload.enabled:
        if row is not None:
            await session.delete(row)
        await session.flush()
        return _provider_response(provider, priority.index(provider) + 1, None)

    api_key = payload.api_key
    if api_key is None and row is None:
        raise ServiceError(
            422,
            "PROVIDER_KEY_REQUIRED",
            "An API key is required before this provider can be enabled.",
        )
    if api_key:
        encrypted = _secret_store().encrypt(api_key).decode("ascii")
        masked = _mask_secret(api_key)
        if row is None:
            row = EncryptedSecret(
                provider=provider,
                encrypted_value=encrypted,
                masked_value=masked,
            )
            session.add(row)
        else:
            row.encrypted_value = encrypted
            row.masked_value = masked
            row.validation_status = None
            row.validation_message = None
            row.last_validated_at = None
    await session.flush()
    return _provider_response(provider, priority.index(provider) + 1, row)


async def test_provider_setting(
    session: AsyncSession,
    *,
    provider: ProviderName,
) -> ProviderSettingResponse:
    if provider not in _KEYED_PROVIDERS:
        raise ServiceError(422, "PROVIDER_TEST_NOT_REQUIRED", "This provider does not require credential validation.")
    setting = await _get_setting(session)
    row = await session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == provider).with_for_update()
    )
    if row is None:
        raise ServiceError(409, "PROVIDER_NOT_CONFIGURED", "Provider credential is not configured.")
    api_key = _secret_store().decrypt(row.encrypted_value.encode("ascii"))
    try:
        await validate_provider_credential(provider, api_key)
    except Exception:
        row.validation_status = "failed"
        row.validation_message = "Credential validation failed."
    else:
        row.validation_status = "valid"
        row.validation_message = "Credential validation succeeded."
    row.last_validated_at = datetime.now(UTC)
    await session.flush()
    priority = _normalized_priority(setting.provider_priority)
    return _provider_response(provider, priority.index(provider) + 1, row)


async def validate_provider_credential(provider: str, api_key: str) -> None:
    reader = EncryptedProviderCredentialReader({provider: api_key})
    if provider == "tushare":
        await TushareProvider(reader).fetch_fx("USD", "CNY")
        return
    if provider == "alpha_vantage":
        await AlphaVantageProvider(reader).fetch_fx("USD", "CNY")
        return
    raise ValueError("Unsupported credential provider.")


async def get_general_settings(session: AsyncSession) -> GeneralSettingsResponse:
    return _general_response(await _get_setting(session))


async def update_general_settings(
    session: AsyncSession,
    payload: GeneralSettingsUpdate,
) -> GeneralSettingsResponse:
    setting = await _get_setting(session, lock=True)
    hour, minute = (int(part) for part in payload.refresh_time.split(":"))
    setting.refresh_hour = hour
    setting.refresh_minute = minute
    setting.provider_priority = list(payload.provider_priority)
    setting.default_tolerance = payload.default_tolerance
    setting.minimum_trade_amount_cny = payload.minimum_trade_amount_cny
    setting.allow_sell = payload.allow_sell
    setting.allow_fx = payload.allow_fx
    setting.updated_at = datetime.now(UTC)
    await session.flush()
    return _general_response(setting)


async def _get_setting(session: AsyncSession, *, lock: bool = False) -> Setting:
    statement = select(Setting).limit(1)
    if lock:
        statement = statement.with_for_update()
    setting = await session.scalar(statement)
    if setting is None:
        raise RuntimeError("Default settings row is missing.")
    return setting


def _normalized_priority(value: list[str]) -> list[ProviderName]:
    result: list[ProviderName] = []
    for candidate in [*value, *_PROVIDER_ORDER]:
        if candidate in _PROVIDER_ORDER and candidate not in result:
            result.append(candidate)  # type: ignore[arg-type]
    return result


def _mask_secret(value: str) -> str:
    suffix = value[-4:] if len(value) >= 4 else value
    return f"****{suffix}"


def _provider_response(
    provider: ProviderName,
    priority: int,
    row: EncryptedSecret | None,
) -> ProviderSettingResponse:
    requires_key = provider in _KEYED_PROVIDERS
    return ProviderSettingResponse(
        provider=provider,
        display_name=_PROVIDER_LABELS[provider],
        requires_key=requires_key,
        enabled=not requires_key or row is not None,
        priority=priority,
        key_status=("not_required" if not requires_key else "configured" if row is not None else "not_configured"),
        masked_key=row.masked_value if row is not None else None,
        validation_status=row.validation_status if row is not None else None,
        validation_message=row.validation_message if row is not None else None,
        last_validated_at=row.last_validated_at if row is not None else None,
    )


def _general_response(setting: Setting) -> GeneralSettingsResponse:
    return GeneralSettingsResponse(
        refresh_time=f"{setting.refresh_hour:02d}:{setting.refresh_minute:02d}",
        provider_priority=_normalized_priority(setting.provider_priority),
        default_tolerance=setting.default_tolerance,
        minimum_trade_amount_cny=setting.minimum_trade_amount_cny,
        allow_sell=setting.allow_sell,
        allow_fx=setting.allow_fx,
        updated_at=setting.updated_at,
    )
