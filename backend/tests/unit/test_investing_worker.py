from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app import worker


@pytest.mark.asyncio
async def test_failed_snapshot_still_records_invalid_daily_observation(monkeypatch):
    class Session:
        @asynccontextmanager
        async def begin(self):
            yield

    @asynccontextmanager
    async def factory():
        yield Session()

    observation = AsyncMock()
    reference = AsyncMock()
    monkeypatch.setattr(worker, 'SessionFactory', factory)
    monkeypatch.setattr(worker, 'refresh_all_required_data', AsyncMock())
    monkeypatch.setattr(worker, 'create_daily_snapshot_if_complete', AsyncMock(side_effect=RuntimeError('snapshot failed')))
    monkeypatch.setattr(worker, 'send_daily_digest_if_configured', AsyncMock())
    monkeypatch.setattr(worker, 'record_scheduled_observation', observation, raising=False)
    monkeypatch.setattr(worker, 'freeze_reference_fx', reference, raising=False)
    await worker.scheduled_refresh()
    assert observation.await_count == 1
    assert observation.call_args.kwargs['snapshot_complete'] is False
    assert reference.await_count == 1


@pytest.mark.asyncio
async def test_periodic_delivery_does_not_record_an_observation(monkeypatch):
    class Session:
        @asynccontextmanager
        async def begin(self):
            yield

    @asynccontextmanager
    async def factory():
        yield Session()

    delivery = AsyncMock()
    observation = AsyncMock()
    monkeypatch.setattr(worker, 'SessionFactory', factory)
    monkeypatch.setattr(worker, 'deliver_pending_notifications', delivery, raising=False)
    monkeypatch.setattr(worker, 'record_scheduled_observation', observation, raising=False)
    assert hasattr(worker, 'retry_investing_notifications')
    await worker.retry_investing_notifications()
    delivery.assert_awaited_once()
    observation.assert_not_awaited()
