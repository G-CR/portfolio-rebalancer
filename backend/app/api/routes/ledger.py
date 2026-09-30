from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.db.session import get_session
from app.schemas.ledger import EntryRequest, OpeningRequest
from app.services import ledger
from app.services.errors import ServiceError

router = APIRouter(prefix='/ledger', tags=['ledger'])


async def run(session, operation, *, write=False):
    try:
        if write:
            async with session.begin():
                return await operation()
        return await operation()
    except ServiceError as exc:
        raise HTTPException(exc.status_code, detail=exc.to_detail()) from exc
    except (IntegrityError, StaleDataError) as exc:
        raise HTTPException(409, detail={'code': 'LEDGER_WRITE_CONFLICT', 'message': '账本已变化或防重复键冲突，请重新预览。'}) from exc


@router.post('/opening/preview')
async def preview_opening(payload: OpeningRequest, session: AsyncSession = Depends(get_session)):
    return await run(session, lambda: ledger.preview_opening(session, payload))


@router.post('/opening/confirm')
async def confirm_opening(payload: OpeningRequest, session: AsyncSession = Depends(get_session)):
    return await run(session, lambda: ledger.confirm_opening(session, payload), write=True)


@router.post('/entries/preview')
async def preview_entry(payload: EntryRequest, session: AsyncSession = Depends(get_session)):
    return await run(session, lambda: ledger.preview_entry(session, payload))


@router.post('/entries/confirm')
async def confirm_entry(payload: EntryRequest, session: AsyncSession = Depends(get_session)):
    return await run(session, lambda: ledger.confirm_entry(session, payload), write=True)


@router.get('/entries')
async def entries(holding_id: UUID | None = None, account: str | None = None, kind: str | None = None,
                  date_from: date | None = None, date_to: date | None = None,
                  session: AsyncSession = Depends(get_session)):
    return await run(session, lambda: ledger.list_entries(session, holding_id, account, kind, date_from, date_to))


@router.get('/statistics')
async def statistics(session: AsyncSession = Depends(get_session)):
    return await run(session, lambda: ledger.statistics(session))
