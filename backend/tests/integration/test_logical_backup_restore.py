from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backups.archive import ArchiveMetadata, write_archive
from app.backups.constants import DATA_MEMBERS
from app.core.secrets import SecretStore
from app.db.models import AssetClass, EncryptedSecret, Setting
from app.schemas.backup import BackupStage
from app.services import backup_restore as restore_module
from app.services import backup_export as export_module
from app.services.backup_export import export_logical_backup
from app.services.backup_restore import BackupRestoreError, restore_validated_backup
from app.services.backup_storage import BackupStorage
from app.services.backup_validation import validate_backup
from tests.conftest import BUSINESS_TABLES
from tests.conftest import SessionFactory
from tests.unit.test_backup_validation import _source as _validated_source


NOW = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
ASSET_ID = UUID("10000000-0000-0000-0000-000000000001")
SETTING_ID = UUID("00000000-0000-0000-0000-000000000001")
SECRET_ID = UUID("20000000-0000-0000-0000-000000000001")


class _Progress:
    def __init__(self) -> None:
        self.stages: list[BackupStage] = []

    async def set_stage(self, stage: BackupStage) -> None:
        self.stages.append(stage)


def _metadata() -> ArchiveMetadata:
    return ArchiveMetadata("test", NOW, "Asia/Shanghai")


def _storage(tmp_path: Path, *, safety_retention: int = 5) -> BackupStorage:
    storage = BackupStorage(
        tmp_path / "backup-data",
        safety_retention=safety_retention,
    )
    storage.initialize()
    return storage


async def _seed_state(session: AsyncSession, secret_store: SecretStore, *, name: str, secret: str) -> None:
    session.add(AssetClass(id=ASSET_ID, name=name, target_weight=Decimal("1.000000000000"), display_order=0, is_active=True, notes="恢复测试", created_at=NOW, updated_at=NOW))
    session.add(Setting(id=SETTING_ID, refresh_hour=7, refresh_minute=30, provider_priority=["yahoo"], default_tolerance=Decimal("0.010000000000"), minimum_trade_amount_cny=Decimal("100.000000000000"), allow_sell=True, allow_fx=True, rebalance_available_cny=Decimal("0"), rebalance_available_usd=Decimal("0"), rebalance_valuation_basis="actual", email_enabled=False, email_recipient=None, email_smtp_host=None, email_smtp_port=465, email_smtp_security="ssl", email_smtp_username=None, email_from=None, created_at=NOW, updated_at=NOW))
    session.add(EncryptedSecret(id=SECRET_ID, provider="yahoo", encrypted_value=secret_store.encrypt(secret).decode("ascii"), masked_value="****test", validation_status="valid", validation_message="synthetic", last_validated_at=NOW, created_at=NOW, updated_at=NOW))
    await session.commit()


async def _export(session: AsyncSession, path: Path, secret_store: SecretStore):
    async with session.begin():
        return await export_logical_backup(session, path, secret_store=secret_store, metadata=_metadata())


@pytest.mark.asyncio
async def test_restore_round_trip_reencrypts_credentials_and_matches_checksum(db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    storage = _storage(tmp_path)
    await _seed_state(db_session, secret_store, name="exported", secret="synthetic-secret")
    source = tmp_path / "source.portfolio-backup"
    expected = await _export(db_session, source, secret_store)
    validated = validate_backup(source, path_id="upload:test", workspace_root=storage.tmp_dir)
    await db_session.execute(delete(EncryptedSecret)); await db_session.execute(delete(Setting)); await db_session.execute(delete(AssetClass)); await db_session.commit()
    await _seed_state(db_session, secret_store, name="replacement", secret="other-secret")
    progress = _Progress()
    monkeypatch.setattr(restore_module, "build_export_metadata_from_storage", lambda: _metadata())

    async with db_session.begin():
        result = await restore_validated_backup(db_session, validated, storage=storage, secret_store=secret_store, progress=progress)

    actual = await _export(db_session, tmp_path / "actual.portfolio-backup", secret_store)
    restored_secret = await db_session.scalar(select(EncryptedSecret.encrypted_value).where(EncryptedSecret.id == SECRET_ID))
    assert restored_secret is not None
    assert secret_store.decrypt(restored_secret.encode("ascii")) == "synthetic-secret"
    assert result.logical_checksum == actual.logical_checksum == expected.logical_checksum
    assert result.record_counts == actual.record_counts == expected.record_counts
    assert progress.stages == [BackupStage.LOCKING_DATA, BackupStage.CREATING_SAFETY_BACKUP, BackupStage.WRITING_DATA, BackupStage.VERIFYING_INTEGRITY]
    assert storage.safety_path(result.safety_backup_id).is_file()


@pytest.mark.asyncio
async def test_complete_logical_state_round_trip_preserves_every_collection(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "complete-fernet.key")
    storage = _storage(tmp_path)
    seed_archive = tmp_path / "complete-seed.portfolio-backup"
    write_archive(seed_archive, _validated_source(), _metadata())
    seed_validated = validate_backup(
        seed_archive, path_id="upload:complete-seed", workspace_root=storage.tmp_dir
    )
    await _seed_state(db_session, secret_store, name="temporary", secret="temporary-secret")
    monkeypatch.setattr(restore_module, "build_export_metadata_from_storage", lambda: _metadata())

    async with db_session.begin():
        await restore_validated_backup(
            db_session,
            seed_validated,
            storage=storage,
            secret_store=secret_store,
            progress=_Progress(),
        )

    source = tmp_path / "complete-source.portfolio-backup"
    expected = await _export(db_session, source, secret_store)
    assert all(expected.record_counts[member] > 0 for member in DATA_MEMBERS)
    validated = validate_backup(source, path_id="upload:complete", workspace_root=storage.tmp_dir)
    await db_session.execute(text(f"TRUNCATE TABLE {', '.join(BUSINESS_TABLES)} CASCADE"))
    await db_session.commit()
    await _seed_state(db_session, secret_store, name="replacement", secret="replacement-secret")

    async with db_session.begin():
        result = await restore_validated_backup(
            db_session,
            validated,
            storage=storage,
            secret_store=secret_store,
            progress=_Progress(),
        )

    actual = await _export(db_session, tmp_path / "complete-actual.portfolio-backup", secret_store)
    assert actual.record_counts == expected.record_counts
    assert result.logical_checksum == actual.logical_checksum == expected.logical_checksum
    restored_credentials = list((await db_session.scalars(select(EncryptedSecret))).all())
    plaintext = {
        row.provider: secret_store.decrypt(row.encrypted_value.encode("ascii"))
        for row in restored_credentials
    }
    assert plaintext == {"yahoo": "synthetic-secret-never-leak"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["safety_backup", "delete", "insert", "encrypt", "verify"])
async def test_restore_failure_preserves_original_state(db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    storage = _storage(tmp_path)
    await _seed_state(db_session, secret_store, name="target", secret="target-secret")
    target_path = tmp_path / "target.portfolio-backup"
    await _export(db_session, target_path, secret_store)
    validated = validate_backup(target_path, path_id="upload:test", workspace_root=storage.tmp_dir)
    asset = await db_session.get(AssetClass, ASSET_ID); assert asset is not None
    asset.name = "current-before-restore"; await db_session.commit()
    before = await _export(db_session, tmp_path / "before.portfolio-backup", secret_store)
    monkeypatch.setattr(restore_module, "build_export_metadata_from_storage", lambda: _metadata())
    executed = {"delete": 0, "insert": 0}
    real_execute = db_session.execute

    async def tracked_execute(statement, *args, **kwargs):
        result = await real_execute(statement, *args, **kwargs)
        sql = str(statement).lstrip().upper()
        if sql.startswith("DELETE"):
            executed["delete"] += 1
        if sql.startswith("INSERT"):
            executed["insert"] += 1
        return result

    monkeypatch.setattr(db_session, "execute", tracked_execute)

    def fail_at(stage: str) -> None:
        if stage == failure_stage:
            if stage in executed:
                assert executed[stage] >= 1
            raise RuntimeError("injected restore failure")

    monkeypatch.setattr(restore_module, "_restore_checkpoint", fail_at)
    with pytest.raises(BackupRestoreError):
        async with db_session.begin():
            await restore_validated_backup(db_session, validated, storage=storage, secret_store=secret_store, progress=_Progress())

    after = await _export(db_session, tmp_path / "after.portfolio-backup", secret_store)
    assert after.logical_checksum == before.logical_checksum
    assert after.record_counts == before.record_counts
    assert len(storage.list_safety_backups()) == (0 if failure_stage == "safety_backup" else 1)


def test_restore_contract_covers_every_logical_member_once() -> None:
    assert set(restore_module.INSERT_MEMBERS) == set(DATA_MEMBERS)
    assert set(restore_module.DELETE_MEMBERS) == set(DATA_MEMBERS)


@pytest.mark.asyncio
async def test_ordinary_write_waits_until_restore_table_locks_release(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    storage = _storage(tmp_path)
    await _seed_state(db_session, secret_store, name="target", secret="target-secret")
    source = tmp_path / "target.portfolio-backup"
    await _export(db_session, source, secret_store)
    validated = validate_backup(source, path_id="upload:test", workspace_root=storage.tmp_dir)
    original_export = restore_module.export_logical_backup
    locks_held = asyncio.Event()
    release = asyncio.Event()

    async def pause_safety_export(session, destination, **kwargs):
        if str(destination).endswith(".safety.partial"):
            locks_held.set()
            await release.wait()
        return await original_export(session, destination, **kwargs)

    monkeypatch.setattr(restore_module, "export_logical_backup", pause_safety_export)
    monkeypatch.setattr(restore_module, "build_export_metadata_from_storage", lambda: _metadata())

    async def run_restore() -> None:
        async with SessionFactory() as restore_session:
            async with restore_session.begin():
                await restore_validated_backup(
                    restore_session,
                    validated,
                    storage=storage,
                    secret_store=secret_store,
                    progress=_Progress(),
                )

    async def ordinary_write() -> None:
        async with SessionFactory() as writer:
            writer.add(
                AssetClass(
                    id=UUID("10000000-0000-0000-0000-000000000099"),
                    name="concurrent",
                    target_weight=Decimal("0"),
                    display_order=99,
                    is_active=False,
                    notes=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await writer.commit()

    restore_task = asyncio.create_task(run_restore())
    await asyncio.wait_for(locks_held.wait(), timeout=5)
    writer_task = asyncio.create_task(ordinary_write())
    await asyncio.sleep(0.1)
    assert not writer_task.done()
    release.set()
    await asyncio.wait_for(restore_task, timeout=10)
    await asyncio.wait_for(writer_task, timeout=10)


@pytest.mark.asyncio
async def test_cancellation_before_commit_rolls_back_database_and_keeps_safety(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    storage = _storage(tmp_path)
    await _seed_state(db_session, secret_store, name="target", secret="target-secret")
    source = tmp_path / "target.portfolio-backup"
    await _export(db_session, source, secret_store)
    validated = validate_backup(source, path_id="upload:test", workspace_root=storage.tmp_dir)
    asset = await db_session.get(AssetClass, ASSET_ID)
    assert asset is not None
    asset.name = "must-survive-cancellation"
    await db_session.commit()
    before = await _export(db_session, tmp_path / "before-cancel.portfolio-backup", secret_store)
    insertion_started = asyncio.Event()
    never_release = asyncio.Event()

    async def interrupted_insert(*args, **kwargs):
        insertion_started.set()
        await never_release.wait()

    monkeypatch.setattr(restore_module, "_insert_archive", interrupted_insert)
    monkeypatch.setattr(restore_module, "build_export_metadata_from_storage", lambda: _metadata())

    async def run_restore() -> None:
        async with SessionFactory() as restore_session:
            async with restore_session.begin():
                await restore_validated_backup(
                    restore_session,
                    validated,
                    storage=storage,
                    secret_store=secret_store,
                    progress=_Progress(),
                )

    task = asyncio.create_task(run_restore())
    await asyncio.wait_for(insertion_started.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    after = await _export(db_session, tmp_path / "after-cancel.portfolio-backup", secret_store)
    assert after.logical_checksum == before.logical_checksum
    assert len(storage.list_safety_backups()) == 1


@pytest.mark.asyncio
async def test_restoring_oldest_safety_file_delays_retention_until_source_is_consumed(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    storage = _storage(tmp_path, safety_retention=1)
    await _seed_state(db_session, secret_store, name="old-safety", secret="target-secret")
    source_id = storage.new_safety_id()
    source_partial = storage.safety_partial_path(source_id)
    await _export(db_session, source_partial, secret_store)
    storage.publish_safety_backup(source_id, source_partial)
    source_path = storage.safety_path(source_id)
    validated = validate_backup(
        source_path,
        path_id=f"safety:{source_id}",
        workspace_root=storage.tmp_dir,
    )
    asset = await db_session.get(AssetClass, ASSET_ID)
    assert asset is not None
    asset.name = "replacement"
    await db_session.commit()
    monkeypatch.setattr(
        restore_module,
        "build_export_metadata_from_storage",
        lambda: _metadata(),
    )

    async with db_session.begin():
        result = await restore_validated_backup(
            db_session,
            validated,
            storage=storage,
            secret_store=secret_store,
            progress=_Progress(),
        )

    restored = await db_session.get(AssetClass, ASSET_ID)
    assert restored is not None and restored.name == "old-safety"
    assert result.safety_backup_id != source_id
    assert len(storage.list_safety_backups()) == 1


@pytest.mark.asyncio
async def test_nested_json_decimal_round_trip_is_lossless_and_checksum_stable(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    precise = Decimal("0.1234567890123456789012345678")
    source = _validated_source()
    source["data/cost_adjustments.json"][0]["input_summary"] = {
        "precise": precise,
        "nested": [precise],
    }
    archive = tmp_path / "decimal-json.portfolio-backup"
    expected = write_archive(archive, source, _metadata())
    storage = _storage(tmp_path)
    validated = validate_backup(archive, path_id="upload:decimal", workspace_root=storage.tmp_dir)
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    await _seed_state(db_session, secret_store, name="temporary", secret="temporary")
    monkeypatch.setattr(
        restore_module,
        "build_export_metadata_from_storage",
        lambda: _metadata(),
    )

    async with db_session.begin():
        await restore_validated_backup(
            db_session,
            validated,
            storage=storage,
            secret_store=secret_store,
            progress=_Progress(),
        )

    stored = await db_session.scalar(
        text("SELECT input_summary::text FROM cost_adjustments LIMIT 1")
    )
    assert stored is not None
    assert format(precise, "f") in stored
    assert f'"precise": "{precise}"' not in stored
    await db_session.rollback()
    actual = await _export(db_session, tmp_path / "decimal-json-after.portfolio-backup", secret_store)
    assert actual.logical_checksum == expected.logical_checksum


@pytest.mark.asyncio
async def test_sync_archive_work_does_not_block_event_loop(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    await _seed_state(db_session, secret_store, name="heartbeat", secret="heartbeat")
    real_write = export_module.write_archive

    def slow_write(*args, **kwargs):
        time.sleep(0.2)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(export_module, "write_archive", slow_write)
    ticks = 0
    running = True

    async def heartbeat() -> None:
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.005)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        await _export(db_session, tmp_path / "heartbeat.portfolio-backup", secret_store)
    finally:
        running = False
        await heartbeat_task
    assert ticks >= 10


@pytest.mark.asyncio
async def test_restore_hash_validation_publication_and_retention_keep_loop_responsive(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "current-fernet.key")
    storage = _storage(tmp_path)
    await _seed_state(db_session, secret_store, name="responsive", secret="responsive")
    archive = tmp_path / "responsive.portfolio-backup"
    await _export(db_session, archive, secret_store)
    validated = validate_backup(archive, path_id="upload:responsive", workspace_root=storage.tmp_dir)
    real_hash = restore_module._archive_sha256
    real_validate = restore_module.validate_backup
    real_publish = storage.publish_safety_backup
    real_retention = storage.enforce_safety_retention

    def delayed(callable_, *args, **kwargs):
        time.sleep(0.1)
        return callable_(*args, **kwargs)

    monkeypatch.setattr(
        restore_module,
        "_archive_sha256",
        lambda *args, **kwargs: delayed(real_hash, *args, **kwargs),
    )
    monkeypatch.setattr(
        restore_module,
        "validate_backup",
        lambda *args, **kwargs: delayed(real_validate, *args, **kwargs),
    )
    monkeypatch.setattr(
        storage,
        "publish_safety_backup",
        lambda *args, **kwargs: delayed(real_publish, *args, **kwargs),
    )
    monkeypatch.setattr(
        storage,
        "enforce_safety_retention",
        lambda *args, **kwargs: delayed(real_retention, *args, **kwargs),
    )
    monkeypatch.setattr(
        restore_module,
        "build_export_metadata_from_storage",
        lambda: _metadata(),
    )
    ticks = 0
    running = True

    async def heartbeat() -> None:
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.005)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        async with db_session.begin():
            await restore_validated_backup(
                db_session,
                validated,
                storage=storage,
                secret_store=secret_store,
                progress=_Progress(),
            )
    finally:
        running = False
        await heartbeat_task
    assert ticks >= 40
