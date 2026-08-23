from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from starlette.background import BackgroundTask

from app.backups.constants import DATA_MEMBERS, MAX_COMPRESSED_BYTES
from app.backups.contracts import CONTRACTS_BY_MEMBER
from app.db.session import SessionFactory
from app.schemas.backup import (
    BackupCountComparison,
    BackupOperationResponse,
    BackupPreviewResponse,
    SafetyBackupResponse,
    BackupRestoreRequest,
)
from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.services.backup_restore import restore_validated_backup
from app.services.backup_export import export_database_backup
from app.services.backup_operations import BackupOperationManager
from app.services.backup_storage import BackupStorage
from app.services.backup_validation import (
    BackupValidationError,
    RestoreTokenRegistry,
    ValidatedBackup,
    validate_backup,
)
from app.services.errors import ServiceError


router = APIRouter(prefix="/backups", tags=["backups"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _storage(request: Request) -> BackupStorage:
    return request.app.state.backup_storage


def _manager(request: Request) -> BackupOperationManager:
    return request.app.state.backup_operation_manager


def _service_error(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.to_detail())


def _validation_error(exc: BackupValidationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.to_detail())


def _internal_preview_error() -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={"code": "BACKUP_PREVIEW_FAILED", "message": "Backup preview could not be prepared."},
    )


def _resource_error() -> HTTPException:
    return HTTPException(
        status_code=507,
        detail={"code": "BACKUP_RESOURCE_LIMIT", "message": "Backup could not be retained within available resources."},
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _current_record_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    async with SessionFactory() as session:
        for member in DATA_MEMBERS:
            counts[member] = int(
                await session.scalar(
                    select(func.count()).select_from(CONTRACTS_BY_MEMBER[member].model)
                )
                or 0
            )
    return counts


def _preview(
    validated: ValidatedBackup,
    current_counts: dict[str, int],
    token: str,
) -> BackupPreviewResponse:
    comparisons = {
        member: BackupCountComparison(
            backup=validated.record_counts[member],
            current=current_counts[member],
            delta=validated.record_counts[member] - current_counts[member],
        )
        for member in DATA_MEMBERS
    }
    return BackupPreviewResponse(
        exported_at=validated.exported_at,
        source_application_version=validated.source_application_version,
        source_format_version=validated.source_format_version,
        current_format_version=validated.current_format_version,
        record_counts=dict(validated.record_counts),
        current_record_counts=current_counts,
        count_comparison=comparisons,
        warnings=list(validated.warnings),
        credential_categories=list(validated.credential_categories),
        restore_token=token,
        expires_at=validated.expires_at,
    )


def _publish_upload(storage: BackupStorage, partial: Path, destination: Path) -> None:
    os.replace(partial, destination)
    storage._fsync_directory(storage.uploads_dir)


async def _validated_preview(
    storage: BackupStorage,
    path: Path,
    *,
    path_id: str,
) -> BackupPreviewResponse:
    validated = await asyncio.to_thread(
        validate_backup,
        path,
        path_id=path_id,
        workspace_root=storage.tmp_dir,
    )
    current_counts = await _current_record_counts()
    validated = replace(validated, expires_at=_utcnow() + storage.upload_ttl)
    token = await asyncio.to_thread(RestoreTokenRegistry(storage).issue, validated)
    return _preview(validated, current_counts, token)


@router.post("/upload", response_model=BackupPreviewResponse)
async def post_upload(request: Request, response: Response) -> BackupPreviewResponse:
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/octet-stream":
        raise HTTPException(
            status_code=415,
            detail={
                "code": "BACKUP_INCOMPATIBLE",
                "message": "Backup upload must use application/octet-stream.",
            },
        )
    storage = _storage(request)
    upload_id = uuid4()
    partial = storage.tmp_dir / f"{upload_id}.upload.partial"
    destination = storage.uploads_dir / f"{upload_id}.portfolio-backup"
    published = False
    token_issued = False
    try:
        observed = 0
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            async for chunk in request.stream():
                observed += len(chunk)
                if observed > MAX_COMPRESSED_BYTES:
                    raise BackupValidationError(
                        "BACKUP_RESOURCE_LIMIT",
                        "Backup exceeds the configured resource limit.",
                        status_code=413,
                    )
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        validated = await asyncio.to_thread(
            validate_backup,
            partial,
            path_id=f"upload:{upload_id}",
            workspace_root=storage.tmp_dir,
        )
        current_counts = await _current_record_counts()
        validated = replace(validated, expires_at=_utcnow() + storage.upload_ttl)
        await asyncio.to_thread(_publish_upload, storage, partial, destination)
        published = True
        validated = replace(validated, retained_archive_path=destination)
        token = await asyncio.to_thread(RestoreTokenRegistry(storage).issue, validated)
        token_issued = True
        response.headers.update(NO_STORE_HEADERS)
        return _preview(validated, current_counts, token)
    except BackupValidationError as exc:
        raise _validation_error(exc) from exc
    except OSError:
        raise _resource_error() from None
    except HTTPException:
        raise
    except Exception:
        raise _internal_preview_error() from None
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        if published and not token_issued:
            try:
                destination.unlink(missing_ok=True)
                storage._fsync_directory(storage.uploads_dir)
            except OSError:
                pass


@router.post("/export", response_model=BackupOperationResponse, status_code=202)
async def post_export(request: Request) -> BackupOperationResponse:
    storage = _storage(request)
    manager = _manager(request)

    async def run_export(context) -> None:
        await export_database_backup(storage.export_path(context.operation_id))

    try:
        operation = await manager.start("export", run_export)
    except ServiceError as exc:
        raise _service_error(exc) from exc
    return BackupOperationResponse.model_validate(operation)


@router.post("/restore", response_model=BackupOperationResponse, status_code=202)
async def post_restore(
    payload: BackupRestoreRequest,
    request: Request,
) -> BackupOperationResponse:
    if payload.confirmation != "恢复":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "BACKUP_CONFIRMATION_INVALID",
                "message": "Restore confirmation text is invalid.",
            },
        )
    storage = _storage(request)
    manager = _manager(request)
    registry = RestoreTokenRegistry(storage)
    binding_holder = []

    async def consume_token() -> None:
        binding_holder.append(
            await asyncio.to_thread(registry.consume, payload.restore_token)
        )

    async def run_restore(context) -> None:
        binding = binding_holder[0]
        referenced_safety_id: UUID | None = None
        if binding.path_id.startswith("safety:"):
            referenced_safety_id = UUID(binding.path_id.partition(":")[2])
        try:
            validated = await asyncio.to_thread(
                validate_backup,
                binding.retained_archive_path,
                path_id=binding.path_id,
                expires_at=binding.expires_at,
                workspace_root=storage.tmp_dir,
            )
            if validated.archive_sha256 != binding.archive_sha256:
                raise BackupValidationError(
                    "BACKUP_TOKEN_INVALID", "Restore token is invalid."
                )
            settings = get_settings()
            async with SessionFactory() as session:
                async with session.begin():
                    result = await restore_validated_backup(
                        session,
                        validated,
                        storage=storage,
                        secret_store=SecretStore(Path(settings.secret_key_path)),
                        progress=context,
                    )
                    await context.set_safety_backup_id(result.safety_backup_id)
        finally:
            if referenced_safety_id is not None:
                manager.release_safety_backup(referenced_safety_id)

    try:
        operation = await manager.start("restore", run_restore, prepare=consume_token)
    except BackupValidationError as exc:
        raise _validation_error(exc) from exc
    except ServiceError as exc:
        raise _service_error(exc) from exc
    binding = binding_holder[0]
    if binding.path_id.startswith("safety:"):
        manager.reference_safety_backup(UUID(binding.path_id.partition(":")[2]))
    return BackupOperationResponse.model_validate(operation)


@router.get("/operations/{operation_id}", response_model=BackupOperationResponse)
async def get_operation(operation_id: UUID, request: Request) -> BackupOperationResponse:
    try:
        return BackupOperationResponse.model_validate(_manager(request).get(operation_id))
    except ServiceError as exc:
        raise _service_error(exc) from exc


@router.get("/operations/{operation_id}/download", response_class=FileResponse)
async def download_operation(operation_id: UUID, request: Request) -> FileResponse:
    manager = _manager(request)
    try:
        operation = manager.get(operation_id)
    except ServiceError as exc:
        raise _service_error(exc) from exc
    path = _storage(request).export_path(operation_id)
    if operation.status != "succeeded" or not operation.download_ready or not path.is_file():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BACKUP_DOWNLOAD_NOT_READY",
                "message": "Backup download is not available.",
            },
        )
    filename = f"portfolio-backup-{operation.created_at:%Y%m%d-%H%M%S}.portfolio-backup"
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers=NO_STORE_HEADERS,
        background=BackgroundTask(manager.consume_export, operation_id),
    )


@router.get("/safety", response_model=list[SafetyBackupResponse])
async def get_safety_backups(request: Request) -> list[SafetyBackupResponse]:
    return _storage(request).list_safety_backups()


@router.get("/safety/{backup_id}/download", response_class=FileResponse)
async def download_safety_backup(backup_id: UUID, request: Request) -> FileResponse:
    storage = _storage(request)
    path = storage.safety_path(backup_id)
    metadata = next(
        (item for item in storage.list_safety_backups() if item.id == backup_id),
        None,
    )
    if metadata is None or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BACKUP_SAFETY_NOT_FOUND",
                "message": "Safety backup was not found.",
            },
        )
    filename = f"portfolio-safety-{metadata.exported_at:%Y%m%d-%H%M%S}.portfolio-backup"
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers=NO_STORE_HEADERS,
    )


@router.post("/safety/{backup_id}/preview", response_model=BackupPreviewResponse)
async def preview_safety_backup(
    backup_id: UUID,
    request: Request,
    response: Response,
) -> BackupPreviewResponse:
    storage = _storage(request)
    path = storage.safety_path(backup_id)
    try:
        exists = path.is_file()
    except OSError:
        raise _resource_error() from None
    if not exists:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BACKUP_SAFETY_NOT_FOUND",
                "message": "Safety backup was not found.",
            },
        )
    try:
        preview = await _validated_preview(
            storage,
            path,
            path_id=f"safety:{backup_id}",
        )
    except BackupValidationError as exc:
        raise _validation_error(exc) from exc
    except OSError:
        raise _resource_error() from None
    except HTTPException:
        raise
    except Exception:
        raise _internal_preview_error() from None
    response.headers.update(NO_STORE_HEADERS)
    return preview


@router.delete("/safety/{backup_id}", status_code=204)
async def delete_safety_backup(
    backup_id: UUID,
    request: Request,
    confirm: Annotated[Literal["true"], Query()],
) -> Response:
    manager = _manager(request)
    if manager.is_safety_backup_referenced(backup_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BACKUP_SAFETY_IN_USE",
                "message": "Safety backup is referenced by an active operation.",
            },
        )
    if not _storage(request).delete_safety_backup(backup_id):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BACKUP_SAFETY_NOT_FOUND",
                "message": "Safety backup was not found.",
            },
        )
    return Response(status_code=204)
