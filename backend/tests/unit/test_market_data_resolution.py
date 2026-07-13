from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.market_data import AutomatedValue, ManualOverride, resolve_effective_value


def test_active_manual_override_wins_over_newer_automated_value() -> None:
    now = datetime(2026, 7, 13, 1, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=Decimal("7.20"),
            source="yahoo",
            as_of=now,
            fetched_at=now,
            status="valid",
        ),
        override=ManualOverride(
            value=Decimal("7.18"),
            note="券商结算参考",
            starts_at=now - timedelta(hours=1),
            expires_at=None,
        ),
        now=now,
    )

    assert result.value == Decimal("7.18")
    assert result.status == "manual"
    assert result.source == "manual"


def test_newest_valid_automated_value_is_used_without_override() -> None:
    now = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=Decimal("651.28"),
            source="yahoo",
            as_of=now - timedelta(hours=8),
            fetched_at=now - timedelta(hours=1),
            status="valid",
        ),
        override=None,
        now=now,
    )

    assert result.value == Decimal("651.28")
    assert result.status == "valid"
    assert result.source == "yahoo"


def test_stale_automated_value_is_returned_when_last_refresh_failed() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=Decimal("530.25"),
            source="yahoo",
            as_of=now - timedelta(days=1),
            fetched_at=now - timedelta(minutes=15),
            status="stale",
            error_summary="provider timeout",
        ),
        override=ManualOverride(
            value=Decimal("531.00"),
            note="已过期覆盖",
            starts_at=now - timedelta(days=2),
            expires_at=now - timedelta(minutes=1),
        ),
        now=now,
    )

    assert result.value == Decimal("530.25")
    assert result.status == "stale"
    assert result.source == "yahoo"
    assert result.error_summary == "provider timeout"


def test_failed_only_attempt_has_no_effective_numeric_value() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=None,
            source="yahoo",
            as_of=None,
            fetched_at=now - timedelta(minutes=5),
            status="failed",
            error_summary="provider timeout",
        ),
        override=None,
        now=now,
    )

    assert result.value is None
    assert result.status == "failed"
    assert result.source == "yahoo"
    assert result.as_of is None
    assert result.fetched_at == now - timedelta(minutes=5)
    assert result.error_summary == "provider timeout"


def test_active_manual_override_wins_over_failed_only_attempt() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=None,
            source="yahoo",
            as_of=None,
            fetched_at=now - timedelta(minutes=5),
            status="failed",
            error_summary="provider timeout",
        ),
        override=ManualOverride(
            value=Decimal("649.90"),
            note="broker close",
            starts_at=now - timedelta(minutes=1),
            expires_at=None,
        ),
        now=now,
    )

    assert result.value == Decimal("649.90")
    assert result.status == "manual"
    assert result.source == "manual"
    assert result.error_summary is None


def test_expired_override_reveals_failed_only_attempt() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=None,
            source="yahoo",
            as_of=None,
            fetched_at=now - timedelta(minutes=5),
            status="failed",
            error_summary="provider timeout",
        ),
        override=ManualOverride(
            value=Decimal("649.90"),
            note="expired broker close",
            starts_at=now - timedelta(hours=1),
            expires_at=now - timedelta(minutes=1),
        ),
        now=now,
    )

    assert result.value is None
    assert result.status == "failed"
    assert result.source == "yahoo"
    assert result.error_summary == "provider timeout"
