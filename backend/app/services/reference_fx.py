"""Date-bound reference quotations. Never treat a spot quote as a daily average."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Holding, MarketData
from app.db.ledger_models import ReferenceFxDay

SHANGHAI = ZoneInfo('Asia/Shanghai')


def shanghai_today() -> date:
    return datetime.now(SHANGHAI).date()


def fx_details(row: ReferenceFxDay | None, *, provisional=False) -> dict:
    if row is None:
        return {'status': 'pending', 'rate': None}
    return {
        'status': 'provisional' if provisional else 'fallback' if row.is_fallback else 'final',
        'rate': str(row.rate), 'reference_date': row.actual_date.isoformat(),
        'selected_date': row.local_date.isoformat(), 'source': row.source,
        'market_time': row.market_time.isoformat() if row.market_time else None,
        'selected_at': row.selected_at.isoformat(),
        'quote_id': str(row.quote_id) if row.quote_id else None,
        'is_fallback': row.is_fallback,
    }


async def reference_for(session: AsyncSession, currency: str, day: date) -> tuple[Decimal | None, dict]:
    if currency == 'CNY':
        return Decimal(1), {'status': 'final', 'rate': '1', 'reference_date': day.isoformat(), 'source': 'CNY identity', 'is_fallback': False}
    row = await session.scalar(select(ReferenceFxDay).where(ReferenceFxDay.currency == currency, ReferenceFxDay.local_date == day, ReferenceFxDay.is_final.is_(True)))
    if row:
        return row.rate, fx_details(row)
    if day == shanghai_today():
        quote = await _same_day_quote(session, currency, day)
        if quote:
            return quote.value, {
                'status': 'provisional', 'rate': str(quote.value), 'reference_date': day.isoformat(),
                'source': quote.source, 'market_time': quote.market_time.isoformat(),
                'selected_at': quote.fetched_at.isoformat(), 'quote_id': str(quote.id), 'is_fallback': False,
            }
    previous = await session.scalar(select(ReferenceFxDay).where(
        ReferenceFxDay.currency == currency, ReferenceFxDay.local_date < day,
        ReferenceFxDay.actual_date >= day - timedelta(days=7), ReferenceFxDay.is_final.is_(True),
        ReferenceFxDay.rate > 0,
    ).order_by(ReferenceFxDay.local_date.desc()).limit(1))
    if previous:
        details = fx_details(previous)
        details.update(status='fallback', is_fallback=True, selected_date=day.isoformat())
        return previous.rate, details
    return None, {'status': 'pending', 'rate': None}


async def _same_day_quote(session: AsyncSession, currency: str, day: date):
    start = datetime.combine(day, datetime.min.time(), SHANGHAI).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return await session.scalar(select(MarketData).where(
        MarketData.data_type == 'fx', MarketData.symbol == f'{currency}/CNY',
        MarketData.status == 'valid', MarketData.value > 0,
        MarketData.market_time >= start, MarketData.market_time < end,
    ).order_by(MarketData.market_time.desc(), MarketData.fetched_at.desc()).limit(1))


async def freeze_reference_fx(session: AsyncSession, local_date: date) -> int:
    """Call after scheduled refresh; caller commits atomically. Final rows never drift."""
    from app.services.ledger import repair_reference_conversions
    if local_date > shanghai_today():
        raise ValueError('不能冻结未来汇率。')
    currencies = set((await session.scalars(select(Holding.trade_currency).distinct())).all())
    from app.db.ledger_models import LedgerEntry
    currencies.update((await session.scalars(select(LedgerEntry.fee_currency).distinct())).all())
    currencies.update((await session.scalars(select(LedgerEntry.currency).distinct())).all())
    count = 0
    for currency in sorted(currencies - {'CNY'}):
        existing = await session.scalar(select(ReferenceFxDay).where(ReferenceFxDay.currency == currency, ReferenceFxDay.local_date == local_date))
        if existing and existing.is_final:
            continue
        quote = await _same_day_quote(session, currency, local_date)
        if quote:
            values = dict(rate=quote.value, source=quote.source, market_time=quote.market_time,
                selected_at=datetime.now(timezone.utc), quote_id=quote.id, actual_date=local_date,
                is_fallback=False, is_final=True)
        else:
            rate, details = await reference_for(session, currency, local_date)
            if rate is None or details['status'] == 'provisional':
                continue
            values = dict(rate=rate, source=details['source'], market_time=datetime.fromisoformat(details['market_time']) if details.get('market_time') else None,
                selected_at=datetime.now(timezone.utc), quote_id=UUID(details['quote_id']) if details.get('quote_id') else None,
                actual_date=date.fromisoformat(details['reference_date']), is_fallback=True, is_final=True)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            session.add(ReferenceFxDay(currency=currency, local_date=local_date, **values))
        count += 1
    await session.flush()
    await repair_reference_conversions(session)
    return count
