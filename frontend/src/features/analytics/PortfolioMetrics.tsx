import type { PortfolioAnalytics } from "../../api/types";
import { formatAmount, formatSignedAmount } from "./format";
import styles from "./Analytics.module.css";

export function PortfolioMetrics({ portfolio }: { portfolio: PortfolioAnalytics }) {
  const metrics = [
    ["核心池市值", formatAmount(portfolio.market_value_cny)],
    ["参考成本", formatAmount(portfolio.cost_cny, 0)],
    ["浮动盈亏", formatSignedAmount(portfolio.unrealized_pnl, 0)],
  ];
  return (
    <dl className={styles.metrics} aria-label="组合汇总指标">
      {metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}<small>CNY</small></dd></div>)}
    </dl>
  );
}
