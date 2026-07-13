import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ApiError } from "../api/client";
import type { PortfolioIncompleteItem } from "../api/types";
import { formatAmount, formatPercent, formatSignedAmount } from "../features/analytics/format";
import { usePortfolioAnalytics } from "../features/analytics/api";
import styles from "./PnlPage.module.css";
import { PageError } from "./PageState";

type View = "cny" | "trade";

function pnlState(value: string) {
  const numeric = Number(value);
  return { label: numeric < 0 ? "亏损" : numeric > 0 ? "盈利" : "持平", className: numeric < 0 ? styles.negative : numeric > 0 ? styles.positive : styles.neutral };
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

  const chartData = data.asset_classes.map((item) => ({ name: item.name, price: Number(item.price_effect), fx: Number(item.fx_effect) }));
  const totalPnlState = pnlState(data.unrealized_pnl);
  return (
    <section className={styles.page} aria-labelledby="pnl-title">
      <header className={styles.header}>
        <div><p>P&amp;L ANALYSIS</p><h2 id="pnl-title">盈亏分析</h2><span>当前持仓，不含已实现盈亏</span></div>
        <div className={styles.segmented} role="group" aria-label="金额口径">
          <button type="button" aria-pressed={view === "cny"} onClick={() => setView("cny")}>人民币</button>
          <button type="button" aria-pressed={view === "trade"} onClick={() => setView("trade")}>交易币种</button>
        </div>
      </header>
      <dl className={styles.metrics}>
        <div><dt>总成本</dt><dd>{formatAmount(data.cost_cny, 2)}<small>CNY</small></dd></div>
        <div><dt>当前市值</dt><dd>{formatAmount(data.market_value_cny, 2)}<small>CNY</small></dd></div>
        <div><dt>浮动盈亏</dt><dd className={totalPnlState.className}><em>{totalPnlState.label}</em>{formatSignedAmount(data.unrealized_pnl)}<small>{formatPercent(data.unrealized_return, 2)}</small></dd></div>
      </dl>
      <section className={styles.chartSection} aria-labelledby="pnl-chart-title">
        <div className={styles.sectionHeading}><div><p>DECOMPOSITION</p><h3 id="pnl-chart-title">价格与汇率影响</h3></div><span>人民币口径</span></div>
        <div className={styles.chart} role="img" aria-label="各资产类别价格与汇率影响图">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid stroke="var(--color-rule)" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 9 }} width={54} />
              <Tooltip formatter={(value) => Number(value).toLocaleString("zh-CN")} />
              <Bar dataKey="price" name="价格影响" fill="var(--color-actual)" stackId="pnl" />
              <Bar dataKey="fx" name="汇率影响" fill="var(--color-fx)" stackId="pnl" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th scope="col">标的 / 类别</th><th scope="col">成本</th><th scope="col">{view === "cny" ? "人民币市值" : "交易币种市值"}</th><th scope="col">浮动盈亏</th><th scope="col">收益率</th><th scope="col">价格影响</th><th scope="col">汇率影响</th></tr></thead>
          <tbody>{data.holdings.map((item) => {
            const assetClass = data.asset_classes.find((candidate) => candidate.id === item.asset_class_id);
            const prefix = view === "trade" ? `${item.trade_currency} ` : "";
            const cost = view === "trade" ? item.cost_trade_currency : item.cost_cny;
            const market = view === "trade" ? item.market_value_trade_currency : item.market_value_cny;
            const pnl = view === "trade" ? item.unrealized_pnl_trade_currency : item.unrealized_pnl;
            const state = pnlState(pnl);
            const amount = view === "trade" ? `${Number(pnl) >= 0 ? "+ " : "− "}${prefix}${formatAmount(String(Math.abs(Number(pnl))), 2)}` : formatSignedAmount(pnl);
            return <tr key={item.holding_id}><td><strong>{item.symbol}</strong><span>{assetClass?.name}</span></td><td>{prefix}{formatAmount(cost, 2)}</td><td>{prefix}{formatAmount(market, 2)}</td><td><span className={`${styles.pnlValue} ${state.className}`}><small>{state.label}</small><span>{amount}</span></span></td><td>{formatPercent(item.unrealized_return, 2)}</td><td>{view === "trade" ? `${prefix}${formatSignedAmount(item.unrealized_pnl_trade_currency)}` : formatSignedAmount(item.price_effect)}</td><td>{view === "trade" ? "不适用" : formatSignedAmount(item.fx_effect)}</td></tr>;
          })}</tbody>
        </table>
      </div>
      <footer className={styles.footer}>浮动盈亏 = 价格影响 + 汇率影响 · 费用已包含在平均成本价中</footer>
    </section>
  );
}
