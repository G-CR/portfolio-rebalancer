from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_session
from app.schemas.decision import DecisionResponse, DecisionSettingsUpdate, DecisionSettingsResponse
from app.services.decision import get_decision, load_policy
from app.services.errors import ServiceError

router = APIRouter(prefix='/decision', tags=['decision'])

@router.get('', response_model=DecisionResponse)
async def decision(session: AsyncSession = Depends(get_session)):
    try:
        result = await get_decision(session)
        await session.commit()
        return result
    except ServiceError as exc:
        await session.rollback()
        raise HTTPException(exc.status_code, detail=exc.to_detail()) from exc

@router.get('/settings', response_model=DecisionSettingsResponse)
async def settings(session: AsyncSession = Depends(get_session)):
    policy = await load_policy(session)
    await session.commit()
    return policy

@router.put('/settings', response_model=DecisionSettingsResponse)
async def update_settings(payload: DecisionSettingsUpdate, session: AsyncSession = Depends(get_session)):
    policy = await load_policy(session, lock=True)
    for key, value in payload.model_dump().items(): setattr(policy, key, value)
    await session.commit()
    return policy

@router.post('/review', response_model=DecisionResponse)
async def acknowledge_review(session: AsyncSession = Depends(get_session)):
    policy = await load_policy(session, lock=True)
    now = datetime.now(UTC)
    policy.acknowledged_month = now.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m')
    policy.last_reviewed_at = now
    await session.flush()
    result = await get_decision(session, now=now)
    await session.commit()
    return result
