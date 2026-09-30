from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.db.decision_models import DecisionObservation, NotificationOutbox
from app.services import decision as service

NOW = datetime(2026, 10, 1, 8, tzinfo=UTC)

def analytics(*, drift='0.1', stale=False):
    from decimal import Decimal
    return SimpleNamespace(data_status='stale' if stale else 'valid', has_manual_data=True, tolerance=Decimal('.02'), asset_classes=[SimpleNamespace(id=CLASS_ID, name='股票', target_weight=Decimal('.5'), actual_weight=Decimal('.5') + Decimal(drift), drift=Decimal(drift))])
CLASS_ID = uuid4()

@pytest.mark.asyncio
async def test_dated_streak_dedup_reset_and_outbox(db_session, monkeypatch):
    monkeypatch.setattr(service, 'current_inputs', AsyncMock(return_value=(analytics(), [])))
    monkeypatch.setattr(service, 'fingerprint', AsyncMock(return_value='rule-one'))
    policy = await service.load_policy(db_session)
    policy.notification_mode = 'attention'
    await db_session.flush()
    for day in range(3):
        assert await service.record_scheduled_observation(db_session, now=NOW + timedelta(days=day))
        assert not await service.record_scheduled_observation(db_session, now=NOW + timedelta(days=day))
    await db_session.flush()
    assert policy.streaks[str(CLASS_ID)]['count'] == 3
    assert len(list(await db_session.scalars(select(NotificationOutbox)))) == 1
    await service.record_scheduled_observation(db_session, now=NOW + timedelta(days=3))
    await db_session.flush()
    assert len(list(await db_session.scalars(select(NotificationOutbox)))) == 1
    monkeypatch.setattr(service, 'current_inputs', AsyncMock(return_value=(None, [{'key': 'price:SPY', 'status': 'failed'}])))
    await service.record_scheduled_observation(db_session, now=NOW + timedelta(days=4))
    assert policy.streaks == {}
    await service.record_scheduled_observation(db_session, now=NOW + timedelta(days=5))
    await db_session.flush()
    assert len(list(await db_session.scalars(select(NotificationOutbox)))) == 2
    monkeypatch.setattr(service, 'fingerprint', AsyncMock(return_value='rule-two'))
    await service.reset_changed_rules(db_session, policy)
    assert policy.streaks == {} and policy.anomalies == {}

@pytest.mark.asyncio
async def test_delivery_retries_and_respects_disabled_mail(db_session, monkeypatch):
    monkeypatch.setattr(service, 'load_email_config', AsyncMock(return_value=None))
    await service.queue_event(db_session, 'review:2026-10', '提醒', '<p>复核</p>')
    policy = await service.load_policy(db_session)
    policy.monthly_email = True
    await db_session.flush()
    await service.deliver_pending_notifications(db_session, now=NOW)
    row = await db_session.get(NotificationOutbox, 'review:2026-10')
    assert row.attempts == 0
    monkeypatch.setattr(service, 'load_email_config', AsyncMock(return_value=object()))
    sender = AsyncMock(side_effect=RuntimeError('SMTP failed'))
    monkeypatch.setattr(service, 'send_email', sender)
    await service.deliver_pending_notifications(db_session, now=NOW)
    assert row.status == 'pending' and row.attempts == 1
    sender.side_effect = None
    await service.deliver_pending_notifications(db_session, now=NOW)
    assert row.status == 'sent' and row.attempts == 2
    await service.deliver_pending_notifications(db_session, now=NOW)
    assert sender.await_count == 2

@pytest.mark.asyncio
async def test_decision_settings_api_preserves_daily_default(api_client):
    result = await api_client.get('/api/decision/settings')
    assert result.status_code == 200, result.text
    assert result.json()['notification_mode'] == 'daily'
    result = await api_client.put('/api/decision/settings', json={'notification_mode': 'attention', 'review_day': 31, 'monthly_email': True})
    assert result.status_code == 200, result.text
    assert (await api_client.get('/api/decision/settings')).json()['review_day'] == 31
    assert (await api_client.put('/api/decision/settings', json={'notification_mode': 'attention', 'review_day': 32, 'monthly_email': True})).status_code == 422

@pytest.mark.asyncio
async def test_old_backup_evidence_and_recovered_drift_do_not_notify(db_session, monkeypatch):
    from decimal import Decimal
    monkeypatch.setattr(service, 'current_inputs', AsyncMock(return_value=(analytics(), [])))
    monkeypatch.setattr(service, 'fingerprint', AsyncMock(return_value='rule-one'))
    policy = await service.load_policy(db_session)
    policy.notification_mode = 'attention'
    for day in range(3):
        await service.record_scheduled_observation(db_session, now=NOW + timedelta(days=day))
    await db_session.flush()
    sender = AsyncMock()
    monkeypatch.setattr(service, 'send_email', sender)
    monkeypatch.setattr(service, 'load_email_config', AsyncMock(return_value=object()))
    monkeypatch.setattr(service, 'current_inputs', AsyncMock(return_value=(analytics(drift='0'), [])))
    await service.deliver_pending_notifications(db_session, now=NOW + timedelta(days=2))
    sender.assert_not_awaited()
    monkeypatch.setattr(service, 'current_inputs', AsyncMock(return_value=(analytics(), [])))
    result = await service.get_decision(db_session, now=NOW + timedelta(days=6))
    assert result['status'] == 'observing'
    assert result['classes'][0]['observations'] == 0
    await service.deliver_pending_notifications(db_session, now=NOW + timedelta(days=6))
    sender.assert_not_awaited()

@pytest.mark.asyncio
async def test_postponed_monthly_review_does_not_deliver_old_pending_mail(db_session, monkeypatch):
    policy = await service.load_policy(db_session)
    policy.monthly_email = True
    await service.queue_event(db_session, 'review:2026-10', '提醒', '<p>复核</p>')
    policy.review_day = 31
    await db_session.flush()
    sender = AsyncMock()
    monkeypatch.setattr(service, 'send_email', sender)
    monkeypatch.setattr(service, 'load_email_config', AsyncMock(return_value=object()))
    await service.deliver_pending_notifications(db_session, now=NOW + timedelta(days=1))
    sender.assert_not_awaited()
    await service.deliver_pending_notifications(db_session, now=NOW + timedelta(days=30))
    sender.assert_awaited_once()
