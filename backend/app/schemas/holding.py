from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic_core import PydanticCustomError

from app.core.market import normalize_currency_code, normalize_market_code
from app.schemas.common import DecimalString


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < 0:
        raise PydanticCustomError(
            "negative_numeric_field",
            "{field} must be non-negative.",
            {"field": field_name},
        )
    return value


MAX_QUANTITY_PRECISION = 12


def _ensure_positive_lot_size(value: Decimal) -> Decimal:
    if value <= 0:
        raise PydanticCustomError(
            "holding_lot_size_invalid",
            "Lot size must be positive.",
            {"field": "lot_size"},
        )
    return value


def _ensure_quantity_precision(value: int) -> int:
    if value < 0:
        raise PydanticCustomError(
            "negative_numeric_field",
            "{field} must be non-negative.",
            {"field": "quantity_precision"},
        )
    if value > MAX_QUANTITY_PRECISION:
        raise PydanticCustomError(
            "holding_quantity_precision_invalid",
            "Quantity precision must be between 0 and 12.",
            {"field": "quantity_precision"},
        )
    return value


def _trim_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if normalized == "-0":
        return "0"
    return normalized


def _scale_decimal(value: Decimal, scale: int) -> str:
    if scale <= 0:
        return format(value.quantize(Decimal("1")), "f")
    quantum = Decimal("1").scaleb(-scale)
    return format(value.quantize(quantum), "f")


def _price_decimal(value: Decimal) -> str:
    trimmed = _trim_decimal(value)
    if "." not in trimmed:
        return trimmed

    integer, fraction = trimmed.split(".", 1)
    if len(fraction) == 1:
        return f"{integer}.{fraction}0"
    return trimmed


class HoldingResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    asset_class_id: UUID
    symbol: str
    name: str
    market: str
    account_name: str
    trade_currency: str
    quantity: DecimalString
    average_cost_price: DecimalString
    cost_fx_to_cny: DecimalString
    baseline_fx_to_cny: DecimalString
    lot_size: DecimalString
    quantity_precision: int
    preferred_data_source: Literal["yahoo", "sina", "akshare", "tushare", "alpha_vantage"] | None
    is_rebalance_preferred: bool
    is_active: bool
    version: int

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return _scale_decimal(value, self.quantity_precision)

    @field_serializer("average_cost_price")
    def serialize_average_cost_price(self, value: Decimal) -> str:
        return _price_decimal(value)

    @field_serializer("cost_fx_to_cny", "baseline_fx_to_cny", "lot_size")
    def serialize_trimmed_decimal(self, value: Decimal) -> str:
        return _trim_decimal(value)


class HoldingReplacementRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    source_version: int
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    market: str
    account_name: str = Field(min_length=1, max_length=100)
    trade_currency: str
    quantity: DecimalString
    average_cost_price: DecimalString
    cost_fx_to_cny: DecimalString
    baseline_fx_to_cny: DecimalString
    lot_size: DecimalString
    quantity_precision: int
    preferred_data_source: Literal[
        "yahoo", "sina", "akshare", "tushare", "alpha_vantage"
    ] | None = None
    note: str | None = None

    @field_validator("market")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        try:
            return normalize_market_code(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "holding_market_invalid",
                "Market must be one of US, SH, or SZ.",
                {"field": "market"},
            ) from exc

    @field_validator("trade_currency")
    @classmethod
    def normalize_trade_currency(cls, value: str) -> str:
        try:
            return normalize_currency_code(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "holding_trade_currency_invalid",
                "Trade currency must be exactly three ASCII letters.",
                {"field": "trade_currency"},
            ) from exc

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise PydanticCustomError(
                "holding_replacement_quantity_invalid",
                "Replacement quantity must be positive.",
                {"field": "quantity"},
            )
        return value

    @field_validator(
        "average_cost_price",
        "cost_fx_to_cny",
        "baseline_fx_to_cny",
    )
    @classmethod
    def non_negative_decimal(cls, value: Decimal, info) -> Decimal:
        return _ensure_non_negative(value, info.field_name)

    @field_validator("lot_size")
    @classmethod
    def validate_lot_size(cls, value: Decimal) -> Decimal:
        return _ensure_positive_lot_size(value)

    @field_validator("quantity_precision")
    @classmethod
    def validate_quantity_precision(cls, value: int) -> int:
        return _ensure_quantity_precision(value)

    @field_validator("source_version")
    @classmethod
    def non_negative_integer(cls, value: int, info) -> int:
        if value < 0:
            raise PydanticCustomError(
                "negative_numeric_field",
                "{field} must be non-negative.",
                {"field": info.field_name},
            )
        return value


class HoldingReplacementResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: HoldingResponse
    target: HoldingResponse


class HoldingCreate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    asset_class_id: UUID
    symbol: str
    name: str
    market: str
    account_name: str
    trade_currency: str
    quantity: DecimalString
    average_cost_price: DecimalString
    cost_fx_to_cny: DecimalString
    baseline_fx_to_cny: DecimalString
    lot_size: DecimalString
    quantity_precision: int
    preferred_data_source: Literal["yahoo", "sina", "akshare", "tushare", "alpha_vantage"] | None = None
    is_rebalance_preferred: bool = False

    @field_validator("market")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        try:
            return normalize_market_code(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "holding_market_invalid",
                "Market must be one of US, SH, or SZ.",
                {"field": "market"},
            ) from exc

    @field_validator("trade_currency")
    @classmethod
    def normalize_trade_currency(cls, value: str) -> str:
        try:
            return normalize_currency_code(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "holding_trade_currency_invalid",
                "Trade currency must be exactly three ASCII letters.",
                {"field": "trade_currency"},
            ) from exc

    @field_validator(
        "quantity",
        "average_cost_price",
        "cost_fx_to_cny",
        "baseline_fx_to_cny",
    )
    @classmethod
    def validate_non_negative_decimal(cls, value: Decimal, info) -> Decimal:
        return _ensure_non_negative(value, info.field_name)

    @field_validator("lot_size")
    @classmethod
    def validate_lot_size(cls, value: Decimal) -> Decimal:
        return _ensure_positive_lot_size(value)

    @field_validator("quantity_precision")
    @classmethod
    def validate_quantity_precision(cls, value: int) -> int:
        return _ensure_quantity_precision(value)


class HoldingUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    asset_class_id: UUID | None = None
    symbol: str | None = None
    name: str | None = None
    market: str | None = None
    account_name: str | None = None
    trade_currency: str | None = None
    quantity: DecimalString | None = None
    average_cost_price: DecimalString | None = None
    cost_fx_to_cny: DecimalString | None = None
    baseline_fx_to_cny: DecimalString | None = None
    lot_size: DecimalString | None = None
    quantity_precision: int | None = None
    preferred_data_source: Literal["yahoo", "sina", "akshare", "tushare", "alpha_vantage"] | None = None
    is_rebalance_preferred: bool | None = None

    @field_validator("market")
    @classmethod
    def normalize_market(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_market_code(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "holding_market_invalid",
                "Market must be one of US, SH, or SZ.",
                {"field": "market"},
            ) from exc

    @field_validator("trade_currency")
    @classmethod
    def normalize_trade_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_currency_code(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "holding_trade_currency_invalid",
                "Trade currency must be exactly three ASCII letters.",
                {"field": "trade_currency"},
            ) from exc

    @field_validator(
        "quantity",
        "average_cost_price",
        "cost_fx_to_cny",
        "baseline_fx_to_cny",
    )
    @classmethod
    def validate_non_negative_decimal(
        cls, value: Decimal | None, info
    ) -> Decimal | None:
        if value is None:
            return None
        return _ensure_non_negative(value, info.field_name)

    @field_validator("lot_size")
    @classmethod
    def validate_lot_size(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return _ensure_positive_lot_size(value)

    @field_validator("quantity_precision")
    @classmethod
    def validate_quantity_precision(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return _ensure_quantity_precision(value)
