from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.db.session import get_session
from app.schemas.cost_adjustment import (
    CostAdjustmentCollectionResponse,
    CostAdjustmentConfirmRequest,
    CostAdjustmentPreviewResponse,
    ManualCorrectionPreviewRequest,
    PurchasePreviewRequest,
    RestorePreviewRequest,
    SellPreviewRequest,
)
from app.services.cost_adjustments import (
    confirm_adjustment,
    get_adjustment_context,
    preview_correction,
    preview_purchase,
    preview_restore,
    preview_sell,
)
from app.services.errors import ServiceError

router = APIRouter(tags=["cost-adjustments"])


@router.get(
    "/cost-adjustments/{holding_id}",
    response_model=CostAdjustmentCollectionResponse,
)
async def get_cost_adjustments(
    holding_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CostAdjustmentCollectionResponse:
    try:
        return await get_adjustment_context(session, holding_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.post(
    "/cost-adjustments/{holding_id}/preview-purchase",
    response_model=CostAdjustmentPreviewResponse,
)
async def post_preview_purchase(
    holding_id: UUID,
    payload: PurchasePreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> CostAdjustmentPreviewResponse:
    try:
        return await preview_purchase(session, holding_id, payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.post(
    "/cost-adjustments/{holding_id}/preview-sell",
    response_model=CostAdjustmentPreviewResponse,
)
async def post_preview_sell(
    holding_id: UUID,
    payload: SellPreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> CostAdjustmentPreviewResponse:
    try:
        return await preview_sell(session, holding_id, payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.post(
    "/cost-adjustments/{holding_id}/preview-correction",
    response_model=CostAdjustmentPreviewResponse,
)
async def post_preview_correction(
    holding_id: UUID,
    payload: ManualCorrectionPreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> CostAdjustmentPreviewResponse:
    try:
        return await preview_correction(session, holding_id, payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.post(
    "/cost-adjustments/{holding_id}/preview-restore/{adjustment_id}",
    response_model=CostAdjustmentPreviewResponse,
)
async def post_preview_restore(
    holding_id: UUID,
    adjustment_id: UUID,
    payload: RestorePreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> CostAdjustmentPreviewResponse:
    try:
        return await preview_restore(session, holding_id, adjustment_id, payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.post(
    "/cost-adjustments/{holding_id}/confirm",
    response_model=CostAdjustmentPreviewResponse,
)
async def post_confirm_adjustment(
    holding_id: UUID,
    payload: CostAdjustmentConfirmRequest,
    session: AsyncSession = Depends(get_session),
) -> CostAdjustmentPreviewResponse:
    return await _run_write(session, lambda: confirm_adjustment(session, holding_id, payload))


async def _run_write(
    session: AsyncSession,
    operation,
) -> CostAdjustmentPreviewResponse:
    try:
        async with session.begin():
            return await operation()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except StaleDataError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "HOLDING_VERSION_CONFLICT",
                "message": "Holding was modified by another transaction.",
            },
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COST_ADJUSTMENT_WRITE_FAILED",
                "message": "Cost adjustment write failed.",
            },
        ) from exc
