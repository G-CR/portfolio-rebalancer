import { Check } from "lucide-react";
import { useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import type { CorrectionPayload, Holding } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { isStaleCostPreview, useConfirmAdjustment, useCorrectionPreview } from "./api";
import { useAutomaticPreview } from "./useAutomaticPreview";
import { CostBasisPreview, previewIdentityMatches } from "./CostBasisPreview";
import styles from "./Holdings.module.css";

type Props = { holding: Holding; open: boolean; onClose: () => void; onUpdated?: () => void };

export function CorrectionDrawer({ holding, open, onClose, onUpdated }: Props) {
  const previewMutation = useCorrectionPreview(holding.id);
  const confirmMutation = useConfirmAdjustment<CorrectionPayload>(holding.id);
  const [quantity, setQuantity] = useState(holding.quantity);
  const [averagePrice, setAveragePrice] = useState(holding.average_cost_price);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const payload = useMemo<CorrectionPayload>(() => ({
    quantity,
    average_cost_price: averagePrice,
    note: note.trim(),
  }), [averagePrice, note, quantity]);
  const auto = useAutomaticPreview(payload, open && Boolean(quantity && averagePrice && note.trim()), previewMutation.mutateAsync);
  const preview = auto.preview;
  const canConfirm = Boolean(preview && previewIdentityMatches(preview));

  async function confirm() {
    if (!preview) return;
    try {
      await confirmMutation.mutateAsync({ expected_version: preview.holding_version, operation: "manual_correction", payload });
      onUpdated?.();
    } catch (caught) {
      if (isStaleCostPreview(caught)) {
        auto.invalidate();
        setError("持仓已发生变化，请重新预览");
        return;
      }
      setError(caught instanceof ApiError ? caught.message : "人工修正确认失败。");
    }
  }

  return (
    <WorkDrawer open={open} title={`人工修正 ${holding.symbol}`} onClose={onClose} footer={<div className={styles.drawerFooter}><button className={styles.secondaryButton} type="button" onClick={onClose}>取消</button><button className={styles.primaryButton} type="button" disabled={!canConfirm || confirmMutation.isPending} onClick={() => void confirm()}><Check size={16} aria-hidden="true" />确认人工修正</button></div>}>
      <div className={styles.drawerContent}>
        <div className={styles.identityStrip}><strong>{holding.symbol}</strong><span>{holding.name}</span><span>直接对齐券商或历史凭证</span></div>
        {error ? <div className={styles.alert} role="alert">{error}</div> : null}
        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>01</span><div><h3>修正后成本状态</h3><p>该操作会新增审计记录，不改写既有历史。</p></div></div>
          <div className={styles.fieldGrid}>
            <FormField label="修正后份额" required><input type="text" inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField>
            <FormField label="修正后成本价" required><input type="text" inputMode="decimal" value={averagePrice} onChange={(event) => setAveragePrice(event.target.value)} /></FormField>
          </div>
          <FormField label="修正原因" required><textarea value={note} onChange={(event) => { setNote(event.target.value); }} /></FormField>
        </section>
        {auto.pending ? <p role="status">正在计算调整结果…</p> : null}
        {auto.error ? <p className={styles.alert} role="alert">{auto.error instanceof Error ? auto.error.message : "预览失败，请检查输入。"}</p> : null}
        {error && !preview ? <button type="button" onClick={() => { setError(null); auto.retry(); }}>重新预览</button> : null}
        {preview ? <CostBasisPreview preview={preview} /> : null}
      </div>
    </WorkDrawer>
  );
}
