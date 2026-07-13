from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.db.session import get_session
from app.schemas.holding import HoldingCreate, HoldingResponse, HoldingUpdate
from app.services.errors import ServiceError
from app.services.holdings import archive_holding, create_holding, list_holdings, update_holding

router = APIRouter(tags=["holdings"])


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[HoldingResponse]:
    return await list_holdings(session, include_archived=include_archived)


@router.post("/holdings", response_model=HoldingResponse, status_code=201)
async def post_holding(
    payload: HoldingCreate,
    session: AsyncSession = Depends(get_session),
) -> HoldingResponse:
    return await _run_write(session, lambda: create_holding(session, payload))


@router.patch("/holdings/{holding_id}", response_model=HoldingResponse)
async def patch_holding(
    holding_id: UUID,
    payload: HoldingUpdate,
    session: AsyncSession = Depends(get_session),
) -> HoldingResponse:
    return await _run_write(session, lambda: update_holding(session, holding_id, payload))


@router.post("/holdings/{holding_id}/archive", response_model=HoldingResponse)
async def post_archive_holding(
    holding_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HoldingResponse:
    return await _run_write(session, lambda: archive_holding(session, holding_id))


async def _run_write(
    session: AsyncSession,
    operation,
) -> HoldingResponse:
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
        detail = _integrity_error_detail(exc)
        if detail is None:
            raise
        raise HTTPException(status_code=detail["status_code"], detail=detail["detail"]) from exc


def _integrity_error_detail(exc: IntegrityError) -> dict[str, object] | None:
    message = str(exc.orig)
    if (
        "uq_holdings_active_symbol_account_name" in message
        or "uq_holdings_symbol_account_name" in message
    ):
        return {
            "status_code": 409,
            "detail": {
                "code": "HOLDING_ALREADY_EXISTS",
                "message": "A holding with the same symbol and account already exists.",
            },
        }
    if "uq_holdings_active_preferred_asset_class" in message:
        return {
            "status_code": 409,
            "detail": {
                "code": "PREFERRED_HOLDING_CONFLICT",
                "message": "Only one active preferred holding is allowed per asset class.",
            },
        }
    return None
