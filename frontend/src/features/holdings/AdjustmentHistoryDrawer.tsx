import { Check, RotateCcw } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import type { CostAdjustmentHistoryItem, Holding, RestorePayload } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { useConfirmAdjustment, useCostAdjustments, useRestorePreview } from "./api";
import { CostBasisPreview, previewIdentityMatches } from "./CostBasisPreview";
import styles from "./Holdings.module.css";

type Props = { holding: Holding; open: boolean; onClose: () => void; onUpdated?: () => void };

const operationNames: Record<string, string> = {
  PURCHASE: "追加买入调整",
  SELL: "卖出调整",
  MANUAL_CORRECTION: "人工修正",
};

function formatTime(value: string) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`;
}

function HistoryBasis({ label, item }: { label: string; item: CostAdjustmentHistoryItem["before"] }) {
  return <div className={styles.historyBasis}><span>{label}</span><strong>{item.quantity}</strong><small>成本价 {item.average_cost_price} · 汇率 {item.cost_fx_to_cny}</small></div>;
}

export function AdjustmentHistoryDrawer({ holding, open, onClose, onUpdated }: Props) {
  const history = useCostAdjustments(holding.id, open);
  const restorePreview = useRestorePreview(holding.id);
  const confirm = useConfirmAdjustment<RestorePayload>(holding.id);
  const [selected, setSelected] = useState<CostAdjustmentHistoryItem | null>(null);
  const [note, setNote] = useState("恢复到此状态");
  const [error, setError] = useState<string | null>(null);

  async function beginRestore(item: CostAdjustmentHistoryItem) {
    setSelected(item);
    setError(null);
    try {
      await restorePreview.mutateAsync({ adjustmentId: item.id, note: note || null });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "恢复预览失败。");
    }
  }

  async function confirmRestore() {
    const preview = restorePreview.data;
    if (!selected || !preview) return;
    try {
      await confirm.mutateAsync({
        expected_version: preview.holding_version,
        operation: "restore",
        payload: { adjustment_id: selected.id, note: note.trim() || null },
      });
      setSelected(null);
      restorePreview.reset();
      onUpdated?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "恢复确认失败。");
    }
  }

  return (
    <>
      <WorkDrawer open={open} title={`${holding.symbol} 调整历史`} onClose={onClose}>
        <div className={styles.drawerContent}>
          <div className={styles.historyIntro}><strong>只追加，不删除</strong><p>每次恢复都会创建新的人工修正记录，历史时间线保持完整。</p></div>
          {history.isPending ? <p className={styles.muted}>正在载入调整历史...</p> : null}
          {history.isError ? <div className={styles.alert} role="alert">调整历史载入失败。</div> : null}
          {history.data?.items.length === 0 ? <p className={styles.emptyState}>暂无成本调整记录。</p> : null}
          <div className={styles.historyList}>
            {history.data?.items.map((item) => (
              <article className={styles.historyItem} key={item.id} aria-label={operationNames[item.operation_type] ?? item.operation_type}>
                <header><strong>{operationNames[item.operation_type] ?? item.operation_type}</strong><time dateTime={item.created_at}>{formatTime(item.created_at)}</time></header>
                <div className={styles.historyChange}><HistoryBasis label="调整前" item={item.before} /><span aria-hidden="true">→</span><HistoryBasis label="调整后" item={item.after} /></div>
                <p className={styles.historyNote}>{item.note || "无备注"}</p>
                <button className={styles.restoreButton} type="button" onClick={() => void beginRestore(item)}><RotateCcw size={15} aria-hidden="true" />恢复到此状态</button>
              </article>
            ))}
          </div>
        </div>
      </WorkDrawer>
      <WorkDrawer
        open={Boolean(selected)}
        title={`恢复 ${holding.symbol} 成本状态`}
        onClose={() => { setSelected(null); restorePreview.reset(); }}
        footer={<div className={styles.drawerFooter}><button className={styles.secondaryButton} type="button" onClick={() => setSelected(null)}>取消</button><button className={styles.primaryButton} type="button" disabled={!restorePreview.data || !previewIdentityMatches(restorePreview.data) || confirm.isPending} onClick={() => void confirmRestore()}><Check size={16} aria-hidden="true" />确认恢复为新修正</button></div>}
      >
        <div className={styles.drawerContent}>
          <div className={styles.historyIntro}><strong>新增修正记录</strong><p>将新增一条人工修正记录，原历史不会删除。</p></div>
          {error ? <div className={styles.alert} role="alert">{error}</div> : null}
          <FormField label="恢复备注"><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
          {restorePreview.isPending ? <p className={styles.muted}>正在生成恢复预览...</p> : null}
          {restorePreview.data ? <CostBasisPreview preview={restorePreview.data} /> : null}
        </div>
      </WorkDrawer>
    </>
  );
}
