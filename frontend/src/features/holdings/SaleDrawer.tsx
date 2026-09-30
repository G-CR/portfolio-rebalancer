import { Check, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import type { Holding, SellPayload } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { isStaleCostPreview, useConfirmAdjustment, useSellPreview } from "./api";
import { CostBasisPreview, previewIdentityMatches } from "./CostBasisPreview";
import styles from "./Holdings.module.css";
import { shanghaiDate } from '../ledger/api';

type Props = { holding: Holding; open: boolean; onClose: () => void; onUpdated?: () => void };

export function SaleDrawer({ holding, open, onClose, onUpdated }: Props) {
  const previewMutation = useSellPreview(holding.id);
  const confirmMutation = useConfirmAdjustment<SellPayload>(holding.id);
  const [quantity, setQuantity] = useState("");
  const [date, setDate] = useState(shanghaiDate);
  const [price, setPrice] = useState('');
  const [fee, setFee] = useState('0');
  const [feeCurrency, setFeeCurrency] = useState(holding.trade_currency);
  const [note, setNote] = useState("");
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const payload = useMemo<SellPayload>(() => ({ quantity, occurred_on: date, ...(price ? {price} : {}), fee, fee_currency: feeCurrency, note: note.trim() || null }), [note, quantity, date, price, fee, feeCurrency]);
  const currentFingerprint = JSON.stringify(payload);
  const preview = fingerprint === currentFingerprint ? previewMutation.data ?? null : null;
  const canConfirm = Boolean(preview && previewIdentityMatches(preview));

  async function generate() {
    setError(null);
    try {
      await previewMutation.mutateAsync(payload);
      setFingerprint(currentFingerprint);
    } catch (caught) {
      setFingerprint(null);
      setError(caught instanceof ApiError ? caught.message : "卖出调整预览失败。");
    }
  }

  async function confirm() {
    if (!preview) return;
    setError(null);
    try {
      await confirmMutation.mutateAsync({ expected_version: preview.holding_version, operation: "sell", payload, preview_token: preview.preview_token });
      onUpdated?.();
    } catch (caught) {
      if (isStaleCostPreview(caught)) {
        previewMutation.reset();
        setFingerprint(null);
        setError("持仓已发生变化，请重新生成卖出调整预览");
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
          <div className={styles.sectionHeading}><span className={styles.step}>01</span><div><h3>卖出成交</h3><p>按平均原币成本计算已实现盈亏，剩余持仓单位成本保持不变。</p></div></div>
          <FormField label="卖出份额" required><input type="text" inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField>
          <FormField label="成交日期" required><input type="date" value={date} max={shanghaiDate()} onChange={(event) => setDate(event.target.value)} /></FormField>
          <FormField label="成交价格" hint="启用长期账本后必填" suffix={holding.trade_currency}><input inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} /></FormField>
          <FormField label="实际费用"><input inputMode="decimal" value={fee} onChange={(event) => setFee(event.target.value)} /></FormField>
          <FormField label="费用币种"><select value={feeCurrency} onChange={(event) => setFeeCurrency(event.target.value)}><option value={holding.trade_currency}>{holding.trade_currency}</option>{holding.trade_currency !== 'CNY' ? <option value="CNY">CNY</option> : null}</select></FormField>
          <p className={styles.muted}>参考汇率自动选取，缺失时原币操作可继续保存。</p>
          <FormField label="调整备注"><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
        </section>
        <button className={styles.previewButton} type="button" disabled={!quantity || previewMutation.isPending} onClick={() => void generate()}><RefreshCw size={16} aria-hidden="true" />预览卖出调整</button>
        {fingerprint && fingerprint !== currentFingerprint ? <p className={styles.staleNotice}>输入已变化，请重新预览卖出调整</p> : null}
        {preview ? <CostBasisPreview preview={preview} /> : null}
      </div>
    </WorkDrawer>
  );
}
