from __future__ import annotations

import asyncio
import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
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


def _completed_export(
    storage: BackupStorage,
    *,
    expires_at: datetime,
    create_file: bool = True,
) -> BackupOperation:
    operation = BackupOperation.new("export", now=expires_at - storage.export_ttl).model_copy(
        update={
            "status": "succeeded",
            "stage": BackupStage.COMPLETED,
            "download_ready": True,
            "updated_at": expires_at - storage.export_ttl,
            "expires_at": expires_at,
        }
    )
    storage.write_operation(operation)
    if create_file:
        storage.export_path(operation.id).write_bytes(b"sensitive")
    return operation


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
async def test_simultaneous_starts_accept_exactly_one_operation(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    manager = BackupOperationManager(storage)
    start_gate = asyncio.Event()
    runner_release = asyncio.Event()

    async def runner(_):
        await runner_release.wait()

    async def contender(kind):
        await start_gate.wait()
        try:
            return await manager.start(kind, runner)
        except BackupOperationConflict as exc:
            return exc

    contenders = [
        asyncio.create_task(contender("export")),
        asyncio.create_task(contender("restore")),
    ]
    start_gate.set()
    results = await asyncio.gather(*contenders)

    accepted = [result for result in results if isinstance(result, BackupOperation)]
    conflicts = [result for result in results if isinstance(result, BackupOperationConflict)]
    assert len(accepted) == 1
    assert len(conflicts) == 1
    runner_release.set()
    await manager.wait(accepted[0].id)


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


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(microseconds=1)])
def test_get_reconciles_export_at_or_after_exact_expiry(
    tmp_path: Path, offset: timedelta
) -> None:
    storage = BackupStorage(tmp_path, export_ttl=timedelta(minutes=30))
    storage.initialize()
    deadline = datetime(2026, 8, 24, tzinfo=timezone.utc)
    operation = _completed_export(storage, expires_at=deadline)
    manager = BackupOperationManager(storage, clock=lambda: deadline + offset)

    reconciled = manager.get(operation.id)

    assert reconciled.status == "succeeded"
    assert reconciled.download_ready is False
    assert not storage.export_path(operation.id).exists()


def test_expired_export_delete_failure_is_retried_after_readiness_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    deadline = datetime(2026, 8, 24, tzinfo=timezone.utc)
    operation = _completed_export(storage, expires_at=deadline)
    manager = BackupOperationManager(
        storage,
        cleanup_interval_seconds=17,
        clock=lambda: deadline,
    )
    real_delete = storage.delete_export
    calls = 0

    def flaky_delete(operation_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic delete failure /private/path")
        real_delete(operation_id)

    monkeypatch.setattr(storage, "delete_export", flaky_delete)

    unavailable = manager.get(operation.id)
    assert unavailable.download_ready is False
    assert storage.export_path(operation.id).exists()
    assert manager._seconds_until_next_expiry() == 17
    assert manager.get(operation.id).download_ready is False
    assert calls == 1
    assert storage.export_path(operation.id).exists()

    manager.cleanup_expired(now=deadline + timedelta(seconds=1))

    assert calls == 2
    assert not storage.export_path(operation.id).exists()


def test_recovery_reconciles_missing_succeeded_export(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    operation = _completed_export(
        storage,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        create_file=False,
    )
    manager = BackupOperationManager(storage)

    manager.recover()

    recovered = manager.get(operation.id)
    assert recovered.status == "succeeded"
    assert recovered.download_ready is False


def test_recovery_preserves_expired_delete_debt_for_periodic_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    deadline = datetime(2026, 8, 24, tzinfo=timezone.utc)
    operation = _completed_export(storage, expires_at=deadline)
    manager = BackupOperationManager(storage, clock=lambda: deadline)
    real_unlink = Path.unlink
    deletion_blocked = True

    def blocked_unlink(path: Path, *args, **kwargs):
        if deletion_blocked and path == storage.export_path(operation.id):
            raise OSError("persistent synthetic delete failure /private/path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked_unlink)

    manager.recover()

    assert manager.get(operation.id).download_ready is False
    assert storage.export_path(operation.id).exists()
    deletion_blocked = False
    manager.cleanup_expired(now=deadline + timedelta(seconds=1))
    assert not storage.export_path(operation.id).exists()


@pytest.mark.asyncio
async def test_cleanup_wakes_at_nearest_export_deadline(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path, export_ttl=timedelta(milliseconds=50))
    storage.initialize()
    manager = BackupOperationManager(storage, cleanup_interval_seconds=60)
    manager.start_cleanup()

    async def export_runner(context):
        storage.export_path(context.operation_id).write_bytes(b"archive")

    operation = await manager.start("export", export_runner)
    await manager.wait(operation.id)

    async with asyncio.timeout(1):
        while storage.export_path(operation.id).exists():
            await asyncio.sleep(0.01)

    assert manager.get(operation.id).download_ready is False
    await manager.stop()


@pytest.mark.asyncio
async def test_cleanup_loop_contains_filesystem_failure_and_cleans_later_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    operation = _completed_export(
        storage,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    manager = BackupOperationManager(storage, cleanup_interval_seconds=0.01)
    real_cleanup = manager.cleanup_expired
    cleaned = asyncio.Event()
    calls = 0

    def flaky_cleanup(*, now=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic cleanup failure /private/path")
        real_cleanup(now=now)
        cleaned.set()

    monkeypatch.setattr(manager, "cleanup_expired", flaky_cleanup)
    manager.start_cleanup()

    async with asyncio.timeout(1):
        await cleaned.wait()

    assert calls >= 2
    assert not storage.export_path(operation.id).exists()
    assert manager.get(operation.id).download_ready is False
    await manager.stop()


@pytest.mark.asyncio
async def test_atomic_journal_failure_retries_at_bounded_interval_then_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    operation = _completed_export(
        storage,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    manager = BackupOperationManager(storage, cleanup_interval_seconds=0.05)
    real_write = storage.write_operation
    writes_blocked = True
    write_attempts = 0
    heartbeats = 0

    def blocked_atomic_write(candidate):
        nonlocal write_attempts
        if candidate.id == operation.id and candidate.download_ready is False:
            write_attempts += 1
            if writes_blocked:
                raise OSError("synthetic atomic journal failure /private/path")
        real_write(candidate)

    async def heartbeat() -> None:
        nonlocal heartbeats
        deadline = asyncio.get_running_loop().time() + 0.13
        while asyncio.get_running_loop().time() < deadline:
            heartbeats += 1
            await asyncio.sleep(0)

    monkeypatch.setattr(storage, "write_operation", blocked_atomic_write)
    manager.start_cleanup()
    await heartbeat()

    assert heartbeats > 10
    assert 2 <= write_attempts <= 4
    assert storage.read_operation(operation.id).download_ready is True
    assert storage.export_path(operation.id).exists()

    writes_blocked = False
    manager._cleanup_wakeup.set()
    async with asyncio.timeout(1):
        while storage.export_path(operation.id).exists():
            await asyncio.sleep(0.01)

    assert storage.read_operation(operation.id).download_ready is False
    await manager.stop()


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


@pytest.mark.parametrize("via_retention", [False, True])
def test_safety_delete_and_retention_are_atomic_with_source_lease_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    via_retention: bool,
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=1)
    storage.initialize()
    backup_id = uuid4()
    partial = storage.safety_partial_path(backup_id)
    _write_archive(partial, datetime(2026, 1, 1, tzinfo=timezone.utc))
    storage.publish_safety_backup(backup_id, partial)
    target = storage.safety_path(backup_id)
    unlink_entered = threading.Event()
    allow_unlink = threading.Event()
    lease_acquired = threading.Event()
    other_lease_round_trip = threading.Event()
    real_unlink = Path.unlink

    def blocked_unlink(path: Path, *args, **kwargs):
        if path == target:
            unlink_entered.set()
            assert allow_unlink.wait(timeout=5)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked_unlink)
    if via_retention:
        storage.safety_retention = 0
        delete = storage.enforce_safety_retention
    else:
        delete = lambda: storage.delete_safety_backup(backup_id)

    with ThreadPoolExecutor(max_workers=3) as executor:
        delete_future = executor.submit(delete)
        assert unlink_entered.wait(timeout=5)

        def acquire():
            lease = storage.acquire_source_lease(f"safety:{backup_id}")
            lease_acquired.set()
            return lease

        lease_future = executor.submit(acquire)

        def acquire_other():
            lease = storage.acquire_source_lease(f"safety:{uuid4()}")
            lease.release()
            other_lease_round_trip.set()

        other_future = executor.submit(acquire_other)
        try:
            assert not lease_acquired.wait(timeout=0.2)
            assert other_lease_round_trip.wait(timeout=0.2)
        finally:
            allow_unlink.set()
        delete_future.result(timeout=5)
        lease = lease_future.result(timeout=5)
        other_future.result(timeout=5)

    assert lease_acquired.is_set()
    assert not target.exists()
    lease.release()


def test_failed_safety_unlink_clears_delete_claim_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=1)
    storage.initialize()
    backup_id = uuid4()
    partial = storage.safety_partial_path(backup_id)
    _write_archive(partial, datetime(2026, 1, 1, tzinfo=timezone.utc))
    storage.publish_safety_backup(backup_id, partial)
    target = storage.safety_path(backup_id)
    entered = threading.Event()
    release = threading.Event()
    acquired = threading.Event()
    real_unlink = Path.unlink
    fail_once = True

    def failing_unlink(path: Path, *args, **kwargs):
        nonlocal fail_once
        if path == target and fail_once:
            fail_once = False
            entered.set()
            assert release.wait(timeout=5)
            raise OSError("synthetic unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with ThreadPoolExecutor(max_workers=2) as executor:
        delete_future = executor.submit(storage.delete_safety_backup, backup_id)
        assert entered.wait(timeout=5)

        def acquire_same():
            lease = storage.acquire_source_lease(f"safety:{backup_id}")
            acquired.set()
            return lease

        lease_future = executor.submit(acquire_same)
        try:
            assert not acquired.wait(timeout=0.2)
        finally:
            release.set()
        with pytest.raises(OSError, match="synthetic unlink failure"):
            delete_future.result(timeout=5)
        lease = lease_future.result(timeout=5)

    assert target.exists()
    lease.release()
    assert storage.delete_safety_backup(backup_id) is True
    assert not target.exists()


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


def test_safety_publication_succeeds_when_best_effort_retention_has_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=10)
    storage.initialize()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    existing_ids = []
    for index in range(5):
        backup_id = uuid4()
        existing_ids.append(backup_id)
        partial = storage.safety_partial_path(backup_id)
        _write_archive(partial, base + timedelta(minutes=index))
        storage.publish_safety_backup(backup_id, partial)

    storage.safety_retention = 2
    real_unlink = Path.unlink
    attempted: list[Path] = []
    failed_once = False

    def flaky_unlink(path: Path, *args, **kwargs):
        nonlocal failed_once
        if path.parent == storage.safety_dir and path.suffix == ".portfolio-backup":
            attempted.append(path)
            if not failed_once:
                failed_once = True
                raise OSError("synthetic unlink failure /private/path")
        return real_unlink(path, *args, **kwargs)

    real_fsync_directory = storage._fsync_directory
    fsync_failed = False

    def flaky_fsync_directory(path: Path) -> None:
        nonlocal fsync_failed
        if path == storage.safety_dir and failed_once and not fsync_failed:
            fsync_failed = True
            raise OSError("synthetic fsync failure /private/path")
        real_fsync_directory(path)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(storage, "_fsync_directory", flaky_fsync_directory)
    newest_id = uuid4()
    partial = storage.safety_partial_path(newest_id)
    _write_archive(partial, base + timedelta(minutes=10))

    published = storage.publish_safety_backup(newest_id, partial)

    assert published.id == newest_id
    assert storage.safety_path(newest_id).exists()
    assert len(attempted) >= 2
    assert any(not storage.safety_path(backup_id).exists() for backup_id in existing_ids)


def test_safety_retention_debt_is_retried_without_new_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=10)
    storage.initialize()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    backup_ids = []
    for index in range(5):
        backup_id = uuid4()
        backup_ids.append(backup_id)
        partial = storage.safety_partial_path(backup_id)
        _write_archive(partial, base + timedelta(minutes=index))
        storage.publish_safety_backup(backup_id, partial)

    storage.safety_retention = 5
    real_unlink = Path.unlink
    failed = False

    def fail_first_retention_unlink(path: Path, *args, **kwargs):
        nonlocal failed
        if path.parent == storage.safety_dir and not failed:
            failed = True
            raise OSError("synthetic retention failure /private/path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_retention_unlink)
    newest_id = uuid4()
    newest_partial = storage.safety_partial_path(newest_id)
    _write_archive(newest_partial, base + timedelta(minutes=5))

    published = storage.publish_safety_backup(newest_id, newest_partial)

    assert published.id == newest_id
    assert len(storage.list_safety_backups()) == 6
    monkeypatch.setattr(Path, "unlink", real_unlink)

    BackupOperationManager(storage).recover()

    retained = storage.list_safety_backups()
    assert len(retained) == 5
    assert [item.id for item in retained] == [
        newest_id,
        backup_ids[4],
        backup_ids[3],
        backup_ids[2],
        backup_ids[1],
    ]


@pytest.mark.asyncio
async def test_cleanup_loop_retries_inner_safety_retention_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=10)
    storage.initialize()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(6):
        backup_id = uuid4()
        partial = storage.safety_partial_path(backup_id)
        _write_archive(partial, base + timedelta(minutes=index))
        storage.publish_safety_backup(backup_id, partial)
    storage.safety_retention = 5

    manager = BackupOperationManager(storage, cleanup_interval_seconds=0.01)
    real_delete = storage.delete_safety_backup
    deleted = asyncio.Event()
    event_loop = asyncio.get_running_loop()
    calls = 0

    def flaky_delete(backup_id):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise OSError("persistent synthetic retention failure /private/path")
        result = real_delete(backup_id)
        event_loop.call_soon_threadsafe(deleted.set)
        return result

    monkeypatch.setattr(storage, "delete_safety_backup", flaky_delete)
    manager.start_cleanup()

    async with asyncio.timeout(1):
        await deleted.wait()

    assert calls == 3
    assert len(storage.list_safety_backups()) == 5
    await manager.stop()


def test_safety_debt_check_with_five_candidates_never_inspects_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=5)
    storage.initialize()
    for _ in range(5):
        storage.safety_path(uuid4()).write_bytes(b"candidate")

    def fail_inspection(*_args, **_kwargs):
        raise AssertionError("cheap debt check must not inspect archives")

    monkeypatch.setattr(storage, "_inspect_safety", fail_inspection)

    assert storage.has_safety_retention_debt() is False


@pytest.mark.asyncio
async def test_normal_cleanup_skips_safety_enforcer_without_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=5)
    storage.initialize()
    checked = asyncio.Event()
    calls = 0

    def cheap_check() -> bool:
        checked.set()
        return False

    def unexpected_enforcement() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(storage, "has_safety_retention_debt", cheap_check)
    monkeypatch.setattr(storage, "enforce_safety_retention", unexpected_enforcement)
    manager = BackupOperationManager(storage, cleanup_interval_seconds=60)
    manager.start_cleanup()

    async with asyncio.timeout(1):
        await checked.wait()
    await asyncio.sleep(0)

    assert calls == 0
    await manager.stop()


@pytest.mark.asyncio
async def test_blocked_safety_enforcement_does_not_block_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = BackupStorage(tmp_path, safety_retention=5)
    storage.initialize()
    for _ in range(6):
        storage.safety_path(uuid4()).write_bytes(b"candidate")
    entered = threading.Event()
    release = threading.Event()

    def blocked_enforcement() -> None:
        entered.set()
        release.wait(timeout=1)

    async def heartbeat() -> None:
        await asyncio.sleep(0.02)
        release.set()

    monkeypatch.setattr(storage, "enforce_safety_retention", blocked_enforcement)
    manager = BackupOperationManager(storage, cleanup_interval_seconds=60)
    started_at = asyncio.get_running_loop().time()
    heartbeat_task = asyncio.create_task(heartbeat())
    manager.start_cleanup()

    async with asyncio.timeout(1):
        while not entered.is_set():
            await asyncio.sleep(0)
        await heartbeat_task

    assert asyncio.get_running_loop().time() - started_at < 0.2
    await manager.stop()


@pytest.mark.asyncio
async def test_stop_interrupts_operation_cancelled_before_runner_starts(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    manager = BackupOperationManager(storage)
    runner_called = False

    async def runner(_):
        nonlocal runner_called
        runner_called = True

    operation = await manager.start("restore", runner)
    await manager.stop()

    persisted = manager.get(operation.id)
    assert runner_called is False
    assert persisted.status == "interrupted"
    assert persisted.error is not None
    assert persisted.error.code == "BACKUP_INTERRUPTED"
    assert manager._active_operation_id is None
    assert manager._tasks == {}


@pytest.mark.asyncio
async def test_stop_blocks_concurrent_and_future_starts(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    manager = BackupOperationManager(storage)

    async def runner(_):
        await asyncio.sleep(0)

    await manager._state_lock.acquire()
    stop_task = asyncio.create_task(manager.stop())
    await asyncio.sleep(0)
    start_task = asyncio.create_task(manager.start("restore", runner))
    manager._state_lock.release()

    await stop_task
    with pytest.raises(BackupOperationConflict):
        await start_task
    with pytest.raises(BackupOperationConflict):
        await manager.start("export", runner)
    assert manager._active_operation_id is None
    assert manager._tasks == {}


@pytest.mark.asyncio
async def test_completed_tasks_are_removed_from_manager_registry(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path)
    storage.initialize()
    manager = BackupOperationManager(storage)

    async def runner(_):
        return None

    operation = await manager.start("restore", runner)
    await manager.wait(operation.id)
    await asyncio.sleep(0)

    assert operation.id not in manager._tasks
