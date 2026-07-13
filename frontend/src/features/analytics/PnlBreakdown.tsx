import type { PortfolioAnalytics } from "../../api/types";
import { formatPercent, formatSignedAmount } from "./format";
import styles from "./Analytics.module.css";

export function PnlBreakdown({ portfolio }: { portfolio: PortfolioAnalytics }) {
  const totalMagnitude = Math.abs(Number(portfolio.price_effect)) + Math.abs(Number(portfolio.fx_effect)) || 1;
  const priceWidth = Math.abs(Number(portfolio.price_effect)) / totalMagnitude * 100;
  return (
    <section className={styles.pnl} aria-labelledby="pnl-breakdown-title">
      <div className={styles.sectionHeading}>
        <div><p>P&amp;L DECOMPOSITION</p><h2 id="pnl-breakdown-title">盈亏拆分</h2></div>
        <span>海外资产占比 {formatPercent(portfolio.overseas_weight)}</span>
      </div>
      <div className={styles.pnlBar} aria-hidden="true">
        <span className={styles.priceBar} style={{ width: `${priceWidth}%` }} />
        <span className={styles.fxBar} style={{ width: `${100 - priceWidth}%` }} />
      </div>
      <dl className={styles.pnlValues}>
        <div><dt><span className={styles.priceKey} />价格影响</dt><dd>{formatSignedAmount(portfolio.price_effect)}</dd></div>
        <div><dt><span className={styles.fxKey} />汇率影响</dt><dd>{formatSignedAmount(portfolio.fx_effect)}</dd></div>
        <div><dt>浮动盈亏</dt><dd>{formatSignedAmount(portfolio.unrealized_pnl)}</dd></div>
      </dl>
    </section>
  );
}
