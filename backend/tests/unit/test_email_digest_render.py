from datetime import UTC, date, datetime

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
        current_fx_to_cny="7.26",
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
    assert "美股" in html
    assert "SPY" in html
    assert "标普 500（SPY）" in html
    assert ">原因</th>" not in html
    assert "当前低配，可直接使用同币种现金补足目标仓位。" not in html
    assert "建议再平衡" in html
    assert "买入" in html
    assert "72.00" in html
    assert "2,160.00" in html
    assert "216.00" in html
    assert "11.1%" in html
    assert "11.11%" not in html
    assert "50.0%" in html
    assert "+0.0%" in html
    assert "3.0" in html
    assert "100.0" in html
    assert "账户A" not in html
    assert "当前配置在容差内" not in html


def test_digest_html_omits_optimizer_trade_reason_column() -> None:
    optimizer_reason = "该交易用于降低投资组合的最大配置偏离。"
    trade = _result().trades[0].model_copy(
        update={"reason_code": "REDUCE_MAX_DRIFT", "reason": optimizer_reason}
    )
    preview = _rebalance()
    preview = preview.model_copy(
        update={"result": preview.result.model_copy(update={"trades": (trade,)})}
    )

    html = build_digest_html(
        analytics=_analytics(),
        rebalance=preview,
        local_date=date(2026, 8, 3),
    )

    assert ">原因</th>" not in html
    assert optimizer_reason not in html
    assert "标普 500（SPY）" in html


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


def _render_trade_label(
    *, holding_symbol: str, holding_name: str, trade_symbol: str
) -> str:
    holding = _holding().model_copy(
        update={"symbol": holding_symbol, "name": holding_name}
    )
    analytics = _analytics().model_copy(update={"holdings": [holding]})
    trade = _result().trades[0].model_copy(update={"symbol": trade_symbol})
    result = _result().model_copy(update={"trades": (trade,)})
    rebalance = _rebalance().model_copy(
        update={
            "result": result,
            "fx_comparison": RebalanceComparisonResponse(
                valuation_basis="fx_neutral",
                result=result,
            ),
        }
    )
    return build_digest_html(
        analytics=analytics,
        rebalance=rebalance,
        local_date=date(2026, 8, 26),
    )


def test_digest_html_shows_symbol_once_when_holding_name_matches() -> None:
    html = _render_trade_label(
        holding_symbol="QQQ",
        holding_name="QQQ",
        trade_symbol="QQQ",
    )

    assert "QQQ" in html
    assert "QQQ（QQQ）" not in html


def test_digest_html_falls_back_to_symbol_when_trade_has_no_holding() -> None:
    html = _render_trade_label(
        holding_symbol="SPY",
        holding_name="标普 500",
        trade_symbol="159209",
    )

    assert "159209" in html
    assert "标普 500（159209）" not in html


def test_digest_html_falls_back_when_one_symbol_has_different_names() -> None:
    first = _holding().model_copy(update={"symbol": "159209", "name": "名称 A"})
    second = _holding().model_copy(
        update={
            "holding_id": "00000000-0000-0000-0000-000000000002",
            "symbol": "159209",
            "name": "名称 B",
        }
    )
    analytics = _analytics().model_copy(update={"holdings": [first, second]})
    trade = _result().trades[0].model_copy(update={"symbol": "159209"})
    result = _result().model_copy(update={"trades": (trade,)})
    rebalance = _rebalance().model_copy(update={"result": result})

    html = build_digest_html(
        analytics=analytics,
        rebalance=rebalance,
        local_date=date(2026, 8, 26),
    )

    assert "159209" in html
    assert "名称 A（159209）" not in html
    assert "名称 B（159209）" not in html


def test_digest_html_escapes_the_complete_trade_label() -> None:
    html = _render_trade_label(
        holding_symbol="159209",
        holding_name="成长<&",
        trade_symbol="159209",
    )

    assert "成长&lt;&amp;（159209）" in html
    assert "成长<&（159209）" not in html


def test_digest_html_escapes_asset_class_names() -> None:
    asset_class = _asset_class().model_copy(update={"name": "A&B <ETF>"})
    analytics = _analytics().model_copy(update={"asset_classes": [asset_class]})

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


def test_digest_html_shows_data_time_in_shanghai() -> None:
    analytics = _analytics().model_copy(
        update={"as_of": datetime(2026, 8, 3, 16, 0, tzinfo=UTC)}
    )

    html = build_digest_html(
        analytics=analytics,
        rebalance=None,
        local_date=date(2026, 8, 3),
    )

    assert "2026-08-04 00:00:00" in html
    assert "16:00:00 UTC" not in html


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
