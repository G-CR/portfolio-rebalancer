from __future__ import annotations

import asyncio
import errno
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
from app.services.backup_validation import BackupValidationError, RestoreTokenRegistry
from app.services.errors import ServiceError


_PUBLIC_BACKUP_FAILURE_MESSAGES = {
    "BACKUP_FUTURE_VERSION": "Backup format is newer than this application.",
    "BACKUP_INCOMPATIBLE": "Backup data does not match the supported format.",
    "BACKUP_RELATIONSHIP_INVALID": "Backup relationships are inconsistent.",
    "BACKUP_RESOURCE_LIMIT": "Backup could not be retained within available resources.",
    "BACKUP_TOKEN_INVALID": "Restore token is invalid.",
    "BACKUP_TOKEN_EXPIRED": "Restore token has expired.",
    "BACKUP_PREVIEW_FAILED": "Backup preview could not be prepared.",
    "BACKUP_OPERATION_CONFLICT": "Another backup operation is already active.",
}


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

    async def set_safety_backup_id(self, backup_id: UUID) -> None:
        self._manager.set_safety_backup_id(self.operation_id, backup_id)


OperationRunner = Callable[[BackupOperationContext], Awaitable[object]]
OperationPrepare = Callable[[], Awaitable[None] | None]
Clock = Callable[[], datetime]


class BackupOperationManager:
    def __init__(
        self,
        storage: BackupStorage,
        *,
        cleanup_interval_seconds: float = 60,
        clock: Clock | None = None,
    ) -> None:
        self.storage = storage
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._operation_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._active_operation_id: UUID | None = None
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_wakeup = asyncio.Event()
        self._referenced_safety_ids: set[UUID] = set()
        self._stopping = False
        self._stopped = False
        self._stopped_event = asyncio.Event()

    async def start(
        self,
        kind: OperationKind,
        runner: OperationRunner,
        *,
        prepare: OperationPrepare | None = None,
    ) -> BackupOperation:
        async with self._state_lock:
            if self._stopping or self._stopped or self._active_operation_id is not None:
                raise BackupOperationConflict()
            if prepare is not None:
                preparation = prepare()
                if preparation is not None:
                    await preparation
            operation = BackupOperation.new(kind, now=self._clock())
            self.storage.write_operation(operation)
            self._active_operation_id = operation.id
        task = asyncio.create_task(self._run(operation, runner))
        self._tasks[operation.id] = task
        task.add_done_callback(
            lambda completed, operation_id=operation.id: self._remove_task(
                operation_id, completed
            )
        )
        return operation

    def get(self, operation_id: UUID) -> BackupOperation:
        operation = self._read_operation(operation_id)
        return self._reconcile_export_readiness(
            operation,
            now=self._clock(),
            retry_expired_artifact=False,
        )

    def _read_operation(self, operation_id: UUID) -> BackupOperation:
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
            update={"stage": stage, "updated_at": self._clock()}
        )
        self.storage.write_operation(operation)
        return operation

    def set_safety_backup_id(
        self, operation_id: UUID, backup_id: UUID
    ) -> BackupOperation:
        operation = self.get(operation_id).model_copy(
            update={"safety_backup_id": backup_id, "updated_at": self._clock()}
        )
        self.storage.write_operation(operation)
        return operation

    def recover(self) -> None:
        completed_exports: set[UUID] = set()
        now = self._clock()
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
                        "updated_at": now,
                    }
                )
                self.storage.write_operation(interrupted)
                self.storage.delete_export(operation.id)
            elif operation.kind == "export" and operation.status == "succeeded":
                operation = self._reconcile_export_readiness(
                    operation,
                    now=now,
                    retry_expired_artifact=True,
                )
                if operation.download_ready or self.storage.export_path(operation.id).is_file():
                    completed_exports.add(operation.id)
        self.storage.cleanup_orphans(valid_export_ids=completed_exports)
        self.cleanup_expired(now=now)
        self.storage.enforce_safety_retention()

    def cleanup_expired(self, *, now: datetime | None = None) -> bool:
        timestamp = now or self._clock()
        maintenance_failed = False
        try:
            operations = self.storage.list_operations()
        except Exception:
            return True
        for operation in operations:
            if operation.kind != "export" or operation.status != "succeeded":
                continue
            try:
                self._reconcile_export_readiness(
                    operation,
                    now=timestamp,
                    retry_expired_artifact=True,
                )
            except Exception:
                maintenance_failed = True
        try:
            if RestoreTokenRegistry(
                self.storage,
                clock=lambda: timestamp,
            ).cleanup_expired():
                maintenance_failed = True
        except Exception:
            maintenance_failed = True
        return maintenance_failed

    def consume_export(self, operation_id: UUID) -> None:
        operation = self._read_operation(operation_id)
        self.storage.delete_export(operation_id)
        if operation.download_ready:
            self.storage.write_operation(
                operation.model_copy(
                    update={
                        "download_ready": False,
                        "updated_at": self._clock(),
                    }
                )
            )

    def reference_safety_backup(self, backup_id: UUID) -> None:
        self._referenced_safety_ids.add(backup_id)

    def release_safety_backup(self, backup_id: UUID) -> None:
        self._referenced_safety_ids.discard(backup_id)

    def is_safety_backup_referenced(self, backup_id: UUID) -> bool:
        return (
            backup_id in self._referenced_safety_ids
            or self.storage.is_safety_backup_leased(backup_id)
        )

    def start_cleanup(self) -> None:
        if self._cleanup_task is None and not self._stopping and not self._stopped:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        async with self._state_lock:
            if self._stopped:
                return
            if self._stopping:
                wait_for_stop = True
                cleanup_task = None
                operation_tasks: list[tuple[UUID, asyncio.Task[None]]] = []
            else:
                wait_for_stop = False
                self._stopping = True
                cleanup_task = self._cleanup_task
                self._cleanup_task = None
                operation_tasks = list(self._tasks.items())
        if wait_for_stop:
            await self._stopped_event.wait()
            return

        self._cleanup_wakeup.set()
        if cleanup_task is not None:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        for _, task in operation_tasks:
            task.cancel()
        if operation_tasks:
            await asyncio.gather(
                *(task for _, task in operation_tasks),
                return_exceptions=True,
            )
        async with self._state_lock:
            for operation_id, _ in operation_tasks:
                try:
                    self._mark_interrupted(operation_id)
                except Exception:
                    pass
            if self._active_operation_id is not None:
                try:
                    self._mark_interrupted(self._active_operation_id)
                except Exception:
                    pass
            self._active_operation_id = None
            self._tasks.clear()
            self._stopped = True
            self._stopping = False
            self._stopped_event.set()

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
                        "updated_at": self._clock(),
                    }
                )
                self.storage.write_operation(operation)
                await runner(BackupOperationContext(self, operation.id))
                if operation.kind == "export":
                    self.storage.secure_file(self.storage.export_path(operation.id))
                completed_at = self._clock()
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
                self._cleanup_wakeup.set()
        except asyncio.CancelledError:
            self._mark_interrupted(operation.id)
            raise
        except BaseException as exc:
            self.storage.delete_export(operation.id)
            failed = self.get(operation.id).model_copy(
                update={
                    "status": "failed",
                    "error": self._failure_for(operation.kind, exc),
                    "download_ready": False,
                    "updated_at": self._clock(),
                }
            )
            self.storage.write_operation(failed)
        finally:
            async with self._state_lock:
                if self._active_operation_id == operation.id:
                    self._active_operation_id = None

    def _mark_interrupted(self, operation_id: UUID) -> None:
        operation = self._read_operation(operation_id)
        if operation.status not in {"pending", "running"}:
            return
        self.storage.delete_export(operation_id)
        operation = operation.model_copy(
            update={
                "status": "interrupted",
                "error": BackupError(
                    code="BACKUP_INTERRUPTED",
                    message="Backup operation was interrupted.",
                ),
                "download_ready": False,
                "updated_at": self._clock(),
            }
        )
        self.storage.write_operation(operation)

    @staticmethod
    def _failure_for(kind: OperationKind, exc: BaseException) -> BackupError:
        if isinstance(exc, (BackupValidationError, ServiceError)):
            public_message = _PUBLIC_BACKUP_FAILURE_MESSAGES.get(exc.code)
            if public_message is not None:
                return BackupError(code=exc.code, message=public_message)
        if isinstance(exc, OSError) and exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            return BackupError(
                code="BACKUP_RESOURCE_LIMIT",
                message="Backup could not be retained because storage space is insufficient.",
            )
        if kind == "restore":
            return BackupError(code="BACKUP_ROLLBACK", message="Backup restore was rolled back.")
        return BackupError(code="BACKUP_EXPORT_FAILED", message="Backup export failed.")

    async def _cleanup_loop(self) -> None:
        while True:
            self._cleanup_wakeup.clear()
            try:
                maintenance_failed = bool(self.cleanup_expired())
            except Exception:
                maintenance_failed = True
            retention_debt = False
            try:
                if self.storage.has_safety_retention_debt():
                    await asyncio.to_thread(self.storage.enforce_safety_retention)
                    retention_debt = self.storage.has_safety_retention_debt()
            except Exception:
                maintenance_failed = True
                retention_debt = True
            if maintenance_failed or retention_debt:
                timeout = self.cleanup_interval_seconds
            else:
                try:
                    timeout = self._seconds_until_next_expiry()
                except Exception:
                    timeout = self.cleanup_interval_seconds
            try:
                await asyncio.wait_for(self._cleanup_wakeup.wait(), timeout=timeout)
            except TimeoutError:
                pass

    def _reconcile_export_readiness(
        self,
        operation: BackupOperation,
        *,
        now: datetime,
        retry_expired_artifact: bool,
    ) -> BackupOperation:
        if (
            operation.kind != "export"
            or operation.status != "succeeded"
        ):
            return operation
        path = self.storage.export_path(operation.id)
        path_exists = path.is_file()
        expired = operation.expires_at is not None and operation.expires_at <= now
        reconciled = operation
        if operation.download_ready and (not path_exists or expired):
            reconciled = operation.model_copy(
                update={"download_ready": False, "updated_at": now}
            )
            self.storage.write_operation(reconciled)
        if expired and path_exists and (operation.download_ready or retry_expired_artifact):
            try:
                self.storage.delete_export(operation.id)
            except OSError:
                pass
        return reconciled

    def _seconds_until_next_expiry(self) -> float:
        deadlines = [
            operation.expires_at
            for operation in self.storage.list_operations()
            if operation.kind == "export"
            and operation.status == "succeeded"
            and operation.download_ready
            and operation.expires_at is not None
        ]
        if not deadlines:
            return self.cleanup_interval_seconds
        return max(0.0, min((deadline - self._clock()).total_seconds() for deadline in deadlines))

    def _remove_task(self, operation_id: UUID, completed: asyncio.Task[None]) -> None:
        if self._tasks.get(operation_id) is completed:
            self._tasks.pop(operation_id, None)
