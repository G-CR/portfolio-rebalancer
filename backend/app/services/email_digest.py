from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import logging
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.schemas.analytics import PortfolioAnalyticsResponse
from app.schemas.email_settings import EmailDigestTriggerResult
from app.schemas.rebalance import RebalancePreviewResponse
from app.services.analytics import get_portfolio_analytics
from app.services.email_sender import send_email
from app.services.email_settings import load_email_config
from app.services.errors import ServiceError
from app.services.market_data import refresh_all_required_data
from app.services.rebalancing import preview_rebalance_with_defaults
from app.services.snapshots import create_daily_snapshot_if_complete

logger = logging.getLogger(__name__)


def _esc(value: object) -> str:
    return escape(str(value))


def _money(value: object) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _signed_money(value: object) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):+,.2f}"


def _percent(value: object) -> str:
    return f"{Decimal(str(value)) * 100:.2f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f"<th style=\"padding:6px 10px;border-bottom:1px solid #ddd;text-align:left;font-size:12px;\">{_esc(header)}</th>"
        for header in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td style=\"padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;\">{cell}</td>"
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return f"<table style=\"border-collapse:collapse;width:100%;\"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build_digest_html(
    *,
    analytics: PortfolioAnalyticsResponse,
    rebalance: RebalancePreviewResponse | None,
    local_date: date,
) -> str:
    stale_banner = ""
    if analytics.has_stale_data:
        stale_banner = (
            "<p style=\"background:#fff7e0;border:1px solid #e0b94d;color:#7a5a00;"
            "padding:10px;font-size:13px;\">部分行情数据可能过期，以下内容基于最近有效数据。</p>"
        )

    decision = analytics.decision
    summary_rows = [
        ["总市值 (CNY)", _money(analytics.market_value_cny)],
        ["总浮动盈亏 (CNY)", _signed_money(analytics.unrealized_pnl)],
        ["总盈亏率", _percent(analytics.unrealized_return)],
        ["决策", f"{_esc(decision.title)}（{_esc(decision.reason)}）"],
        [
            "数据时间",
            _esc(analytics.as_of.strftime("%Y-%m-%d %H:%M:%S %Z") if analytics.as_of else "-"),
        ],
    ]

    class_rows = [
        [
            _esc(item.name),
            _percent(item.target_weight),
            _percent(item.actual_weight),
            f"{Decimal(item.drift) * 100:+.2f}%",
            _signed_money(item.unrealized_pnl),
        ]
        for item in analytics.asset_classes
    ]

    class_names = {item.id: item.name for item in analytics.asset_classes}
    holdings_by_class: list[tuple[str, list]] = []
    for holding in analytics.holdings:
        name = class_names.get(holding.asset_class_id, "未分类")
        if holdings_by_class and holdings_by_class[-1][0] == name:
            holdings_by_class[-1][1].append(holding)
        else:
            holdings_by_class.append((name, [holding]))

    holding_sections = []
    for class_name, holdings in holdings_by_class:
        rows = [
            [
                _esc(holding.name),
                _esc(holding.symbol),
                _esc(holding.account_name),
                _esc(holding.quantity),
                _esc(holding.current_price),
                _esc(holding.current_fx_to_cny),
                _money(holding.market_value_cny),
                _signed_money(holding.unrealized_pnl),
                _percent(holding.unrealized_return),
                _signed_money(holding.price_effect),
                _signed_money(holding.fx_effect),
            ]
            for holding in holdings
        ]
        holding_sections.append(
            f"<h3 style=\"margin:18px 0 6px;font-size:14px;\">{_esc(class_name)}</h3>"
            + _table(
                [
                    "名称",
                    "代码",
                    "账户",
                    "份额",
                    "现价",
                    "汇率",
                    "市值 (CNY)",
                    "浮动盈亏 (CNY)",
                    "盈亏率",
                    "价格影响",
                    "汇率影响",
                ],
                rows,
            )
        )

    if rebalance is not None and rebalance.result.trades:
        trade_rows = [
            [
                _esc(trade.symbol),
                "买入" if trade.action == "buy" else "卖出",
                _esc(trade.quantity),
                _money(trade.amount_cny),
                _esc(trade.reason),
            ]
            for trade in rebalance.result.trades
        ]
        rebalance_html = _table(
            ["标的", "方向", "数量", "金额 (CNY)", "原因"],
            trade_rows,
        )
    elif rebalance is not None:
        rebalance_html = "<p style=\"font-size:13px;\">当前配置在容差内，无需调整。</p>"
    else:
        rebalance_html = "<p style=\"font-size:13px;\">再平衡建议暂不可用。</p>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Microsoft YaHei',sans-serif;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;padding:24px;border:1px solid #e5e5e5;">
    <h1 style="margin:0 0 4px;font-size:20px;">投资组合日报</h1>
    <p style="margin:0 0 16px;color:#666;font-size:12px;">{_esc(local_date.isoformat())}</p>
    {stale_banner}
    <h2 style="font-size:14px;">组合摘要</h2>
    {_table(["指标", "数值"], summary_rows)}
    <h2 style="font-size:14px;margin-top:18px;">资产类别</h2>
    {_table(["名称", "目标占比", "实际占比", "偏移", "浮动盈亏 (CNY)"], class_rows)}
    <h2 style="font-size:14px;margin-top:18px;">持仓盈亏明细</h2>
    {''.join(holding_sections) or '<p style="font-size:13px;">暂无持仓。</p>'}
    <h2 style="font-size:14px;margin-top:18px;">再平衡建议</h2>
    {rebalance_html}
    <p style="margin-top:20px;color:#999;font-size:11px;">再平衡建议基于当前默认约束计算，仅供参考。</p>
  </div>
</body>
</html>"""


def build_anomaly_html(*, items: list[dict[str, object]], local_date: date) -> str:
    rows = [
        [
            _esc(item.get("symbol", "-")),
            _esc(item.get("input", "-")),
            _esc(item.get("key", "-")),
            _esc(item.get("status", "-")),
            _esc(item.get("source", "-") or "-"),
            _esc(item.get("error_summary", "-") or "-"),
        ]
        for item in items
    ]
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Microsoft YaHei',sans-serif;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;padding:24px;border:1px solid #e5e5e5;">
    <h1 style="margin:0 0 4px;font-size:20px;">投资组合日报（数据异常）</h1>
    <p style="margin:0 0 16px;color:#666;font-size:12px;">{_esc(local_date.isoformat())}</p>
    <p style="font-size:13px;">部分必要行情或汇率数据不完整，本次未生成盈亏分析与再平衡建议。请到「数据源」页面检查以下异常项：</p>
    {_table(["标的", "类型", "数据项", "状态", "来源", "错误摘要"], rows)}
  </div>
</body>
</html>"""


def _is_trading_day(local_date: date) -> bool:
    return local_date.weekday() < 5


async def send_daily_digest_if_configured(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> None:
    config = await load_email_config(session)
    if config is None:
        return
    local_now = now or datetime.now(UTC)
    local_date = local_now.astimezone(ZoneInfo(get_settings().timezone)).date()
    if not _is_trading_day(local_date):
        return
    await _run_digest(session, config, local_date)


async def _run_digest(session: AsyncSession, config, local_date: date) -> str:
    try:
        analytics = await get_portfolio_analytics(session)
    except ServiceError as exc:
        if exc.code == "PORTFOLIO_DATA_INCOMPLETE":
            await send_email(
                config,
                subject=f"投资组合日报 {local_date.isoformat()}（数据异常）",
                html=build_anomaly_html(items=exc.extra["items"], local_date=local_date),
            )
            return "anomaly_sent"
        raise
    if analytics.data_status == "setup" or not analytics.holdings:
        return "skipped_empty"

    rebalance: RebalancePreviewResponse | None = None
    try:
        rebalance = await preview_rebalance_with_defaults(session)
    except ServiceError:
        rebalance = None
    await send_email(
        config,
        subject=f"投资组合日报 {local_date.isoformat()}",
        html=build_digest_html(
            analytics=analytics,
            rebalance=rebalance,
            local_date=local_date,
        ),
    )
    return "sent"


async def trigger_manual_digest(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> EmailDigestTriggerResult:
    config = await load_email_config(session)
    if config is None:
        return EmailDigestTriggerResult(status="not_configured", sent_at=None)
    local_now = now or datetime.now(UTC)
    local_date = local_now.astimezone(ZoneInfo(get_settings().timezone)).date()
    status = await _run_digest(session, config, local_date)
    sent_at = datetime.now(UTC) if status in {"sent", "anomaly_sent"} else None
    return EmailDigestTriggerResult(status=status, sent_at=sent_at)


async def run_manual_digest(*, now: datetime | None = None) -> EmailDigestTriggerResult:
    async with SessionFactory() as session:
        async with session.begin():
            await refresh_all_required_data(session)
    try:
        async with SessionFactory() as session:
            async with session.begin():
                await create_daily_snapshot_if_complete(session)
    except Exception:
        logger.exception("Daily snapshot creation failed before manual email digest")
    async with SessionFactory() as session:
        async with session.begin():
            return await trigger_manual_digest(session, now=now)
