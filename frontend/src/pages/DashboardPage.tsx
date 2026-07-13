import { RefreshCw } from "lucide-react";

import { ApiError } from "../api/client";
import type { PortfolioIncompleteItem } from "../api/types";
import { CalibrationRail } from "../components/CalibrationRail/CalibrationRail";
import { DecisionBanner } from "../features/analytics/DecisionBanner";
import { formatDataTime, formatDecimal, statusLabel } from "../features/analytics/format";
import { PnlBreakdown } from "../features/analytics/PnlBreakdown";
import { PortfolioMetrics } from "../features/analytics/PortfolioMetrics";
import { usePortfolioAnalytics } from "../features/analytics/api";
import styles from "./DashboardPage.module.css";
import { PageError } from "./PageState";

function AnalyticsLoading() {
  return <section className={styles.loading} role="status" aria-label="正在载入组合分析"><span /><span /><span /><span /></section>;
}

function IncompleteState({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  const items = Array.isArray(error.detail.items) ? error.detail.items as unknown as PortfolioIncompleteItem[] : [];
  return (
    <section className={styles.incomplete} role="alert">
      <strong>组合数据不完整</strong>
      <p>以下必需行情或汇率没有可用值。补充数据后可继续查看组合分析。</p>
      <ul>{items.map((item) => <li key={`${item.holding_id}-${item.input}`}><b>{item.symbol}</b><span>{item.input === "price" ? "当前价" : "当前汇率"}</span><em>{statusLabel(item.status)}</em></li>)}</ul>
      <button type="button" onClick={onRetry}><RefreshCw size={16} aria-hidden="true" />重试载入分析</button>
    </section>
  );
}

export function DashboardPage() {
  const portfolio = usePortfolioAnalytics();
  if (portfolio.isPending) return <AnalyticsLoading />;
  if (portfolio.isError) {
    if (portfolio.error instanceof ApiError && portfolio.error.code === "PORTFOLIO_DATA_INCOMPLETE") {
      return <IncompleteState error={portfolio.error} onRetry={() => void portfolio.refetch()} />;
    }
    const message = portfolio.error instanceof ApiError ? portfolio.error.message : "组合分析载入失败。";
    return <PageError title="总览无法载入" message={message} retryLabel="重试载入分析" onRetry={() => void portfolio.refetch()} />;
  }

  const data = portfolio.data;
  if (data.decision.status === "setup") {
    return <section className={styles.page}><DecisionBanner decision={data.decision} /></section>;
  }

  const domestic = data.data_inputs.filter((item) => item.input === "price" && /^price:\d/.test(item.key));
  const overseas = data.data_inputs.filter((item) => item.input === "price" && !/^price:\d/.test(item.key));
  const fx = data.data_inputs.filter((item) => item.key !== "fx:CNY/CNY" && item.input === "fx");
  const groups = [["国内行情", domestic], ["美股行情", overseas], ["USD/CNY", fx]] as const;

  return (
    <section className={styles.page} aria-label="组合总览">
      <DecisionBanner decision={data.decision} />
      <PortfolioMetrics portfolio={data} />
      <section className={styles.rails} aria-labelledby="allocation-title">
        <div className={styles.sectionHeading}><div><p>ALLOCATION CALIBRATION</p><h2 id="allocation-title">资产配置校准</h2></div><span>允许偏离 ±{(Number(data.tolerance) * 100).toFixed(1)}pp</span></div>
        <div className={styles.railGrid}>
          {data.asset_classes.map((item) => <CalibrationRail key={item.id} assetName={item.name} target={Number(item.target_weight) * 100} actual={Number(item.actual_weight) * 100} fxNeutral={Number(item.fx_neutral_weight) * 100} tolerance={Number(data.tolerance) * 100} />)}
        </div>
      </section>
      <PnlBreakdown portfolio={data} />
      <section className={styles.dataStatus} aria-labelledby="data-status-title">
        <div className={styles.sectionHeading}><div><p>INPUT STATUS</p><h2 id="data-status-title">数据状态</h2></div>{data.has_stale_data ? <strong>数据已过期</strong> : data.has_manual_data ? <strong>包含手动值</strong> : <strong>数据有效</strong>}</div>
        <div className={styles.statusGrid}>{groups.map(([label, items]) => {
          const attention = items.find((item) => item.status === "stale") ?? items.find((item) => item.status === "manual") ?? items[0];
          const source = attention?.source === "manual" ? "手动覆盖" : attention?.source ?? "本机";
          return <div key={label}><span>{label}</span><b>{attention ? statusLabel(attention.status) : "未涉及"}</b><small>{attention ? `${source} · ${formatDataTime(attention.market_time)}` : "当前组合无此类数据"}</small>{attention?.value ? <em>{formatDecimal(attention.value, 6)}</em> : null}</div>;
        })}</div>
      </section>
    </section>
  );
}
