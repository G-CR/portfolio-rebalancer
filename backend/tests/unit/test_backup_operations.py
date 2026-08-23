from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.backups.archive import ArchiveMetadata, write_archive
from app.backups.constants import DATA_MEMBERS
from app.schemas.backup import BackupOperation, BackupStage
from app.services import backup_storage as storage_module
from app.services.backup_operations import (
    BackupOperationConflict,
    BackupOperationManager,
)
from app.services.backup_storage import BackupStorage


def _empty_source() -> dict[str, list[dict[str, object]]]:
    return {member: [] for member in DATA_MEMBERS}


def _write_archive(path: Path, exported_at: datetime) -> None:
    write_archive(
        path,
        _empty_source(),
        ArchiveMetadata(
            source_application_version="test",
            exported_at=exported_at,
            display_timezone="Asia/Shanghai",
        ),
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_storage_initializes_private_directories_and_atomically_writes_private_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()

    for directory in (
        storage.operations_dir,
        storage.exports_dir,
        storage.uploads_dir,
        storage.safety_dir,
        storage.tmp_dir,
    ):
        assert directory.is_dir()
        assert _mode(directory) == 0o700

    replacements: list[tuple[Path, Path]] = []
    real_replace = storage_module.os.replace

    def tracking_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(storage_module.os, "replace", tracking_replace)
    operation = BackupOperation.new("export")
    storage.write_operation(operation)

    journal = storage.operation_journal_path(operation.id)
    assert json.loads(journal.read_text())["id"] == str(operation.id)
    assert _mode(journal) == 0o600
    assert replacements == [(replacements[0][0], journal)]
    assert replacements[0][0].parent == storage.tmp_dir
    assert not replacements[0][0].exists()


@pytest.mark.asyncio
async def test_manager_rejects_a_second_active_operation_without_queueing(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    manager = BackupOperationManager(storage)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_runner(_):
        entered.set()
        await release.wait()

    first = await manager.start("restore", blocked_runner)
    await entered.wait()

    with pytest.raises(BackupOperationConflict) as raised:
        await manager.start("export", blocked_runner)

    assert raised.value.status_code == 409
    assert raised.value.code == "BACKUP_OPERATION_CONFLICT"
    release.set()
    await manager.wait(first.id)
    assert manager.get(first.id).status == "succeeded"


@pytest.mark.asyncio
async def test_manager_sanitizes_runner_failure_in_persisted_journal(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    manager = BackupOperationManager(storage)
    secret = "synthetic-super-secret"

    async def failed_runner(_):
        raise RuntimeError(f"database /private/path failed with {secret} SELECT *")

    operation = await manager.start("export", failed_runner)
    await manager.wait(operation.id)

    persisted = storage.operation_journal_path(operation.id).read_text()
    result = manager.get(operation.id)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "BACKUP_EXPORT_FAILED"
    assert result.error.message == "Backup export failed."
    assert secret not in persisted
    assert "/private/path" not in persisted
    assert "SELECT" not in persisted


def test_recovery_interrupts_unfinished_operations_and_removes_orphan_files(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    running = BackupOperation.new("restore").model_copy(
        update={"status": "running", "stage": BackupStage.LOCKING_DATA}
    )
    storage.write_operation(running)
    export_path = storage.export_path(running.id)
    export_path.write_bytes(b"partial secret archive")
    export_path.chmod(0o600)
    orphan = storage.tmp_dir / ".orphan.partial"
    orphan.write_bytes(b"partial")

    manager = BackupOperationManager(storage)
    manager.recover()

    recovered = manager.get(running.id)
    assert recovered.status == "interrupted"
    assert recovered.error is not None
    assert recovered.error.code == "BACKUP_INTERRUPTED"
    assert not export_path.exists()
    assert not orphan.exists()


def test_cleanup_expires_completed_manual_export_after_thirty_minutes(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path, export_ttl=timedelta(minutes=30))
    storage.initialize()
    now = datetime.now(timezone.utc)
    operation = BackupOperation.new("export", now=now - timedelta(minutes=31)).model_copy(
        update={
            "status": "succeeded",
            "stage": BackupStage.COMPLETED,
            "download_ready": True,
            "updated_at": now - timedelta(minutes=31),
            "expires_at": now - timedelta(minutes=1),
        }
    )
    storage.write_operation(operation)
    storage.export_path(operation.id).write_bytes(b"sensitive")

    BackupOperationManager(storage).cleanup_expired(now=now)

    assert not storage.export_path(operation.id).exists()
    assert BackupOperationManager(storage).get(operation.id).download_ready is False


def test_safety_retention_deletes_oldest_only_after_sixth_is_valid_and_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=5)
    storage.initialize()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    backup_ids = []

    for index in range(5):
        backup_id = uuid4()
        backup_ids.append(backup_id)
        partial = storage.safety_partial_path(backup_id)
        _write_archive(partial, base + timedelta(minutes=index))
        storage.publish_safety_backup(backup_id, partial)

    observed_sixth_durable: list[bool] = []
    real_unlink = Path.unlink

    sixth_id = uuid4()
    sixth_partial = storage.safety_partial_path(sixth_id)
    _write_archive(sixth_partial, base + timedelta(minutes=5))
    sixth_destination = storage.safety_path(sixth_id)

    def tracking_unlink(path: Path, *args, **kwargs):
        if path.parent == storage.safety_dir and path.suffix == ".portfolio-backup":
            observed_sixth_durable.append(sixth_destination.exists())
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", tracking_unlink)
    storage.publish_safety_backup(sixth_id, sixth_partial)

    retained = storage.list_safety_backups()
    assert len(retained) == 5
    assert [item.id for item in retained] == [
        sixth_id,
        backup_ids[4],
        backup_ids[3],
        backup_ids[2],
        backup_ids[1],
    ]
    assert observed_sixth_durable == [True]
    assert _mode(sixth_destination) == 0o600


def test_failed_sixth_safety_validation_preserves_existing_five(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path, safety_retention=5)
    storage.initialize()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    existing_ids = []
    for index in range(5):
        backup_id = uuid4()
        existing_ids.append(backup_id)
        partial = storage.safety_partial_path(backup_id)
        _write_archive(partial, base + timedelta(minutes=index))
        storage.publish_safety_backup(backup_id, partial)

    invalid_id = uuid4()
    invalid = storage.safety_partial_path(invalid_id)
    invalid.write_bytes(b"not an archive")

    with pytest.raises(Exception):
        storage.publish_safety_backup(invalid_id, invalid)

    assert {item.id for item in storage.list_safety_backups()} == set(existing_ids)
