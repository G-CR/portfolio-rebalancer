from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backups.archive import ArchiveMetadata, iter_current_rows, open_verified_archive
from app.backups.canonical import canonical_parsed_json_bytes
from app.backups.constants import DATA_MEMBERS, STREAM_CHUNK_BYTES
from app.backups.contracts import CREDENTIAL_CONTRACT, CONTRACTS_BY_MEMBER, Codec
from app.backups.migrations import migrate_to_current
from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.schemas.backup import BackupStage
from app.services.backup_export import build_export_metadata, export_logical_backup
from app.services.async_thread import run_in_thread
from app.services.backup_storage import BackupStorage
from app.services.backup_validation import ValidatedBackup, validate_backup


RESTORE_ADVISORY_LOCK_KEY = 0x504F5254464F4C49
RESTORE_TABLES = (
    "encrypted_secrets",
    "rebalance_plans",
    "snapshot_items",
    "cost_adjustments",
    "holding_defaults",
    "market_data_overrides",
    "market_data",
    "snapshots",
    "holdings",
    "asset_classes",
    "settings",
)
DELETE_MEMBERS = (
    "credentials.json",
    "data/rebalance_plans.json",
    "data/snapshot_items.json",
    "data/cost_adjustments.json",
    "data/holding_defaults.json",
    "data/market_data_overrides.json",
    "data/market_data.json",
    "data/snapshots.json",
    "data/holdings.json",
    "data/asset_classes.json",
    "data/settings.json",
)
INSERT_MEMBERS = (
    "data/asset_classes.json",
    "data/holdings.json",
    "data/holding_defaults.json",
    "data/market_data.json",
    "data/market_data_overrides.json",
    "data/cost_adjustments.json",
    "data/snapshots.json",
    "data/snapshot_items.json",
    "data/rebalance_plans.json",
    "data/settings.json",
    "credentials.json",
)
INSERT_BATCH_SIZE = 1000
INSERT_BATCH_MAX_BYTES = 4 * 1024 * 1024


class RestoreProgress(Protocol):
    async def set_stage(self, stage: BackupStage) -> None: ...


class BackupRestoreError(Exception):
    """Sanitized restore failure. The caller-owned transaction must roll back."""


@dataclass(frozen=True, slots=True)
class RestoreResult:
    safety_backup_id: UUID
    record_counts: dict[str, int]
    logical_checksum: str


async def _run_sync(callable_, *args, **kwargs):
    return await run_in_thread(callable_, *args, **kwargs)


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(STREAM_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_value(codec: Codec, value: object) -> object:
    if value is None:
        return None
    if codec is Codec.UUID:
        return UUID(str(value))
    if codec is Codec.DECIMAL:
        return Decimal(str(value))
    if codec is Codec.DATE:
        return date.fromisoformat(str(value))
    if codec is Codec.DATETIME:
        return datetime.fromisoformat(str(value))
    if codec is Codec.JSON:
        return canonical_parsed_json_bytes(value).decode("utf-8")
    return value


def _database_row(
    member: str,
    row: dict[str, object],
    secret_store: SecretStore,
) -> dict[str, object]:
    contract = CONTRACTS_BY_MEMBER[member]
    values = {
        field: _decode_value(field_codec.codec, row[field])
        for field, field_codec in contract.field_codecs.items()
    }
    if contract is CREDENTIAL_CONTRACT:
        plaintext = values.pop("value")
        if not isinstance(plaintext, str):
            raise BackupRestoreError("credential encryption failed")
        _restore_checkpoint("encrypt")
        values["encrypted_value"] = secret_store.encrypt(plaintext).decode("ascii")
    return values


def _restore_checkpoint(_stage: str) -> None:
    """Test seam for transaction rollback coverage."""


async def _insert_archive(
    session: AsyncSession,
    validated: ValidatedBackup,
    *,
    secret_store: SecretStore,
) -> None:
    reader = _ArchiveBatchReader(validated, secret_store)
    await _run_sync(reader.open)
    inserted_batch = False
    try:
        for member in INSERT_MEMBERS:
            contract = CONTRACTS_BY_MEMBER[member]
            await _run_sync(reader.begin_member, member)
            while batch := await _run_sync(reader.next_batch):
                statement = _insert_statement(member)
                await session.execute(statement, batch)
                if not inserted_batch:
                    inserted_batch = True
                    _restore_checkpoint("insert")
    finally:
        await _run_sync(reader.close)


class _ArchiveBatchReader:
    def __init__(
        self,
        validated: ValidatedBackup,
        secret_store: SecretStore,
    ) -> None:
        self.validated = validated
        self.secret_store = secret_store
        self.inspected = None
        self.migrated = None
        self.rows = None
        self.member = ""

    def open(self) -> None:
        inspected = open_verified_archive(self.validated.retained_archive_path)
        if not hmac.compare_digest(
            inspected.archive_sha256,
            self.validated.archive_sha256,
        ):
            inspected.close()
            raise BackupRestoreError("validated archive binding changed")
        self.inspected = inspected
        self.migrated = migrate_to_current(inspected)

    def begin_member(self, member: str) -> None:
        assert self.migrated is not None
        self.rows = iter_current_rows(self.migrated, member)
        self.member = member

    def next_batch(self) -> list[dict[str, object]]:
        assert self.rows is not None
        batch: list[dict[str, object]] = []
        batch_bytes = 0
        for _ in range(INSERT_BATCH_SIZE):
            try:
                row = next(self.rows)
            except StopIteration:
                break
            database_row = _database_row(self.member, row, self.secret_store)
            row_bytes = _database_parameter_bytes(database_row)
            batch.append(database_row)
            batch_bytes += row_bytes
            if batch_bytes >= INSERT_BATCH_MAX_BYTES:
                break
        return batch

    def close(self) -> None:
        if self.inspected is not None:
            self.inspected.close()
            self.inspected = None


def _database_parameter_bytes(row: dict[str, object]) -> int:
    return sum(
        len(column.encode("utf-8")) + len(str(value).encode("utf-8"))
        for column, value in row.items()
        if value is not None
    )


def _insert_statement(member: str):
    contract = CONTRACTS_BY_MEMBER[member]
    if not any(codec.codec is Codec.JSON for codec in contract.codecs):
        return insert(contract.model)
    values = [
        (
            f"CAST(:{column} AS JSON)"
            if field_codec.codec is Codec.JSON
            else f":{column}"
        )
        for column, field_codec in contract.field_codecs.items()
    ]
    return text(
        f"INSERT INTO {contract.model.__tablename__} "
        f"({', '.join(contract.columns)}) VALUES ({', '.join(values)})"
    )


async def restore_validated_backup(
    session: AsyncSession,
    validated: ValidatedBackup,
    *,
    storage: BackupStorage,
    secret_store: SecretStore,
    progress: RestoreProgress,
) -> RestoreResult:
    """Replace logical state inside the caller's one transaction."""

    if not session.in_transaction():
        raise RuntimeError("restore requires a caller-owned transaction")
    try:
        if not hmac.compare_digest(
            await _run_sync(_archive_sha256, validated.retained_archive_path),
            validated.archive_sha256,
        ):
            raise BackupRestoreError("validated archive binding changed")

        await progress.set_stage(BackupStage.LOCKING_DATA)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": RESTORE_ADVISORY_LOCK_KEY},
        )
        await session.execute(
            text(f"LOCK TABLE {', '.join(RESTORE_TABLES)} IN ACCESS EXCLUSIVE MODE")
        )

        await progress.set_stage(BackupStage.CREATING_SAFETY_BACKUP)
        safety_id = storage.new_safety_id()
        safety_partial = storage.safety_partial_path(safety_id)
        safety_published = False
        try:
            _restore_checkpoint("safety_backup")
            await export_logical_backup(
                session,
                safety_partial,
                secret_store=secret_store,
                metadata=build_export_metadata_from_storage(),
            )
            await _run_sync(
                validate_backup,
                safety_partial,
                path_id=f"safety:{safety_id}",
                workspace_root=storage.tmp_dir,
            )
            # Retention waits until the source archive has been fully consumed. If the
            # source is the oldest safety file, deleting it here would break restore.
            await _run_sync(
                storage.publish_safety_backup,
                safety_id,
                safety_partial,
                enforce_retention=False,
            )
            safety_published = True
        finally:
            if not safety_published:
                safety_partial.unlink(missing_ok=True)

        await progress.set_stage(BackupStage.WRITING_DATA)
        for index, member in enumerate(DELETE_MEMBERS):
            await session.execute(delete(CONTRACTS_BY_MEMBER[member].model))
            if index == 0:
                _restore_checkpoint("delete")
        await _insert_archive(session, validated, secret_store=secret_store)

        await progress.set_stage(BackupStage.VERIFYING_INTEGRITY)
        verification_path = storage.tmp_dir / f"{safety_id}.verification.partial"
        try:
            summary = await export_logical_backup(
                session,
                verification_path,
                secret_store=secret_store,
                metadata=build_export_metadata_from_storage(),
            )
            _restore_checkpoint("verify")
            if (
                summary.record_counts != validated.record_counts
                or not hmac.compare_digest(
                    summary.logical_checksum, validated.canonical_logical_checksum
                )
            ):
                raise BackupRestoreError("restored logical state verification failed")
        finally:
            verification_path.unlink(missing_ok=True)
        return RestoreResult(safety_id, summary.record_counts, summary.logical_checksum)
    except BackupRestoreError:
        raise
    except Exception:
        raise BackupRestoreError("logical backup restore failed") from None


def build_export_metadata_from_storage() -> ArchiveMetadata:
    # Keep metadata creation centralized with ordinary exports without opening a session.
    return build_export_metadata(get_settings())
