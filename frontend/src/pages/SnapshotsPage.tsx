import { Camera, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import type { SnapshotType } from "../api/types";
import { WorkDrawer } from "../components/WorkDrawer/WorkDrawer";
import { useAssetClasses } from "../features/assetClasses/api";
import { formatDataTime } from "../features/analytics/format";
import { useCreateManualSnapshot, useSnapshotDetail, useSnapshots } from "../features/snapshots/api";
import { SnapshotChart, type SnapshotMetric } from "../features/snapshots/SnapshotChart";
import styles from "../features/snapshots/Snapshots.module.css";
import { SnapshotTable, snapshotTypeLabel } from "../features/snapshots/SnapshotTable";
import { PageError } from "./PageState";

type Range = "30" | "90" | "all";

const metrics: { id: SnapshotMetric; label: string }[] = [
  { id: "market", label: "核心池市值" },
  { id: "cost", label: "人民币成本" },
  { id: "pnl", label: "浮动盈亏" },
  { id: "actual_weight", label: "实际占比" },
  { id: "fx_neutral_weight", label: "剔汇率占比" },
  { id: "price_effect", label: "价格影响" },
  { id: "fx_effect", label: "汇率影响" },
];

function fromDate(range: Range) {
  if (range === "all") return undefined;
  const value = new Date();
  value.setHours(0, 0, 0, 0);
  value.setDate(value.getDate() - Number(range));
  return value.toISOString().slice(0, 10);
}

function SnapshotLoading() {
  return <section className={styles.loading} role="status" aria-label="正在载入历史快照"><i /><i /><i /><i /></section>;
}

export function SnapshotsPage() {
  const [range, setRange] = useState<Range>("90");
  const [snapshotType, setSnapshotType] = useState<SnapshotType | "">("");
  const [assetClass, setAssetClass] = useState("");
  const [metric, setMetric] = useState<SnapshotMetric>("market");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [note, setNote] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => ({
    fromDate: fromDate(range),
    snapshotType: snapshotType || undefined,
    assetClass: assetClass || undefined,
    page: 1,
    pageSize: 25,
  }), [range, snapshotType, assetClass]);
  const snapshots = useSnapshots(filters);
  const assetClasses = useAssetClasses();
  const detail = useSnapshotDetail(selectedId);
  const createManual = useCreateManualSnapshot();

  useEffect(() => {
    if (searchParams.get("capture") !== "manual") return;
    setManualOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("capture");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  async function saveManual() {
    try {
      await createManual.mutateAsync({ note: note.trim() || null });
      setNote("");
      setManualOpen(false);
    } catch {
      // The drawer renders the structured API error without losing the note.
    }
  }

  if (snapshots.isPending) return <SnapshotLoading />;
  if (snapshots.isError) {
    const message = snapshots.error instanceof ApiError ? snapshots.error.message : "历史快照载入失败。";
    return <PageError title="历史快照无法载入" message={message} retryLabel="重试载入历史" onRetry={() => void snapshots.refetch()} />;
  }

  return (
    <section className={styles.page} aria-labelledby="snapshots-title">
      <header className={styles.header}>
        <div><p>HISTORY LEDGER</p><h2 id="snapshots-title">历史快照</h2><span>复核日终、手动与再平衡时点的核心池状态</span></div>
        <button className={styles.primaryButton} type="button" onClick={() => setManualOpen(true)}><Camera size={16} aria-hidden="true" />保存当前快照</button>
      </header>
      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <span>时间范围</span>
          <div className={styles.segmented} role="group" aria-label="时间范围">
            <button type="button" aria-pressed={range === "30"} onClick={() => setRange("30")}>近 30 天</button>
            <button type="button" aria-pressed={range === "90"} onClick={() => setRange("90")}>近 90 天</button>
            <button type="button" aria-pressed={range === "all"} onClick={() => setRange("all")}>全部时间</button>
          </div>
        </div>
        <div className={styles.filterGroup}><label htmlFor="snapshot-type">快照类型</label><select id="snapshot-type" value={snapshotType} onChange={(event) => setSnapshotType(event.target.value as SnapshotType | "")}><option value="">全部类型</option><option value="daily">日终快照</option><option value="manual">手动快照</option><option value="rebalance_before">再平衡前</option><option value="rebalance_after">再平衡后</option></select></div>
        <div className={styles.filterGroup}><label htmlFor="snapshot-asset-class">资产类别</label><select id="snapshot-asset-class" value={assetClass} onChange={(event) => setAssetClass(event.target.value)}><option value="">全部类别</option>{assetClasses.data?.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></div>
      </div>
      <div className={styles.metrics} role="group" aria-label="主要分析口径">{metrics.map((item) => <button key={item.id} type="button" aria-pressed={metric === item.id} onClick={() => setMetric(item.id)}>{item.label}</button>)}</div>
      {snapshots.data.items.length === 0 ? <section className={styles.empty}><strong>还没有历史快照</strong><p>完成一次有效数据刷新，或保存当前手动快照后，这里会出现可复核的时点记录。</p></section> : <><SnapshotChart items={snapshots.data.items} metric={metric} /><SnapshotTable items={snapshots.data.items} onSelect={setSelectedId} /></>}

      <WorkDrawer open={Boolean(selectedId)} title="快照详情" onClose={() => setSelectedId(null)}>
        {detail.isPending ? <p role="status">正在载入快照详情...</p> : null}
        {detail.isError ? <p role="alert">快照详情载入失败。</p> : null}
        {detail.data ? <><dl className={styles.drawerMeta}><div><dt>时间</dt><dd>{formatDataTime(detail.data.captured_at)}</dd></div><div><dt>类型</dt><dd>{snapshotTypeLabel(detail.data.snapshot_type)}</dd></div><div><dt>备注</dt><dd>{detail.data.note || "无备注"}</dd></div><div><dt>数据状态</dt><dd>{detail.data.has_stale_data ? "含过期数据" : detail.data.has_manual_data ? "含手动值" : "数据完整"}</dd></div></dl><div className={styles.detailList}>{detail.data.items.map((item) => <article className={styles.detailItem} key={item.id}><h3>{item.symbol}</h3><p>{item.holding_name} · {item.asset_class_name} · {item.account_name}</p><div className={styles.detailGrid}><div><span>份额</span><strong>{item.quantity}</strong></div><div><span>市场价格</span><strong>{item.market_price ?? "缺失"}</strong></div><div><span>当前汇率</span><strong>{item.current_fx_to_cny ?? "缺失"}</strong></div><div><span>基准汇率</span><strong>{item.baseline_fx_to_cny}</strong></div><div><span>平均成本价</span><strong>{item.average_cost_price}</strong></div><div><span>成本汇率</span><strong>{item.cost_fx_to_cny}</strong></div><div><span>目标占比</span><strong>{item.target_weight}</strong></div><div><span>实际占比</span><strong>{item.actual_weight ?? "缺失"}</strong></div><div><span>剔汇率占比</span><strong>{item.fx_neutral_weight ?? "缺失"}</strong></div><div><span>价格 / 汇率状态</span><strong>{item.price_status} / {item.fx_status}</strong></div></div></article>)}</div></> : null}
      </WorkDrawer>

      <WorkDrawer open={manualOpen} title="保存手动快照" onClose={() => setManualOpen(false)}>
        <div className={styles.manualForm}><label htmlFor="snapshot-note">快照备注</label><textarea id="snapshot-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录本次复核、调整背景或数据说明" /><p>当前数据含过期或手动值时，必须填写备注。</p>{createManual.isError ? <p className={styles.manualError} role="alert">{createManual.error instanceof ApiError ? createManual.error.message : "手动快照保存失败。"}</p> : null}<div className={styles.drawerActions}><button className={styles.secondaryButton} type="button" onClick={() => setManualOpen(false)}>取消</button><button className={styles.primaryButton} type="button" disabled={createManual.isPending} onClick={() => void saveManual()}>{createManual.isPending ? <RefreshCw size={16} aria-hidden="true" /> : <Camera size={16} aria-hidden="true" />}{createManual.isPending ? "正在保存" : "保存快照"}</button></div></div>
      </WorkDrawer>
    </section>
  );
}
