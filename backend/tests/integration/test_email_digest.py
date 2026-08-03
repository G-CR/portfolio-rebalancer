from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

from app.db.models import MarketData
from app.services.email_digest import send_daily_digest_if_configured


async def _enable_email(api_client, db_session) -> None:
    response = await api_client.put(
        "/api/settings/email",
        json={
            "enabled": True,
            "recipient": "owner@example.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
            "smtp_security": "ssl",
            "smtp_username": "owner@qq.com",
            "from_address": None,
            "password": "smtp-auth-code",
        },
    )
    assert response.status_code == 200, response.text


async def _seed_portfolio(api_client, db_session) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    for index, asset_class in enumerate(asset_classes):
        response = await api_client.post(
            "/api/holdings",
            json={
                "asset_class_id": asset_class["id"],
                "symbol": f"51010{index}",
                "name": f"标的{index}",
                "market": "SH",
                "account_name": f"账户{index}",
                "trade_currency": "CNY",
                "quantity": "20",
                "average_cost_price": "1",
                "cost_fx_to_cny": "1",
                "baseline_fx_to_cny": "1",
                "lot_size": "1",
                "quantity_precision": 12,
                "is_rebalance_preferred": True,
            },
        )
        assert response.status_code == 201, response.text
        now = datetime.now(UTC)
        db_session.add(
            MarketData(
                data_type="price",
                symbol=f"51010{index}",
                source="test-provider",
                value=Decimal("1"),
                market_time=now,
                fetched_at=now,
                status="valid",
            )
        )
    await db_session.commit()


async def test_digest_skipped_when_email_disabled(api_client, db_session, monkeypatch) -> None:
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_not_awaited()


async def test_digest_skipped_on_weekend(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(
        db_session,
        now=datetime(2026, 8, 2, 8, 0, tzinfo=UTC),  # Sunday
    )

    send.assert_not_awaited()


async def test_digest_sends_anomaly_email_when_data_incomplete(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _enable_email(api_client, db_session)
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    await api_client.post(
        "/api/holdings",
        json={
            "asset_class_id": asset_classes[0]["id"],
            "symbol": "MISSING",
            "name": "缺失标的",
            "market": "SH",
            "account_name": "账户",
            "trade_currency": "CNY",
            "quantity": "10",
            "average_cost_price": "1",
            "cost_fx_to_cny": "1",
            "baseline_fx_to_cny": "1",
            "lot_size": "1",
            "quantity_precision": 12,
            "is_rebalance_preferred": True,
        },
    )
    await db_session.commit()
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_awaited_once()
    subject = send.await_args.kwargs["subject"]
    html = send.await_args.kwargs["html"]
    assert "数据异常" in subject
    assert "MISSING" in html
    assert "总市值" not in html


async def test_digest_sends_full_analysis_email(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_awaited_once()
    subject = send.await_args.kwargs["subject"]
    html = send.await_args.kwargs["html"]
    assert subject.startswith("投资组合日报")
    assert "总市值" in html
    assert "标的0" in html
    assert "再平衡建议" in html


async def test_digest_skipped_for_empty_portfolio(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_not_awaited()
