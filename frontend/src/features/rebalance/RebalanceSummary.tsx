import { ArrowRight, CheckCircle2, CircleAlert, ShieldCheck } from "lucide-react";

import type { RebalancePreview } from "../../api/types";
import { formatAmount, formatDecimal, formatPercentagePoints } from "../analytics/format";
import styles from "./Rebalance.module.css";

function formatBasisPoints(value: string, maximumFractionDigits = 2) {
  const basisPoints = Number(value) * 10_000;
  return Number.isFinite(basisPoints) ? `${formatDecimal(String(basisPoints), maximumFractionDigits)}bp` : value;
}

function netFxText(direction: RebalancePreview["result"]["net_fx_direction"], amountCny: string) {
  if (direction === "cny_to_usd") return `净换汇：人民币换美元 ¥${formatAmount(amountCny, 0)}`;
  if (direction === "usd_to_cny") return `净换汇：美元换人民币 ¥${formatAmount(amountCny, 0)}`;
  return "净换汇：无需换汇";
}

export function RebalanceSummary({ preview }: { preview: RebalancePreview }) {
  const result = preview.result;
  const before = formatPercentagePoints(result.max_drift_before, 2);
  const buyOnly = formatPercentagePoints(result.buy_only_max_drift, 2);
  const after = formatPercentagePoints(result.max_drift_after, 2);
  const precision = formatBasisPoints(result.optimization_precision);
  const optimalityGap = formatBasisPoints(result.optimality_gap, 4);
  const driftAccessibleText = result.sell_phase_used
    ? `最大偏离变化：测算前 ${before}，纯补仓 ${buyOnly}，最终 ${after}`
    : `最大偏离变化：测算前 ${before}，最终 ${after}`;
  const certificationAccessibleText = result.optimization_certified
    ? `优化器认证：已在 ${precision} 精度内认证；最优性差距 ${optimalityGap}`
    : "历史方案未经过新优化器认证";

  return (
    <section className={styles.summary} aria-label="再平衡方案摘要" data-feasible={result.feasible}>
      <div className={styles.summaryLead}>
        {result.feasible ? <CheckCircle2 size={21} aria-hidden="true" /> : <CircleAlert size={21} aria-hidden="true" />}
        <div><p>{result.feasible ? "方案可执行" : "当前约束下无法完全校准"}</p><h2>建议执行 {result.trades.length} 笔交易</h2></div>
      </div>
      <div className={styles.summaryDetails}>
        <div className={styles.driftSummary}>
          <p className={styles.driftOutcome}>{`最大偏离 ${before} → ${after}`}</p>
          <div className={`${styles.driftTrack} ${result.sell_phase_used ? styles.driftTrackThree : styles.driftTrackTwo}`} role="group" aria-label={driftAccessibleText}>
            <span className={styles.driftStage}><small>测算前</small><strong>{before}</strong></span>
            <ArrowRight className={styles.driftArrow} size={15} aria-hidden="true" />
            {result.sell_phase_used ? <>
              <span className={styles.driftStage}><small>纯补仓</small><strong>{buyOnly}</strong></span>
              <ArrowRight className={styles.driftArrow} size={15} aria-hidden="true" />
            </> : null}
            <span className={`${styles.driftStage} ${styles.driftStageFinal}`}><small>最终方案</small><strong>{after}</strong></span>
          </div>
          {result.sell_phase_used ? <p className={styles.driftDetail}>{`纯补仓 ${buyOnly}，卖出转配后 ${after}`}</p> : null}
        </div>
        <div className={styles.summaryFacts}>
          <div className={styles.certification} role="status" aria-label={certificationAccessibleText} data-certified={result.optimization_certified}>
            {result.optimization_certified ? <ShieldCheck size={17} aria-hidden="true" /> : <CircleAlert size={17} aria-hidden="true" />}
            {result.optimization_certified ? <p><strong>{`已在 ${precision} 精度内认证`}</strong><small>{`最优性差距 ${optimalityGap}`}</small></p> : <p><strong>历史方案未经过新优化器认证</strong></p>}
          </div>
          <p className={styles.netFx}>{netFxText(result.net_fx_direction, result.net_fx_amount_cny)}</p>
          <dl className={styles.remainingCash}>
            <div><dt>剩余人民币</dt><dd>¥{formatAmount(result.remaining_cny, 0)}</dd></div>
            <div><dt>剩余美元</dt><dd>${formatAmount(result.remaining_usd, 2)}</dd></div>
          </dl>
        </div>
      </div>
    </section>
  );
}
