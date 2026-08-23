from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.fernet import InvalidToken
from sqlalchemy import Select, Text, cast, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backups.archive import (
    ArchiveMetadata,
    ArchiveSummary,
    BackupArchiveError,
    canonical_source_row_bytes,
    write_archive,
)
from app.backups.canonical import canonical_json_bytes
from app.backups.constants import DATA_MEMBERS
from app.backups.contracts import CREDENTIAL_CONTRACT, TABLE_CONTRACTS, TableContract
from app.core.config import Settings, get_settings
from app.core.secrets import SecretStore
from app.db.models import EncryptedSecret
from app.db.session import SessionFactory


DEFAULT_BATCH_SIZE = 1000


class BackupExportError(BackupArchiveError):
    """A sanitized failure while reading the logical database snapshot."""


class _JsonLineRows:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __iter__(self) -> Iterator[Mapping[str, object]]:
        with self.path.open("rb") as source:
            for payload in source:
                row = json.loads(payload, parse_float=Decimal)
                if not isinstance(row, dict):
                    raise BackupExportError("logical backup staging data is invalid")
                yield row


class DatabaseLogicalSource:
    """Keyset-batched adapter from one caller-owned transaction to archive rows."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        secret_store: SecretStore,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.session = session
        self.secret_store = secret_store
        self.batch_size = batch_size

    async def stage(
        self,
        workspace: Path,
    ) -> dict[str, Iterable[Mapping[str, object]]]:
        source: dict[str, Iterable[Mapping[str, object]]] = {}
        contracts = (CREDENTIAL_CONTRACT, *TABLE_CONTRACTS)
        if {contract.member for contract in contracts} != set(DATA_MEMBERS):
            raise BackupExportError("logical backup contracts are incomplete")
        for contract in contracts:
            if contract is CREDENTIAL_CONTRACT:
                source[contract.member] = await self._credentials_in_memory(contract)
                continue
            path = workspace / contract.member.replace("/", "_")
            with path.open("wb") as staged_rows:
                last_id: UUID | None = None
                while True:
                    batch = await self._fetch_batch(contract, last_id)
                    if not batch:
                        break
                    for row in batch:
                        staged_rows.write(canonical_source_row_bytes(contract, row))
                        staged_rows.write(b"\n")
                    last_id = batch[-1][contract.order_key]
                    if not isinstance(last_id, UUID):
                        raise BackupExportError("logical backup row identity is invalid")
                    if len(batch) < self.batch_size:
                        break
            source[contract.member] = _JsonLineRows(path)
        return source

    async def _credentials_in_memory(
        self,
        contract: TableContract,
    ) -> list[dict[str, object]]:
        credentials: list[dict[str, object]] = []
        last_id: UUID | None = None
        while True:
            batch = await self._fetch_batch(contract, last_id)
            if not batch:
                return credentials
            credentials.extend(batch)
            last_id = batch[-1][contract.order_key]
            if not isinstance(last_id, UUID):
                raise BackupExportError("logical backup row identity is invalid")
            if len(batch) < self.batch_size:
                return credentials

    async def _fetch_batch(
        self,
        contract: TableContract,
        last_id: UUID | None,
    ) -> list[dict[str, object]]:
        statement = self._batch_statement(contract, last_id)
        result = await self.session.execute(statement)
        rows = [dict(row) for row in result.mappings()]
        for row in rows:
            for column, field_codec in contract.field_codecs.items():
                if field_codec.codec.value == "json" and row[column] is not None:
                    raw_json = row[column]
                    if not isinstance(raw_json, str):
                        raise BackupExportError("logical JSON data is invalid")
                    try:
                        row[column] = json.loads(raw_json, parse_float=Decimal)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        raise BackupExportError("logical JSON data is invalid") from None
        if contract is CREDENTIAL_CONTRACT:
            for row in rows:
                encrypted_value = row["value"]
                if not isinstance(encrypted_value, str):
                    raise BackupExportError("credential decryption failed")
                decrypted_value: str | None = None
                try:
                    decrypted_value = self.secret_store.decrypt(encrypted_value.encode("ascii"))
                except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
                    pass
                if decrypted_value is None:
                    raise BackupExportError("credential decryption failed") from None
                row["value"] = decrypted_value
        return rows

    def _batch_statement(
        self,
        contract: TableContract,
        last_id: UUID | None,
    ) -> Select[Any]:
        model = contract.model
        selected_columns = []
        for column, field_codec in contract.field_codecs.items():
            selected = (
                EncryptedSecret.encrypted_value.label("value")
                if contract is CREDENTIAL_CONTRACT and column == "value"
                else getattr(model, column)
            )
            if field_codec.codec.value == "json":
                selected = cast(selected, Text).label(column)
            selected_columns.append(selected)
        order_column = getattr(model, contract.order_key)
        statement = select(*selected_columns)
        if last_id is not None:
            statement = statement.where(order_column > last_id)
        return statement.order_by(order_column).limit(self.batch_size)


async def export_logical_backup(
    session: AsyncSession,
    destination: Path,
    *,
    secret_store: SecretStore,
    metadata: ArchiveMetadata,
) -> ArchiveSummary:
    """Export from the transaction already owned by ``session`` without ending it."""

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_adapter = DatabaseLogicalSource(session, secret_store=secret_store)
    with tempfile.TemporaryDirectory(dir=destination.parent) as workspace_name:
        source = await source_adapter.stage(Path(workspace_name))
        archive_task = asyncio.create_task(
            asyncio.to_thread(write_archive, destination, source, metadata)
        )
        try:
            return await asyncio.shield(archive_task)
        except asyncio.CancelledError:
            await archive_task
            raise


def build_export_metadata(settings: Settings) -> ArchiveMetadata:
    try:
        application_version = version("portfolio-rebalancer-api")
    except PackageNotFoundError:
        application_version = "0.1.0"
    return ArchiveMetadata(
        source_application_version=application_version,
        exported_at=datetime.now(timezone.utc),
        display_timezone=settings.timezone,
    )


async def export_database_backup(destination: Path) -> ArchiveSummary:
    """Manually export one read-only, repeatable-read database snapshot."""

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    staged_archive: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".complete",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            staged_archive = Path(temporary.name)
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                summary = await export_logical_backup(
                    session,
                    staged_archive,
                    secret_store=SecretStore(Path(settings.secret_key_path)),
                    metadata=build_export_metadata(settings),
                )
        os.replace(staged_archive, destination)
        staged_archive = None
        return summary
    finally:
        if staged_archive is not None:
            staged_archive.unlink(missing_ok=True)
