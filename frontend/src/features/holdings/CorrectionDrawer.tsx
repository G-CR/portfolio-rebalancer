import { Check, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import type { CorrectionPayload, Holding } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { useConfirmAdjustment, useCorrectionPreview } from "./api";
import { CostBasisPreview, previewIdentityMatches } from "./CostBasisPreview";
import styles from "./Holdings.module.css";

type Props = { holding: Holding; open: boolean; onClose: () => void; onUpdated?: () => void };

export function CorrectionDrawer({ holding, open, onClose, onUpdated }: Props) {
  const previewMutation = useCorrectionPreview(holding.id);
  const confirmMutation = useConfirmAdjustment<CorrectionPayload>(holding.id);
  const [quantity, setQuantity] = useState(holding.quantity);
  const [averagePrice, setAveragePrice] = useState(holding.average_cost_price);
  const [costFx, setCostFx] = useState(holding.cost_fx_to_cny);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState(false);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const payload = useMemo<CorrectionPayload>(() => ({
    quantity,
    average_cost_price: averagePrice,
    cost_fx_to_cny: costFx,
    note: note.trim(),
  }), [averagePrice, costFx, note, quantity]);
  const currentFingerprint = JSON.stringify(payload);
  const preview = fingerprint === currentFingerprint ? previewMutation.data ?? null : null;
  const canConfirm = Boolean(preview && previewIdentityMatches(preview));

  async function generate() {
    if (!note.trim()) {
      setNoteError(true);
      return;
    }
    setNoteError(false);
    setError(null);
    try {
      await previewMutation.mutateAsync(payload);
      setFingerprint(currentFingerprint);
    } catch (caught) {
      setFingerprint(null);
      setError(caught instanceof ApiError ? caught.message : "人工修正预览失败。");
    }
  }

  async function confirm() {
    if (!preview) return;
    try {
      await confirmMutation.mutateAsync({ expected_version: preview.holding_version, operation: "manual_correction", payload });
      onUpdated?.();
    } catch (caught) {
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
            <FormField label="修正后成本汇率" required><input type="text" inputMode="decimal" value={costFx} onChange={(event) => setCostFx(event.target.value)} /></FormField>
          </div>
          <FormField label="修正原因" required error={noteError ? "请填写修正原因" : undefined}><textarea value={note} onChange={(event) => { setNote(event.target.value); setNoteError(false); }} /></FormField>
        </section>
        <button className={styles.previewButton} type="button" disabled={!quantity || !averagePrice || !costFx || previewMutation.isPending} onClick={() => void generate()}><RefreshCw size={16} aria-hidden="true" />预览人工修正</button>
        {fingerprint && fingerprint !== currentFingerprint ? <p className={styles.staleNotice}>输入已变化，请重新预览人工修正</p> : null}
        {preview ? <CostBasisPreview preview={preview} /> : null}
      </div>
    </WorkDrawer>
  );
}
