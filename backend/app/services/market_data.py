from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import logging

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal import fits_numeric_28_12
from app.core.market import normalize_currency_code, normalize_market_code
from app.db.models import AssetClass, Holding, MarketData, MarketDataOverride, Setting
from app.providers.akshare import AkshareProvider
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.base import (
    MarketQuote,
    NullCredentialReader,
    ProviderError,
    ProviderNotConfigured,
    ProviderPayloadError,
    ProviderRequestError,
)
from app.providers.tushare import TushareProvider
from app.providers.yahoo import YahooProvider
from app.schemas.market_data import (
    MarketDataCollectionResponse,
    MarketDataDiagnosticResponse,
    MarketDataStatusResponse,
)
from app.services.errors import ServiceError
from app.services.settings import load_provider_credential_reader

_ONE = Decimal("1")
_ERROR_SUMMARY_LIMIT = 200
_DOMESTIC_PROVIDER_ORDER = ("akshare", "tushare")
_INTERNATIONAL_PROVIDER_ORDER = ("yahoo", "alpha_vantage")
_FX_PROVIDER_ORDER = ("yahoo", "alpha_vantage")
_SAFE_FAILURE_DETAILS = {
    "provider_not_configured": "Market-data provider is not configured.",
    "provider_payload_invalid": "Market-data provider returned invalid data.",
    "provider_request_failed": "Market-data provider request failed.",
    "provider_internal_error": "Market-data provider failed unexpectedly.",
    "legacy_refresh_error": "Previous market-data refresh failed.",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ManualOverride:
    value: Decimal
    note: str
    starts_at: datetime
    expires_at: datetime | None

    def is_active(self, *, now: datetime) -> bool:
        if self.starts_at > now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True


@dataclass(frozen=True, slots=True)
class AutomatedValue:
    value: Decimal | None
    source: str
    as_of: datetime | None
    fetched_at: datetime
    status: str
    error_summary: str | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveValue:
    value: Decimal | None
    source: str | None
    status: str
    as_of: datetime | None
    fetched_at: datetime | None
    error_summary: str | None = None
    note: str | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedMarketDataKey:
    key: str
    data_type: str
    symbol: str

    @property
    def fx_pair(self) -> tuple[str, str] | None:
        if self.data_type != "fx":
            return None
        base, quote = self.symbol.split("/", 1)
        return (base, quote)


@dataclass(frozen=True, slots=True)
class RequiredMarketDataItem:
    key: str
    data_type: str
    symbol: str
    currency: str
    market: str | None = None
    preferred_source: str | None = None


@dataclass(frozen=True, slots=True)
class RequiredMarketDataCollection:
    items: list[RequiredMarketDataItem]
    diagnostics: list[MarketDataDiagnosticResponse]


class ProviderRegistry:
    def __init__(self) -> None:
        credentials = NullCredentialReader()
        self._providers = {
            "yahoo": YahooProvider(),
            "akshare": AkshareProvider(),
            "tushare": TushareProvider(credentials),
            "alpha_vantage": AlphaVantageProvider(credentials),
        }

    def configure_credentials(self, credentials) -> None:
        self._providers["tushare"] = TushareProvider(credentials)
        self._providers["alpha_vantage"] = AlphaVantageProvider(credentials)

    async def fetch_price(
        self,
        symbol: str,
        *,
        market: str,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        last_error: ProviderError | None = None
        last_provider_name: str | None = None
        for provider_name in _provider_order_for_price(
            market=market,
            preferred_source=preferred_source,
            provider_priority=provider_priority or [],
        ):
            provider = self._providers[provider_name]
            try:
                return await provider.fetch_price(symbol)
            except ProviderNotConfigured as exc:
                last_provider_name = provider_name
                last_error = exc
                continue
            except ProviderError as exc:
                last_provider_name = provider_name
                last_error = exc
                continue
        if last_error is not None:
            raise ProviderSelectionError(last_provider_name or "unknown", last_error)
        raise ProviderError(f"No configured provider could refresh price for {symbol}.")

    async def fetch_fx(
        self,
        base: str,
        quote: str,
        *,
        preferred_source: str | None = None,
        provider_priority: list[str] | None = None,
    ) -> MarketQuote:
        last_error: ProviderError | None = None
        last_provider_name: str | None = None
        for provider_name in _provider_order_for_fx(
            preferred_source=preferred_source,
            provider_priority=provider_priority or [],
        ):
            provider = self._providers[provider_name]
            try:
                return await provider.fetch_fx(base, quote)
            except ProviderNotConfigured as exc:
                last_provider_name = provider_name
                last_error = exc
                continue
            except ProviderError as exc:
                last_provider_name = provider_name
                last_error = exc
                continue
        if last_error is not None:
            raise ProviderSelectionError(last_provider_name or "unknown", last_error)
        raise ProviderError(f"No configured provider could refresh FX for {base}/{quote}.")


class ProviderSelectionError(ProviderError):
    def __init__(self, provider_name: str, cause: ProviderError) -> None:
        super().__init__("No market-data provider returned a valid quote.")
        self.provider_name = provider_name
        self.failure_category = _provider_failure_category(cause)


def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry()


def resolve_effective_value(
    *,
    automated: AutomatedValue | None,
    override: ManualOverride | None,
    now: datetime,
) -> EffectiveValue:
    if override is not None and override.is_active(now=now):
        return EffectiveValue(
            value=override.value,
            source="manual",
            status="manual",
            as_of=override.starts_at,
            fetched_at=override.starts_at,
            note=override.note,
        )

    if automated is not None:
        return EffectiveValue(
            value=automated.value,
            source=automated.source,
            status=automated.status,
            as_of=automated.as_of,
            fetched_at=automated.fetched_at,
            error_summary=automated.error_summary,
            currency=automated.currency,
        )

    return EffectiveValue(
        value=None,
        source=None,
        status="missing",
        as_of=None,
        fetched_at=None,
    )


async def list_market_data(session: AsyncSession) -> MarketDataCollectionResponse:
    required = await _collect_required_market_data_items(session)
    return await _build_market_data_response(
        session,
        required.items,
        diagnostics=required.diagnostics,
    )


async def refresh_all_required_data(session: AsyncSession) -> MarketDataCollectionResponse:
    await _acquire_transaction_lock(session, "market-data-refresh-all")
    required = await _collect_required_market_data_items(session)
    required_items = required.items
    registry = get_provider_registry()
    if isinstance(registry, ProviderRegistry):
        registry.configure_credentials(await load_provider_credential_reader(session))
    provider_priority = await _load_provider_priority(session)

    for item in required_items:
        if item.key == "fx:CNY/CNY":
            continue
        try:
            if item.data_type == "price":
                quote = await registry.fetch_price(
                    item.symbol,
                    market=item.market or "",
                    preferred_source=item.preferred_source,
                    provider_priority=provider_priority,
                )
            else:
                base, quote_currency = item.symbol.split("/", 1)
                quote = await registry.fetch_fx(
                    base,
                    quote_currency,
                    preferred_source=item.preferred_source,
                    provider_priority=provider_priority,
                )
            _validate_quote_for_storage(quote)
        except Exception as exc:
            source = exc.provider_name if isinstance(exc, ProviderSelectionError) else _default_failure_source(item)
            logger.warning(
                "Market-data refresh failed provider=%s data_type=%s exception_class=%s",
                source,
                item.data_type,
                type(exc).__name__,
            )
            await _upsert_market_data_row(
                session,
                data_type=item.data_type,
                symbol=item.symbol,
                source=source,
                value=None,
                market_time=None,
                fetched_at=datetime.now(UTC),
                status="failed",
                error_summary=_safe_failure_summary(exc),
            )
            continue

        await _upsert_market_data_row(
            session,
            data_type=item.data_type,
            symbol=item.symbol,
            source=quote.source,
            value=quote.value,
            market_time=quote.as_of,
            fetched_at=quote.fetched_at,
            status="valid",
            error_summary=None,
        )

    await session.flush()
    return await _build_market_data_response(
        session,
        required_items,
        diagnostics=required.diagnostics,
    )


async def set_manual_override(
    session: AsyncSession,
    *,
    raw_key: str,
    value: Decimal,
    note: str,
    effective_at: datetime | None,
    expires_at: datetime | None,
) -> MarketDataStatusResponse:
    parsed_key = parse_market_data_key(raw_key)
    if not value.is_finite() or value <= 0:
        raise ServiceError(
            422,
            "MARKET_DATA_OVERRIDE_VALUE_INVALID",
            "Override value must be positive and finite.",
        )
    if not fits_numeric_28_12(value):
        raise ServiceError(
            422,
            "MARKET_DATA_NUMERIC_OUT_OF_RANGE",
            "Market-data values must fit NUMERIC(28,12).",
            {"field": "value"},
        )
    if not note.strip():
        raise ServiceError(
            422,
            "MARKET_DATA_OVERRIDE_NOTE_REQUIRED",
            "Override note is required.",
        )

    starts_at = effective_at or datetime.now(UTC)
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ServiceError(
            422,
            "MARKET_DATA_OVERRIDE_TIME_INVALID",
            "Override times must be timezone-aware.",
        )
    if expires_at is not None:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ServiceError(
                422,
                "MARKET_DATA_OVERRIDE_TIME_INVALID",
                "Override times must be timezone-aware.",
            )
        if expires_at <= starts_at:
            raise ServiceError(
                422,
                "MARKET_DATA_OVERRIDE_TIME_INVALID",
                "Override expiry must be later than the effective time.",
            )

    await _acquire_transaction_lock(session, f"market-data-override:{parsed_key.key}")
    await session.execute(
        delete(MarketDataOverride).where(
            MarketDataOverride.data_type == parsed_key.data_type,
            MarketDataOverride.symbol == parsed_key.symbol,
        )
    )
    session.add(
        MarketDataOverride(
            data_type=parsed_key.data_type,
            symbol=parsed_key.symbol,
            value=value,
            note=note.strip(),
            effective_at=starts_at,
            expires_at=expires_at,
        )
    )
    await session.flush()

    response = await _status_for_key(session, parsed_key)
    if response is None:
        raise ServiceError(500, "MARKET_DATA_OVERRIDE_WRITE_FAILED", "Override write failed.")
    return response


async def delete_manual_override(session: AsyncSession, *, raw_key: str) -> None:
    parsed_key = parse_market_data_key(raw_key)
    await _acquire_transaction_lock(session, f"market-data-override:{parsed_key.key}")
    existing = await session.scalar(
        select(MarketDataOverride.id).where(
            MarketDataOverride.data_type == parsed_key.data_type,
            MarketDataOverride.symbol == parsed_key.symbol,
        )
    )
    if existing is None:
        raise ServiceError(
            404,
            "MARKET_DATA_OVERRIDE_NOT_FOUND",
            "Active override was not found for the requested market-data key.",
        )
    await session.execute(
        delete(MarketDataOverride).where(
            MarketDataOverride.data_type == parsed_key.data_type,
            MarketDataOverride.symbol == parsed_key.symbol,
        )
    )


def parse_market_data_key(raw_key: str) -> ParsedMarketDataKey:
    if raw_key.startswith("price:"):
        symbol = raw_key.removeprefix("price:").strip()
        if not symbol:
            raise ServiceError(422, "MARKET_DATA_KEY_INVALID", "Market-data key is invalid.")
        return ParsedMarketDataKey(key=f"price:{symbol}", data_type="price", symbol=symbol)

    if raw_key.startswith("fx:"):
        symbol = raw_key.removeprefix("fx:").strip()
        parts = symbol.split("/")
        if len(parts) != 2 or not all(parts):
            raise ServiceError(422, "MARKET_DATA_KEY_INVALID", "Market-data key is invalid.")
        try:
            base, quote = (normalize_currency_code(part) for part in parts)
        except ValueError:
            raise ServiceError(422, "MARKET_DATA_KEY_INVALID", "Market-data key is invalid.")

        return ParsedMarketDataKey(key=f"fx:{base}/{quote}", data_type="fx", symbol=f"{base}/{quote}")

    raise ServiceError(422, "MARKET_DATA_KEY_INVALID", "Market-data key is invalid.")


async def _build_market_data_response(
    session: AsyncSession,
    required_items: list[RequiredMarketDataItem],
    *,
    diagnostics: list[MarketDataDiagnosticResponse] | None = None,
) -> MarketDataCollectionResponse:
    items = [
        response
        for response in [
            await _status_for_item(session, item)
            for item in required_items
        ]
        if response is not None
    ]
    return MarketDataCollectionResponse(items=items, diagnostics=diagnostics or [])


async def _status_for_item(
    session: AsyncSession,
    item: RequiredMarketDataItem,
) -> MarketDataStatusResponse | None:
    if item.key == "fx:CNY/CNY":
        return MarketDataStatusResponse(
            key=item.key,
            data_type=item.data_type,
            symbol=item.symbol,
            currency="CNY",
            effective_value=_ONE,
            source="local",
            status="valid",
        )
    return await _status_for_key(session, parse_market_data_key(item.key), currency=item.currency)


async def _status_for_key(
    session: AsyncSession,
    parsed_key: ParsedMarketDataKey,
    *,
    currency: str | None = None,
) -> MarketDataStatusResponse | None:
    automated_rows = list(
        await session.scalars(
            select(MarketData)
            .where(
                MarketData.data_type == parsed_key.data_type,
                MarketData.symbol == parsed_key.symbol,
            )
            .order_by(MarketData.fetched_at.desc(), MarketData.created_at.desc())
        )
    )
    override_row = await session.scalar(
        select(MarketDataOverride)
        .where(
            MarketDataOverride.data_type == parsed_key.data_type,
            MarketDataOverride.symbol == parsed_key.symbol,
        )
        .order_by(MarketDataOverride.updated_at.desc(), MarketDataOverride.created_at.desc())
    )
    automated = _resolve_automated_value(automated_rows)
    override = (
        ManualOverride(
            value=override_row.value,
            note=override_row.note,
            starts_at=override_row.effective_at,
            expires_at=override_row.expires_at,
        )
        if override_row is not None
        else None
    )
    effective = resolve_effective_value(
        automated=automated,
        override=override,
        now=datetime.now(UTC),
    )
    return MarketDataStatusResponse(
        key=parsed_key.key,
        data_type=parsed_key.data_type,
        symbol=parsed_key.symbol,
        currency=currency or (automated.currency if automated is not None else None) or _currency_for_key(parsed_key),
        effective_value=effective.value,
        source=effective.source,
        status=effective.status,
        market_time=effective.as_of,
        fetched_at=effective.fetched_at,
        error_summary=effective.error_summary,
        note=effective.note,
    )


def _resolve_automated_value(rows: list[MarketData]) -> AutomatedValue | None:
    latest_attempt = max(rows, key=_attempt_order_key, default=None)
    latest_valid = max(
        (row for row in rows if row.status == "valid" and row.value is not None),
        key=_valid_quote_order_key,
        default=None,
    )
    if latest_valid is None:
        if latest_attempt is None:
            return None
        return AutomatedValue(
            value=None,
            source=latest_attempt.source,
            as_of=None,
            fetched_at=latest_attempt.fetched_at,
            status=latest_attempt.status,
            error_summary=_sanitize_error_text(latest_attempt.error_summary),
            currency=_currency_for_symbol(latest_attempt),
        )

    status = "valid"
    error_summary = None
    fetched_at = latest_valid.fetched_at
    if latest_attempt is not None and latest_attempt.status != "valid":
        status = "stale"
        error_summary = _sanitize_error_text(latest_attempt.error_summary)
        fetched_at = latest_attempt.fetched_at

    return AutomatedValue(
        value=latest_valid.value,
        source=latest_valid.source,
        as_of=latest_valid.market_time or latest_valid.fetched_at,
        fetched_at=fetched_at,
        status=status,
        error_summary=error_summary,
        currency=_currency_for_symbol(latest_valid),
    )


def _attempt_order_key(row: MarketData) -> tuple[datetime, datetime]:
    return (row.fetched_at, row.created_at)


def _valid_quote_order_key(row: MarketData) -> tuple[datetime, datetime, datetime]:
    return (
        row.market_time or row.fetched_at,
        row.fetched_at,
        row.created_at,
    )


async def _collect_required_market_data_items(
    session: AsyncSession,
) -> RequiredMarketDataCollection:
    rows = await session.execute(
        select(Holding)
        .join(AssetClass, Holding.asset_class_id == AssetClass.id)
        .where(
            Holding.is_active.is_(True),
            AssetClass.is_active.is_(True),
        )
        .order_by(Holding.symbol.asc(), Holding.account_name.asc())
    )

    deduped: dict[str, RequiredMarketDataItem] = {}
    diagnostics: list[MarketDataDiagnosticResponse] = []
    for holding in rows.scalars():
        invalid_fields: list[str] = []
        try:
            market = normalize_market_code(holding.market)
        except ValueError:
            invalid_fields.append("market")
            market = None
        try:
            trade_currency = normalize_currency_code(holding.trade_currency)
        except ValueError:
            invalid_fields.append("trade_currency")
            trade_currency = None
        if invalid_fields:
            diagnostics.append(
                MarketDataDiagnosticResponse(
                    code="HOLDING_MARKET_DATA_CONFIG_INVALID",
                    message="Holding market-data configuration is invalid.",
                    holding_id=holding.id,
                    symbol=holding.symbol,
                    fields=invalid_fields,
                )
            )
            continue

        price_key = f"price:{holding.symbol}"
        deduped.setdefault(
            price_key,
            RequiredMarketDataItem(
                key=price_key,
                data_type="price",
                symbol=holding.symbol,
                currency=trade_currency,
                market=market,
                preferred_source=holding.preferred_data_source,
            ),
        )

        if trade_currency == "CNY":
            fx_key = "fx:CNY/CNY"
            deduped.setdefault(
                fx_key,
                RequiredMarketDataItem(
                    key=fx_key,
                    data_type="fx",
                    symbol="CNY/CNY",
                    currency="CNY",
                ),
            )
            continue

        fx_symbol = f"{trade_currency}/CNY"
        fx_key = f"fx:{fx_symbol}"
        deduped.setdefault(
            fx_key,
            RequiredMarketDataItem(
                key=fx_key,
                data_type="fx",
                symbol=fx_symbol,
                currency="CNY",
            ),
        )

    return RequiredMarketDataCollection(
        items=[deduped[key] for key in sorted(deduped)],
        diagnostics=diagnostics,
    )


async def _load_provider_priority(session: AsyncSession) -> list[str]:
    priority = await session.scalar(select(Setting.provider_priority).limit(1))
    if priority is None:
        return []
    return [str(item) for item in priority]


async def _upsert_market_data_row(
    session: AsyncSession,
    *,
    data_type: str,
    symbol: str,
    source: str,
    value: Decimal | None,
    market_time: datetime | None,
    fetched_at: datetime,
    status: str,
    error_summary: str | None,
) -> None:
    statement = insert(MarketData).values(
        data_type=data_type,
        symbol=symbol,
        source=source,
        value=value,
        market_time=market_time,
        fetched_at=fetched_at,
        status=status,
        error_summary=error_summary,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_market_data_source_key",
            set_={
                "value": value,
                "fetched_at": fetched_at,
                "status": status,
                "error_summary": error_summary,
            },
        )
    )


async def _acquire_transaction_lock(session: AsyncSession, lock_key: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )


def _sanitize_error_text(value: str | None) -> str | None:
    if value is None:
        return None
    category = value.partition(":")[0]
    if category not in _SAFE_FAILURE_DETAILS:
        category = "legacy_refresh_error"
    return _format_failure_summary(category)


def _safe_failure_summary(exc: Exception) -> str:
    if isinstance(exc, ProviderSelectionError):
        return _format_failure_summary(exc.failure_category)
    return _format_failure_summary(_provider_failure_category(exc))


def _provider_failure_category(exc: Exception) -> str:
    if isinstance(exc, ProviderNotConfigured):
        return "provider_not_configured"
    if isinstance(exc, ProviderPayloadError):
        return "provider_payload_invalid"
    if isinstance(exc, ProviderRequestError):
        return "provider_request_failed"
    return "provider_internal_error"


def _format_failure_summary(category: str) -> str:
    detail = _SAFE_FAILURE_DETAILS[category]
    return f"{category}: {detail}"[:_ERROR_SUMMARY_LIMIT]


def _validate_quote_for_storage(quote: MarketQuote) -> None:
    if not quote.value.is_finite() or quote.value <= 0:
        raise ProviderPayloadError("Provider quote value must be positive and finite.")
    if not fits_numeric_28_12(quote.value):
        raise ProviderPayloadError("Provider quote value must fit NUMERIC(28,12).")


def _default_failure_source(item: RequiredMarketDataItem) -> str:
    if item.data_type == "price":
        order = _provider_order_for_price(
            market=item.market or "",
            preferred_source=item.preferred_source,
            provider_priority=[],
        )
        return order[0]
    order = _provider_order_for_fx(
        preferred_source=item.preferred_source,
        provider_priority=[],
    )
    return order[0]


def _provider_order_for_price(
    *,
    market: str,
    preferred_source: str | None,
    provider_priority: list[str],
) -> list[str]:
    defaults = (
        _DOMESTIC_PROVIDER_ORDER
        if market.upper() in {"SH", "SZ", "SSE", "SZSE", "CN"}
        else _INTERNATIONAL_PROVIDER_ORDER
    )
    return _merge_provider_order(preferred_source, provider_priority, defaults)


def _provider_order_for_fx(
    *,
    preferred_source: str | None,
    provider_priority: list[str],
) -> list[str]:
    return _merge_provider_order(preferred_source, provider_priority, _FX_PROVIDER_ORDER)


def _merge_provider_order(
    preferred_source: str | None,
    provider_priority: list[str],
    defaults: tuple[str, ...],
) -> list[str]:
    merged: list[str] = []
    for candidate in [preferred_source, *provider_priority, *defaults]:
        if candidate is None:
            continue
        normalized = candidate.strip()
        if normalized and normalized not in merged and normalized in {
            "yahoo",
            "akshare",
            "tushare",
            "alpha_vantage",
        }:
            merged.append(normalized)
    return merged


def _currency_for_key(parsed_key: ParsedMarketDataKey) -> str:
    if parsed_key.data_type == "fx":
        return parsed_key.symbol.split("/", 1)[1]
    if parsed_key.symbol.isdigit():
        return "CNY"
    return "USD"


def _currency_for_symbol(row: MarketData) -> str:
    parsed_key = ParsedMarketDataKey(
        key=f"{row.data_type}:{row.symbol}",
        data_type=row.data_type,
        symbol=row.symbol,
    )
    return _currency_for_key(parsed_key)
