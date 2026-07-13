from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.schemas.common import DecimalString


class PositionAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    cost_cny: DecimalString
    market_value_cny: DecimalString
    fx_neutral_value_cny: DecimalString
    unrealized_pnl: DecimalString
    unrealized_return: DecimalString
    price_effect: DecimalString
    fx_effect: DecimalString


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


class PortfolioDataInputResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    input: str
    value: Decimal | None
    status: str
    source: str | None = None
    market_time: datetime | None = None
    fetched_at: datetime | None = None
    error_summary: str | None = None
    note: str | None = None

    @field_serializer("value")
    def serialize_value(self, value: Decimal | None) -> str | None:
        return _decimal_string(value)


class HoldingAnalyticsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    holding_id: UUID
    asset_class_id: UUID
    symbol: str
    name: str
    trade_currency: str
    current_price: DecimalString
    current_fx_to_cny: DecimalString
    price_status: str
    fx_status: str
    cost_trade_currency: DecimalString
    market_value_trade_currency: DecimalString
    unrealized_pnl_trade_currency: DecimalString
    cost_cny: DecimalString
    market_value_cny: DecimalString
    fx_neutral_value_cny: DecimalString
    unrealized_pnl: DecimalString
    unrealized_return: DecimalString
    price_effect: DecimalString
    fx_effect: DecimalString


class AssetClassAnalyticsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    target_weight: DecimalString
    display_order: int
    actual_weight: DecimalString
    fx_neutral_weight: DecimalString
    drift: DecimalString
    fx_weight_contribution: DecimalString
    cost_cny: DecimalString
    market_value_cny: DecimalString
    fx_neutral_value_cny: DecimalString
    unrealized_pnl: DecimalString
    price_effect: DecimalString
    fx_effect: DecimalString


class PortfolioDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    title: str
    reason: str
    max_drift: DecimalString
    fx_contribution: DecimalString
    primary_action: str


class PortfolioAnalyticsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime | None
    data_status: str
    has_stale_data: bool
    has_manual_data: bool
    tolerance: DecimalString
    cost_cny: DecimalString
    market_value_cny: DecimalString
    fx_neutral_value_cny: DecimalString
    unrealized_pnl: DecimalString
    unrealized_return: DecimalString
    price_effect: DecimalString
    fx_effect: DecimalString
    overseas_weight: DecimalString
    decision: PortfolioDecisionResponse
    asset_classes: list[AssetClassAnalyticsResponse]
    holdings: list[HoldingAnalyticsResponse]
    data_inputs: list[PortfolioDataInputResponse]
