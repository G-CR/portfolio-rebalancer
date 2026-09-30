import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

import app.worker as worker_module


@pytest.fixture(autouse=True)
def isolate_investing_maintenance(monkeypatch):
    # This file tests the pre-existing refresh lifecycle; investing maintenance
    # is exercised independently in test_investing_worker.py.
    monkeypatch.setattr(worker_module, "scheduled_investing_updates", AsyncMock())


class _FakeScheduler:
    def __init__(self, *, timezone: str) -> None:
        self.timezone = timezone
        self.jobs: list[dict[str, object]] = []
        self.started = False
        self.shutdown_calls: list[bool] = []

    def add_job(self, func, **kwargs) -> None:
        if kwargs.get("replace_existing"):
            self.jobs = [job for job in self.jobs if job.get("id") != kwargs.get("id")]
        self.jobs.append({"func": func, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self, *, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


def test_preview_job_uses_a_five_minute_optimization_budget() -> None:
    assert worker_module.PREVIEW_JOB_OPTIMIZATION_SECONDS == 300


def test_build_scheduler_uses_configured_timezone_and_single_instance(monkeypatch) -> None:
    fake_scheduler = _FakeScheduler(timezone="unused")
    monkeypatch.setattr(
        worker_module,
        "AsyncIOScheduler",
        lambda *, timezone: fake_scheduler,
    )
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(timezone="Asia/Shanghai", refresh_hour=9, refresh_minute=15),
    )

    scheduler = worker_module.build_scheduler()

    assert scheduler is fake_scheduler
    assert fake_scheduler.started is False
    assert fake_scheduler.jobs == [
        {
            "func": worker_module.scheduled_refresh,
            "trigger": "cron",
            "hour": 9,
            "minute": 15,
            "id": "daily-market-refresh",
            "replace_existing": True,
            "max_instances": 1,
        }
    ]


def test_build_scheduler_uses_shared_refresh_job_configuration(monkeypatch) -> None:
    fake_scheduler = _FakeScheduler(timezone="unused")
    configure = Mock()
    monkeypatch.setattr(
        worker_module,
        "AsyncIOScheduler",
        lambda *, timezone: fake_scheduler,
    )
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(timezone="Asia/Shanghai", refresh_hour=9, refresh_minute=15),
    )
    monkeypatch.setattr(worker_module, "configure_refresh_job", configure)

    scheduler = worker_module.build_scheduler()

    assert scheduler is fake_scheduler
    configure.assert_called_once_with(
        fake_scheduler,
        worker_module.RefreshSchedule(hour=9, minute=15),
    )


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(-1, 0), (24, 0), (8, -1), (8, 60)],
)
def test_refresh_schedule_rejects_invalid_time(hour: int, minute: int) -> None:
    with pytest.raises(ValueError, match="refresh schedule"):
        worker_module.RefreshSchedule(hour=hour, minute=minute)


def test_build_scheduler_rejects_invalid_timezone(monkeypatch) -> None:
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(
            timezone="Mars/Olympus",
            refresh_hour=9,
            refresh_minute=15,
        ),
    )

    with pytest.raises(ValueError, match="timezone"):
        worker_module.build_scheduler()


@pytest.mark.asyncio
async def test_reconcile_unchanged_schedule_does_not_replace_job() -> None:
    scheduler = _FakeScheduler(timezone="Asia/Shanghai")
    active = worker_module.RefreshSchedule(hour=8, minute=0)
    worker_module.configure_refresh_job(scheduler, active)
    existing_job = scheduler.jobs[0]

    result = await worker_module.reconcile_refresh_schedule(
        scheduler,
        active,
        loader=AsyncMock(return_value=active),
    )

    assert result == active
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0] is existing_job


@pytest.mark.asyncio
async def test_reconcile_changed_schedule_replaces_only_daily_refresh_job() -> None:
    scheduler = _FakeScheduler(timezone="Asia/Shanghai")
    active = worker_module.RefreshSchedule(hour=8, minute=0)
    worker_module.configure_refresh_job(scheduler, active)
    scheduler.add_job(Mock(name="other_job"), id="other-job")

    changed = worker_module.RefreshSchedule(hour=9, minute=30)
    result = await worker_module.reconcile_refresh_schedule(
        scheduler,
        active,
        loader=AsyncMock(return_value=changed),
    )

    assert result == changed
    assert [job["id"] for job in scheduler.jobs] == ["other-job", "daily-market-refresh"]
    assert scheduler.jobs[-1]["hour"] == 9
    assert scheduler.jobs[-1]["minute"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        ValueError("Worker refresh schedule must contain a valid hour and minute."),
        RuntimeError("database temporarily unavailable"),
    ],
)
async def test_reconcile_contains_load_errors_and_keeps_current_job(
    failure: Exception,
    monkeypatch,
) -> None:
    scheduler = _FakeScheduler(timezone="Asia/Shanghai")
    active = worker_module.RefreshSchedule(hour=8, minute=0)
    worker_module.configure_refresh_job(scheduler, active)
    existing_job = scheduler.jobs[0]
    log_exception = Mock()
    monkeypatch.setattr(worker_module.logger, "exception", log_exception)

    result = await worker_module.reconcile_refresh_schedule(
        scheduler,
        active,
        loader=AsyncMock(side_effect=failure),
    )

    assert result == active
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0] is existing_job
    log_exception.assert_called_once_with("Worker schedule reconciliation failed")


@pytest.mark.asyncio
async def test_watch_refresh_schedule_polls_repeatedly_every_30_seconds() -> None:
    scheduler = _FakeScheduler(timezone="Asia/Shanghai")
    active = worker_module.RefreshSchedule(hour=8, minute=0)
    delays: list[float] = []

    async def recording_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 3:
            raise asyncio.CancelledError

    loader = AsyncMock(return_value=active)

    with pytest.raises(asyncio.CancelledError):
        await worker_module.watch_refresh_schedule(
            scheduler,
            active,
            loader=loader,
            sleep=recording_sleep,
        )

    assert delays == [30, 30, 30]
    assert loader.await_count == 2


@pytest.mark.asyncio
async def test_watch_refresh_schedule_cancellation_is_clean() -> None:
    scheduler = _FakeScheduler(timezone="Asia/Shanghai")
    active = worker_module.RefreshSchedule(hour=8, minute=0)
    sleeping = asyncio.Event()

    async def blocked_sleep(delay: float) -> None:
        assert delay == 30
        sleeping.set()
        await asyncio.Event().wait()

    watcher = asyncio.create_task(
        worker_module.watch_refresh_schedule(
            scheduler,
            active,
            loader=AsyncMock(),
            sleep=blocked_sleep,
        )
    )
    await sleeping.wait()
    watcher.cancel()

    with pytest.raises(asyncio.CancelledError):
        await watcher

    assert watcher.done()


@pytest.mark.asyncio
async def test_run_shuts_down_scheduler_when_cancelled(monkeypatch) -> None:
    scheduler = _FakeScheduler(timezone="Asia/Shanghai")

    class _CancelledEvent:
        async def wait(self) -> None:
            raise asyncio.CancelledError

    monkeypatch.setattr(
        worker_module,
        "load_refresh_schedule",
        AsyncMock(return_value=worker_module.RefreshSchedule(hour=9, minute=15)),
    )
    monkeypatch.setattr(worker_module, "build_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(worker_module.asyncio, "Event", _CancelledEvent)

    with pytest.raises(asyncio.CancelledError):
        await worker_module._run()

    assert scheduler.started is True
    assert scheduler.shutdown_calls == [False]


@pytest.mark.asyncio
async def test_run_cancels_and_awaits_watcher_before_scheduler_shutdown(monkeypatch) -> None:
    lifecycle: list[str] = []

    class _OrderedScheduler(_FakeScheduler):
        def shutdown(self, *, wait: bool = True) -> None:
            lifecycle.append("shutdown")
            super().shutdown(wait=wait)

    class _CancelledEvent:
        async def wait(self) -> None:
            raise asyncio.CancelledError

    class _WatcherTask:
        def cancel(self) -> None:
            lifecycle.append("cancel")

        def __await__(self):
            async def mark_awaited() -> None:
                lifecycle.append("await")
                raise asyncio.CancelledError

            return mark_awaited().__await__()

    scheduler = _OrderedScheduler(timezone="Asia/Shanghai")

    def create_task(coroutine):
        coroutine.close()
        return _WatcherTask()

    monkeypatch.setattr(
        worker_module,
        "load_refresh_schedule",
        AsyncMock(return_value=worker_module.RefreshSchedule(hour=9, minute=15)),
    )
    monkeypatch.setattr(worker_module, "build_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(worker_module.asyncio, "Event", _CancelledEvent)
    monkeypatch.setattr(worker_module.asyncio, "create_task", create_task)

    with pytest.raises(asyncio.CancelledError):
        await worker_module._run()

    assert lifecycle == ["cancel", "cancel", "cancel", "await", "await", "await", "shutdown"]


def test_compose_worker_has_restart_policy() -> None:
    compose_path = Path(__file__).resolve().parents[3] / "compose.yaml"
    if not compose_path.exists():
        pytest.skip("compose.yaml is not available in the backend test image")

    compose = yaml.safe_load(compose_path.read_text())

    assert compose["services"]["worker"]["restart"] == "unless-stopped"


@pytest.mark.asyncio
async def test_scheduled_refresh_uses_distinct_transactions(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    refresh_session = _FakeSession()
    snapshot_session = _FakeSession()
    digest_session = _FakeSession()
    sessions = iter([refresh_session, snapshot_session, digest_session])
    refresh_all_required_data = AsyncMock()
    create_daily_snapshot_if_complete = AsyncMock()
    send_daily_digest_if_configured = AsyncMock()

    class _SessionScope:
        def __init__(self, session) -> None:
            self.session = session

        async def __aenter__(self) -> _FakeSession:
            return self.session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope(next(sessions)))
    monkeypatch.setattr(
        worker_module,
        "refresh_all_required_data",
        refresh_all_required_data,
    )
    monkeypatch.setattr(
        worker_module,
        "create_daily_snapshot_if_complete",
        create_daily_snapshot_if_complete,
    )
    monkeypatch.setattr(
        worker_module,
        "send_daily_digest_if_configured",
        send_daily_digest_if_configured,
    )

    await worker_module.scheduled_refresh()

    refresh_all_required_data.assert_awaited_once_with(refresh_session)
    create_daily_snapshot_if_complete.assert_awaited_once_with(snapshot_session)
    send_daily_digest_if_configured.assert_awaited_once_with(digest_session)


@pytest.mark.asyncio
async def test_scheduled_refresh_does_not_snapshot_when_refresh_fails(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    class _SessionScope:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    snapshot = AsyncMock()
    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope())
    monkeypatch.setattr(
        worker_module,
        "refresh_all_required_data",
        AsyncMock(side_effect=RuntimeError("provider failed")),
    )
    monkeypatch.setattr(worker_module, "create_daily_snapshot_if_complete", snapshot)

    with pytest.raises(RuntimeError, match="provider failed"):
        await worker_module.scheduled_refresh()

    snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_refresh_contains_snapshot_failure(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    class _SessionScope:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    refresh = AsyncMock()
    snapshot = AsyncMock(side_effect=RuntimeError("snapshot write failed"))
    digest = AsyncMock()
    log_exception = Mock()
    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope())
    monkeypatch.setattr(worker_module, "refresh_all_required_data", refresh)
    monkeypatch.setattr(worker_module, "create_daily_snapshot_if_complete", snapshot)
    monkeypatch.setattr(worker_module, "send_daily_digest_if_configured", digest)
    monkeypatch.setattr(worker_module.logger, "exception", log_exception)

    await worker_module.scheduled_refresh()

    refresh.assert_awaited_once()
    snapshot.assert_awaited_once()
    digest.assert_awaited_once()
    log_exception.assert_called_once_with(
        "Daily snapshot creation failed after successful market refresh"
    )


@pytest.mark.asyncio
async def test_scheduled_refresh_contains_digest_failure(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    class _SessionScope:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    refresh = AsyncMock()
    snapshot = AsyncMock()
    digest = AsyncMock(side_effect=RuntimeError("smtp failed"))
    log_exception = Mock()
    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope())
    monkeypatch.setattr(worker_module, "refresh_all_required_data", refresh)
    monkeypatch.setattr(worker_module, "create_daily_snapshot_if_complete", snapshot)
    monkeypatch.setattr(worker_module, "send_daily_digest_if_configured", digest)
    monkeypatch.setattr(worker_module.logger, "exception", log_exception)

    await worker_module.scheduled_refresh()

    refresh.assert_awaited_once()
    snapshot.assert_awaited_once()
    digest.assert_awaited_once()
    log_exception.assert_called_once_with(
        "Daily email digest failed after successful market refresh"
    )
