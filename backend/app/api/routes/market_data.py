from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.market_data import (
    MarketDataCollectionResponse,
    MarketDataOverrideRequest,
    MarketDataStatusResponse,
)
from app.services.errors import ServiceError
from app.services.market_data import (
    delete_manual_override,
    list_market_data,
    refresh_all_required_data,
    set_manual_override,
)

router = APIRouter(tags=["market-data"])
logger = logging.getLogger(__name__)


@router.get("/market-data", response_model=MarketDataCollectionResponse)
async def get_market_data(
    session: AsyncSession = Depends(get_session),
) -> MarketDataCollectionResponse:
    return await list_market_data(session)


@router.post("/market-data/refresh", response_model=MarketDataCollectionResponse)
async def post_market_data_refresh(
    session: AsyncSession = Depends(get_session),
) -> MarketDataCollectionResponse:
    return await _run_write(session, lambda: refresh_all_required_data(session))


@router.post("/market-data/{raw_key:path}/override", response_model=MarketDataStatusResponse)
async def post_market_data_override(
    raw_key: str,
    payload: MarketDataOverrideRequest,
    session: AsyncSession = Depends(get_session),
) -> MarketDataStatusResponse:
    return await _run_write(
        session,
        lambda: set_manual_override(
            session,
            raw_key=raw_key,
            value=payload.value,
            note=payload.note,
            effective_at=payload.effective_at,
            expires_at=payload.expires_at,
        ),
    )


@router.delete("/market-data/{raw_key:path}/override", status_code=204)
async def delete_market_data_override(
    raw_key: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _run_write(session, lambda: delete_manual_override(session, raw_key=raw_key))
    return Response(status_code=204)


async def _run_write(session: AsyncSession, operation):
    try:
        async with session.begin():
            return await operation()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except SQLAlchemyError as exc:
        logger.error(
            "Market-data storage operation failed exception_class=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "MARKET_DATA_STORAGE_ERROR",
                "message": "Market-data storage operation failed.",
            },
        ) from exc
