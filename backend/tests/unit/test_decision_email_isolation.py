from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.services import decision, email_digest

@pytest.mark.asyncio
async def test_automatic_daily_digest_does_not_send_independent_outbox(monkeypatch):
    monkeypatch.setattr(decision, 'load_policy', AsyncMock(return_value=SimpleNamespace(notification_mode='daily')))
    delivery = AsyncMock()
    monkeypatch.setattr(decision, 'deliver_pending_notifications', delivery)
    monkeypatch.setattr(email_digest, 'load_email_config', AsyncMock(return_value=None))
    await email_digest.send_daily_digest_if_configured(AsyncMock())
    delivery.assert_not_awaited()

@pytest.mark.asyncio
async def test_attention_mode_never_runs_daily_optimizer(monkeypatch):
    monkeypatch.setattr(decision, 'load_policy', AsyncMock(return_value=SimpleNamespace(notification_mode='attention')))
    optimizer = AsyncMock()
    monkeypatch.setattr(email_digest, 'preview_rebalance_with_defaults', optimizer)
    await email_digest.send_daily_digest_if_configured(AsyncMock())
    optimizer.assert_not_awaited()
