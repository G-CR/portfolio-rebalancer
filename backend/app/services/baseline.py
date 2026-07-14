from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Holding

_ONE = Decimal("1")


async def list_active_holdings_for_update(session: AsyncSession) -> list[Holding]:
    return list(
        await session.scalars(
            select(Holding)
            .where(Holding.is_active.is_(True))
            .order_by(Holding.id.asc())
            .with_for_update()
        )
    )


async def reset_baseline_fx(
    session: AsyncSession,
    effective_fx: dict[str, Decimal],
) -> None:
    holdings = await list_active_holdings_for_update(session)
    for holding in holdings:
        holding.baseline_fx_to_cny = (
            _ONE
            if holding.trade_currency == "CNY"
            else effective_fx[holding.trade_currency]
        )
