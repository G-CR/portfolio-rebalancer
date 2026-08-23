from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.api.routes import backups as backup_routes
from app.backups.archive import ArchiveMetadata, write_archive
from app.backups.constants import DATA_MEMBERS
from app.main import app
from app.schemas.backup import BackupOperation, BackupStage


async def _poll_terminal(api_client, operation_id: str) -> dict[str, object]:
    for _ in range(200):
        response = await api_client.get(f"/api/backups/operations/{operation_id}")
        assert response.status_code == 200
        document = response.json()
        if document["status"] in {"succeeded", "failed", "interrupted"}:
            return document
        await asyncio.sleep(0.01)
    raise AssertionError("backup operation did not finish")


async def test_export_operation_can_be_polled_and_downloaded_without_caching(api_client) -> None:
    started = await api_client.post("/api/backups/export")

    assert started.status_code == 202
    operation = started.json()
    assert set(operation) >= {
        "id",
        "kind",
        "status",
        "stage",
        "error",
        "download_ready",
    }
    assert operation["kind"] == "export"

    completed = await _poll_terminal(api_client, operation["id"])
    assert completed["status"] == "succeeded"
    assert completed["download_ready"] is True

    downloaded = await api_client.get(
        f"/api/backups/operations/{operation['id']}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"].startswith(
        'attachment; filename="portfolio-backup-'
    )
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["pragma"] == "no-cache"
    assert downloaded.content.startswith(b"PK")

    unavailable = await api_client.get(
        f"/api/backups/operations/{operation['id']}/download"
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "BACKUP_DOWNLOAD_NOT_READY"


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(microseconds=1)])
async def test_export_download_rejects_exactly_at_and_after_expiry(
    api_client, monkeypatch, offset: timedelta
) -> None:
    storage = app.state.backup_storage
    manager = app.state.backup_operation_manager
    deadline = datetime(2026, 8, 24, tzinfo=timezone.utc)
    operation = BackupOperation.new("export", now=deadline - timedelta(minutes=30)).model_copy(
        update={
            "status": "succeeded",
            "stage": BackupStage.COMPLETED,
            "download_ready": True,
            "expires_at": deadline,
        }
    )
    storage.write_operation(operation)
    storage.export_path(operation.id).write_bytes(b"sensitive archive")
    monkeypatch.setattr(manager, "_clock", lambda: deadline + offset)

    response = await api_client.get(f"/api/backups/operations/{operation.id}/download")
    polled = await api_client.get(f"/api/backups/operations/{operation.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "BACKUP_DOWNLOAD_NOT_READY"
    assert polled.status_code == 200
    assert polled.json()["status"] == "succeeded"
    assert polled.json()["download_ready"] is False
    assert not storage.export_path(operation.id).exists()


async def test_recovery_reconciles_crash_window_missing_export(api_client) -> None:
    storage = app.state.backup_storage
    manager = app.state.backup_operation_manager
    operation = BackupOperation.new("export").model_copy(
        update={
            "status": "succeeded",
            "stage": BackupStage.COMPLETED,
            "download_ready": True,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
    )
    storage.write_operation(operation)

    manager.recover()

    polled = await api_client.get(f"/api/backups/operations/{operation.id}")
    downloaded = await api_client.get(f"/api/backups/operations/{operation.id}/download")
    assert polled.status_code == 200
    assert polled.json()["status"] == "succeeded"
    assert polled.json()["download_ready"] is False
    assert downloaded.status_code == 409
    assert downloaded.json()["detail"]["code"] == "BACKUP_DOWNLOAD_NOT_READY"


async def test_concurrent_export_returns_sanitized_conflict(api_client, monkeypatch) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_export(destination: Path):
        entered.set()
        await release.wait()
        destination.write_bytes(b"archive")

    monkeypatch.setattr(backup_routes, "export_database_backup", blocked_export)
    first = await api_client.post("/api/backups/export")
    await entered.wait()

    second = await api_client.post("/api/backups/export")
    assert second.status_code == 409
    assert second.json() == {
        "detail": {
            "code": "BACKUP_OPERATION_CONFLICT",
            "message": "Another backup operation is already active.",
        }
    }

    release.set()
    await _poll_terminal(api_client, first.json()["id"])


async def test_safety_list_download_and_explicit_delete_confirmation(api_client) -> None:
    storage = app.state.backup_storage
    backup_id = storage.new_safety_id()
    partial = storage.safety_partial_path(backup_id)
    write_archive(
        partial,
        {member: [] for member in DATA_MEMBERS},
        ArchiveMetadata(
            source_application_version="api-test",
            exported_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            display_timezone="Asia/Shanghai",
        ),
    )
    storage.publish_safety_backup(backup_id, partial)

    listed = await api_client.get("/api/backups/safety")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": str(backup_id),
            "exported_at": "2026-08-23T00:00:00Z",
            "source_application_version": "api-test",
            "format_version": 1,
            "size_bytes": storage.safety_path(backup_id).stat().st_size,
            "record_counts": {member: 0 for member in DATA_MEMBERS},
        }
    ]

    downloaded = await api_client.get(f"/api/backups/safety/{backup_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["pragma"] == "no-cache"
    assert downloaded.headers["content-disposition"].startswith("attachment;")

    missing_confirmation = await api_client.delete(f"/api/backups/safety/{backup_id}")
    assert missing_confirmation.status_code == 422
    wrong_confirmation = await api_client.delete(
        f"/api/backups/safety/{backup_id}", params={"confirm": "yes"}
    )
    assert wrong_confirmation.status_code == 422
    assert storage.safety_path(backup_id).exists()

    deleted = await api_client.delete(
        f"/api/backups/safety/{backup_id}", params={"confirm": "true"}
    )
    assert deleted.status_code == 204
    assert not storage.safety_path(backup_id).exists()


async def test_safety_delete_rejects_item_referenced_by_active_operation(api_client) -> None:
    storage = app.state.backup_storage
    manager = app.state.backup_operation_manager
    backup_id = storage.new_safety_id()
    partial = storage.safety_partial_path(backup_id)
    write_archive(
        partial,
        {member: [] for member in DATA_MEMBERS},
        ArchiveMetadata(
            source_application_version="api-test",
            exported_at=datetime.now(timezone.utc),
            display_timezone="Asia/Shanghai",
        ),
    )
    storage.publish_safety_backup(backup_id, partial)
    manager.reference_safety_backup(backup_id)

    response = await api_client.delete(
        f"/api/backups/safety/{backup_id}", params={"confirm": "true"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "BACKUP_SAFETY_IN_USE"
    assert storage.safety_path(backup_id).exists()
    manager.release_safety_backup(backup_id)


async def test_backup_errors_do_not_expose_raw_exception_or_paths(api_client, monkeypatch) -> None:
    secret = "synthetic-secret-value"

    async def failed_export(_destination: Path):
        raise RuntimeError(f"{secret} at /var/lib/private SELECT password")

    monkeypatch.setattr(backup_routes, "export_database_backup", failed_export)
    started = await api_client.post("/api/backups/export")
    operation = await _poll_terminal(api_client, started.json()["id"])
    serialized = str(operation)

    assert operation["error"] == {
        "code": "BACKUP_EXPORT_FAILED",
        "message": "Backup export failed.",
    }
    assert secret not in serialized
    assert "/var/lib" not in serialized
    assert "SELECT" not in serialized
