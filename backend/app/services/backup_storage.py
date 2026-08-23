from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.backups.archive import inspect_archive
from app.schemas.backup import BackupOperation, SafetyBackupResponse


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class BackupSourceLease:
    def __init__(self, storage: BackupStorage, path_id: str) -> None:
        self._storage = storage
        self.path_id = path_id
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._storage._release_source_lease(self.path_id)


class BackupStorage:
    def __init__(
        self,
        root: Path,
        *,
        export_ttl: timedelta = timedelta(minutes=30),
        upload_ttl: timedelta = timedelta(minutes=30),
        safety_retention: int = 5,
    ) -> None:
        self.root = Path(root)
        self.export_ttl = export_ttl
        self.upload_ttl = upload_ttl
        self.safety_retention = safety_retention
        self.operations_dir = self.root / "operations"
        self.exports_dir = self.root / "exports"
        self.uploads_dir = self.root / "uploads"
        self.safety_dir = self.root / "safety"
        self.tmp_dir = self.root / "tmp"
        self._source_lease_lock = threading.Lock()
        self._source_leases: dict[str, int] = {}

    def acquire_source_lease(self, path_id: str) -> BackupSourceLease:
        with self._source_lease_lock:
            self._source_leases[path_id] = self._source_leases.get(path_id, 0) + 1
        return BackupSourceLease(self, path_id)

    def _release_source_lease(self, path_id: str) -> None:
        with self._source_lease_lock:
            count = self._source_leases.get(path_id, 0)
            if count <= 1:
                self._source_leases.pop(path_id, None)
            else:
                self._source_leases[path_id] = count - 1

    def is_source_leased(self, path_id: str) -> bool:
        with self._source_lease_lock:
            return self._source_leases.get(path_id, 0) > 0

    def is_safety_backup_leased(self, backup_id: UUID) -> bool:
        return self.is_source_leased(f"safety:{backup_id}")

    def initialize(self) -> None:
        for directory in (
            self.root,
            self.operations_dir,
            self.exports_dir,
            self.uploads_dir,
            self.safety_dir,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
            directory.chmod(PRIVATE_DIRECTORY_MODE)
        self.enforce_safety_retention()

    def operation_journal_path(self, operation_id: UUID) -> Path:
        return self.operations_dir / f"{operation_id}.json"

    def export_path(self, operation_id: UUID) -> Path:
        return self.exports_dir / f"{operation_id}.portfolio-backup"

    def safety_path(self, backup_id: UUID) -> Path:
        return self.safety_dir / f"{backup_id}.portfolio-backup"

    def safety_partial_path(self, backup_id: UUID) -> Path:
        return self.tmp_dir / f"{backup_id}.safety.partial"

    @staticmethod
    def new_safety_id() -> UUID:
        return uuid4()

    def write_operation(self, operation: BackupOperation) -> None:
        payload = operation.model_dump_json().encode("utf-8")
        self._atomic_write(self.operation_journal_path(operation.id), payload)

    def read_operation(self, operation_id: UUID) -> BackupOperation | None:
        path = self.operation_journal_path(operation_id)
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return None
        return BackupOperation.model_validate_json(payload)

    def list_operations(self) -> list[BackupOperation]:
        operations: list[BackupOperation] = []
        for path in sorted(self.operations_dir.glob("*.json")):
            try:
                operations.append(BackupOperation.model_validate_json(path.read_bytes()))
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
        return operations

    def secure_file(self, path: Path) -> None:
        path.chmod(PRIVATE_FILE_MODE)
        self._fsync_file(path)
        self._fsync_directory(path.parent)

    def delete_export(self, operation_id: UUID) -> None:
        self.export_path(operation_id).unlink(missing_ok=True)

    def publish_safety_backup(
        self,
        backup_id: UUID,
        partial_path: Path,
        *,
        enforce_retention: bool = True,
    ) -> SafetyBackupResponse:
        partial_path = Path(partial_path)
        expected_partial = self.safety_partial_path(backup_id)
        if partial_path != expected_partial:
            raise ValueError("safety backup partial path is invalid")
        destination = self.safety_path(backup_id)
        try:
            metadata = self._inspect_safety(backup_id, partial_path)
            self.secure_file(partial_path)
            os.replace(partial_path, destination)
            destination.chmod(PRIVATE_FILE_MODE)
            self._fsync_directory(self.safety_dir)
        except BaseException:
            partial_path.unlink(missing_ok=True)
            raise
        if enforce_retention:
            self.enforce_safety_retention()
        return metadata

    def list_safety_backups(self) -> list[SafetyBackupResponse]:
        backups: list[SafetyBackupResponse] = []
        for path in self.safety_dir.glob("*.portfolio-backup"):
            try:
                backup_id = UUID(path.stem)
                backups.append(self._inspect_safety(backup_id, path))
            except (OSError, ValueError):
                continue
            except Exception:
                continue
        return sorted(backups, key=lambda backup: (backup.exported_at, str(backup.id)), reverse=True)

    def delete_safety_backup(self, backup_id: UUID) -> bool:
        path = self.safety_path(backup_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        self._fsync_directory(self.safety_dir)
        return True

    def cleanup_orphans(self, *, valid_export_ids: set[UUID] | None = None) -> None:
        for directory in (self.tmp_dir, self.exports_dir, self.uploads_dir):
            for pattern in ("*.partial", "*.complete", ".*.partial", ".*.complete"):
                for path in directory.glob(pattern):
                    path.unlink(missing_ok=True)
        if valid_export_ids is not None:
            for path in self.exports_dir.glob("*.portfolio-backup"):
                try:
                    operation_id = UUID(path.stem)
                except ValueError:
                    path.unlink(missing_ok=True)
                    continue
                if operation_id not in valid_export_ids:
                    path.unlink(missing_ok=True)

    def _inspect_safety(self, backup_id: UUID, path: Path) -> SafetyBackupResponse:
        with inspect_archive(path) as inspected:
            return SafetyBackupResponse(
                id=backup_id,
                exported_at=datetime.fromisoformat(inspected.manifest.exported_at),
                source_application_version=inspected.manifest.source_application_version,
                format_version=inspected.manifest.format_version,
                size_bytes=inspected.compressed_size,
                record_counts=dict(inspected.manifest.record_counts),
            )

    def enforce_safety_retention(self) -> None:
        try:
            backups = self.list_safety_backups()
        except Exception:
            return
        for expired in backups[self.safety_retention :]:
            if self.is_safety_backup_leased(expired.id):
                continue
            try:
                self.delete_safety_backup(expired.id)
            except Exception:
                continue

    def has_safety_retention_debt(self) -> bool:
        candidate_count = 0
        for path in self.safety_dir.glob("*.portfolio-backup"):
            try:
                UUID(path.stem)
            except ValueError:
                continue
            candidate_count += 1
            if candidate_count > self.safety_retention:
                return True
        return False

    def _atomic_write(self, destination: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".partial",
                dir=self.tmp_dir,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.chmod(temporary_path, PRIVATE_FILE_MODE)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            destination.chmod(PRIVATE_FILE_MODE)
            self._fsync_directory(destination.parent)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("rb") as source:
            os.fsync(source.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
