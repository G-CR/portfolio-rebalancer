import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

import app.worker as worker_module


class _FakeScheduler:
    def __init__(self, *, timezone: str) -> None:
        self.timezone = timezone
        self.jobs: list[dict[str, object]] = []
        self.started = False
        self.shutdown_calls: list[bool] = []

    def add_job(self, func, **kwargs) -> None:
        self.jobs.append({"func": func, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self, *, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


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


def test_compose_worker_has_restart_policy() -> None:
    compose_path = Path(__file__).resolve().parents[3] / "compose.yaml"
    if not compose_path.exists():
        pytest.skip("compose.yaml is not available in the backend test image")

    compose = yaml.safe_load(compose_path.read_text())

    assert compose["services"]["worker"]["restart"] == "unless-stopped"


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
