from __future__ import annotations

import asyncio
from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Setting
from app.db.session import SessionFactory
from app.services.market_data import refresh_all_required_data


@dataclass(frozen=True, slots=True)
class RefreshSchedule:
    hour: int
    minute: int


async def scheduled_refresh() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await refresh_all_required_data(session)


def build_scheduler(*, refresh_hour: int | None = None, refresh_minute: int | None = None):
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        scheduled_refresh,
        trigger="cron",
        hour=settings.refresh_hour if refresh_hour is None else refresh_hour,
        minute=settings.refresh_minute if refresh_minute is None else refresh_minute,
        id="daily-market-refresh",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


async def load_refresh_schedule() -> RefreshSchedule:
    settings = get_settings()
    async with SessionFactory() as session:
        configured = await session.scalar(select(Setting).limit(1))
    if configured is None:
        return RefreshSchedule(hour=settings.refresh_hour, minute=settings.refresh_minute)
    return RefreshSchedule(hour=configured.refresh_hour, minute=configured.refresh_minute)


async def _run() -> None:
    schedule = await load_refresh_schedule()
    scheduler = build_scheduler(
        refresh_hour=schedule.hour,
        refresh_minute=schedule.minute,
    )
    scheduler.start()
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
