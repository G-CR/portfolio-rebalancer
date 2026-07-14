from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.settings import (
    GeneralSettingsResponse,
    GeneralSettingsUpdate,
    ProviderName,
    ProviderSettingResponse,
    ProviderSettingUpdate,
)
from app.services.errors import ServiceError
from app.services.settings import (
    get_general_settings,
    list_provider_settings,
    test_provider_setting,
    update_general_settings,
    update_provider_setting,
)

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("/providers", response_model=list[ProviderSettingResponse])
async def get_provider_settings(
    session: AsyncSession = Depends(get_session),
) -> list[ProviderSettingResponse]:
    return await list_provider_settings(session)


@router.put("/providers/{provider}", response_model=ProviderSettingResponse)
async def put_provider_setting(
    provider: ProviderName,
    payload: ProviderSettingUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProviderSettingResponse:
    return await _run_write(
        session,
        lambda: update_provider_setting(session, provider=provider, payload=payload),
    )


@router.post("/providers/{provider}/test", response_model=ProviderSettingResponse)
async def post_provider_test(
    provider: ProviderName,
    session: AsyncSession = Depends(get_session),
) -> ProviderSettingResponse:
    return await _run_write(session, lambda: test_provider_setting(session, provider=provider))


@router.get("/general", response_model=GeneralSettingsResponse)
async def get_general_setting(
    session: AsyncSession = Depends(get_session),
) -> GeneralSettingsResponse:
    return await get_general_settings(session)


@router.put("/general", response_model=GeneralSettingsResponse)
async def put_general_setting(
    payload: GeneralSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> GeneralSettingsResponse:
    return await _run_write(session, lambda: update_general_settings(session, payload))


async def _run_write(session: AsyncSession, operation):
    try:
        async with session.begin():
            return await operation()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except SQLAlchemyError as exc:
        logger.error("Settings storage operation failed exception_class=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"code": "SETTINGS_STORAGE_ERROR", "message": "Settings storage operation failed."},
        ) from exc
