import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Calculator, RefreshCw } from "lucide-react";

import { ApiError } from "../api/client";
import type { ApiErrorDetail, RebalanceDefaultsUpdate, RebalancePlan, RebalancePreview, RebalancePreviewJobStatus, RebalancePreviewPayload, RebalanceValuationBasis } from "../api/types";
import { useAssetClasses } from "../features/assetClasses/api";
import { formatPercent } from "../features/analytics/format";
import { useHoldings } from "../features/holdings/api";
import { useMarketDataRefreshVersion } from "../features/marketData/api";
import { useRebalanceDefaults, useSaveRebalanceDefaults } from "../features/settings/api";
import {
  useCancelRebalancePlan,
  useCompleteRebalancePlan,
  useCreateRebalancePlan,
  useRebalancePlans,
  useRebalancePreview,
  useRebalancePreviewJob,
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

function percentFromRatio(value: string) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  const formatted = (parsed * 100).toFixed(8).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return formatted || "0";
}

function defaultsPayloadFor(form: RebalanceFormState): RebalanceDefaultsUpdate {
  return {
    available_cny: form.availableCny || "0",
    available_usd: form.availableUsd || "0",
    valuation_basis: form.valuationBasis,
    tolerance: ratioFromPercent(form.tolerance),
    allow_sell: form.allowSell,
    allow_fx: form.allowFx,
  };
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
    acknowledge_stale_data: form.acknowledgeStaleData,
  };
}

function previewFromPlan(plan: RebalancePlan): RebalancePreview {
  return {
    session_token: "",
    request_token: "",
    status: "ok",
    data_status: plan.data_status,
    acknowledge_stale_data: plan.data_status === "stale",
    refresh_attempted: false,
    valuation_basis: plan.valuation_basis,
    result: plan.result,
    fx_comparison: plan.fx_comparison,
  };
}

function previewJobMessage(status: RebalancePreviewJobStatus | undefined) {
  if (status === "refreshing") return "正在刷新行情";
  if (status === "calculating") return "正在计算方案";
  return "正在排队测算";
}

export function RebalancePage() {
  const sessionToken = useRef(token("rebalance-session"));
  const [form, setForm] = useState(initialForm);
  const [isDirty, setIsDirty] = useState(false);
  const [plan, setPlan] = useState<RebalancePlan | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [defaultsWarning, setDefaultsWarning] = useState<string | null>(null);
  const [defaultsReady, setDefaultsReady] = useState(false);
  const preview = useRebalancePreview();
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<RebalancePreview | null>(null);
  const [previewJobFailure, setPreviewJobFailure] = useState<ApiErrorDetail | null>(null);
  const previewJob = useRebalancePreviewJob(previewJobId);
  const plans = useRebalancePlans();
  const refreshVersion = useMarketDataRefreshVersion().data;
  const observedRefreshVersion = useRef(refreshVersion);
  const [planRestoreCompleted, setPlanRestoreCompleted] = useState(false);
  const defaults = useRebalanceDefaults();
  const saveDefaults = useSaveRebalanceDefaults();
  const defaultsHydrated = useRef(false);
  const assetClasses = useAssetClasses();
  const holdings = useHoldings();
  const createPlan = useCreateRebalancePlan();
  const startPlan = useStartRebalancePlan();
  const cancelPlan = useCancelRebalancePlan();
  const completePlan = useCompleteRebalancePlan();
  const transitionPending = createPlan.isPending || startPlan.isPending || cancelPlan.isPending || completePlan.isPending;

  useEffect(() => {
    if (planRestoreCompleted || plans.isFetching || !plans.data) return;
    if (!preview.data) {
      const recoverablePlan = plans.data.items.find((item) => item.status === "in_progress") ?? null;
      setPlan((current) => current ?? recoverablePlan);
    }
    setPlanRestoreCompleted(true);
  }, [planRestoreCompleted, plans.data, plans.isFetching, preview.data]);

  useEffect(() => {
    if (refreshVersion === observedRefreshVersion.current) return;
    observedRefreshVersion.current = refreshVersion;
    preview.reset();
    setPreviewResult(null);
    setPreviewJobId(null);
    setPreviewJobFailure(null);
    setPlan((current) => current?.status === "in_progress" ? current : null);
    setIsDirty(false);
    setOperationError(null);
    setDefaultsWarning(null);
  }, [refreshVersion]);

  useEffect(() => {
    const job = previewJob.data;
    if (!job) return;
    if (job.status === "succeeded" && job.result) {
      setPreviewResult(job.result);
      setPreviewJobId(null);
      setIsDirty(false);
    } else if (job.status === "failed" && job.error) {
      setPreviewJobFailure(job.error);
      setPreviewJobId(null);
    }
  }, [previewJob.data]);

  useEffect(() => {
    if (defaultsHydrated.current || (!defaults.data && !defaults.isError)) return;
    defaultsHydrated.current = true;
    if (defaults.data) {
      setForm({
        availableCny: defaults.data.available_cny,
        availableUsd: defaults.data.available_usd,
        tolerance: percentFromRatio(defaults.data.tolerance),
        allowSell: defaults.data.allow_sell,
        allowFx: defaults.data.allow_fx,
        valuationBasis: defaults.data.valuation_basis,
        acknowledgeStaleData: false,
      });
    }
    setDefaultsReady(true);
  }, [defaults.data, defaults.isError]);

  const runPreview = async (nextForm = form) => {
    if ((!planRestoreCompleted && !plans.isError) || plan?.status === "in_progress") return;
    setOperationError(null);
    setDefaultsWarning(null);
    let defaultsSaveFailed = false;
    try {
      await saveDefaults.mutateAsync(defaultsPayloadFor(nextForm));
    } catch {
      defaultsSaveFailed = true;
    }
    try {
      const job = await preview.mutateAsync(payloadFor(nextForm, sessionToken.current));
      setPreviewResult(null);
      setPreviewJobFailure(null);
      if (job.status === "succeeded" && job.result) {
        setPreviewResult(job.result);
        setIsDirty(false);
      } else if (job.status === "failed" && job.error) {
        setPreviewJobFailure(job.error);
      } else {
        setPreviewJobId(job.id);
      }
      if (defaultsSaveFailed) setDefaultsWarning("测算任务已提交，但默认配置保存失败。");
      setPlan(null);
    } catch {
      // Mutation state renders the actionable API error.
    }
  };

  const changeBasis = (valuationBasis: RebalanceValuationBasis) => {
    if ((!planRestoreCompleted && !plans.isError) || plan?.status === "in_progress") return;
    setForm((current) => ({ ...current, valuationBasis }));
    setIsDirty(Boolean(preview.data));
    setPlan(null);
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

  const previewJobError = previewJobFailure ?? (previewJob.data?.status === "failed" ? previewJob.data.error : null);
  const staleError = (preview.error instanceof ApiError && preview.error.code === "REBALANCE_STALE_DATA_ACK_REQUIRED")
    || previewJobError?.code === "REBALANCE_STALE_DATA_ACK_REQUIRED";
  const generalError = previewJobError && !staleError
    ? previewJobError.message
    : (preview.error instanceof ApiError && !staleError ? preview.error.message : null);
  const currentPreview = previewResult ?? (plan ? previewFromPlan(plan) : undefined);
  const activePlan = plan?.status === "in_progress" ? plan : null;
  const planLookupPending = !planRestoreCompleted && !plans.isError;
  const displayedForm = activePlan ? {
    ...form,
    availableCny: activePlan.available_cny,
    availableUsd: activePlan.available_usd,
    valuationBasis: activePlan.valuation_basis,
    tolerance: percentFromRatio(activePlan.tolerance),
    allowSell: activePlan.allow_sell,
    allowFx: activePlan.allow_fx,
    acknowledgeStaleData: activePlan.acknowledge_stale_data,
  } : form;
  const displayedTolerance = activePlan?.tolerance ?? ratioFromPercent(form.tolerance);
  const holdingNames = Object.fromEntries(
    (holdings.data ?? []).map((holding) => [holding.symbol, holding.name]),
  );
  const lifecycleDisabled = planLookupPending || isDirty || !currentPreview || staleError || (currentPreview.data_status === "stale" && !plan && !form.acknowledgeStaleData);

  return (
    <section className={styles.page} aria-label="再平衡工作台">
      <header className={styles.pageHeader}>
        <div><p>REBALANCE WORKBENCH</p><h1>再平衡校准</h1><span>建议只用于规划，不会连接券商或自动提交订单。</span></div>
        <div className={styles.basisStatus}><span>当前口径</span><strong>{displayedForm.valuationBasis === "actual" ? "实际人民币占比" : "剔汇率模拟"}</strong></div>
      </header>
      <div className={styles.workspace}>
        {!defaultsReady ? <div className={styles.defaultsLoading} role="status"><RefreshCw size={18} aria-hidden="true" />正在载入上次使用的资金与约束</div> : <>
          <RebalanceInputs value={displayedForm} pending={preview.isPending || previewJob.isFetching || Boolean(previewJobId) || saveDefaults.isPending} disabled={planLookupPending || Boolean(activePlan)} hasPreview={Boolean(currentPreview)} onChange={(next) => { if (activePlan) return; setForm(next); setIsDirty(Boolean(currentPreview)); setPlan(null); }} onBasisChange={changeBasis} onSubmit={() => void runPreview()} />
          <main className={styles.results}>
          {defaults.isError ? <p className={styles.defaultsWarning}>默认配置载入失败，当前使用内置默认值。</p> : null}
          {defaultsWarning ? <p className={styles.defaultsWarning}>{defaultsWarning}</p> : null}
          {!preview.isPending && !previewJobId && !currentPreview && !preview.error && !previewJobError ? <div className={styles.previewPrompt}>
            <Calculator size={18} aria-hidden="true" /><div><strong>配置本次资金与约束后开始测算</strong><span>行情刷新将在你点击开始测算后执行。</span></div>
          </div> : null}
          {(preview.isPending || previewJobId) && !currentPreview ? <div className={styles.loading} role="status"><RefreshCw size={18} aria-hidden="true" />{previewJobMessage(previewJob.data?.status)}</div> : null}
          {staleError ? <section className={styles.stale} role="alert">
            <AlertTriangle size={20} aria-hidden="true" /><div><h2>部分行情数据已过期</h2><p>保存正式方案前，需要明确确认使用当前旧值。重新测算后，结果会保留过期数据标记。</p><label><input type="checkbox" checked={form.acknowledgeStaleData} onChange={(event) => { setForm({ ...form, acknowledgeStaleData: event.target.checked }); setIsDirty(true); }} />我已了解数据时效风险</label></div>
          </section> : null}
          {generalError ? <p className={styles.error} role="alert">{generalError}</p> : null}
          {isDirty && currentPreview ? <p className={styles.dirtyNotice}>参数已修改，请重新测算后再保存或开始方案。</p> : null}
          {assetClasses.isError ? <p className={styles.error} role="alert">资产类别名称载入失败。</p> : null}
          {currentPreview ? <>
            {currentPreview.data_status === "stale" ? <div className={styles.dataWarning}><AlertTriangle size={16} aria-hidden="true" />本方案使用了已确认的过期行情数据。</div> : null}
            <RebalanceSummary preview={currentPreview} />
            <ProjectedAllocation preview={currentPreview} assetClasses={assetClasses.data ?? []} tolerance={displayedTolerance} />
            <TradeSuggestions trades={currentPreview.result.trades} holdingNames={holdingNames} />
            <section className={styles.comparison} aria-labelledby="fx-comparison-title">
              <header className={styles.sectionHeading}><div><p>FX COMPARISON</p><h2 id="fx-comparison-title">汇率口径对照</h2></div></header>
              <p>切换为{currentPreview.fx_comparison.valuation_basis === "actual" ? "实际占比" : "剔汇率口径"}时，建议交易为 <b>{currentPreview.fx_comparison.result.trades.length}</b> 笔，最大偏离为 <b>{formatPercent(currentPreview.fx_comparison.result.max_drift_after, 2)}</b>。用于判断比例变化是否主要来自汇率。</p>
            </section>
          </> : null}
          {operationError ? <p className={styles.error} role="alert">{operationError}</p> : null}
            <RebalanceLifecycle plan={plan} disabled={lifecycleDisabled} pending={transitionPending} onSave={() => void save()} onStart={() => void start()} onCancel={() => void cancel()} onComplete={() => void complete()} />
          </main>
        </>}
      </div>
    </section>
  );
}
