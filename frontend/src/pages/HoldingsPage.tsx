import { Filter, Plus } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import type { Holding } from "../api/types";
import { useAssetClasses } from "../features/assetClasses/api";
import { AddHoldingDrawer } from "../features/holdings/AddHoldingDrawer";
import { AdjustmentHistoryDrawer } from "../features/holdings/AdjustmentHistoryDrawer";
import { CorrectionDrawer } from "../features/holdings/CorrectionDrawer";
import { HoldingsTable, type HoldingCommand } from "../features/holdings/HoldingsTable";
import { PurchaseDrawer } from "../features/holdings/PurchaseDrawer";
import { SaleDrawer } from "../features/holdings/SaleDrawer";
import { useArchiveHolding, useHoldings } from "../features/holdings/api";
import styles from "./HoldingsPage.module.css";
import { PageError, PageLoading } from "./PageState";

type OpenDrawer = Exclude<HoldingCommand, "archive"> | null;

export function HoldingsPage() {
  const [showArchived, setShowArchived] = useState(false);
  const holdings = useHoldings(showArchived);
  const assetClasses = useAssetClasses();
  const archive = useArchiveHolding();
  const [selected, setSelected] = useState<Holding | null>(null);
  const [drawer, setDrawer] = useState<OpenDrawer>(null);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  async function command(holding: Holding, next: HoldingCommand) {
    if (next === "archive") {
      if (!window.confirm(`归档 ${holding.symbol} 后，默认列表将不再显示该持仓。继续吗？`)) return;
      setError(null);
      try {
        await archive.mutateAsync(holding.id);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "持仓归档失败。");
      }
      return;
    }
    setSelected(holding);
    setDrawer(next);
  }

  function closeDrawer() {
    setDrawer(null);
    setSelected(null);
  }

  if (holdings.isPending || assetClasses.isPending) return <PageLoading kind="holdings" />;
  if (holdings.isError || assetClasses.isError) {
    const loadError = holdings.error ?? assetClasses.error;
    const message = loadError instanceof ApiError ? loadError.message : "持仓数据载入失败。";
    return <PageError title="持仓与成本无法载入" message={message} retryLabel="重试载入持仓" onRetry={() => { void holdings.refetch(); void assetClasses.refetch(); }} />;
  }

  const activeCount = holdings.data.filter((item) => item.is_active).length;
  const archivedCount = holdings.data.filter((item) => !item.is_active).length;
  const filterLoading = holdings.isFetching && !holdings.isPending;

  return (
    <section className={styles.page} aria-labelledby="holdings-title">
      <header className={styles.header}>
        <div><p>MANUAL CORE</p><h2 id="holdings-title">持仓与成本维护</h2><span>行情、市值与浮动盈亏将在市场数据接入后显示。</span></div>
        <div className={styles.headerActions}>
          <button className={styles.addButton} type="button" onClick={() => setAddOpen(true)}>
            <Plus size={16} aria-hidden="true" />添加持仓
          </button>
          <label className={styles.filter}><Filter size={15} aria-hidden="true" /><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />仅显示已归档持仓</label>
        </div>
      </header>
      {error ? <div className={styles.alert} role="alert">{error}</div> : null}
      {filterLoading ? <div className={styles.filterStatus} role="status">正在载入已归档持仓...</div> : null}
      {!showArchived && activeCount === 0 ? (
        <div className={styles.emptyState}>
          <strong>尚未添加持仓</strong>
          <p>先记录一个标的及其初始成本状态，再维护买入、卖出和修正。</p>
          <button type="button" onClick={() => setAddOpen(true)}><Plus size={16} aria-hidden="true" />添加第一个持仓</button>
        </div>
      ) : null}
      {showArchived && !filterLoading && archivedCount === 0 ? (
        <div className={styles.emptyState}><strong>没有已归档持仓</strong><p>当前所有持仓都处于启用状态。</p></div>
      ) : null}
      {((!showArchived && activeCount > 0) || (showArchived && archivedCount > 0)) ? (
        <HoldingsTable holdings={holdings.data} assetClasses={assetClasses.data} showArchived={showArchived} onCommand={(holding, next) => void command(holding, next)} />
      ) : null}
      <footer className={styles.statusBar}><span>{activeCount} 个启用持仓{showArchived ? ` · ${archivedCount} 个已归档` : ""}</span><span>成本字段来自手工维护 · 不含已实现盈亏</span></footer>

      {selected ? <PurchaseDrawer holding={selected} open={drawer === "purchase"} onClose={closeDrawer} onUpdated={closeDrawer} /> : null}
      {selected ? <SaleDrawer holding={selected} open={drawer === "sell"} onClose={closeDrawer} onUpdated={closeDrawer} /> : null}
      {selected ? <CorrectionDrawer holding={selected} open={drawer === "correction"} onClose={closeDrawer} onUpdated={closeDrawer} /> : null}
      {selected ? <AdjustmentHistoryDrawer holding={selected} open={drawer === "history"} onClose={closeDrawer} /> : null}
      {addOpen ? <AddHoldingDrawer assetClasses={assetClasses.data} open onClose={() => setAddOpen(false)} onCreated={() => { setAddOpen(false); setShowArchived(false); }} /> : null}
    </section>
  );
}
