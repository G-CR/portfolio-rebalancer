from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.core.decimal import fits_numeric_28_12

class ProviderError(Exception):
    pass


class ProviderPayloadError(ProviderError):
    pass


class ProviderRequestError(ProviderError):
    pass


class ProviderNotConfigured(ProviderError):
    pass


def _normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized or not normalized.isalpha() or not (3 <= len(normalized) <= 8):
        raise ProviderPayloadError("Provider payload must include a valid currency code.")
    return normalized


def _normalize_timestamp(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderPayloadError(f"Provider payload must include timezone-aware {field_name}.")
    return value


def decimal_from_value(value: object, *, field_name: str = "value") -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ProviderPayloadError(
            f"Provider payload must include a positive finite value for {field_name}."
        ) from exc

    if not decimal_value.is_finite() or decimal_value <= 0:
        raise ProviderPayloadError(
            f"Provider payload must include a positive finite value for {field_name}."
        )
    return decimal_value


@dataclass(frozen=True, slots=True)
class MarketQuote:
    key: str
    symbol: str
    value: Decimal
    currency: str
    source: str
    as_of: datetime
    fetched_at: datetime

    def __post_init__(self) -> None:
        if not self.key:
            raise ProviderPayloadError("Provider payload must include a market-data key.")
        if not self.symbol:
            raise ProviderPayloadError("Provider payload must include a symbol.")
        if not self.value.is_finite() or self.value <= 0:
            raise ProviderPayloadError(
                "Provider payload must include a positive finite value."
            )
        if not fits_numeric_28_12(self.value):
            raise ProviderPayloadError(
                "Provider quote value must fit NUMERIC(28,12)."
            )
        object.__setattr__(self, "currency", _normalize_currency(self.currency))
        object.__setattr__(self, "as_of", _normalize_timestamp(self.as_of, field_name="as_of"))
        object.__setattr__(
            self,
            "fetched_at",
            _normalize_timestamp(self.fetched_at, field_name="fetched_at"),
        )


class MarketDataProvider(Protocol):
    async def fetch_price(self, symbol: str) -> MarketQuote: ...
    async def fetch_fx(self, base: str, quote: str) -> MarketQuote: ...


class ProviderCredentialReader(Protocol):
    def get_api_key(self, provider: str) -> str | None: ...


class NullCredentialReader:
    """Task 9 credential boundary; Task 15 replaces this with encrypted storage."""

    def get_api_key(self, provider: str) -> str | None:
        return None
