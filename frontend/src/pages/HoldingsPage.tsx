import { Filter } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import type { Holding } from "../api/types";
import { useAssetClasses } from "../features/assetClasses/api";
import { AdjustmentHistoryDrawer } from "../features/holdings/AdjustmentHistoryDrawer";
import { CorrectionDrawer } from "../features/holdings/CorrectionDrawer";
import { HoldingsTable, type HoldingCommand } from "../features/holdings/HoldingsTable";
import { PurchaseDrawer } from "../features/holdings/PurchaseDrawer";
import { SaleDrawer } from "../features/holdings/SaleDrawer";
import { useArchiveHolding, useHoldings } from "../features/holdings/api";
import styles from "./HoldingsPage.module.css";
import pageState from "./PageState.module.css";

type OpenDrawer = Exclude<HoldingCommand, "archive"> | null;

export function HoldingsPage() {
  const holdings = useHoldings();
  const assetClasses = useAssetClasses();
  const archive = useArchiveHolding();
  const [showArchived, setShowArchived] = useState(false);
  const [selected, setSelected] = useState<Holding | null>(null);
  const [drawer, setDrawer] = useState<OpenDrawer>(null);
  const [error, setError] = useState<string | null>(null);

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

  if (holdings.isPending || assetClasses.isPending) return <div className={pageState.state}>正在载入持仓与成本...</div>;
  if (holdings.isError || assetClasses.isError) return <div className={`${pageState.state} ${pageState.error}`} role="alert">持仓数据载入失败。</div>;

  return (
    <section className={styles.page} aria-labelledby="holdings-title">
      <header className={styles.header}>
        <div><p>MANUAL CORE</p><h2 id="holdings-title">持仓与成本维护</h2><span>行情、市值与浮动盈亏将在市场数据接入后显示。</span></div>
        <label className={styles.filter}><Filter size={15} aria-hidden="true" /><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />显示已归档持仓</label>
      </header>
      {error ? <div className={styles.alert} role="alert">{error}</div> : null}
      <HoldingsTable holdings={holdings.data} assetClasses={assetClasses.data} showArchived={showArchived} onCommand={(holding, next) => void command(holding, next)} />
      <footer className={styles.statusBar}><span>{holdings.data.filter((item) => item.is_active).length} 个启用持仓</span><span>成本字段来自手工维护 · 不含已实现盈亏</span></footer>

      {selected ? <PurchaseDrawer holding={selected} open={drawer === "purchase"} onClose={closeDrawer} onUpdated={closeDrawer} /> : null}
      {selected ? <SaleDrawer holding={selected} open={drawer === "sell"} onClose={closeDrawer} onUpdated={closeDrawer} /> : null}
      {selected ? <CorrectionDrawer holding={selected} open={drawer === "correction"} onClose={closeDrawer} onUpdated={closeDrawer} /> : null}
      {selected ? <AdjustmentHistoryDrawer holding={selected} open={drawer === "history"} onClose={closeDrawer} /> : null}
    </section>
  );
}
