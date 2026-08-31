from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.db.models import MarketData
from app.db.models import AssetClass, EncryptedSecret, Holding, Setting
from app.schemas.rebalance import TradeSuggestionResponse
from app.services import email_digest as email_digest_service
from app.services.email_digest import (
    run_manual_digest,
    send_daily_digest_if_configured,
)


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

    await send_daily_digest_if_configured(
        db_session,
        now=datetime(2026, 8, 3, 8, 0, tzinfo=UTC),  # Monday
    )

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
    original_preview = email_digest_service.preview_rebalance_with_defaults

    async def preview_with_optimizer_reason(session):
        preview = await original_preview(session)
        trade = TradeSuggestionResponse(
            symbol="510100",
            action="buy",
            quantity="10",
            amount_cny="10",
            amount_trade_currency="10",
            reason_code="REDUCE_MAX_DRIFT",
            reason="该交易用于降低投资组合的最大配置偏离。",
        )
        return preview.model_copy(
            update={"result": preview.result.model_copy(update={"trades": (trade,)})}
        )

    monkeypatch.setattr("app.services.email_digest.send_email", send)
    monkeypatch.setattr(
        "app.services.email_digest.preview_rebalance_with_defaults",
        preview_with_optimizer_reason,
    )

    await send_daily_digest_if_configured(
        db_session,
        now=datetime(2026, 8, 3, 8, 0, tzinfo=UTC),  # Monday
    )

    send.assert_awaited_once()
    subject = send.await_args.kwargs["subject"]
    html = send.await_args.kwargs["html"]
    assert subject.startswith("投资组合日报")
    assert "总市值" in html
    assert "份额" in html
    assert "再平衡建议" in html
    assert "标的0（510100）" in html
    assert "该交易用于降低投资组合的最大配置偏离。" in html
    assert "UNDERWEIGHT_WITH_CASH" not in html


async def test_digest_skipped_for_empty_portfolio(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_not_awaited()


async def _enable_email_using_session(db_session) -> None:
    store = SecretStore(Path(get_settings().secret_key_path))
    await db_session.execute(
        update(Setting).values(
            email_enabled=True,
            email_recipient="owner@example.com",
            email_smtp_host="smtp.qq.com",
            email_smtp_port=465,
            email_smtp_security="ssl",
            email_smtp_username="owner@qq.com",
            email_from=None,
        )
    )
    db_session.add(
        EncryptedSecret(
            provider="smtp",
            encrypted_value=store.encrypt("smtp-auth-code").decode("ascii"),
            masked_value="****code",
        )
    )
    await db_session.commit()


async def _seed_portfolio_using_session(db_session) -> None:
    asset_classes = list(
        await db_session.scalars(
            select(AssetClass).where(AssetClass.is_active.is_(True)).order_by(AssetClass.id)
        )
    )
    now = datetime.now(UTC)
    for index, asset_class in enumerate(asset_classes):
        db_session.add(
            Holding(
                asset_class=asset_class,
                symbol=f"51010{index}",
                name=f"标的{index}",
                market="SH",
                account_name=f"账户{index}",
                trade_currency="CNY",
                quantity=Decimal("20"),
                average_cost_price=Decimal("1"),
                cost_fx_to_cny=Decimal("1"),
                baseline_fx_to_cny=Decimal("1"),
                lot_size=Decimal("1"),
                quantity_precision=12,
                is_rebalance_preferred=True,
            )
        )
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


async def test_manual_digest_not_configured(api_client, monkeypatch) -> None:
    send = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)
    monkeypatch.setattr("app.services.email_digest.refresh_all_required_data", refresh)

    response = await api_client.post("/api/email/digest")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "not_configured", "sent_at": None}
    send.assert_not_awaited()


async def test_manual_digest_skipped_for_empty_portfolio(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _enable_email(api_client, db_session)
    send = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)
    monkeypatch.setattr("app.services.email_digest.refresh_all_required_data", refresh)

    response = await api_client.post("/api/email/digest")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "skipped_empty", "sent_at": None}
    send.assert_not_awaited()


async def test_manual_digest_sends_anomaly_email(api_client, db_session, monkeypatch) -> None:
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
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)
    monkeypatch.setattr("app.services.email_digest.refresh_all_required_data", refresh)

    response = await api_client.post("/api/email/digest")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "anomaly_sent"
    assert response.json()["sent_at"] is not None
    send.assert_awaited_once()
    assert "数据异常" in send.await_args.kwargs["subject"]


async def test_manual_digest_sends_full_digest(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)
    monkeypatch.setattr("app.services.email_digest.refresh_all_required_data", refresh)

    response = await api_client.post("/api/email/digest")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sent"
    send.assert_awaited_once()
    assert send.await_args.kwargs["subject"].startswith("投资组合日报")


async def test_manual_digest_ignores_weekend(api_client, db_session, monkeypatch) -> None:
    await _enable_email_using_session(db_session)
    await _seed_portfolio_using_session(db_session)
    send = AsyncMock()
    refresh = AsyncMock()
    snapshot = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)
    monkeypatch.setattr("app.services.email_digest.refresh_all_required_data", refresh)
    monkeypatch.setattr("app.services.email_digest.create_daily_snapshot_if_complete", snapshot)

    result = await run_manual_digest(now=datetime(2026, 8, 2, 8, 0, tzinfo=UTC))  # Sunday

    assert result.status == "sent"
    send.assert_awaited_once()
