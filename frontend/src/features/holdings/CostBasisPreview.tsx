import { CheckCircle2, XCircle } from "lucide-react";

import type { CostAdjustmentPreview } from "../../api/types";
import { costBasisIdentityMatches } from "./decimalIdentity";
import { formatDecimal } from "../analytics/format";
import styles from "./Holdings.module.css";

const COST_PRICE_KEYS = new Set(["average_cost_price"]);
const MONEY_KEYS = new Set(["total_cost_trade_currency"]);
function fmtRawValue(key: string, value: string) {
  if (COST_PRICE_KEYS.has(key)) return formatDecimal(value, 3);
  if (MONEY_KEYS.has(key)) return formatDecimal(value, 2);
  return value;
}

const rows = [
  ["份额", "quantity"],
  ["平均成本价", "average_cost_price"],
  ["交易币种成本", "total_cost_trade_currency"],
] as const;

export function previewIdentityMatches(preview: CostAdjustmentPreview | null) {
  if (!preview) return false;
  return costBasisIdentityMatches(
    preview.after.quantity,
    preview.after.average_cost_price,
    preview.after.total_cost_trade_currency,
  );
}

export function CostBasisPreview({ preview }: { preview: CostAdjustmentPreview }) {
  const identityMatches = previewIdentityMatches(preview);
  return (
    <section className={styles.previewSection} role="region" aria-label="成本预览">
      <div className={styles.sectionHeading}>
        <span className={styles.step}>04</span>
        <div><h3>成本预览</h3><p>所有财务结果由后端十进制成本引擎计算。</p></div>
      </div>
      <div className={styles.comparison}>
        <div className={styles.comparisonHeader}>字段</div>
        <div className={styles.comparisonHeader}>调整前</div>
        <div className={styles.comparisonHeader}>调整后</div>
        {rows.map(([label, key]) => (
          <div className={styles.comparisonRow} key={key}>
            <span>{label}</span>
            <strong>{fmtRawValue(key, preview.before[key])}</strong>
            <strong>{fmtRawValue(key, preview.after[key])}</strong>
          </div>
        ))}
      </div>
      {preview.fee ? (
        <p className={styles.feeResult}>
          {preview.fee.mode === "actual" ? "实际费用" : "预估费用"} {preview.fee.amount} {preview.fee.currency}
        </p>
      ) : null}
      <div className={identityMatches ? styles.identityValid : styles.identityInvalid}>
        {identityMatches ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />}
        <div>
          <strong>{identityMatches ? "公式校验通过" : "公式校验未通过"}</strong>
          <span>份额 × 成本价 = 交易币种成本</span>
        </div>
      </div>
    </section>
  );
}
