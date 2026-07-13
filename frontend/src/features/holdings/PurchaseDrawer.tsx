import { Check, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import type { Holding, PurchasePayload } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import {
  useConfirmAdjustment,
  useCostAdjustments,
  usePurchasePreview,
} from "./api";
import { CostBasisPreview, previewIdentityMatches } from "./CostBasisPreview";
import styles from "./Holdings.module.css";

type FeeMode = "estimated" | "actual";

type Props = {
  holding: Holding;
  open: boolean;
  onClose: () => void;
  onUpdated?: () => void;
};

function today() {
  const date = new Date();
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function messageFor(error: unknown) {
  if (!(error instanceof ApiError)) return "请求失败，请检查输入后重试。";
  if (error.code === "STALE_COST_PREVIEW") return "持仓已发生变化，请重新生成预览";
  return error.message;
}

export function PurchaseDrawer({ holding, open, onClose, onUpdated }: Props) {
  const context = useCostAdjustments(holding.id, open);
  const previewMutation = usePurchasePreview(holding.id);
  const confirmMutation = useConfirmAdjustment<PurchasePayload>(holding.id);
  const [quantity, setQuantity] = useState("");
  const [tradeDate, setTradeDate] = useState(today);
  const [price, setPrice] = useState("");
  const [fx, setFx] = useState(holding.trade_currency === "CNY" ? "1" : "");
  const [feeMode, setFeeMode] = useState<FeeMode>("estimated");
  const [feeCurrency, setFeeCurrency] = useState(holding.trade_currency);
  const [commissionRate, setCommissionRate] = useState("0");
  const [minimumCommission, setMinimumCommission] = useState("0");
  const [perShareFee, setPerShareFee] = useState("0");
  const [fixedFee, setFixedFee] = useState("0");
  const [actualFee, setActualFee] = useState("");
  const [saveDefaults, setSaveDefaults] = useState(false);
  const [note, setNote] = useState("");
  const [defaultsApplied, setDefaultsApplied] = useState(false);
  const [previewFingerprint, setPreviewFingerprint] = useState<string | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!open) setDefaultsApplied(false);
  }, [open]);

  useEffect(() => {
    if (!context.data || defaultsApplied) return;
    const defaults = context.data.defaults;
    if (defaults) {
      setFeeCurrency(defaults.fee_currency);
      setCommissionRate(defaults.commission_rate);
      setMinimumCommission(defaults.minimum_commission);
      setPerShareFee(defaults.per_share_fee);
      setFixedFee(defaults.fixed_fee);
    }
    setDefaultsApplied(true);
  }, [context.data, defaultsApplied]);

  const payload = useMemo<PurchasePayload>(() => ({
    quantity,
    price,
    fx,
    fee_currency: feeCurrency || null,
    commission_rate: commissionRate || null,
    minimum_commission: minimumCommission || null,
    per_share_fee: perShareFee || null,
    fixed_fee: fixedFee || null,
    actual_fee: feeMode === "actual" ? actualFee || null : null,
    save_fee_defaults: saveDefaults,
    note: note.trim() || null,
  }), [actualFee, commissionRate, feeCurrency, feeMode, fixedFee, fx, minimumCommission, note, perShareFee, price, quantity, saveDefaults]);
  const fingerprint = JSON.stringify(payload);
  const stale = Boolean(previewFingerprint && previewFingerprint !== fingerprint);
  const preview = stale ? null : previewMutation.data ?? null;
  const validInputs = Boolean(quantity && price && fx && (feeMode === "estimated" || actualFee));
  const canConfirm = Boolean(preview && previewIdentityMatches(preview) && !stale && !confirmMutation.isPending);

  async function generatePreview() {
    setClientError(null);
    setSuccess(false);
    try {
      await previewMutation.mutateAsync(payload);
      setPreviewFingerprint(fingerprint);
    } catch (error) {
      setPreviewFingerprint(null);
      setClientError(messageFor(error));
    }
  }

  async function confirm() {
    if (!preview || !canConfirm) return;
    setClientError(null);
    try {
      await confirmMutation.mutateAsync({
        expected_version: preview.holding_version,
        operation: "purchase",
        payload,
      });
      setSuccess(true);
      onUpdated?.();
    } catch (error) {
      if (error instanceof ApiError && error.code === "STALE_COST_PREVIEW") {
        previewMutation.reset();
        setPreviewFingerprint(null);
      }
      setClientError(messageFor(error));
    }
  }

  const footer = (
    <div className={styles.drawerFooter}>
      <button className={styles.secondaryButton} type="button" onClick={onClose}>取消</button>
      <button className={styles.primaryButton} type="button" disabled={!canConfirm} onClick={() => void confirm()}>
        <Check size={16} aria-hidden="true" />
        {confirmMutation.isPending ? "正在更新" : `更新 ${holding.symbol} 持仓`}
      </button>
    </div>
  );

  return (
    <WorkDrawer open={open} title={`追加买入 ${holding.symbol}`} onClose={onClose} footer={footer}>
      <div className={styles.drawerContent}>
        <div className={styles.identityStrip}>
          <strong>{holding.symbol}</strong>
          <span>{holding.name}</span>
          <span>{holding.account_name} · {holding.trade_currency}</span>
        </div>
        {clientError ? <div className={styles.alert} role="alert">{clientError}</div> : null}
        {success ? <div className={styles.success} role="status">{holding.symbol} 持仓已更新</div> : null}

        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>01</span><div><h3>本次成交</h3><p>输入券商确认的成交数据。</p></div></div>
          <div className={styles.fieldGrid}>
            <FormField label="新增份额" required><input type="text" inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField>
            <FormField label="成交日期" required><input type="date" value={tradeDate} onChange={(event) => setTradeDate(event.target.value)} /></FormField>
            <FormField label="成交价" required suffix={holding.trade_currency}><input type="text" inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} /></FormField>
            <FormField label="本次汇率" required hint="1 单位交易币种折合人民币"><input type="text" inputMode="decimal" value={fx} onChange={(event) => setFx(event.target.value)} /></FormField>
          </div>
        </section>

        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>02</span><div><h3>交易费用</h3><p>选择按规则预估或录入券商实际费用。</p></div></div>
          <div className={styles.tabs} role="tablist" aria-label="费用模式">
            <button type="button" role="tab" aria-selected={feeMode === "estimated"} onClick={() => setFeeMode("estimated")}>按规则预估</button>
            <button type="button" role="tab" aria-selected={feeMode === "actual"} onClick={() => setFeeMode("actual")}>录入实际费用</button>
          </div>
          {feeMode === "actual" ? (
            <div className={styles.fieldGrid}>
              <FormField label="实际费用" required><input type="text" inputMode="decimal" value={actualFee} onChange={(event) => setActualFee(event.target.value)} /></FormField>
              <FormField label="费用币种"><select value={feeCurrency} onChange={(event) => setFeeCurrency(event.target.value)}><option value={holding.trade_currency}>{holding.trade_currency}</option>{holding.trade_currency !== "CNY" ? <option value="CNY">CNY</option> : null}</select></FormField>
            </div>
          ) : null}
        </section>

        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>03</span><div><h3>当前标的默认值</h3><p>预估费用使用这些规则，实际费用不会覆盖规则。</p></div></div>
          {context.isPending ? <p className={styles.muted}>正在载入费用默认值...</p> : null}
          {context.isError ? <p className={styles.inlineError}>费用默认值载入失败，当前使用零费用规则。</p> : null}
          <div className={styles.fieldGrid}>
            <FormField label="佣金费率"><input type="text" inputMode="decimal" value={commissionRate} onChange={(event) => setCommissionRate(event.target.value)} /></FormField>
            <FormField label="最低佣金"><input type="text" inputMode="decimal" value={minimumCommission} onChange={(event) => setMinimumCommission(event.target.value)} /></FormField>
            <FormField label="每份费用"><input type="text" inputMode="decimal" value={perShareFee} onChange={(event) => setPerShareFee(event.target.value)} /></FormField>
            <FormField label="固定费用"><input type="text" inputMode="decimal" value={fixedFee} onChange={(event) => setFixedFee(event.target.value)} /></FormField>
          </div>
          <label className={styles.checkboxRow}><input type="checkbox" checked={saveDefaults} onChange={(event) => setSaveDefaults(event.target.checked)} />保存为 {holding.symbol} 的费用默认值</label>
          <FormField label="调整备注"><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
        </section>

        <button className={styles.previewButton} type="button" disabled={!validInputs || previewMutation.isPending} onClick={() => void generatePreview()}>
          <RefreshCw size={16} aria-hidden="true" />
          {previewMutation.isPending ? "正在计算" : "生成成本预览"}
        </button>
        {stale ? <p className={styles.staleNotice}>输入已变化，请重新生成成本预览</p> : null}
        {preview ? <CostBasisPreview preview={preview} /> : null}
      </div>
    </WorkDrawer>
  );
}
