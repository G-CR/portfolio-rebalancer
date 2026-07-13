from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.asset_class import AssetClassResponse, AssetClassUpdate
from app.services.asset_classes import list_asset_classes, replace_asset_classes
from app.services.errors import ServiceError

router = APIRouter(tags=["asset-classes"])


@router.get("/asset-classes", response_model=list[AssetClassResponse])
async def get_asset_classes(
    session: AsyncSession = Depends(get_session),
) -> list[AssetClassResponse]:
    return await list_asset_classes(session)


@router.put("/asset-classes", response_model=list[AssetClassResponse])
async def put_asset_classes(
    payload: list[AssetClassUpdate],
    session: AsyncSession = Depends(get_session),
) -> list[AssetClassResponse]:
    try:
        async with session.begin():
            return await replace_asset_classes(session, payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
