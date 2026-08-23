from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import UUID

from app.schemas.backup import (
    BackupError,
    BackupOperation,
    BackupStage,
    OperationKind,
)
from app.services.backup_storage import BackupStorage
from app.services.errors import ServiceError


class BackupOperationConflict(ServiceError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="BACKUP_OPERATION_CONFLICT",
            message="Another backup operation is already active.",
        )


class BackupOperationContext:
    def __init__(self, manager: BackupOperationManager, operation_id: UUID) -> None:
        self.operation_id = operation_id
        self._manager = manager

    async def set_stage(self, stage: BackupStage) -> None:
        self._manager.set_stage(self.operation_id, stage)


OperationRunner = Callable[[BackupOperationContext], Awaitable[object]]


class BackupOperationManager:
    def __init__(self, storage: BackupStorage, *, cleanup_interval_seconds: float = 60) -> None:
        self.storage = storage
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self._operation_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._active_operation_id: UUID | None = None
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._referenced_safety_ids: set[UUID] = set()

    async def start(self, kind: OperationKind, runner: OperationRunner) -> BackupOperation:
        async with self._state_lock:
            if self._active_operation_id is not None:
                raise BackupOperationConflict()
            operation = BackupOperation.new(kind)
            self.storage.write_operation(operation)
            self._active_operation_id = operation.id
        self._tasks[operation.id] = asyncio.create_task(self._run(operation, runner))
        return operation

    def get(self, operation_id: UUID) -> BackupOperation:
        operation = self.storage.read_operation(operation_id)
        if operation is None:
            raise ServiceError(
                status_code=404,
                code="BACKUP_OPERATION_NOT_FOUND",
                message="Backup operation was not found.",
            )
        return operation

    async def wait(self, operation_id: UUID) -> None:
        task = self._tasks.get(operation_id)
        if task is not None:
            await asyncio.shield(task)

    def set_stage(self, operation_id: UUID, stage: BackupStage) -> BackupOperation:
        operation = self.get(operation_id).model_copy(
            update={"stage": stage, "updated_at": datetime.now(timezone.utc)}
        )
        self.storage.write_operation(operation)
        return operation

    def recover(self) -> None:
        completed_exports: set[UUID] = set()
        for operation in self.storage.list_operations():
            if operation.status in {"pending", "running"}:
                interrupted = operation.model_copy(
                    update={
                        "status": "interrupted",
                        "error": BackupError(
                            code="BACKUP_INTERRUPTED",
                            message="Backup operation was interrupted.",
                        ),
                        "download_ready": False,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                self.storage.write_operation(interrupted)
                self.storage.delete_export(operation.id)
            elif operation.kind == "export" and operation.status == "succeeded" and operation.download_ready:
                completed_exports.add(operation.id)
        self.storage.cleanup_orphans(valid_export_ids=completed_exports)
        self.cleanup_expired()

    def cleanup_expired(self, *, now: datetime | None = None) -> None:
        timestamp = now or datetime.now(timezone.utc)
        for operation in self.storage.list_operations():
            if (
                operation.kind == "export"
                and operation.status == "succeeded"
                and operation.expires_at is not None
                and operation.expires_at <= timestamp
            ):
                self.storage.delete_export(operation.id)
                if operation.download_ready:
                    self.storage.write_operation(
                        operation.model_copy(
                            update={"download_ready": False, "updated_at": timestamp}
                        )
                    )

    def consume_export(self, operation_id: UUID) -> None:
        operation = self.get(operation_id)
        self.storage.delete_export(operation_id)
        if operation.download_ready:
            self.storage.write_operation(
                operation.model_copy(
                    update={
                        "download_ready": False,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            )

    def reference_safety_backup(self, backup_id: UUID) -> None:
        self._referenced_safety_ids.add(backup_id)

    def release_safety_backup(self, backup_id: UUID) -> None:
        self._referenced_safety_ids.discard(backup_id)

    def is_safety_backup_referenced(self, backup_id: UUID) -> bool:
        return backup_id in self._referenced_safety_ids

    def start_cleanup(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        active_tasks = [task for task in self._tasks.values() if not task.done()]
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

    async def _run(self, operation: BackupOperation, runner: OperationRunner) -> None:
        try:
            async with self._operation_lock:
                running_stage = (
                    BackupStage.WRITING_DATA
                    if operation.kind == "export"
                    else BackupStage.VALIDATED
                )
                operation = operation.model_copy(
                    update={
                        "status": "running",
                        "stage": running_stage,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                self.storage.write_operation(operation)
                await runner(BackupOperationContext(self, operation.id))
                if operation.kind == "export":
                    self.storage.secure_file(self.storage.export_path(operation.id))
                completed_at = datetime.now(timezone.utc)
                operation = self.get(operation.id).model_copy(
                    update={
                        "status": "succeeded",
                        "stage": BackupStage.COMPLETED,
                        "error": None,
                        "download_ready": operation.kind == "export",
                        "updated_at": completed_at,
                        "expires_at": (
                            completed_at + self.storage.export_ttl
                            if operation.kind == "export"
                            else None
                        ),
                    }
                )
                self.storage.write_operation(operation)
        except asyncio.CancelledError:
            self._mark_interrupted(operation.id)
            raise
        except BaseException:
            self.storage.delete_export(operation.id)
            failed = self.get(operation.id).model_copy(
                update={
                    "status": "failed",
                    "error": self._failure_for(operation.kind),
                    "download_ready": False,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.storage.write_operation(failed)
        finally:
            async with self._state_lock:
                if self._active_operation_id == operation.id:
                    self._active_operation_id = None

    def _mark_interrupted(self, operation_id: UUID) -> None:
        self.storage.delete_export(operation_id)
        operation = self.get(operation_id).model_copy(
            update={
                "status": "interrupted",
                "error": BackupError(
                    code="BACKUP_INTERRUPTED",
                    message="Backup operation was interrupted.",
                ),
                "download_ready": False,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.storage.write_operation(operation)

    @staticmethod
    def _failure_for(kind: OperationKind) -> BackupError:
        if kind == "restore":
            return BackupError(code="BACKUP_ROLLBACK", message="Backup restore was rolled back.")
        return BackupError(code="BACKUP_EXPORT_FAILED", message="Backup export failed.")

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval_seconds)
            self.cleanup_expired()
