import type { PortfolioAnalytics } from "../../api/types";
import { proportionDecimalSeries } from "./chartScale";
import { formatPercent, formatSignedAmount } from "./format";
import styles from "./Analytics.module.css";

export function PnlBreakdown({ portfolio }: { portfolio: PortfolioAnalytics }) {
  const [priceGeometry, fxGeometry] = proportionDecimalSeries([portfolio.price_effect, portfolio.fx_effect]);
  return (
    <section className={styles.pnl} aria-labelledby="pnl-breakdown-title">
      <div className={styles.sectionHeading}>
        <div><p>P&amp;L DECOMPOSITION</p><h2 id="pnl-breakdown-title">盈亏拆分</h2></div>
        <span>海外资产占比 {formatPercent(portfolio.overseas_weight)}</span>
      </div>
      <div className={styles.pnlBar} aria-hidden="true">
        <span className={styles.priceBar} style={{ width: `${priceGeometry.scaled}%` }} />
        <span className={styles.fxBar} style={{ width: `${fxGeometry.scaled}%` }} />
      </div>
      <dl className={styles.pnlValues}>
        <div><dt><span className={styles.priceKey} />价格影响</dt><dd>{formatSignedAmount(portfolio.price_effect)}</dd></div>
        <div><dt><span className={styles.fxKey} />汇率影响</dt><dd>{formatSignedAmount(portfolio.fx_effect)}</dd></div>
        <div><dt>浮动盈亏</dt><dd>{formatSignedAmount(portfolio.unrealized_pnl)}</dd></div>
      </dl>
    </section>
  );
}
