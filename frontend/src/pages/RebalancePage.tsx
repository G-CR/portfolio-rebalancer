import { useEffect, useRef, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { ApiError } from "../api/client";
import type { RebalancePlan, RebalancePreviewPayload, RebalanceValuationBasis } from "../api/types";
import { useAssetClasses } from "../features/assetClasses/api";
import {
  useCancelRebalancePlan,
  useCompleteRebalancePlan,
  useCreateRebalancePlan,
  useRebalancePreview,
  useStartRebalancePlan,
} from "../features/rebalance/api";
import { ProjectedAllocation } from "../features/rebalance/ProjectedAllocation";
import { RebalanceInputs, type RebalanceFormState } from "../features/rebalance/RebalanceInputs";
import { RebalanceLifecycle } from "../features/rebalance/RebalanceLifecycle";
import { RebalanceSummary } from "../features/rebalance/RebalanceSummary";
import { TradeSuggestions } from "../features/rebalance/TradeSuggestions";
import styles from "../features/rebalance/Rebalance.module.css";

const initialForm: RebalanceFormState = {
  availableCny: "0",
  availableUsd: "0",
  tolerance: "2",
  minimumTradeCny: "500",
  allowSell: true,
  allowFx: true,
  valuationBasis: "actual",
  acknowledgeStaleData: false,
};

function token(prefix: string) {
  const value = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}-${value}`;
}

function ratioFromPercent(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? String(parsed / 100) : value;
}

function payloadFor(form: RebalanceFormState, sessionToken: string): RebalancePreviewPayload {
  return {
    session_token: sessionToken,
    request_token: token("preview"),
    available_cny: form.availableCny || "0",
    available_usd: form.availableUsd || "0",
    valuation_basis: form.valuationBasis,
    allow_sell: form.allowSell,
    allow_fx: form.allowFx,
    tolerance: ratioFromPercent(form.tolerance),
    minimum_trade_cny: form.minimumTradeCny || "0",
    acknowledge_stale_data: form.acknowledgeStaleData,
  };
}

export function RebalancePage() {
  const sessionToken = useRef(token("rebalance-session"));
  const initialized = useRef(false);
  const [form, setForm] = useState(initialForm);
  const [isDirty, setIsDirty] = useState(false);
  const [plan, setPlan] = useState<RebalancePlan | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const preview = useRebalancePreview();
  const assetClasses = useAssetClasses();
  const createPlan = useCreateRebalancePlan();
  const startPlan = useStartRebalancePlan();
  const cancelPlan = useCancelRebalancePlan();
  const completePlan = useCompleteRebalancePlan();
  const transitionPending = createPlan.isPending || startPlan.isPending || cancelPlan.isPending || completePlan.isPending;

  const runPreview = async (nextForm = form) => {
    setOperationError(null);
    try {
      await preview.mutateAsync(payloadFor(nextForm, sessionToken.current));
      setPlan(null);
      setIsDirty(false);
    } catch {
      // Mutation state renders the actionable API error.
    }
  };

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void runPreview(initialForm);
  }, []);

  const changeBasis = (valuationBasis: RebalanceValuationBasis) => {
    const next = { ...form, valuationBasis };
    setForm(next);
    setIsDirty(true);
    void runPreview(next);
  };

  const save = async () => {
    setOperationError(null);
    try {
      const saved = await createPlan.mutateAsync({
        ...payloadFor(form, sessionToken.current),
        idempotency_key: token("save-plan"),
      });
      setPlan(saved);
      return saved;
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "方案保存失败。");
      return null;
    }
  };

  const start = async () => {
    const current = plan ?? await save();
    if (!current) return;
    setOperationError(null);
    try {
      setPlan(await startPlan.mutateAsync({ planId: current.id, idempotencyKey: token("start-plan") }));
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "方案开始失败。");
    }
  };

  const cancel = async () => {
    if (!plan) return;
    setOperationError(null);
    try {
      setPlan(await cancelPlan.mutateAsync({ planId: plan.id, idempotencyKey: token("cancel-plan") }));
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "方案取消失败。");
    }
  };

  const complete = async () => {
    if (!plan) return;
    setOperationError(null);
    try {
      setPlan(await completePlan.mutateAsync({ planId: plan.id, idempotencyKey: token("complete-plan") }));
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "方案完成失败。");
    }
  };

  const staleError = preview.error instanceof ApiError && preview.error.code === "REBALANCE_STALE_DATA_ACK_REQUIRED";
  const generalError = preview.error instanceof ApiError && !staleError ? preview.error.message : null;
  const currentPreview = preview.data;
  const lifecycleDisabled = isDirty || !currentPreview || staleError || (currentPreview.data_status === "stale" && !form.acknowledgeStaleData);

  return (
    <section className={styles.page} aria-label="再平衡工作台">
      <header className={styles.pageHeader}>
        <div><p>REBALANCE WORKBENCH</p><h1>再平衡校准</h1><span>建议只用于规划，不会连接券商或自动提交订单。</span></div>
        <div className={styles.basisStatus}><span>当前口径</span><strong>{form.valuationBasis === "actual" ? "实际人民币占比" : "剔汇率模拟"}</strong></div>
      </header>
      <div className={styles.workspace}>
        <RebalanceInputs value={form} pending={preview.isPending} onChange={(next) => { setForm(next); setIsDirty(true); setPlan(null); }} onBasisChange={changeBasis} onSubmit={() => void runPreview()} />
        <main className={styles.results}>
          {preview.isPending && !currentPreview ? <div className={styles.loading} role="status"><RefreshCw size={18} aria-hidden="true" />正在载入行情并计算方案</div> : null}
          {staleError ? <section className={styles.stale} role="alert">
            <AlertTriangle size={20} aria-hidden="true" /><div><h2>部分行情数据已过期</h2><p>保存正式方案前，需要明确确认使用当前旧值。重新测算后，结果会保留过期数据标记。</p><label><input type="checkbox" checked={form.acknowledgeStaleData} onChange={(event) => { setForm({ ...form, acknowledgeStaleData: event.target.checked }); setIsDirty(true); }} />我已了解数据时效风险</label></div>
          </section> : null}
          {generalError ? <p className={styles.error} role="alert">{generalError}</p> : null}
          {isDirty && currentPreview ? <p className={styles.dirtyNotice}>参数已修改，请重新测算后再保存或开始方案。</p> : null}
          {assetClasses.isError ? <p className={styles.error} role="alert">资产类别名称载入失败。</p> : null}
          {currentPreview ? <>
            {currentPreview.data_status === "stale" ? <div className={styles.dataWarning}><AlertTriangle size={16} aria-hidden="true" />本方案使用了已确认的过期行情数据。</div> : null}
            <RebalanceSummary preview={currentPreview} />
            <ProjectedAllocation preview={currentPreview} assetClasses={assetClasses.data ?? []} tolerance={ratioFromPercent(form.tolerance)} />
            <TradeSuggestions trades={currentPreview.result.trades} />
            <section className={styles.comparison} aria-labelledby="fx-comparison-title">
              <header className={styles.sectionHeading}><div><p>FX COMPARISON</p><h2 id="fx-comparison-title">汇率口径对照</h2></div></header>
              <p>切换为{currentPreview.fx_comparison.valuation_basis === "actual" ? "实际占比" : "剔汇率口径"}时，建议交易为 <b>{currentPreview.fx_comparison.result.trades.length}</b> 笔，最大偏离为 <b>{currentPreview.fx_comparison.result.max_drift_after}</b>。用于判断比例变化是否主要来自汇率。</p>
            </section>
          </> : null}
          {operationError ? <p className={styles.error} role="alert">{operationError}</p> : null}
          <RebalanceLifecycle plan={plan} disabled={lifecycleDisabled} pending={transitionPending} onSave={() => void save()} onStart={() => void start()} onCancel={() => void cancel()} onComplete={() => void complete()} />
        </main>
      </div>
    </section>
  );
}
