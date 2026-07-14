import { CheckCircle2, CircleAlert } from "lucide-react";

import type { RebalancePreview } from "../../api/types";
import { formatAmount, formatPercentagePoints } from "../analytics/format";
import styles from "./Rebalance.module.css";

export function RebalanceSummary({ preview }: { preview: RebalancePreview }) {
  const result = preview.result;
  return (
    <section className={styles.summary} aria-label="再平衡方案摘要" data-feasible={result.feasible}>
      <div className={styles.summaryLead}>
        {result.feasible ? <CheckCircle2 size={21} aria-hidden="true" /> : <CircleAlert size={21} aria-hidden="true" />}
        <div><p>{result.feasible ? "方案可执行" : "当前约束下无法完全校准"}</p><h2>建议执行 {result.trades.length} 笔交易</h2></div>
      </div>
      <dl>
        <div><dt>最大偏离</dt><dd>{formatPercentagePoints(result.max_drift_before)} → {formatPercentagePoints(result.max_drift_after)}</dd></div>
        <div><dt>剩余人民币</dt><dd>{formatAmount(result.remaining_cny, 0)}</dd></div>
        <div><dt>剩余美元</dt><dd>{formatAmount(result.remaining_usd, 2)}</dd></div>
      </dl>
    </section>
  );
}
