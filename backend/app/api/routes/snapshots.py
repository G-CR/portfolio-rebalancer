from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.snapshot import (
    ManualSnapshotRequest,
    SnapshotCollectionResponse,
    SnapshotDetailResponse,
    SnapshotType,
)
from app.services.errors import ServiceError
from app.services.snapshots import create_manual_snapshot, get_snapshot_detail, list_snapshots

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.get("", response_model=SnapshotCollectionResponse)
async def get_snapshots(
    snapshot_type: SnapshotType | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    asset_class: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> SnapshotCollectionResponse:
    return await list_snapshots(
        session,
        snapshot_type=snapshot_type,
        from_date=from_date,
        to_date=to_date,
        asset_class=asset_class,
        page=page,
        page_size=page_size,
    )


@router.get("/{snapshot_id}", response_model=SnapshotDetailResponse)
async def get_snapshot(
    snapshot_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> SnapshotDetailResponse:
    return await _service_call(lambda: get_snapshot_detail(session, snapshot_id))


@router.post("/manual", response_model=SnapshotDetailResponse, status_code=201)
async def post_manual_snapshot(
    payload: ManualSnapshotRequest,
    session: AsyncSession = Depends(get_session),
) -> SnapshotDetailResponse:
    try:
        async with session.begin():
            return await create_manual_snapshot(session, note=payload.note)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "SNAPSHOT_STORAGE_ERROR", "message": "Snapshot storage operation failed."},
        ) from exc


async def _service_call(operation):
    try:
        return await operation()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
