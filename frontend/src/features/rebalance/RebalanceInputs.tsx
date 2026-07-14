import { Calculator } from "lucide-react";

import type { RebalanceValuationBasis } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import styles from "./Rebalance.module.css";

export type RebalanceFormState = {
  availableCny: string;
  availableUsd: string;
  tolerance: string;
  minimumTradeCny: string;
  allowSell: boolean;
  allowFx: boolean;
  valuationBasis: RebalanceValuationBasis;
  acknowledgeStaleData: boolean;
};

type Props = {
  value: RebalanceFormState;
  pending: boolean;
  onChange: (value: RebalanceFormState) => void;
  onBasisChange: (basis: RebalanceValuationBasis) => void;
  onSubmit: () => void;
};

export function RebalanceInputs({ value, pending, onChange, onBasisChange, onSubmit }: Props) {
  const set = <K extends keyof RebalanceFormState>(key: K, next: RebalanceFormState[K]) => onChange({ ...value, [key]: next });
  return (
    <aside className={styles.inputs} aria-labelledby="rebalance-inputs-title">
      <header className={styles.panelHeading}>
        <p>CALIBRATION INPUT</p>
        <h2 id="rebalance-inputs-title">本次可用资金与约束</h2>
      </header>

      <fieldset className={styles.segmented}>
        <legend>计算口径</legend>
        <label><input type="radio" name="valuation-basis" checked={value.valuationBasis === "actual"} onChange={() => onBasisChange("actual")} />实际占比</label>
        <label><input type="radio" name="valuation-basis" checked={value.valuationBasis === "fx_neutral"} onChange={() => onBasisChange("fx_neutral")} />剔汇率口径</label>
      </fieldset>

      <div className={styles.fieldGrid}>
        <FormField label="人民币" suffix="CNY"><input inputMode="decimal" value={value.availableCny} onChange={(event) => set("availableCny", event.target.value)} /></FormField>
        <FormField label="美元" suffix="USD"><input inputMode="decimal" value={value.availableUsd} onChange={(event) => set("availableUsd", event.target.value)} /></FormField>
        <FormField label="允许偏离" suffix="%"><input inputMode="decimal" value={value.tolerance} onChange={(event) => set("tolerance", event.target.value)} /></FormField>
        <FormField label="最小交易金额" suffix="CNY"><input inputMode="decimal" value={value.minimumTradeCny} onChange={(event) => set("minimumTradeCny", event.target.value)} /></FormField>
      </div>

      <div className={styles.switches}>
        <label><input type="checkbox" checked={value.allowSell} onChange={(event) => set("allowSell", event.target.checked)} /><span><b>允许卖出</b><small>新增资金不足时可减少高配资产</small></span></label>
        <label><input type="checkbox" checked={value.allowFx} onChange={(event) => set("allowFx", event.target.checked)} /><span><b>允许换汇</b><small>人民币不足时可估算换入美元</small></span></label>
      </div>

      {value.acknowledgeStaleData ? <p className={styles.acknowledged}>已确认使用过期行情进行本次测算。</p> : null}
      <button className={styles.recalculate} type="button" onClick={onSubmit} disabled={pending}>
        <Calculator size={16} aria-hidden="true" />{pending ? "测算中" : "重新测算"}
      </button>
    </aside>
  );
}
