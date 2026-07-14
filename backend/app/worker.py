from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Setting
from app.db.session import SessionFactory
from app.services.market_data import refresh_all_required_data
from app.services.snapshots import create_daily_snapshot_if_complete

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefreshSchedule:
    hour: int
    minute: int

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise ValueError("Worker refresh schedule must contain a valid hour and minute.")


async def scheduled_refresh() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await refresh_all_required_data(session)

    try:
        async with SessionFactory() as session:
            async with session.begin():
                await create_daily_snapshot_if_complete(session)
    except Exception:
        logger.exception("Daily snapshot creation failed after successful market refresh")


def build_scheduler(*, refresh_hour: int | None = None, refresh_minute: int | None = None):
    settings = get_settings()
    schedule = RefreshSchedule(
        hour=settings.refresh_hour if refresh_hour is None else refresh_hour,
        minute=settings.refresh_minute if refresh_minute is None else refresh_minute,
    )
    try:
        ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Worker timezone is invalid.") from exc
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        scheduled_refresh,
        trigger="cron",
        hour=schedule.hour,
        minute=schedule.minute,
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
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
