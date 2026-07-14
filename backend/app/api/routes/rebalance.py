from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.rebalance import (
    RebalancePlanCollectionResponse,
    RebalancePlanCreateRequest,
    RebalancePlanResponse,
    RebalancePlanTransitionRequest,
    RebalancePreviewRequest,
    RebalancePreviewResponse,
)
from app.services.errors import ServiceError
from app.services.rebalancing import (
    cancel_rebalance_plan,
    complete_rebalance_plan,
    create_rebalance_plan,
    get_rebalance_plan,
    list_rebalance_plans,
    preview_rebalance,
    start_rebalance_plan,
)

router = APIRouter(prefix="/rebalance", tags=["rebalance"])
logger = logging.getLogger(__name__)


@router.post("/preview", response_model=RebalancePreviewResponse)
async def post_rebalance_preview(
    payload: RebalancePreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> RebalancePreviewResponse:
    return await _run_write(session, lambda: preview_rebalance(session, payload))


@router.post("/plans", response_model=RebalancePlanResponse, status_code=201)
async def post_rebalance_plan(
    payload: RebalancePlanCreateRequest,
    http_response: Response,
    session: AsyncSession = Depends(get_session),
) -> RebalancePlanResponse:
    response, created = await _run_write(session, lambda: create_rebalance_plan(session, payload))
    if not created:
        http_response.status_code = 200
    return response


@router.get("/plans", response_model=RebalancePlanCollectionResponse)
async def get_rebalance_plans(
    session: AsyncSession = Depends(get_session),
) -> RebalancePlanCollectionResponse:
    return RebalancePlanCollectionResponse(items=await list_rebalance_plans(session))


@router.get("/plans/{plan_id}", response_model=RebalancePlanResponse)
async def get_rebalance_plan_detail(
    plan_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> RebalancePlanResponse:
    return await _run_read(lambda: get_rebalance_plan(session, plan_id))


@router.post("/plans/{plan_id}/start", response_model=RebalancePlanResponse)
async def post_rebalance_plan_start(
    plan_id: UUID,
    payload: RebalancePlanTransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> RebalancePlanResponse:
    return await _run_write(
        session,
        lambda: start_rebalance_plan(session, plan_id=plan_id, idempotency_key=payload.idempotency_key),
    )


@router.post("/plans/{plan_id}/cancel", response_model=RebalancePlanResponse)
async def post_rebalance_plan_cancel(
    plan_id: UUID,
    payload: RebalancePlanTransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> RebalancePlanResponse:
    return await _run_write(
        session,
        lambda: cancel_rebalance_plan(session, plan_id=plan_id, idempotency_key=payload.idempotency_key),
    )


@router.post("/plans/{plan_id}/complete", response_model=RebalancePlanResponse)
async def post_rebalance_plan_complete(
    plan_id: UUID,
    payload: RebalancePlanTransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> RebalancePlanResponse:
    return await _run_write(
        session,
        lambda: complete_rebalance_plan(session, plan_id=plan_id, idempotency_key=payload.idempotency_key),
    )


async def _run_read(operation):
    try:
        return await operation()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


async def _run_write(session: AsyncSession, operation):
    try:
        async with session.begin():
            return await operation()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except Exception as exc:
        logger.error("Rebalance storage operation failed exception_class=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "REBALANCE_STORAGE_ERROR",
                "message": "Rebalance storage operation failed.",
            },
        ) from exc
