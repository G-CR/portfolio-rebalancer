from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.schemas.backup import BackupOperationResponse, SafetyBackupResponse
from app.services.backup_export import export_database_backup
from app.services.backup_operations import BackupOperationManager
from app.services.backup_storage import BackupStorage
from app.services.errors import ServiceError


router = APIRouter(prefix="/backups", tags=["backups"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _storage(request: Request) -> BackupStorage:
    return request.app.state.backup_storage


def _manager(request: Request) -> BackupOperationManager:
    return request.app.state.backup_operation_manager


def _service_error(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.to_detail())


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
