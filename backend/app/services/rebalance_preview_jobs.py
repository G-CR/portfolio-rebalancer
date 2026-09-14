from __future__ import annotations

from uuid import UUID

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RebalancePreviewJob
from app.schemas.rebalance import (
    RebalancePreviewJobStatusResponse,
    RebalancePreviewRequest,
    RebalancePreviewResponse,
)
from app.services.errors import ServiceError


async def create_preview_job(
    session: AsyncSession,
    payload: RebalancePreviewRequest,
) -> tuple[RebalancePreviewJobStatusResponse, bool]:
    existing = await session.scalar(
        select(RebalancePreviewJob).where(RebalancePreviewJob.request_token == payload.request_token)
    )
    if existing is not None:
        return _status_response(existing), False

    job = RebalancePreviewJob(
        request_token=payload.request_token,
        status="queued",
        payload=payload.model_dump(mode="json"),
    )
    session.add(job)
    await session.flush()
    return _status_response(job), True


async def get_preview_job(
    session: AsyncSession,
    job_id: UUID,
) -> RebalancePreviewJobStatusResponse:
    job = await session.get(RebalancePreviewJob, job_id)
    if job is None:
        raise ServiceError(
            404,
            "REBALANCE_PREVIEW_JOB_NOT_FOUND",
            "Rebalance preview job was not found.",
        )
    return _status_response(job)


def _status_response(job: RebalancePreviewJob) -> RebalancePreviewJobStatusResponse:
    return RebalancePreviewJobStatusResponse(
        id=str(job.id),
        status=job.status,
        result=job.result,
        error=job.error,
    )


async def claim_next_preview_job(session: AsyncSession) -> RebalancePreviewJob | None:
    job = await session.scalar(
        select(RebalancePreviewJob)
        .where(RebalancePreviewJob.status == "queued")
        .order_by(RebalancePreviewJob.created_at.asc(), RebalancePreviewJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    now = datetime.now(UTC)
    job.status = "refreshing"
    job.started_at = now
    job.heartbeat_at = now
    await session.flush()
    return job


async def mark_preview_job_calculating(session: AsyncSession, job_id: UUID) -> None:
    job = await session.get(RebalancePreviewJob, job_id, with_for_update=True)
    if job is None:
        return
    job.status = "calculating"
    job.heartbeat_at = datetime.now(UTC)
    await session.flush()


async def complete_preview_job(
    session: AsyncSession,
    job_id: UUID,
    result: RebalancePreviewResponse,
) -> None:
    job = await session.get(RebalancePreviewJob, job_id, with_for_update=True)
    if job is None:
        return
    now = datetime.now(UTC)
    job.status = "succeeded"
    job.result = result.model_dump(mode="json")
    job.error = None
    job.heartbeat_at = now
    job.finished_at = now
    await session.flush()


async def fail_preview_job(
    session: AsyncSession,
    job_id: UUID,
    error: dict[str, object],
) -> None:
    job = await session.get(RebalancePreviewJob, job_id, with_for_update=True)
    if job is None:
        return
    now = datetime.now(UTC)
    job.status = "failed"
    job.result = None
    job.error = error
    job.heartbeat_at = now
    job.finished_at = now
    await session.flush()


async def requeue_abandoned_preview_jobs(
    session: AsyncSession,
    *,
    recovery_seconds: int,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=recovery_seconds)
    result = await session.execute(
        update(RebalancePreviewJob)
        .where(
            RebalancePreviewJob.status.in_(("refreshing", "calculating")),
            RebalancePreviewJob.heartbeat_at < cutoff,
        )
        .values(status="queued", started_at=None, heartbeat_at=None)
    )
    return result.rowcount or 0
