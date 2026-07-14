from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Holding


async def reset_baseline_fx(
    session: AsyncSession,
    holding_fx: tuple[tuple[UUID, Decimal], ...],
) -> None:
    for holding_id, fx_to_cny in holding_fx:
        result = await session.execute(
            update(Holding)
            .where(Holding.id == holding_id, Holding.is_active.is_(True))
            .values(
                baseline_fx_to_cny=fx_to_cny,
                version=Holding.version + 1,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Captured active holding {holding_id} changed during baseline reset.")
