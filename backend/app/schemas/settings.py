from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.common import DecimalString

ProviderName = Literal["yahoo", "sina", "akshare", "tushare", "alpha_vantage"]


class ProviderSettingUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    api_key: str | None = Field(default=None, max_length=512)
    priority: int = Field(ge=1, le=5)
    enabled: bool


class ProviderSettingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    display_name: str
    requires_key: bool
    enabled: bool
    priority: int
    key_status: Literal["not_required", "not_configured", "configured"]
    masked_key: str | None
    validation_status: Literal["valid", "failed"] | None
    validation_message: str | None
    last_validated_at: datetime | None


class GeneralSettingsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    refresh_time: str
    provider_priority: list[ProviderName]
    default_tolerance: DecimalString
    minimum_trade_amount_cny: DecimalString
    allow_sell: bool
    allow_fx: bool

    @field_validator("refresh_time")
    @classmethod
    def validate_refresh_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise PydanticCustomError("settings_refresh_time_invalid", "refresh_time must use HH:MM.")
        hour, minute = (int(part) for part in parts)
        if hour not in range(24) or minute not in range(60):
            raise PydanticCustomError("settings_refresh_time_invalid", "refresh_time must use HH:MM.")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("provider_priority")
    @classmethod
    def validate_provider_priority(cls, value: list[ProviderName]) -> list[ProviderName]:
        expected = {"yahoo", "sina", "akshare", "tushare", "alpha_vantage"}
        if len(value) != len(expected) or set(value) != expected:
            raise PydanticCustomError(
                "settings_provider_priority_invalid",
                "provider_priority must include every supported provider exactly once.",
            )
        return value

    @field_validator("default_tolerance", "minimum_trade_amount_cny")
    @classmethod
    def validate_nonnegative(cls, value: Decimal, info) -> Decimal:
        if not value.is_finite() or value < 0:
            raise PydanticCustomError(
                "negative_numeric_field",
                "{field} must be non-negative.",
                {"field": info.field_name},
            )
        if info.field_name == "default_tolerance" and value > 1:
            raise PydanticCustomError(
                "settings_tolerance_out_of_range",
                "default_tolerance must not exceed 1.",
            )
        return value


class GeneralSettingsResponse(GeneralSettingsUpdate):
    updated_at: datetime

    @field_serializer("default_tolerance", "minimum_trade_amount_cny")
    def serialize_decimal(self, value: Decimal) -> str:
        normalized = format(value.normalize(), "f")
        return "0" if normalized == "-0" else normalized


class RebalanceDefaultsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    available_cny: DecimalString
    available_usd: DecimalString
    valuation_basis: Literal["actual", "fx_neutral"]
    tolerance: DecimalString
    minimum_trade_cny: DecimalString
    allow_sell: bool
    allow_fx: bool

    @field_validator(
        "available_cny",
        "available_usd",
        "tolerance",
        "minimum_trade_cny",
    )
    @classmethod
    def validate_numeric_defaults(cls, value: Decimal, info) -> Decimal:
        if not value.is_finite() or value < 0:
            raise PydanticCustomError(
                "negative_numeric_field",
                "{field} must be non-negative.",
                {"field": info.field_name},
            )
        if info.field_name == "tolerance" and value > 1:
            raise PydanticCustomError(
                "settings_tolerance_out_of_range",
                "tolerance must not exceed 1.",
            )
        return value


class RebalanceDefaultsResponse(RebalanceDefaultsUpdate):
    updated_at: datetime

    @field_serializer(
        "available_cny",
        "available_usd",
        "tolerance",
        "minimum_trade_cny",
    )
    def serialize_decimal(self, value: Decimal) -> str:
        normalized = format(value.normalize(), "f")
        return "0" if normalized == "-0" else normalized
