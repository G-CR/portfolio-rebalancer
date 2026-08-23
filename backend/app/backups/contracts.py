from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.db.base import Base
from app.db.models import (
    AssetClass,
    CostAdjustment,
    EncryptedSecret,
    Holding,
    HoldingDefault,
    MarketData,
    MarketDataOverride,
    RebalancePlan,
    Setting,
    Snapshot,
    SnapshotItem,
)


class Codec(str, Enum):
    UUID = "uuid"
    STRING = "string"
    DECIMAL = "decimal"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class FieldCodec:
    codec: Codec
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class TableContract:
    member: str
    model: type[Base]
    columns: tuple[str, ...]
    codecs: tuple[FieldCodec, ...]
    order_key: str = "id"

    @property
    def field_codecs(self) -> dict[str, FieldCodec]:
        return dict(zip(self.columns, self.codecs, strict=True))


U = FieldCodec(Codec.UUID)
UN = FieldCodec(Codec.UUID, nullable=True)
S = FieldCodec(Codec.STRING)
SN = FieldCodec(Codec.STRING, nullable=True)
D = FieldCodec(Codec.DECIMAL)
DN = FieldCodec(Codec.DECIMAL, nullable=True)
I = FieldCodec(Codec.INTEGER)
B = FieldCodec(Codec.BOOLEAN)
DA = FieldCodec(Codec.DATE)
DT = FieldCodec(Codec.DATETIME)
DTN = FieldCodec(Codec.DATETIME, nullable=True)
J = FieldCodec(Codec.JSON)
JN = FieldCodec(Codec.JSON, nullable=True)


TABLE_CONTRACTS = (
    TableContract(
        "data/asset_classes.json",
        AssetClass,
        ("id", "name", "target_weight", "display_order", "is_active", "notes", "created_at", "updated_at"),
        (U, S, D, I, B, SN, DT, DT),
    ),
    TableContract(
        "data/holdings.json",
        Holding,
        (
            "id", "asset_class_id", "symbol", "name", "market", "account_name",
            "trade_currency", "quantity", "average_cost_price", "cost_fx_to_cny",
            "baseline_fx_to_cny", "lot_size", "quantity_precision",
            "preferred_data_source", "is_rebalance_preferred", "is_active", "version",
            "created_at", "updated_at",
        ),
        (U, U, S, S, S, S, S, D, D, D, D, D, I, SN, B, B, I, DT, DT),
    ),
    TableContract(
        "data/holding_defaults.json",
        HoldingDefault,
        (
            "id", "holding_id", "fee_currency", "commission_rate", "minimum_commission",
            "per_share_fee", "fixed_fee", "default_data_source", "created_at", "updated_at",
        ),
        (U, U, S, D, D, D, D, SN, DT, DT),
    ),
    TableContract(
        "data/market_data.json",
        MarketData,
        (
            "id", "data_type", "symbol", "source", "value", "market_time",
            "fetched_at", "status", "error_summary", "created_at",
        ),
        (U, S, S, S, DN, DTN, DT, S, SN, DT),
    ),
    TableContract(
        "data/market_data_overrides.json",
        MarketDataOverride,
        (
            "id", "data_type", "symbol", "value", "note", "effective_at",
            "expires_at", "created_at", "updated_at",
        ),
        (U, S, S, D, S, DT, DTN, DT, DT),
    ),
    TableContract(
        "data/cost_adjustments.json",
        CostAdjustment,
        (
            "id", "holding_id", "operation_type", "before_quantity",
            "before_average_cost_price", "before_cost_fx_to_cny", "after_quantity",
            "after_average_cost_price", "after_cost_fx_to_cny", "input_summary", "note",
            "created_at",
        ),
        (U, U, S, D, D, D, D, D, D, J, SN, DT),
    ),
    TableContract(
        "data/snapshots.json",
        Snapshot,
        (
            "id", "snapshot_type", "local_date", "captured_at", "note", "data_complete",
            "has_stale_data", "has_manual_data", "created_at",
        ),
        (U, S, DA, DT, SN, B, B, B, DT),
    ),
    TableContract(
        "data/snapshot_items.json",
        SnapshotItem,
        (
            "id", "snapshot_id", "holding_id", "asset_class_name", "holding_name", "symbol",
            "account_name", "trade_currency", "quantity", "market_price", "current_fx_to_cny",
            "baseline_fx_to_cny", "average_cost_price", "cost_fx_to_cny", "target_weight",
            "market_value_cny", "fx_neutral_value_cny", "cost_value_cny",
            "unrealized_pnl_amount_cny", "unrealized_pnl_rate", "price_effect_cny",
            "fx_effect_cny", "actual_weight", "fx_neutral_weight", "price_status", "fx_status",
            "created_at",
        ),
        (U, U, UN, S, S, S, S, S, D, DN, DN, D, D, D, D, DN, DN, DN, DN, DN, DN, DN, DN, DN, S, S, DT),
    ),
    TableContract(
        "data/rebalance_plans.json",
        RebalancePlan,
        (
            "id", "strategy_mode", "status", "data_version", "create_idempotency_key",
            "input_summary", "suggested_actions", "projected_result", "before_snapshot_id",
            "after_snapshot_id", "started_at", "cancelled_at", "created_at", "updated_at",
            "baseline_reset_at", "start_market_data_record_ids",
            "completion_market_data_record_ids", "start_idempotency_key", "cancel_idempotency_key",
            "complete_idempotency_key", "completed_at",
        ),
        (U, S, S, S, SN, J, J, J, UN, UN, DTN, DTN, DT, DT, DTN, JN, JN, SN, SN, SN, DTN),
    ),
    TableContract(
        "data/settings.json",
        Setting,
        (
            "id", "refresh_hour", "refresh_minute", "provider_priority", "default_tolerance",
            "minimum_trade_amount_cny", "allow_sell", "allow_fx", "rebalance_available_cny",
            "rebalance_available_usd", "rebalance_valuation_basis", "email_enabled",
            "email_recipient", "email_smtp_host", "email_smtp_port", "email_smtp_security",
            "email_smtp_username", "email_from", "created_at", "updated_at",
        ),
        (U, I, I, J, D, D, B, B, D, D, S, B, SN, SN, I, S, SN, SN, DT, DT),
    ),
)

CREDENTIAL_CONTRACT = TableContract(
    "credentials.json",
    EncryptedSecret,
    (
        "id", "provider", "value", "masked_value", "validation_status",
        "validation_message", "last_validated_at", "created_at", "updated_at",
    ),
    (U, S, S, S, SN, SN, DTN, DT, DT),
)

CONTRACTS_BY_MEMBER = {
    contract.member: contract for contract in (*TABLE_CONTRACTS, CREDENTIAL_CONTRACT)
}
