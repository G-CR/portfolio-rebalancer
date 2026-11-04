import { Calculator } from "lucide-react";

import { FormField } from "../../components/FormField/FormField";
import styles from "./Rebalance.module.css";

export type RebalanceFormState = {
  availableCny: string;
  availableUsd: string;
  tolerance: string;
  allowSell: boolean;
  allowFx: boolean;
  acknowledgeStaleData: boolean;
};

type Props = {
  value: RebalanceFormState;
  pending: boolean;
  disabled: boolean;
  hasPreview: boolean;
  onChange: (value: RebalanceFormState) => void;
  onSubmit: () => void;
};

export function RebalanceInputs({ value, pending, disabled, hasPreview, onChange, onSubmit }: Props) {
  const set = <K extends keyof RebalanceFormState>(key: K, next: RebalanceFormState[K]) => onChange({ ...value, [key]: next });
  return (
    <aside className={styles.inputs} aria-labelledby="rebalance-inputs-title">
      <header className={styles.panelHeading}>
        <p>CALIBRATION INPUT</p>
        <h2 id="rebalance-inputs-title">本次可用资金与约束</h2>
      </header>

      <div className={styles.fieldGrid}>
        <FormField label="人民币" suffix="CNY"><input inputMode="decimal" value={value.availableCny} disabled={disabled} onChange={(event) => set("availableCny", event.target.value)} /></FormField>
        <FormField label="美元" suffix="USD"><input inputMode="decimal" value={value.availableUsd} disabled={disabled} onChange={(event) => set("availableUsd", event.target.value)} /></FormField>
        <FormField label="允许偏离" suffix="%"><input inputMode="decimal" value={value.tolerance} disabled={disabled} onChange={(event) => set("tolerance", event.target.value)} /></FormField>
      </div>

      <div className={styles.switches}>
        <label><input type="checkbox" checked={value.allowSell} disabled={disabled} onChange={(event) => set("allowSell", event.target.checked)} /><span><b>允许卖出</b><small>新增资金不足时可减少高配资产</small></span></label>
        <label><input type="checkbox" checked={value.allowFx} disabled={disabled} onChange={(event) => set("allowFx", event.target.checked)} /><span><b>允许换汇</b><small>人民币与美元可按需要双向净换汇</small></span></label>
      </div>

      {value.acknowledgeStaleData ? <p className={styles.acknowledged}>已确认使用过期行情进行本次测算。</p> : null}
      <button className={styles.recalculate} type="button" onClick={onSubmit} disabled={pending || disabled}>
        <Calculator size={16} aria-hidden="true" />{pending ? "测算中" : hasPreview ? "重新测算" : "开始测算"}
      </button>
    </aside>
  );
}
