import { RefreshCw } from "lucide-react";
import { useState } from "react";

import type { MarketDataStatus } from "../api/types";
import { MarketDataTable } from "../features/marketData/MarketDataTable";
import { OverrideDrawer } from "../features/marketData/OverrideDrawer";
import { useMarketData, useRefreshMarketData } from "../features/marketData/api";
import styles from "../features/marketData/MarketData.module.css";
import { ProviderSettings } from "../features/settings/ProviderSettings";

export function MarketDataPage() {
  const marketData = useMarketData();
  const refresh = useRefreshMarketData();
  const [overrideItem, setOverrideItem] = useState<MarketDataStatus | null>(null);
  return (
    <section className={styles.page} aria-label="数据源设置">
      <header className={styles.pageHeader}>
        <div><p>MARKET DATA CONTROL</p><h1>行情与汇率状态</h1><span>有效值按手动覆盖、最近有效自动值和过期回退的顺序确定。</span></div>
        <button type="button" className={styles.primary} disabled={refresh.isPending} onClick={() => void refresh.mutateAsync()}><RefreshCw size={16} aria-hidden="true" />{refresh.isPending ? "正在刷新" : "刷新全部数据"}</button>
      </header>
      <section className={styles.statusSection} aria-labelledby="market-status-title">
        <header className={styles.sectionHeading}><div><p>EFFECTIVE VALUES</p><h2 id="market-status-title">当前有效数据</h2></div><span>{marketData.data?.items.length ?? 0} 个必需数据项</span></header>
        {marketData.isPending ? <div className={styles.loading} role="status">正在载入数据状态</div> : marketData.isError ? <p className={styles.error} role="alert">行情与汇率状态载入失败。</p> : <MarketDataTable items={marketData.data.items} onOverride={setOverrideItem} />}
      </section>
      <ProviderSettings />
      {overrideItem ? <OverrideDrawer marketKey={overrideItem.key} symbol={overrideItem.symbol} open onClose={() => setOverrideItem(null)} /> : null}
    </section>
  );
}
