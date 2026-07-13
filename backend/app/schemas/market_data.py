from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


def _trim_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = format(value.normalize(), "f")
    if normalized == "-0":
        return "0"
    if "." not in normalized:
        return normalized
    integer, fraction = normalized.split(".", 1)
    if len(fraction) == 1:
        return f"{integer}.{fraction}0"
    return normalized


class MarketDataStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    data_type: str
    symbol: str
    currency: str
    effective_value: Decimal | None = None
    source: str | None = None
    status: str
    market_time: datetime | None = None
    fetched_at: datetime | None = None
    error_summary: str | None = None
    note: str | None = None

    @field_serializer("effective_value")
    def serialize_effective_value(self, value: Decimal | None) -> str | None:
        return _trim_decimal(value)


class MarketDataCollectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[MarketDataStatusResponse]


class MarketDataOverrideRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    value: Decimal
    note: str
    effective_at: datetime | None = None
    expires_at: datetime | None = None
