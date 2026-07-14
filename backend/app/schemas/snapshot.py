from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import DecimalString

SnapshotType = Literal["daily", "manual", "rebalance_before", "rebalance_after"]


class SnapshotItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    holding_id: UUID | None
    asset_class_name: str
    holding_name: str
    symbol: str
    account_name: str
    trade_currency: str
    quantity: DecimalString
    market_price: DecimalString | None
    current_fx_to_cny: DecimalString | None
    baseline_fx_to_cny: DecimalString
    average_cost_price: DecimalString
    cost_fx_to_cny: DecimalString
    target_weight: DecimalString
    market_value_cny: DecimalString | None
    fx_neutral_value_cny: DecimalString | None
    cost_value_cny: DecimalString | None
    unrealized_pnl_amount_cny: DecimalString | None
    unrealized_pnl_rate: DecimalString | None
    price_effect_cny: DecimalString | None
    fx_effect_cny: DecimalString | None
    actual_weight: DecimalString | None
    fx_neutral_weight: DecimalString | None
    price_status: str
    fx_status: str


class SnapshotSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    snapshot_type: SnapshotType
    local_date: date
    captured_at: datetime
    note: str | None
    data_complete: bool
    has_stale_data: bool
    has_manual_data: bool
    total_market_value_cny: DecimalString
    total_fx_neutral_value_cny: DecimalString
    total_cost_value_cny: DecimalString
    total_unrealized_pnl_cny: DecimalString
    total_price_effect_cny: DecimalString
    total_fx_effect_cny: DecimalString
    actual_weight: DecimalString
    fx_neutral_weight: DecimalString
    target_weight: DecimalString | None


class SnapshotDetailResponse(SnapshotSummaryResponse):
    items: list[SnapshotItemResponse]


class SnapshotCollectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SnapshotSummaryResponse]
    page: int
    page_size: int
    total: int


class ManualSnapshotRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
