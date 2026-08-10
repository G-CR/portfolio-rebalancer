import { Ban, Check, Play, Save } from "lucide-react";

import type { RebalancePlan } from "../../api/types";
import styles from "./Rebalance.module.css";

type Props = {
  plan: RebalancePlan | null;
  disabled: boolean;
  pending: boolean;
  onSave: () => void;
  onStart: () => void;
  onCancel: () => void;
  onComplete: () => void;
};

export function RebalanceLifecycle({ plan, disabled, pending, onSave, onStart, onCancel, onComplete }: Props) {
  const message = !plan ? "当前测算尚未保存" : plan.status === "draft" ? "方案已保存，尚未开始" : plan.status === "in_progress" ? "再平衡进行中" : plan.status === "completed" ? "本次再平衡已完成，新汇率基准已建立" : "方案已取消";
  return (
    <section className={styles.lifecycle} aria-labelledby="rebalance-lifecycle-title" data-status={plan?.status ?? "unsaved"}>
      <div><p>FORMAL REBALANCE</p><h2 id="rebalance-lifecycle-title">{message}</h2>{plan?.status === "in_progress" ? <span><b>系统没有向券商提交订单</b>。完成实际交易并更新持仓后，再建立新基准。</span> : null}</div>
      {plan?.status === "in_progress" ? <div className={styles.execution}><ol className={styles.executionChecklist} aria-label="再平衡执行清单"><li>按方案完成券商交易</li><li>更新实际持仓数量</li><li>确认成交价格和当前汇率</li><li>完成再平衡并建立新基准</li></ol><p className={styles.completionNote}>完成后会创建调仓后快照，并将当前汇率重置为新的汇率基准；不会修改成本价或成本汇率。</p></div> : null}
      <div className={styles.commands}>
        {!plan ? <button type="button" className={styles.secondary} onClick={onSave} disabled={disabled || pending}><Save size={16} aria-hidden="true" />保存方案</button> : null}
        {(!plan || plan.status === "draft") ? <button type="button" className={styles.primary} onClick={onStart} disabled={disabled || pending}><Play size={16} aria-hidden="true" />开始本次再平衡</button> : null}
        {plan?.status === "draft" || plan?.status === "in_progress" ? <button type="button" className={styles.ghost} onClick={onCancel} disabled={pending}><Ban size={16} aria-hidden="true" />取消方案</button> : null}
        {plan?.status === "in_progress" ? <button type="button" className={styles.primary} onClick={onComplete} disabled={pending}><Check size={16} aria-hidden="true" />完成再平衡并建立新基准</button> : null}
      </div>
    </section>
  );
}
