from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.common import DecimalString


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < 0:
        raise PydanticCustomError(
            "negative_numeric_field",
            "{field} must be non-negative.",
            {"field": field_name},
        )
    return value


def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
    if value <= 0:
        raise PydanticCustomError(
            "non_positive_numeric_field",
            "{field} must be positive.",
            {"field": field_name},
        )
    return value


class HoldingDefaultsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    fee_currency: str
    commission_rate: str
    minimum_commission: str
    per_share_fee: str
    fixed_fee: str


class CostBasisStateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    quantity: str
    average_cost_price: str
    cost_fx_to_cny: str
    total_cost_cny: str


class FeePreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["estimated", "actual"]
    currency: str
    amount: str
    amount_cny: str


class CostAdjustmentPreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    holding_id: UUID
    holding_version: int
    operation: Literal["purchase", "sell", "manual_correction", "restore"]
    before: CostBasisStateResponse
    after: CostBasisStateResponse
    fee: FeePreviewResponse | None = None
    note: str | None = None
    adjustment_id: UUID | None = None


class CostAdjustmentHistoryItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    operation_type: str
    before: CostBasisStateResponse
    after: CostBasisStateResponse
    input_summary: dict[str, Any]
    note: str | None = None
    created_at: datetime


class CostAdjustmentCollectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    holding_id: UUID
    holding_version: int
    defaults: HoldingDefaultsResponse | None = None
    items: list[CostAdjustmentHistoryItemResponse]


class PurchasePreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    quantity: DecimalString
    price: DecimalString
    fx: DecimalString
    fee_currency: str | None = None
    commission_rate: DecimalString | None = None
    minimum_commission: DecimalString | None = None
    per_share_fee: DecimalString | None = None
    fixed_fee: DecimalString | None = None
    actual_fee: DecimalString | None = None
    save_fee_defaults: bool = False
    note: str | None = None

    @field_validator("fee_currency")
    @classmethod
    def normalize_fee_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()

    @field_validator("quantity", "price", "fx")
    @classmethod
    def validate_positive_decimal(cls, value: Decimal, info) -> Decimal:
        return _ensure_positive(value, info.field_name)

    @field_validator(
        "commission_rate",
        "minimum_commission",
        "per_share_fee",
        "fixed_fee",
        "actual_fee",
    )
    @classmethod
    def validate_non_negative_decimal(
        cls, value: Decimal | None, info
    ) -> Decimal | None:
        if value is None:
            return None
        return _ensure_non_negative(value, info.field_name)


class SellPreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    quantity: DecimalString
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def validate_positive_quantity(cls, value: Decimal) -> Decimal:
        return _ensure_positive(value, "quantity")


class ManualCorrectionPreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    quantity: DecimalString
    average_cost_price: DecimalString
    cost_fx_to_cny: DecimalString
    note: str | None = None

    @field_validator("quantity", "average_cost_price")
    @classmethod
    def validate_non_negative_decimal(cls, value: Decimal, info) -> Decimal:
        return _ensure_non_negative(value, info.field_name)

    @field_validator("cost_fx_to_cny")
    @classmethod
    def validate_non_negative_cost_fx(cls, value: Decimal) -> Decimal:
        return _ensure_non_negative(value, "cost_fx_to_cny")


class RestorePreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    note: str | None = None


class RestoreConfirmPayload(RestorePreviewRequest):
    adjustment_id: UUID


class CostAdjustmentConfirmRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    expected_version: int
    operation: Literal["purchase", "sell", "manual_correction", "restore"]
    payload: dict[str, Any]
