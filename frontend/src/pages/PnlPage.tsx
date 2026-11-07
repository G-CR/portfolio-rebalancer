import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import type { PortfolioIncompleteItem } from "../api/types";
import { decimalSign, formatAmount, formatPercent, formatSignedAmount } from "../features/analytics/format";
import { usePortfolioAnalytics } from "../features/analytics/api";
import styles from "./PnlPage.module.css";
import { PageError } from "./PageState";

type View = "cny" | "trade";

function pnlState(value: string) {
  const sign = decimalSign(value);
  return { label: sign < 0 ? "亏损" : sign > 0 ? "盈利" : "持平", className: sign < 0 ? styles.negative : sign > 0 ? styles.positive : styles.neutral };
}

function formatSignedCurrency(value: string, currency: string) {
  const formatted = formatSignedAmount(value);
  if (!/^[+−±]/.test(formatted)) return `${currency} ${formatted}`;
  return `${formatted[0]} ${currency} ${formatted.slice(1)}`;
}

export function PnlPage() {
  const [view, setView] = useState<View>("cny");
  const portfolio = usePortfolioAnalytics();
  if (portfolio.isPending) return <section className={styles.loading} role="status">正在载入盈亏分析</section>;
  if (portfolio.isError) {
    if (portfolio.error instanceof ApiError && portfolio.error.code === "PORTFOLIO_DATA_INCOMPLETE") {
      const items = Array.isArray(portfolio.error.detail.items) ? portfolio.error.detail.items as unknown as PortfolioIncompleteItem[] : [];
      return <section className={styles.incomplete} role="alert"><strong>盈亏数据不完整</strong><p>补充以下必需数据后可继续计算当前持仓盈亏。</p><ul>{items.map((item) => <li key={`${item.holding_id}-${item.input}`}>{item.symbol} · {item.input === "price" ? "当前价" : "当前汇率"}</li>)}</ul><button type="button" onClick={() => void portfolio.refetch()}><RefreshCw size={16} aria-hidden="true" />重试载入盈亏</button></section>;
    }
    const message = portfolio.error instanceof ApiError ? portfolio.error.message : "盈亏分析载入失败。";
    return <PageError title="盈亏分析无法载入" message={message} retryLabel="重试载入盈亏" onRetry={() => void portfolio.refetch()} />;
  }
  const data = portfolio.data;
  if (data.decision.status === "setup") return <section className={styles.empty}><strong>尚无持仓盈亏</strong><p>添加持仓与有效市场数据后，这里将显示当前浮动盈亏。</p></section>;

  const totalPnlState = pnlState(data.unrealized_pnl);
  return (
    <section className={styles.page} aria-labelledby="pnl-title">
      <header className={styles.header}>
        <div><p>P&amp;L ANALYSIS</p><h2 id="pnl-title">盈亏分析</h2><span>当前持仓，不含已实现盈亏；人民币金额按当前汇率折算，仅供参考。</span></div>
      </header>
      <dl className={styles.metrics}>
        <div><dt>参考成本</dt><dd>{formatAmount(data.cost_cny, 2)}<small>CNY</small></dd></div>
        <div><dt>当前市值</dt><dd>{formatAmount(data.market_value_cny, 2)}<small>CNY</small></dd></div>
        <div><dt>浮动盈亏</dt><dd className={totalPnlState.className}><em>{totalPnlState.label}</em>{formatSignedAmount(data.unrealized_pnl)}<small>{formatPercent(data.unrealized_return, 2)}</small></dd></div>
      </dl>
      <div className={styles.detailsHeading}>
        <h3 id="pnl-details-title">持仓明细</h3>
        <div className={styles.detailControls}>
          <span>明细币种</span>
          <div className={styles.segmented} role="group" aria-label="持仓明细币种">
            <button type="button" aria-pressed={view === "cny"} onClick={() => setView("cny")}>人民币参考</button>
            <button type="button" aria-pressed={view === "trade"} onClick={() => setView("trade")}>交易币种</button>
          </div>
        </div>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table} aria-labelledby="pnl-details-title">
          <thead><tr><th scope="col">标的 / 类别</th><th scope="col">成本</th><th scope="col">{view === "cny" ? "人民币市值" : "交易币种市值"}</th><th scope="col">浮动盈亏</th><th scope="col">收益率</th></tr></thead>
          <tbody>{data.holdings.map((item) => {
            const assetClass = data.asset_classes.find((candidate) => candidate.id === item.asset_class_id);
            const prefix = view === "trade" ? `${item.trade_currency} ` : "";
            const cost = view === "trade" ? item.cost_trade_currency : item.cost_cny;
            const market = view === "trade" ? item.market_value_trade_currency : item.market_value_cny;
            const pnl = view === "trade" ? item.unrealized_pnl_trade_currency : item.unrealized_pnl;
            const state = pnlState(pnl);
            const amount = view === "trade" ? formatSignedCurrency(pnl, item.trade_currency) : formatSignedAmount(pnl);
            return <tr key={item.holding_id}><td><strong>{item.symbol}</strong><span>{assetClass?.name}</span></td><td>{prefix}{formatAmount(cost, 2)}</td><td>{prefix}{formatAmount(market, 2)}</td><td><span className={`${styles.pnlValue} ${state.className}`}><small>{state.label}</small><span>{amount}</span></span></td><td>{formatPercent(item.unrealized_return, 2)}</td></tr>;
          })}</tbody>
        </table>
      </div>
      <footer className={styles.footer}>原币盈亏 = 原币市值 − 原币成本 · 费用已包含在平均成本价中 · 人民币盈亏按当前汇率折算</footer>
    </section>
  );
}
