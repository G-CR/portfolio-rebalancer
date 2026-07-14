from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.common import DecimalString


def _ensure_finite_nonnegative(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise PydanticCustomError(
            "rebalance_numeric_not_finite",
            "{field} must be finite.",
            {"field": field_name},
        )
    if value < 0:
        raise PydanticCustomError(
            "negative_numeric_field",
            "{field} must be non-negative.",
            {"field": field_name},
        )
    return value


class RebalancePreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    available_cny: DecimalString
    available_usd: DecimalString
    valuation_basis: Literal["actual", "fx_neutral"] = "actual"
    allow_sell: bool
    allow_fx: bool
    tolerance: DecimalString
    minimum_trade_cny: DecimalString
    acknowledge_stale_data: bool = False

    @field_validator(
        "available_cny",
        "available_usd",
        "tolerance",
        "minimum_trade_cny",
    )
    @classmethod
    def validate_nonnegative_decimal(cls, value: Decimal, info) -> Decimal:
        value = _ensure_finite_nonnegative(value, info.field_name)
        if info.field_name == "tolerance" and value > 1:
            raise PydanticCustomError(
                "rebalance_tolerance_out_of_range",
                "tolerance must not exceed 1.",
            )
        return value


class TradeSuggestionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    symbol: str
    action: Literal["buy", "sell"]
    quantity: DecimalString
    amount_cny: DecimalString
    amount_trade_currency: DecimalString
    reason_code: str


class ProjectedWeightResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    asset_class_id: str
    before: DecimalString
    after: DecimalString
    target: DecimalString


class RebalanceResultResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    feasible: bool
    max_drift_before: DecimalString
    max_drift_after: DecimalString
    fx_required_cny: DecimalString
    remaining_cny: DecimalString
    remaining_usd: DecimalString
    projected_weights: tuple[ProjectedWeightResponse, ...]
    trades: tuple[TradeSuggestionResponse, ...]
