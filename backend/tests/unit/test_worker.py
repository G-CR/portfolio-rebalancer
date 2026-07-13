from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.worker as worker_module


class _FakeScheduler:
    def __init__(self, *, timezone: str) -> None:
        self.timezone = timezone
        self.jobs: list[dict[str, object]] = []
        self.started = False

    def add_job(self, func, **kwargs) -> None:
        self.jobs.append({"func": func, **kwargs})

    def start(self) -> None:
        self.started = True


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


@pytest.mark.asyncio
async def test_scheduled_refresh_uses_session_factory(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    session = _FakeSession()
    refresh_all_required_data = AsyncMock()

    class _SessionScope:
        async def __aenter__(self) -> _FakeSession:
            return session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope())
    monkeypatch.setattr(
        worker_module,
        "refresh_all_required_data",
        refresh_all_required_data,
    )

    await worker_module.scheduled_refresh()

    refresh_all_required_data.assert_awaited_once_with(session)
