from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import email_digest


@pytest.mark.parametrize(
    "now, expected_date",
    [
        (datetime(2026, 10, 12, 0, tzinfo=UTC), None),  # Monday
        *[
            (datetime(2026, 10, day, 0, tzinfo=UTC), date(2026, 10, day))
            for day in range(13, 18)  # Tuesday through Saturday
        ],
        (datetime(2026, 10, 18, 0, tzinfo=UTC), None),  # Sunday
        # Local midnight crosses the send-day boundary before UTC does.
        (datetime(2026, 10, 12, 16, tzinfo=UTC), date(2026, 10, 13)),
        (datetime(2026, 10, 17, 16, tzinfo=UTC), None),
    ],
)
async def test_scheduled_digest_sends_tuesday_through_saturday_in_local_timezone(
    monkeypatch, now, expected_date
):
    session = object()
    config = object()
    monkeypatch.setattr(
        "app.services.decision.load_policy",
        AsyncMock(return_value=SimpleNamespace(notification_mode="daily")),
    )
    monkeypatch.setattr(email_digest, "load_email_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        email_digest, "get_settings", lambda: SimpleNamespace(timezone="Asia/Shanghai")
    )
    run_digest = AsyncMock()
    monkeypatch.setattr(email_digest, "_run_digest", run_digest)

    await email_digest.send_daily_digest_if_configured(session, now=now)

    if expected_date is None:
        run_digest.assert_not_awaited()
    else:
        run_digest.assert_awaited_once_with(session, config, expected_date)
