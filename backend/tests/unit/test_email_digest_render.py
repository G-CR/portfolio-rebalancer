from datetime import date

from app.schemas.analytics import (
    AssetClassAnalyticsResponse,
    HoldingAnalyticsResponse,
    PortfolioAnalyticsResponse,
    PortfolioDecisionResponse,
)
from app.schemas.rebalance import (
    ProjectedWeightResponse,
    RebalanceComparisonResponse,
    RebalancePreviewResponse,
    RebalanceResultResponse,
    TradeSuggestionResponse,
)
from app.services.email_digest import build_anomaly_html, build_digest_html


def _holding() -> HoldingAnalyticsResponse:
    return HoldingAnalyticsResponse(
        holding_id="00000000-0000-0000-0000-000000000001",
        asset_class_id="00000000-0000-0000-0000-0000000000aa",
        symbol="SPY",
        name="标普 500",
        account_name="账户A",
        trade_currency="USD",
        quantity="3",
        current_price="100",
        current_fx_to_cny="7.2",
        price_status="valid",
        fx_status="valid",
        cost_trade_currency="270",
        market_value_trade_currency="300",
        unrealized_pnl_trade_currency="30",
        cost_cny="1944",
        market_value_cny="2160",
        fx_neutral_value_cny="2040",
        unrealized_pnl="216",
        unrealized_return="0.111111111111",
        price_effect="189",
        fx_effect="27",
    )


def _asset_class() -> AssetClassAnalyticsResponse:
    return AssetClassAnalyticsResponse(
        id="00000000-0000-0000-0000-0000000000aa",
        name="美股",
        target_weight="0.5",
        display_order=1,
        actual_weight="0.5",
        fx_neutral_weight="0.48",
        drift="0",
        fx_weight_contribution="0.02",
        cost_cny="1944",
        market_value_cny="2160",
        fx_neutral_value_cny="2040",
        unrealized_pnl="216",
        price_effect="189",
        fx_effect="27",
    )


def _analytics() -> PortfolioAnalyticsResponse:
    return PortfolioAnalyticsResponse(
        as_of=None,
        data_status="valid",
        has_stale_data=False,
        has_manual_data=False,
        tolerance="0.02",
        cost_cny="1944",
        market_value_cny="2160",
        fx_neutral_value_cny="2040",
        unrealized_pnl="216",
        unrealized_return="0.111111111111",
        price_effect="189",
        fx_effect="27",
        overseas_weight="1",
        decision=PortfolioDecisionResponse(
            status="rebalance",
            title="建议再平衡",
            reason="至少一个资产类别超出策略区间。",
            max_drift="0.05",
            fx_contribution="0.02",
            primary_action="view_rebalance",
        ),
        asset_classes=[_asset_class()],
        holdings=[_holding()],
        data_inputs=[],
    )


def _result() -> RebalanceResultResponse:
    return RebalanceResultResponse(
        feasible=True,
        max_drift_before="0.05",
        max_drift_after="0.01",
        fx_required_cny="0",
        remaining_cny="0",
        remaining_usd="0",
        projected_weights=(
            ProjectedWeightResponse(
                asset_class_id="00000000-0000-0000-0000-0000000000aa",
                before="0.5",
                after="0.5",
                target="0.5",
            ),
        ),
        trades=(
            TradeSuggestionResponse(
                symbol="SPY",
                action="buy",
                quantity="0.1",
                amount_cny="72",
                amount_trade_currency="10",
                reason_code="UNDERWEIGHT_WITH_CASH",
                reason="当前低配，可直接使用同币种现金补足目标仓位。",
            ),
        ),
    )


def _rebalance() -> RebalancePreviewResponse:
    result = _result()
    return RebalancePreviewResponse(
        session_token="t",
        request_token="r",
        status="ok",
        data_status="valid",
        acknowledge_stale_data=True,
        refresh_attempted=False,
        valuation_basis="actual",
        result=result,
        fx_comparison=RebalanceComparisonResponse(
            valuation_basis="fx_neutral",
            result=result,
        ),
    )


def test_digest_html_contains_summary_holdings_and_trades() -> None:
    html = build_digest_html(
        analytics=_analytics(),
        rebalance=_rebalance(),
        local_date=date(2026, 8, 3),
    )

    assert "投资组合日报" in html
    assert "2026-08-03" in html
    assert "总市值" in html
    assert "标普 500" in html
    assert "SPY" in html
    assert "建议再平衡" in html
    assert "买入" in html
    assert "72.00" in html
    assert "当前配置在容差内" not in html


def test_digest_html_no_trades_shows_hold_copy() -> None:
    empty = _result().model_copy(update={"trades": ()})
    html = build_digest_html(
        analytics=_analytics(),
        rebalance=RebalancePreviewResponse(
            session_token="t",
            request_token="r",
            status="ok",
            data_status="valid",
            acknowledge_stale_data=True,
            refresh_attempted=False,
            valuation_basis="actual",
            result=empty,
            fx_comparison=RebalanceComparisonResponse(
                valuation_basis="fx_neutral",
                result=empty,
            ),
        ),
        local_date=date(2026, 8, 3),
    )

    assert "当前配置在容差内，无需调整" in html


def test_digest_html_escapes_holding_names() -> None:
    holding = _holding().model_copy(update={"name": "A&B <ETF>"})
    analytics = _analytics().model_copy(update={"holdings": [holding]})

    html = build_digest_html(
        analytics=analytics,
        rebalance=None,
        local_date=date(2026, 8, 3),
    )

    assert "A&amp;B &lt;ETF&gt;" in html
    assert "A&B <ETF>" not in html
    assert "再平衡建议暂不可用" in html


def test_digest_html_stale_banner() -> None:
    analytics = _analytics().model_copy(update={"has_stale_data": True})

    html = build_digest_html(
        analytics=analytics,
        rebalance=None,
        local_date=date(2026, 8, 3),
    )

    assert "部分行情数据可能过期" in html


def test_anomaly_html_lists_items_without_analysis() -> None:
    html = build_anomaly_html(
        items=[
            {
                "holding_id": "00000000-0000-0000-0000-000000000001",
                "symbol": "SPY",
                "input": "price",
                "key": "price:SPY",
                "status": "failed",
                "value": None,
                "market_time": None,
                "source": "yahoo",
                "error_summary": "provider_request_failed: hidden",
            }
        ],
        local_date=date(2026, 8, 3),
    )

    assert "数据异常" in html
    assert "SPY" in html
    assert "price" in html
    assert "总市值" not in html
