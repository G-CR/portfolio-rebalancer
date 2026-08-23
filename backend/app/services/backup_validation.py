from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from app.backups.archive import (
    ArchiveLimitExceeded,
    InvalidBackupArchive,
    InvalidBackupDocument,
    UnsupportedBackupVersion,
    inspect_archive,
    iter_current_rows,
)
from app.backups.canonical import JsonValue, canonical_json_bytes
from app.backups.constants import CURRENT_FORMAT_VERSION, DATA_MEMBERS, STREAM_CHUNK_BYTES
from app.backups.contracts import CONTRACTS_BY_MEMBER, Codec
from app.backups.migrations import BackupMigrationError, migrate_to_current
from app.core.decimal import fits_numeric_28_12
from app.db.models import DEFAULT_SETTINGS_ID
from app.services.backup_storage import BackupStorage


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
    ("credentials.json", "validation_status"): {"valid", "failed", "untested"},
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
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RestoreTokenBinding:
    retained_archive_path: Path
    path_id: str
    archive_sha256: str
    expires_at: datetime


def _open_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
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
            kind TEXT NOT NULL
        );
        CREATE INDEX refs_target ON refs(target_member, target_id);
        CREATE TABLE snapshots (
            id TEXT PRIMARY KEY,
            snapshot_type TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )
    return connection


def _require_json_shape(member: str, row: dict[str, JsonValue]) -> None:
    object_fields = {
        "data/cost_adjustments.json": ("input_summary",),
        "data/rebalance_plans.json": ("input_summary", "projected_result"),
    }
    for field in object_fields.get(member, ()):
        if not isinstance(row[field], dict):
            raise _Incompatible
    if member == "data/rebalance_plans.json" and not isinstance(
        row["suggested_actions"], (dict, list)
    ):
        raise _Incompatible
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
) -> None:
    if target_id is None:
        return
    connection.execute(
        "INSERT INTO refs(owner_member, owner_id, target_member, target_id, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (member, owner_id, target_member, str(target_id), kind),
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
    for reference in value.values():
        if not isinstance(reference, str):
            raise _Incompatible
        try:
            parsed = UUID(reference)
        except ValueError:
            raise _Incompatible from None
        if str(parsed) != reference:
            raise _Incompatible
        _add_ref(
            connection, member, owner_id, "market_input", reference, kind
        )


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
    if has_start:
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

    if member == "data/asset_classes.json" and row["is_active"]:
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


def validate_backup(
    path: Path,
    *,
    path_id: str,
    expires_at: datetime,
    workspace_root: Path,
) -> ValidatedBackup:
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    try:
        workspace_root = Path(workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        with inspect_archive(path) as inspected:
            migrated = migrate_to_current(inspected)
            categories: set[str] = set()
            with tempfile.TemporaryDirectory(dir=workspace_root) as workspace_name:
                connection = _open_index(Path(workspace_name) / "semantic.sqlite3")
                try:
                    for member in DATA_MEMBERS:
                        for row in iter_current_rows(migrated, member):
                            category = _index_row(connection, member, row)
                            if category is not None:
                                categories.add(category)
                    if connection.execute(
                        "SELECT COUNT(*) FROM identities WHERE member = 'data/settings.json'"
                    ).fetchone()[0] != 1:
                        raise _Incompatible
                    connection.commit()
                    _verify_relationships(connection)
                finally:
                    connection.close()
            return ValidatedBackup(
                retained_archive_path=Path(path),
                path_id=path_id,
                archive_sha256=inspected.archive_sha256,
                canonical_logical_checksum=inspected.manifest.logical_checksum,
                source_format_version=inspected.manifest.format_version,
                current_format_version=CURRENT_FORMAT_VERSION,
                source_application_version=inspected.manifest.source_application_version,
                exported_at=datetime.fromisoformat(inspected.manifest.exported_at),
                record_counts=dict(inspected.manifest.record_counts),
                credential_categories=tuple(sorted(categories)),
                warnings=("Backup archives contain plaintext credentials.",),
                expires_at=expires_at.astimezone(timezone.utc),
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
        for token_claim in self.storage.uploads_dir.glob("*.token.claimed"):
            token_hash = token_claim.name.removesuffix(".token.claimed")
            try:
                os.replace(token_claim, self._consumed_path(token_hash))
                self.storage._fsync_directory(self.storage.uploads_dir)
            except OSError:
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
            claim_path: Path | None = None
            completed = False
            try:
                document = json.loads(journal_path.read_bytes())
                expires_at = datetime.fromisoformat(document["expires_at"])
                if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                    raise ValueError
                if now < expires_at:
                    continue
                claim_path = Path(f"{journal_path}.claimed")
                os.replace(journal_path, claim_path)
                self.storage._fsync_directory(self.storage.uploads_dir)
                path_id = str(document["path_id"])
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
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        journal_path = self._journal_path(token_hash)
        claim_path = self._claim_path(token_hash)
        try:
            os.replace(journal_path, claim_path)
            self.storage._fsync_directory(self.storage.uploads_dir)
        except OSError:
            raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
        try:
            try:
                document = json.loads(claim_path.read_bytes())
                if set(document) != {"token_hash", "archive_sha256", "path_id", "expires_at"}:
                    raise ValueError
                if not hmac.compare_digest(document["token_hash"], token_hash):
                    raise ValueError
                expires_at = datetime.fromisoformat(document["expires_at"])
                path_id = str(document["path_id"])
                expected_hash = str(document["archive_sha256"])
            except (OSError, TypeError, ValueError, KeyError):
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
            path = self._resolve_path(path_id)
            if self._clock() >= expires_at:
                if path_id.startswith("upload:"):
                    path.unlink(missing_ok=True)
                    self.storage._fsync_directory(self.storage.uploads_dir)
                raise BackupValidationError("BACKUP_TOKEN_EXPIRED", "Restore token has expired.")
            digest = hashlib.sha256()
            try:
                with path.open("rb") as source:
                    while chunk := source.read(STREAM_CHUNK_BYTES):
                        digest.update(chunk)
            except OSError:
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.") from None
            if not hmac.compare_digest(digest.hexdigest(), expected_hash):
                raise BackupValidationError("BACKUP_TOKEN_INVALID", "Restore token is invalid.")
            return RestoreTokenBinding(path, path_id, expected_hash, expires_at)
        finally:
            try:
                os.replace(claim_path, self._consumed_path(token_hash))
                self.storage._fsync_directory(self.storage.uploads_dir)
            except OSError:
                # The durable claim remains discoverable by periodic maintenance.
                pass
