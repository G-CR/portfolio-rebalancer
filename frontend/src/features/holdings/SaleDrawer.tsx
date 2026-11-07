import { Check } from "lucide-react";
import { useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import type { Holding, SellPayload } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { isStaleCostPreview, useConfirmAdjustment, useSellPreview } from "./api";
import { useAutomaticPreview } from "./useAutomaticPreview";
import { CostBasisPreview, previewIdentityMatches } from "./CostBasisPreview";
import styles from "./Holdings.module.css";

type Props = { holding: Holding; open: boolean; onClose: () => void; onUpdated?: () => void };

export function SaleDrawer({ holding, open, onClose, onUpdated }: Props) {
  const previewMutation = useSellPreview(holding.id);
  const confirmMutation = useConfirmAdjustment<SellPayload>(holding.id);
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const payload = useMemo<SellPayload>(() => ({ quantity, note: note.trim() || null }), [note, quantity]);
  const auto = useAutomaticPreview(payload, open && Boolean(quantity), previewMutation.mutateAsync);
  const preview = auto.preview;
  const canConfirm = Boolean(preview && previewIdentityMatches(preview));

  async function confirm() {
    if (!preview) return;
    setError(null);
    try {
      await confirmMutation.mutateAsync({ expected_version: preview.holding_version, operation: "sell", payload });
      onUpdated?.();
    } catch (caught) {
      if (isStaleCostPreview(caught)) {
        auto.invalidate();
        setError("持仓已发生变化，请重新预览");
        return;
      }
      setError(caught instanceof ApiError ? caught.message : "卖出调整确认失败。");
    }
  }

  return (
    <WorkDrawer
      open={open}
      title={`卖出调整 ${holding.symbol}`}
      onClose={onClose}
      footer={<div className={styles.drawerFooter}><button className={styles.secondaryButton} type="button" onClick={onClose}>取消</button><button className={styles.primaryButton} type="button" disabled={!canConfirm || confirmMutation.isPending} onClick={() => void confirm()}><Check size={16} aria-hidden="true" />确认卖出调整</button></div>}
    >
      <div className={styles.drawerContent}>
        <div className={styles.identityStrip}><strong>{holding.symbol}</strong><span>{holding.name}</span><span>当前份额 {holding.quantity}</span></div>
        {error ? <div className={styles.alert} role="alert">{error}</div> : null}
        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>01</span><div><h3>卖出份额</h3><p>卖出只减少当前份额，保留剩余持仓的平均成本价。</p></div></div>
          <FormField label="卖出份额" required><input type="text" inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField>
          <FormField label="调整备注"><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
        </section>
        {auto.pending ? <p role="status">正在计算调整结果…</p> : null}
        {auto.error ? <p className={styles.alert} role="alert">{auto.error instanceof Error ? auto.error.message : "预览失败，请检查输入。"}</p> : null}
        {error && !preview ? <button type="button" onClick={() => { setError(null); auto.retry(); }}>重新预览</button> : null}
        {preview ? <CostBasisPreview preview={preview} /> : null}
      </div>
    </WorkDrawer>
  );
}
