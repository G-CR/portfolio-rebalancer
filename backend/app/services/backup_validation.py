from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from app.backups.archive import (
    ArchiveLimitExceeded,
    InvalidBackupArchive,
    InvalidBackupDocument,
    UnsupportedBackupVersion,
    open_verified_archive,
    iter_current_rows,
)
from app.backups.canonical import JsonValue, canonical_json_bytes, canonical_parsed_json_bytes
from app.backups.constants import CURRENT_FORMAT_VERSION, DATA_MEMBERS, STREAM_CHUNK_BYTES
from app.backups.contracts import CONTRACTS_BY_MEMBER, Codec
from app.backups.migrations import BackupMigrationError, migrate_to_current
from app.core.decimal import fits_numeric_28_12
from app.db.models import DEFAULT_SETTINGS_ID
from app.schemas.rebalance import RebalanceComparisonResponse, RebalanceResultResponse, TradeSuggestionResponse
from app.schemas.email_settings import EmailSettingsUpdate
from pydantic import TypeAdapter, ValidationError
from app.services.backup_storage import BackupSourceLease, BackupStorage
from app.services.rebalance_version import rebalance_data_version

try:  # Linux production uses flock; the fallback keeps local Windows tests faithful.
    import fcntl
except ImportError:  # pragma: no cover - exercised by Windows development only
    fcntl = None
    import msvcrt


_PROVIDERS = {"yahoo", "sina", "akshare", "tushare", "alpha_vantage"}
_ENUM_FIELDS: dict[tuple[str, str], set[str]] = {
    ("data/holdings.json", "market"): {"US", "SH", "SZ"},
    ("data/holdings.json", "preferred_data_source"): _PROVIDERS,
    ("data/holding_defaults.json", "default_data_source"): _PROVIDERS,
    ("data/market_data.json", "data_type"): {"price", "fx"},
    ("data/market_data.json", "status"): {"valid", "failed"},
    ("data/market_data_overrides.json", "data_type"): {"price", "fx"},
    ("data/cost_adjustments.json", "operation_type"): {
        "PURCHASE", "SELL", "MANUAL_CORRECTION", "RESTORE"
    },
    ("data/snapshots.json", "snapshot_type"): {
        "daily", "manual", "rebalance_before", "rebalance_after"
    },
    ("data/snapshot_items.json", "price_status"): {
        "valid", "stale", "manual", "missing", "failed"
    },
    ("data/snapshot_items.json", "fx_status"): {
        "valid", "stale", "manual", "missing", "failed"
    },
    ("data/rebalance_plans.json", "strategy_mode"): {"actual", "fx_neutral"},
    ("data/rebalance_plans.json", "status"): {
        "draft", "in_progress", "cancelled", "completed"
    },
    ("data/settings.json", "rebalance_valuation_basis"): {"actual", "fx_neutral"},
    ("data/settings.json", "email_smtp_security"): {"ssl", "starttls"},
    ("credentials.json", "provider"): {*_PROVIDERS, "smtp"},
    ("credentials.json", "validation_status"): {"valid", "failed"},
}


class BackupValidationError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class _Incompatible(Exception):
    pass


class _RelationshipInvalid(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedBackup:
    retained_archive_path: Path
    path_id: str
    archive_sha256: str
    canonical_logical_checksum: str
    source_format_version: int
    current_format_version: int
    source_application_version: str
    exported_at: datetime
    record_counts: dict[str, int]
    credential_categories: tuple[str, ...]
    warnings: tuple[str, ...]
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class RestoreTokenBinding:
    retained_archive_path: Path
    path_id: str
    archive_sha256: str
    expires_at: datetime


def _open_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(
        """
        CREATE TABLE identities (
            member TEXT NOT NULL,
            id TEXT NOT NULL,
            PRIMARY KEY (member, id)
        ) WITHOUT ROWID;
        CREATE TABLE uniqueness (
            kind TEXT NOT NULL,
            value BLOB NOT NULL,
            owner_id TEXT NOT NULL,
            PRIMARY KEY (kind, value)
        ) WITHOUT ROWID;
        CREATE TABLE refs (
            owner_member TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            target_member TEXT NOT NULL,
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            semantic_key TEXT
        );
        CREATE INDEX refs_target ON refs(target_member, target_id);
        CREATE TABLE snapshots (
            id TEXT PRIMARY KEY,
            snapshot_type TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE market_inputs (
            id TEXT PRIMARY KEY,
            semantic_key TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE current_rows (
            member TEXT NOT NULL,
            order_key TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (member, order_key)
        ) WITHOUT ROWID;
        CREATE TABLE asset_weights (active INTEGER NOT NULL, weight TEXT NOT NULL);
        """
        )
        return connection
    except Exception:
        connection.close()
        raise


def _decimal(value: JsonValue) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        raise _Incompatible from None


def _uuid_decimal_map(value: JsonValue, *, bounded: bool) -> None:
    if not isinstance(value, dict):
        raise _Incompatible
    for key, item in value.items():
        try:
            if str(UUID(key)) != key:
                raise ValueError
        except (ValueError, TypeError):
            raise _Incompatible from None
        number = _decimal(item)
        if not fits_numeric_28_12(number) or number < 0 or (bounded and number > 1):
            raise _Incompatible


def _rebalance_shapes(row: dict[str, JsonValue]) -> None:
    summary = row["input_summary"]
    projected = row["projected_result"]
    actions = row["suggested_actions"]
    required_summary = {
        "session_token", "request_token", "available_cny", "available_usd",
        "valuation_basis", "allow_sell", "allow_fx", "tolerance",
        "minimum_trade_cny", "acknowledge_stale_data", "holding_versions",
        "market_data_record_ids",
    }
    optional_summary = {"asset_class_targets", "resolved_constraints"}
    if (
        not isinstance(summary, dict)
        or not required_summary.issubset(summary)
        or set(summary) - required_summary - optional_summary
    ):
        raise _Incompatible
    if not isinstance(summary["session_token"], str) or not isinstance(summary["request_token"], str):
        raise _Incompatible
    if summary["valuation_basis"] != row["strategy_mode"] or not isinstance(summary["acknowledge_stale_data"], bool):
        raise _Incompatible
    for field in ("available_cny", "available_usd"):
        if _decimal(summary[field]) < 0:
            raise _Incompatible
    for field in ("allow_sell", "allow_fx"):
        if summary[field] is not None and not isinstance(summary[field], bool):
            raise _Incompatible
    for field in ("tolerance", "minimum_trade_cny"):
        if summary[field] is not None and _decimal(summary[field]) < 0:
            raise _Incompatible
    if summary["tolerance"] is not None and _decimal(summary["tolerance"]) > 1:
        raise _Incompatible
    versions = summary["holding_versions"]
    if not isinstance(versions, dict):
        raise _Incompatible
    for key, value in versions.items():
        try:
            canonical = str(UUID(key)) == key
        except (ValueError, TypeError):
            canonical = False
        if not canonical or isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise _Incompatible
    _uuid_decimal_map(summary.get("asset_class_targets", {}), bounded=True)
    resolved = summary.get("resolved_constraints", summary)
    if (
        not isinstance(resolved, dict)
        or not {"allow_sell", "allow_fx", "tolerance", "minimum_trade_cny"}.issubset(resolved)
        or (
            "resolved_constraints" in summary
            and set(resolved) != {"allow_sell", "allow_fx", "tolerance", "minimum_trade_cny"}
        )
    ):
        raise _Incompatible
    if not isinstance(resolved["allow_sell"], bool) or not isinstance(resolved["allow_fx"], bool):
        raise _Incompatible
    if _decimal(resolved["tolerance"]) < 0 or _decimal(resolved["tolerance"]) > 1 or _decimal(resolved["minimum_trade_cny"]) < 0:
        raise _Incompatible
    result_keys = {
        "feasible", "max_drift_before", "max_drift_after", "fx_required_cny",
        "remaining_cny", "remaining_usd", "projected_weights", "trades",
    }
    weight_keys = {"asset_class_id", "before", "after", "target"}
    action_keys = {
        "symbol", "action", "quantity", "amount_cny", "amount_trade_currency",
        "reason_code", "reason",
    }
    comparison_keys = {"valuation_basis", "result"}

    def exact_result(value: JsonValue) -> bool:
        return (
            isinstance(value, dict)
            and set(value) == result_keys
            and isinstance(value["projected_weights"], list)
            and all(isinstance(item, dict) and set(item) == weight_keys for item in value["projected_weights"])
            and isinstance(value["trades"], list)
            and all(isinstance(item, dict) and set(item) == action_keys for item in value["trades"])
        )

    if (
        not isinstance(actions, list)
        or not all(isinstance(item, dict) and set(item) == action_keys for item in actions)
        or not isinstance(projected, dict)
        or set(projected) != {"valuation_basis", "result", "fx_comparison", "data_status"}
    ):
        raise _Incompatible
    comparison = projected["fx_comparison"]
    if (
        not exact_result(projected["result"])
        or not isinstance(comparison, dict)
        or set(comparison) != comparison_keys
        or not exact_result(comparison["result"])
    ):
        raise _Incompatible
    if projected["valuation_basis"] != row["strategy_mode"] or projected["data_status"] not in {"valid", "stale", "manual"}:
        raise _Incompatible
    try:
        TypeAdapter(list[TradeSuggestionResponse]).validate_python(actions)
        result = RebalanceResultResponse.model_validate(projected["result"])
        RebalanceComparisonResponse.model_validate(projected["fx_comparison"])
    except ValidationError:
        raise _Incompatible from None
    if [item.model_dump(mode="json") for item in result.trades] != actions:
        raise _Incompatible


def _require_json_shape(member: str, row: dict[str, JsonValue]) -> None:
    object_fields = {
        "data/cost_adjustments.json": ("input_summary",),
        "data/rebalance_plans.json": ("input_summary", "projected_result"),
    }
    for field in object_fields.get(member, ()):
        if not isinstance(row[field], dict):
            raise _Incompatible
    if member == "data/rebalance_plans.json":
        _rebalance_shapes(row)
    if member == "data/settings.json":
        providers = row["provider_priority"]
        if (
            not isinstance(providers, list)
            or any(not isinstance(provider, str) or provider not in _PROVIDERS for provider in providers)
            or len(set(providers)) != len(providers)
        ):
            raise _Incompatible


def _validate_scalars(member: str, row: dict[str, JsonValue]) -> None:
    contract = CONTRACTS_BY_MEMBER[member]
    for field, codec in contract.field_codecs.items():
        value = row[field]
        if value is None:
            continue
        if codec.codec is Codec.DECIMAL and not fits_numeric_28_12(Decimal(str(value))):
            raise _Incompatible
        if codec.codec is Codec.INTEGER and not -(2**31) <= int(value) <= 2**31 - 1:
            raise _Incompatible
        allowed = _ENUM_FIELDS.get((member, field))
        if allowed is not None and value not in allowed:
            raise _Incompatible

        model_field = "encrypted_value" if member == "credentials.json" and field == "value" else field
        column = contract.model.__table__.columns[model_field]
        max_length = getattr(column.type, "length", None)
        if max_length is not None and isinstance(value, str) and len(value) > max_length:
            raise _Incompatible

    currency_fields = {
        "data/holdings.json": ("trade_currency",),
        "data/holding_defaults.json": ("fee_currency",),
        "data/snapshot_items.json": ("trade_currency",),
    }
    for field in currency_fields.get(member, ()):
        currency = row[field]
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency.upper() != currency
        ):
            raise _Incompatible

    if member == "data/settings.json":
        if row["id"] != str(DEFAULT_SETTINGS_ID):
            raise _Incompatible
        if not 0 <= int(row["refresh_hour"]) <= 23:
            raise _Incompatible
        if not 0 <= int(row["refresh_minute"]) <= 59:
            raise _Incompatible
        if not 1 <= int(row["email_smtp_port"]) <= 65535:
            raise _Incompatible
        for field in ("default_tolerance", "minimum_trade_amount_cny", "rebalance_available_cny", "rebalance_available_usd"):
            if _decimal(row[field]) < 0:
                raise _Incompatible
        if _decimal(row["default_tolerance"]) > 1:
            raise _Incompatible
        try:
            email = EmailSettingsUpdate.model_validate({
                "enabled": row["email_enabled"], "recipient": row["email_recipient"],
                "smtp_host": row["email_smtp_host"], "smtp_port": row["email_smtp_port"],
                "smtp_security": row["email_smtp_security"],
                "smtp_username": row["email_smtp_username"], "from_address": row["email_from"],
            })
        except ValidationError:
            raise _Incompatible from None
        if (
            email.recipient != row["email_recipient"]
            or email.smtp_host != row["email_smtp_host"]
            or email.smtp_username != row["email_smtp_username"]
            or email.from_address != row["email_from"]
        ):
            raise _Incompatible
    elif member == "data/asset_classes.json":
        weight = _decimal(row["target_weight"])
        if weight < 0 or weight > 1:
            raise _Incompatible
    elif member == "data/holdings.json":
        version = row["version"]
        if (
            not 0 <= int(row["quantity_precision"]) <= 12
            or _decimal(row["lot_size"]) <= 0
            or isinstance(version, bool)
            or not isinstance(version, int)
            or version < 1
        ):
            raise _Incompatible
        for field in ("quantity", "average_cost_price", "cost_fx_to_cny", "baseline_fx_to_cny"):
            if _decimal(row[field]) < 0:
                raise _Incompatible
    elif member == "data/holding_defaults.json":
        for field in ("commission_rate", "minimum_commission", "per_share_fee", "fixed_fee"):
            if _decimal(row[field]) < 0:
                raise _Incompatible
    elif member == "data/market_data_overrides.json" and _decimal(row["value"]) <= 0:
        raise _Incompatible
    elif member == "data/market_data.json" and row["value"] is not None and _decimal(row["value"]) <= 0:
        raise _Incompatible
    elif member == "data/cost_adjustments.json":
        for field in (
            "before_quantity", "before_average_cost_price", "before_cost_fx_to_cny",
            "after_quantity", "after_average_cost_price", "after_cost_fx_to_cny",
        ):
            if _decimal(row[field]) < 0:
                raise _Incompatible
    _require_json_shape(member, row)


def _insert_unique(
    connection: sqlite3.Connection,
    kind: str,
    value: object,
    owner_id: str,
) -> None:
    try:
        connection.execute(
            "INSERT INTO uniqueness(kind, value, owner_id) VALUES (?, ?, ?)",
            (kind, canonical_json_bytes(value), owner_id),
        )
    except sqlite3.IntegrityError:
        raise _RelationshipInvalid from None


def _add_ref(
    connection: sqlite3.Connection,
    member: str,
    owner_id: str,
    target_member: str,
    target_id: JsonValue,
    kind: str,
    semantic_key: str | None = None,
) -> None:
    if target_id is None:
        return
    connection.execute(
        "INSERT INTO refs(owner_member, owner_id, target_member, target_id, kind, semantic_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (member, owner_id, target_member, str(target_id), kind, semantic_key),
    )


def _validate_reference_map(
    connection: sqlite3.Connection,
    member: str,
    owner_id: str,
    value: JsonValue,
    kind: str,
) -> None:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _Incompatible
    for key, reference in value.items():
        if not isinstance(reference, str):
            raise _Incompatible
        try:
            parsed = UUID(reference)
        except ValueError:
            raise _Incompatible from None
        if str(parsed) != reference:
            raise _Incompatible
        if not (key.startswith("price:") or key.startswith("fx:")) or not key.partition(":")[2]:
            raise _Incompatible
        _add_ref(connection, member, owner_id, "market_input", reference, kind, key)


def _validate_rebalance(
    connection: sqlite3.Connection,
    row: dict[str, JsonValue],
) -> None:
    status = str(row["status"])
    start_fields = (
        "before_snapshot_id", "started_at", "start_market_data_record_ids",
        "start_idempotency_key",
    )
    cancel_fields = ("cancelled_at", "cancel_idempotency_key")
    complete_fields = (
        "after_snapshot_id", "baseline_reset_at", "completion_market_data_record_ids",
        "complete_idempotency_key", "completed_at",
    )
    has_start = all(row[field] is not None for field in start_fields)
    no_start = all(row[field] is None for field in start_fields)
    has_cancel = all(row[field] is not None for field in cancel_fields)
    no_cancel = all(row[field] is None for field in cancel_fields)
    has_complete = all(row[field] is not None for field in complete_fields)
    no_complete = all(row[field] is None for field in complete_fields)
    valid = {
        "draft": no_start and no_cancel and no_complete,
        "in_progress": has_start and no_cancel and no_complete,
        "cancelled": (has_start or no_start) and has_cancel and no_complete,
        "completed": has_start and no_cancel and has_complete,
    }[status]
    if not valid:
        raise _RelationshipInvalid
    owner_id = str(row["id"])
    summary = row["input_summary"]
    assert isinstance(summary, dict)
    if {"resolved_constraints", "asset_class_targets"}.issubset(summary):
        expected_version = rebalance_data_version(
            market_data_record_ids=summary["market_data_record_ids"],
            holding_versions=summary["holding_versions"],
            asset_class_targets=summary["asset_class_targets"],
        )
        if row["data_version"] != expected_version:
            raise _RelationshipInvalid
    _validate_reference_map(
        connection, "data/rebalance_plans.json", owner_id,
        summary["market_data_record_ids"], "input_market_data",
    )
    for holding_id in summary["holding_versions"]:
        _add_ref(connection, "data/rebalance_plans.json", owner_id, "data/holdings.json", holding_id, "input_holding")
    for asset_id in summary.get("asset_class_targets", {}):
        _add_ref(connection, "data/rebalance_plans.json", owner_id, "data/asset_classes.json", asset_id, "input_asset")
    if has_start:
        if row["start_market_data_record_ids"] != summary["market_data_record_ids"]:
            raise _RelationshipInvalid
        _add_ref(
            connection, "data/rebalance_plans.json", owner_id,
            "data/snapshots.json", row["before_snapshot_id"], "rebalance_before",
        )
        _validate_reference_map(
            connection, "data/rebalance_plans.json", owner_id,
            row["start_market_data_record_ids"], "start_market_data",
        )
    if has_complete:
        _add_ref(
            connection, "data/rebalance_plans.json", owner_id,
            "data/snapshots.json", row["after_snapshot_id"], "rebalance_after",
        )
        _validate_reference_map(
            connection, "data/rebalance_plans.json", owner_id,
            row["completion_market_data_record_ids"], "completion_market_data",
        )


def _index_row(
    connection: sqlite3.Connection,
    member: str,
    row: dict[str, JsonValue],
) -> str | None:
    _validate_scalars(member, row)
    owner_id = str(row["id"])
    try:
        connection.execute(
            "INSERT INTO identities(member, id) VALUES (?, ?)", (member, owner_id)
        )
    except sqlite3.IntegrityError:
        raise _RelationshipInvalid from None

    if member == "data/asset_classes.json":
        connection.execute("INSERT INTO asset_weights(active, weight) VALUES (?, ?)", (int(bool(row["is_active"])), str(row["target_weight"])))
        if row["is_active"]:
            _insert_unique(connection, "active_asset_name", row["name"], owner_id)
    elif member == "data/holdings.json":
        _add_ref(connection, member, owner_id, "data/asset_classes.json", row["asset_class_id"], "fk")
        if row["is_active"]:
            _insert_unique(connection, "active_holding", [row["symbol"], row["account_name"]], owner_id)
            if row["is_rebalance_preferred"]:
                _insert_unique(connection, "preferred_holding", row["asset_class_id"], owner_id)
    elif member == "data/holding_defaults.json":
        _add_ref(connection, member, owner_id, "data/holdings.json", row["holding_id"], "fk")
        _insert_unique(connection, "holding_default", row["holding_id"], owner_id)
    elif member == "data/market_data.json":
        _insert_unique(
            connection, "market_data",
            [row["data_type"], row["symbol"], row["source"], row["market_time"]], owner_id,
        )
        connection.execute("INSERT INTO market_inputs(id, semantic_key) VALUES (?, ?)", (owner_id, f"{row['data_type']}:{row['symbol']}"))
    elif member == "data/market_data_overrides.json":
        connection.execute("INSERT INTO market_inputs(id, semantic_key) VALUES (?, ?)", (owner_id, f"{row['data_type']}:{row['symbol']}"))
    elif member == "data/cost_adjustments.json":
        _add_ref(connection, member, owner_id, "data/holdings.json", row["holding_id"], "fk")
    elif member == "data/snapshots.json":
        connection.execute(
            "INSERT INTO snapshots(id, snapshot_type) VALUES (?, ?)",
            (owner_id, row["snapshot_type"]),
        )
        if row["snapshot_type"] == "daily":
            _insert_unique(connection, "daily_snapshot", row["local_date"], owner_id)
    elif member == "data/snapshot_items.json":
        _add_ref(connection, member, owner_id, "data/snapshots.json", row["snapshot_id"], "fk")
        _add_ref(connection, member, owner_id, "data/holdings.json", row["holding_id"], "fk")
    elif member == "data/rebalance_plans.json":
        if row["create_idempotency_key"] is not None:
            _insert_unique(connection, "rebalance_create_key", row["create_idempotency_key"], owner_id)
        _validate_rebalance(connection, row)
    elif member == "credentials.json":
        _insert_unique(connection, "credential_provider", row["provider"], owner_id)
        return str(row["provider"])
    return None


def _verify_relationships(connection: sqlite3.Connection) -> None:
    missing = connection.execute(
        """
        SELECT 1
        FROM refs AS reference
        LEFT JOIN identities AS target
          ON target.member = reference.target_member AND target.id = reference.target_id
        WHERE target.id IS NULL
          AND reference.target_member != 'market_input'
        LIMIT 1
        """
    ).fetchone()
    if missing is not None:
        raise _RelationshipInvalid
    missing_market_input = connection.execute(
        """
        SELECT 1
        FROM refs AS reference
        LEFT JOIN identities AS target
          ON target.id = reference.target_id
         AND target.member IN ('data/market_data.json', 'data/market_data_overrides.json')
        WHERE reference.target_member = 'market_input'
          AND target.id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if missing_market_input is not None:
        raise _RelationshipInvalid
    mismatched_market_input = connection.execute(
        """
        SELECT 1 FROM refs AS reference
        JOIN market_inputs AS target ON target.id = reference.target_id
        WHERE reference.target_member = 'market_input'
          AND target.semantic_key != reference.semantic_key
        LIMIT 1
        """
    ).fetchone()
    if mismatched_market_input is not None:
        raise _RelationshipInvalid
    invalid_snapshot = connection.execute(
        """
        SELECT 1
        FROM refs AS reference
        JOIN snapshots ON snapshots.id = reference.target_id
        WHERE reference.kind IN ('rebalance_before', 'rebalance_after')
          AND snapshots.snapshot_type != reference.kind
        LIMIT 1
        """
    ).fetchone()
    if invalid_snapshot is not None:
        raise _RelationshipInvalid
    weights = (
        Decimal(value)
        for (value,) in connection.execute(
            "SELECT weight FROM asset_weights WHERE active = 1"
        )
    )
    if sum(weights, Decimal(0)) != Decimal(1):
        raise _RelationshipInvalid


def _current_checksum(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    digest.update(b"{")
    for member_index, member in enumerate(sorted(DATA_MEMBERS)):
        if member_index:
            digest.update(b",")
        digest.update(canonical_json_bytes(member))
        digest.update(b":[")
        rows = connection.execute("SELECT payload FROM current_rows WHERE member = ? ORDER BY order_key", (member,))
        for row_index, (payload,) in enumerate(rows):
            if row_index:
                digest.update(b",")
            digest.update(bytes(payload))
        digest.update(b"]")
    digest.update(b"}")
    return digest.hexdigest()


def validate_backup(
    path: Path,
    *,
    path_id: str,
    expires_at: datetime | None = None,
    workspace_root: Path,
) -> ValidatedBackup:
    if expires_at is not None and (expires_at.tzinfo is None or expires_at.utcoffset() is None):
        raise ValueError("expires_at must be timezone-aware")
    try:
        workspace_root = Path(workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        with open_verified_archive(path) as inspected:
            migrated = migrate_to_current(inspected)
            categories: set[str] = set()
            with tempfile.TemporaryDirectory(dir=workspace_root) as workspace_name:
                connection = _open_index(Path(workspace_name) / "semantic.sqlite3")
                try:
                    record_counts: dict[str, int] = {}
                    for member in DATA_MEMBERS:
                        count = 0
                        contract = CONTRACTS_BY_MEMBER[member]
                        for row in iter_current_rows(migrated, member):
                            category = _index_row(connection, member, row)
                            try:
                                connection.execute(
                                    "INSERT INTO current_rows(member, order_key, payload) VALUES (?, ?, ?)",
                                    (member, str(row[contract.order_key]), canonical_parsed_json_bytes(row)),
                                )
                            except sqlite3.IntegrityError:
                                raise _RelationshipInvalid from None
                            count += 1
                            if category is not None:
                                categories.add(category)
                        record_counts[member] = count
                        if count != inspected.manifest.record_counts[member]:
                            raise _Incompatible
                    if connection.execute(
                        "SELECT COUNT(*) FROM identities WHERE member = 'data/settings.json'"
                    ).fetchone()[0] != 1:
                        raise _Incompatible
                    connection.commit()
                    _verify_relationships(connection)
                    canonical_checksum = _current_checksum(connection)
                    if inspected.format_version == CURRENT_FORMAT_VERSION and canonical_checksum != inspected.manifest.logical_checksum:
                        raise _Incompatible
                finally:
                    connection.close()
            return ValidatedBackup(
                retained_archive_path=Path(path),
                path_id=path_id,
                archive_sha256=inspected.archive_sha256,
                canonical_logical_checksum=canonical_checksum,
                source_format_version=inspected.manifest.format_version,
                current_format_version=CURRENT_FORMAT_VERSION,
                source_application_version=inspected.manifest.source_application_version,
                exported_at=datetime.fromisoformat(inspected.manifest.exported_at),
                record_counts=record_counts,
                credential_categories=tuple(sorted(categories)),
                warnings=("Backup archives contain plaintext credentials.",),
                expires_at=expires_at.astimezone(timezone.utc) if expires_at is not None else None,
            )
    except BackupValidationError:
        raise
    except ArchiveLimitExceeded:
        raise BackupValidationError(
            "BACKUP_RESOURCE_LIMIT", "Backup exceeds the configured resource limit.",
            status_code=413,
        ) from None
    except UnsupportedBackupVersion:
        raise BackupValidationError(
            "BACKUP_FUTURE_VERSION", "Backup format is newer than this application."
        ) from None
    except BackupMigrationError:
        raise BackupValidationError(
            "BACKUP_INCOMPATIBLE", "Backup format cannot be migrated by this application."
        ) from None
    except InvalidBackupArchive:
        raise BackupValidationError(
            "BACKUP_CORRUPT", "Backup archive is corrupt or unsafe."
        ) from None
    except (_Incompatible, InvalidBackupDocument):
        raise BackupValidationError(
            "BACKUP_INCOMPATIBLE", "Backup data does not match the supported format."
        ) from None
    except _RelationshipInvalid:
        raise BackupValidationError(
            "BACKUP_RELATIONSHIP_INVALID", "Backup relationships are inconsistent."
        ) from None
    except (sqlite3.Error, OSError, MemoryError):
        raise BackupValidationError(
            "BACKUP_RESOURCE_LIMIT",
            "Backup validation could not complete within available resources.",
            status_code=507,
        ) from None


class RestoreTokenRegistry:
    # An unlocked claim older than this interval is an abandoned-process artifact.
    # A held OS lock always wins over age, so maintenance never steals live work.
    CLAIM_STALE_AFTER = timedelta(minutes=5)
    def __init__(
        self,
        storage: BackupStorage,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.storage = storage
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _journal_path(self, token_hash: str) -> Path:
        return self.storage.uploads_dir / f"{token_hash}.token.json"

    def _claim_path(self, token_hash: str) -> Path:
        return self.storage.uploads_dir / f"{token_hash}.token.claimed"

    def _consumed_path(self, token_hash: str) -> Path:
        return self.storage.uploads_dir / f"{token_hash}.consumed.json"

    def _resolve_path(self, path_id: str) -> Path:
        kind, separator, raw_id = path_id.partition(":")
        if not separator or not raw_id:
            raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.")
        if kind == "upload":
            try:
                UUID(raw_id)
            except ValueError:
                # Unit-level callers may use deterministic path IDs; never treat them as paths.
                if not raw_id.replace("-", "").isalnum():
                    raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
            return self.storage.uploads_dir / f"{raw_id}.portfolio-backup"
        if kind == "safety":
            try:
                return self.storage.safety_path(UUID(raw_id))
            except ValueError:
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
        raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.")

    def issue(self, validated: ValidatedBackup) -> str:
        resolved = self._resolve_path(validated.path_id)
        if resolved.resolve() != validated.retained_archive_path.resolve():
            raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.")
        if validated.expires_at is None:
            raise BackupValidationError("BACKUP_PREVIEW_FAILED", "Backup preview could not be prepared.", status_code=500)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        payload = canonical_json_bytes({
            "token_hash": token_hash,
            "archive_sha256": validated.archive_sha256,
            "path_id": validated.path_id,
            "expires_at": validated.expires_at.astimezone(timezone.utc).isoformat(),
        })
        self.storage._atomic_write(self._journal_path(token_hash), payload)
        return token

    def cleanup_expired(self) -> bool:
        """Remove expired token journals and uploaded archives; report retryable debt."""
        maintenance_failed = False
        now = self._clock()
        protected_token_hashes: set[str] = set()
        for token_claim in self.storage.uploads_dir.glob("*.token.claimed"):
            token_hash = token_claim.name.removesuffix(".token.claimed")
            descriptor: int | None = None
            locked = False
            remove_after_close = False
            try:
                descriptor = os.open(token_claim, os.O_RDWR)
                locked = _lock_claim(descriptor, nonblocking=True)
                if not locked:
                    protected_token_hashes.add(token_hash)
                    continue
                stat_result = os.fstat(descriptor)
                claimed_at = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc)
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    document = json.loads(os.read(descriptor, 4096))
                    metadata_time = datetime.fromisoformat(document["claimed_at"])
                    if metadata_time.tzinfo is not None and metadata_time.utcoffset() is not None:
                        claimed_at = metadata_time.astimezone(timezone.utc)
                except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
                    pass
                if now - claimed_at < self.CLAIM_STALE_AFTER:
                    protected_token_hashes.add(token_hash)
                    continue
                if fcntl is None:  # Windows cannot unlink an open locked file.
                    remove_after_close = True
                else:
                    token_claim.unlink()
                    self.storage._fsync_directory(self.storage.uploads_dir)
            except OSError:
                protected_token_hashes.add(token_hash)
                maintenance_failed = True
            finally:
                if descriptor is not None:
                    if locked:
                        _unlock_claim(descriptor)
                    os.close(descriptor)
            if remove_after_close:
                try:
                    token_claim.unlink()
                    self.storage._fsync_directory(self.storage.uploads_dir)
                except OSError:
                    protected_token_hashes.add(token_hash)
                    maintenance_failed = True
        for abandoned_claim in self.storage.uploads_dir.glob("*.json.claimed"):
            journal_path = Path(str(abandoned_claim).removesuffix(".claimed"))
            try:
                os.replace(abandoned_claim, journal_path)
                self.storage._fsync_directory(self.storage.uploads_dir)
            except OSError:
                maintenance_failed = True
        expiry_records = (
            *self.storage.uploads_dir.glob("*.token.json"),
            *self.storage.uploads_dir.glob("*.consumed.json"),
        )
        for journal_path in expiry_records:
            if (
                journal_path.name.endswith(".token.json")
                and journal_path.name.removesuffix(".token.json") in protected_token_hashes
            ):
                continue
            claim_path: Path | None = None
            completed = False
            try:
                document = json.loads(journal_path.read_bytes())
                expires_at = datetime.fromisoformat(document["expires_at"])
                if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                    raise ValueError
                if now < expires_at:
                    continue
                path_id = str(document["path_id"])
                if self.storage.is_source_leased(path_id):
                    continue
                claim_path = Path(f"{journal_path}.claimed")
                os.replace(journal_path, claim_path)
                self.storage._fsync_directory(self.storage.uploads_dir)
                if path_id.startswith("upload:"):
                    self._resolve_path(path_id).unlink(missing_ok=True)
                    self.storage._fsync_directory(self.storage.uploads_dir)
                completed = True
            except FileNotFoundError:
                continue
            except (OSError, TypeError, ValueError, KeyError):
                maintenance_failed = True
            finally:
                if claim_path is not None:
                    try:
                        if completed:
                            claim_path.unlink(missing_ok=True)
                        else:
                            os.replace(claim_path, journal_path)
                        self.storage._fsync_directory(self.storage.uploads_dir)
                    except OSError:
                        maintenance_failed = True
        return maintenance_failed

    def consume(self, token: str) -> RestoreTokenBinding:
        binding, lease = self._consume(token, acquire_lease=False)
        assert lease is None
        return binding

    def consume_with_lease(
        self,
        token: str,
    ) -> tuple[RestoreTokenBinding, BackupSourceLease]:
        binding, lease = self._consume(token, acquire_lease=True)
        assert lease is not None
        return binding, lease

    def _consume(
        self,
        token: str,
        *,
        acquire_lease: bool,
    ) -> tuple[RestoreTokenBinding, BackupSourceLease | None]:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        journal_path = self._journal_path(token_hash)
        claim_path = self._claim_path(token_hash)
        descriptor: int | None = None
        locked = False
        source_lease: BackupSourceLease | None = None
        try:
            descriptor = os.open(
                claim_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.write(descriptor, b"{}")
            os.lseek(descriptor, 0, os.SEEK_SET)
            locked = _lock_claim(descriptor, nonblocking=False)
            _after_claim_file_created(claim_path)
            claim_document = canonical_json_bytes({
                "token_hash": token_hash,
                "claimed_at": self._clock().astimezone(timezone.utc).isoformat(),
            })
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, claim_document)
            os.fsync(descriptor)
            self.storage._fsync_directory(self.storage.uploads_dir)
        except OSError:
            if descriptor is not None:
                if locked:
                    _unlock_claim(descriptor)
                os.close(descriptor)
            raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
        try:
            try:
                with journal_path.open("rb") as source:
                    document = json.load(source)
            except FileNotFoundError:
                raise BackupValidationError(
                    "BACKUP_TOKEN_INVALID", "Restore token is invalid."
                ) from None
            try:
                if set(document) != {"token_hash", "archive_sha256", "path_id", "expires_at"}:
                    raise ValueError
                if not hmac.compare_digest(document["token_hash"], token_hash):
                    raise ValueError
                expires_at = datetime.fromisoformat(document["expires_at"])
                if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                    raise ValueError
                path_id = str(document["path_id"])
                expected_hash = str(document["archive_sha256"])
            except (OSError, TypeError, ValueError, KeyError):
                self._mark_consumed(journal_path, token_hash)
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
            if acquire_lease:
                source_lease = self.storage.acquire_source_lease(path_id)
            try:
                path = self._resolve_path(path_id)
            except BaseException:
                if source_lease is not None:
                    source_lease.release()
                raise
            if self._clock() >= expires_at:
                if source_lease is not None:
                    source_lease.release()
                storage_failed = False
                if path_id.startswith("upload:"):
                    try:
                        path.unlink(missing_ok=True)
                        self.storage._fsync_directory(self.storage.uploads_dir)
                    except OSError:
                        storage_failed = True
                if storage_failed:
                    raise BackupValidationError(
                        "BACKUP_RESOURCE_LIMIT",
                        "Restore token storage could not be updated.",
                        status_code=507,
                    ) from None
                self._mark_consumed(journal_path, token_hash)
                raise BackupValidationError("BACKUP_TOKEN_EXPIRED", "Restore token has expired.")
            try:
                observed_hash = _retained_archive_sha256(path)
            except OSError:
                if source_lease is not None:
                    source_lease.release()
                self._mark_consumed(journal_path, token_hash)
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
            except BaseException:
                if source_lease is not None:
                    source_lease.release()
                raise
            if not hmac.compare_digest(observed_hash, expected_hash):
                if source_lease is not None:
                    source_lease.release()
                self._mark_consumed(journal_path, token_hash)
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.")
            try:
                self._mark_consumed(journal_path, token_hash)
            except BaseException:
                if source_lease is not None:
                    source_lease.release()
                raise
            return (
                RestoreTokenBinding(path, path_id, expected_hash, expires_at),
                source_lease,
            )
        finally:
            assert descriptor is not None
            if locked:
                _unlock_claim(descriptor)
            os.close(descriptor)
            try:
                claim_path.unlink(missing_ok=True)
                self.storage._fsync_directory(self.storage.uploads_dir)
            except OSError:
                # The unlocked claim remains discoverable by periodic maintenance.
                pass

    def _mark_consumed(self, journal_path: Path, token_hash: str) -> None:
        failed = False
        try:
            os.replace(journal_path, self._consumed_path(token_hash))
            self.storage._fsync_directory(self.storage.uploads_dir)
        except OSError:
            failed = True
        if failed:
            raise BackupValidationError(
                "BACKUP_RESOURCE_LIMIT",
                "Restore token storage could not be updated.",
                status_code=507,
            ) from None


def _retained_archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(STREAM_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _lock_claim(descriptor: int, *, nonblocking: bool) -> bool:
    if fcntl is not None:
        operation = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError:
            return False
        return True
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:  # pragma: no cover - Windows-only development fallback
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK, 1)
    except OSError:
        return False
    return True


def _unlock_claim(descriptor: int) -> None:
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)  # pragma: no cover


def _after_claim_file_created(_claim_path: Path) -> None:
    """Deterministic seam after exclusive creation and locking, before metadata."""
