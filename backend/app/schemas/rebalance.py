from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
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

    session_token: str
    request_token: str
    available_cny: DecimalString
    available_usd: DecimalString
    valuation_basis: Literal["actual", "fx_neutral"] = "actual"
    allow_sell: bool | None = None
    allow_fx: bool | None = None
    tolerance: DecimalString | None = None
    minimum_trade_cny: DecimalString | None = None
    acknowledge_stale_data: bool = False

    @field_validator(
        "available_cny",
        "available_usd",
        "tolerance",
        "minimum_trade_cny",
    )
    @classmethod
    def validate_nonnegative_decimal(cls, value: Decimal | None, info) -> Decimal | None:
        if value is None:
            return None
        value = _ensure_finite_nonnegative(value, info.field_name)
        if info.field_name == "tolerance" and value > 1:
            raise PydanticCustomError(
                "rebalance_tolerance_out_of_range",
                "tolerance must not exceed 1.",
        )
        return value


class RebalancePlanCreateRequest(RebalancePreviewRequest):
    idempotency_key: str


class RebalancePlanTransitionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    idempotency_key: str


class TradeSuggestionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    symbol: str
    action: Literal["buy", "sell"]
    quantity: DecimalString
    amount_cny: DecimalString
    amount_trade_currency: DecimalString
    reason_code: Literal[
        "UNDERWEIGHT_WITH_CASH",
        "UNDERWEIGHT_AFTER_FX",
        "UNDERWEIGHT_WITH_SELL_PROCEEDS",
        "UNDERWEIGHT_WITH_CASH_AND_FX",
        "UNDERWEIGHT_WITH_CASH_AND_SELL_PROCEEDS",
        "UNDERWEIGHT_AFTER_SELL_AND_FX",
        "UNDERWEIGHT_WITH_CASH_SELL_PROCEEDS_AND_FX",
        "OVERWEIGHT_AFTER_CASH",
    ]
    reason: str


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


class RebalanceComparisonResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    valuation_basis: Literal["actual", "fx_neutral"]
    result: RebalanceResultResponse


class RebalancePreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_token: str
    request_token: str
    status: Literal["ok"]
    data_status: Literal["valid", "stale", "manual"]
    acknowledge_stale_data: bool
    refresh_attempted: bool
    valuation_basis: Literal["actual", "fx_neutral"]
    result: RebalanceResultResponse
    fx_comparison: RebalanceComparisonResponse


class RebalancePlanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    status: Literal["draft", "in_progress", "completed", "cancelled"]
    valuation_basis: Literal["actual", "fx_neutral"]
    data_version: str
    data_status: Literal["valid", "stale", "manual"]
    market_data_record_ids: dict[str, str]
    holding_versions: dict[str, int]
    asset_class_targets: dict[str, str] = Field(default_factory=dict)
    result: RebalanceResultResponse
    fx_comparison: RebalanceComparisonResponse
    before_snapshot_id: str | None
    after_snapshot_id: str | None
    baseline_reset_at: str | None
    created_at: str
    updated_at: str


class RebalancePlanCollectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RebalancePlanResponse]
