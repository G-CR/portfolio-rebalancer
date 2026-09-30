from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Setting
from app.db.session import SessionFactory
from app.services.email_digest import send_daily_digest_if_configured
from app.services.market_data import refresh_all_required_data
from app.services.rebalance_preview_jobs import (
    claim_next_preview_job,
    complete_preview_job,
    fail_preview_job,
    mark_preview_job_calculating,
    requeue_abandoned_preview_jobs,
)
from app.services.rebalancing import preview_rebalance_from_current_data
from app.schemas.rebalance import RebalancePreviewRequest
from app.services.errors import ServiceError
from app.services.snapshots import create_daily_snapshot_if_complete
from app.services.reference_fx import freeze_reference_fx
from app.services.decision import record_scheduled_observation, deliver_pending_notifications

logger = logging.getLogger(__name__)

REFRESH_SCHEDULE_POLL_SECONDS = 30
PREVIEW_JOB_POLL_SECONDS = 1
PREVIEW_JOB_RECOVERY_SECONDS = 120
PREVIEW_JOB_OPTIMIZATION_SECONDS = 300


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

    snapshot_complete = False
    try:
        async with SessionFactory() as session:
            async with session.begin():
                snapshot = await create_daily_snapshot_if_complete(session)
                snapshot_complete = bool(snapshot and snapshot.data_complete)
    except Exception:
        logger.exception("Daily snapshot creation failed after successful market refresh")

    await scheduled_investing_updates(snapshot_complete=snapshot_complete)

    try:
        async with SessionFactory() as session:
            async with session.begin():
                await send_daily_digest_if_configured(session)
    except Exception:
        logger.exception("Daily email digest failed after successful market refresh")


async def scheduled_investing_updates(*, snapshot_complete: bool) -> None:
    # Reference repair failures must not suppress an invalid decision observation.
    try:
        async with SessionFactory() as session:
            async with session.begin():
                day = datetime.now(ZoneInfo("Asia/Shanghai")).date()
                await freeze_reference_fx(session, day)
    except Exception:
        logger.exception("Reference currency conversions could not be finalized")
    try:
        async with SessionFactory() as session:
            async with session.begin():
                await record_scheduled_observation(session, snapshot_complete=snapshot_complete)
    except Exception:
        logger.exception("Daily decision observation could not be saved")


async def retry_investing_notifications() -> None:
    try:
        async with SessionFactory() as session:
            async with session.begin():
                await deliver_pending_notifications(session)
    except Exception:
        logger.exception("Pending investment notifications could not be delivered")


async def watch_investing_notifications() -> None:
    while True:
        await retry_investing_notifications()
        await asyncio.sleep(60)


async def run_preview_job_once() -> bool:
    async with SessionFactory() as session:
        async with session.begin():
            await requeue_abandoned_preview_jobs(
                session,
                recovery_seconds=PREVIEW_JOB_RECOVERY_SECONDS,
            )
            job = await claim_next_preview_job(session)
    if job is None:
        return False

    try:
        async with SessionFactory() as session:
            async with session.begin():
                await refresh_all_required_data(session)
                await mark_preview_job_calculating(session, job.id)
        async with SessionFactory() as session:
            async with session.begin():
                result = await preview_rebalance_from_current_data(
                    session,
                    RebalancePreviewRequest.model_validate(job.payload),
                    optimization_deadline_seconds=PREVIEW_JOB_OPTIMIZATION_SECONDS,
                )
                await complete_preview_job(session, job.id, result)
    except ServiceError as exc:
        async with SessionFactory() as session:
            async with session.begin():
                await fail_preview_job(session, job.id, exc.to_detail())
    except Exception:
        logger.exception("Rebalance preview job failed job_id=%s", job.id)
        async with SessionFactory() as session:
            async with session.begin():
                await fail_preview_job(
                    session,
                    job.id,
                    {
                        "code": "REBALANCE_PREVIEW_JOB_FAILED",
                        "message": "Rebalance preview job failed.",
                    },
                )
    return True


async def watch_preview_jobs() -> None:
    while True:
        processed = await run_preview_job_once()
        if not processed:
            await asyncio.sleep(PREVIEW_JOB_POLL_SECONDS)


def configure_refresh_job(
    scheduler: AsyncIOScheduler,
    schedule: RefreshSchedule,
) -> None:
    scheduler.add_job(
        scheduled_refresh,
        trigger="cron",
        hour=schedule.hour,
        minute=schedule.minute,
        id="daily-market-refresh",
        replace_existing=True,
        max_instances=1,
    )


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
    configure_refresh_job(scheduler, schedule)
    return scheduler


async def load_refresh_schedule() -> RefreshSchedule:
    settings = get_settings()
    async with SessionFactory() as session:
        configured = await session.scalar(select(Setting).limit(1))
    if configured is None:
        return RefreshSchedule(hour=settings.refresh_hour, minute=settings.refresh_minute)
    return RefreshSchedule(hour=configured.refresh_hour, minute=configured.refresh_minute)


async def reconcile_refresh_schedule(
    scheduler: AsyncIOScheduler,
    active: RefreshSchedule,
    *,
    loader: Callable[[], Awaitable[RefreshSchedule]] | None = None,
) -> RefreshSchedule:
    load = load_refresh_schedule if loader is None else loader
    try:
        configured = await load()
        if configured != active:
            configure_refresh_job(scheduler, configured)
            return configured
    except Exception:
        logger.exception("Worker schedule reconciliation failed")
    return active


async def watch_refresh_schedule(
    scheduler: AsyncIOScheduler,
    initial: RefreshSchedule,
    *,
    loader: Callable[[], Awaitable[RefreshSchedule]] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    active = initial
    wait = asyncio.sleep if sleep is None else sleep
    while True:
        await wait(REFRESH_SCHEDULE_POLL_SECONDS)
        active = await reconcile_refresh_schedule(
            scheduler,
            active,
            loader=loader,
        )


async def _run() -> None:
    schedule = await load_refresh_schedule()
    scheduler = build_scheduler(
        refresh_hour=schedule.hour,
        refresh_minute=schedule.minute,
    )
    scheduler.start()
    watcher = asyncio.create_task(watch_refresh_schedule(scheduler, schedule))
    preview_watcher = asyncio.create_task(watch_preview_jobs())
    notification_watcher = asyncio.create_task(watch_investing_notifications())
    try:
        await asyncio.Event().wait()
    finally:
        watcher.cancel()
        preview_watcher.cancel()
        notification_watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        with suppress(asyncio.CancelledError):
            await preview_watcher
        with suppress(asyncio.CancelledError):
            await notification_watcher
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
