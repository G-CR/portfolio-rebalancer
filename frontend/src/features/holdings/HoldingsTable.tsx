import { Archive, History, MoreHorizontal, Pencil, Plus, TrendingDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { AssetClass, Holding, HoldingAnalytics, PortfolioIncompleteItem } from "../../api/types";
import { formatAmount, formatDecimal, formatSignedAmount, statusLabel } from "../analytics/format";
import styles from "./HoldingsTable.module.css";

export type HoldingCommand = "purchase" | "sell" | "correction" | "history" | "archive";

type Props = {
  holdings: Holding[];
  assetClasses: AssetClass[];
  analyticsById: Map<string, HoldingAnalytics>;
  incompleteById: Map<string, PortfolioIncompleteItem[]>;
  showArchived: boolean;
  onCommand: (holding: Holding, command: HoldingCommand) => void;
};

function ActionMenu({ holding, onCommand }: { holding: Holding; onCommand: Props["onCommand"] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  function run(command: HoldingCommand) {
    setOpen(false);
    onCommand(holding, command);
  }

  return (
    <div className={styles.menuRoot} ref={root}>
      <button className={styles.iconButton} type="button" title="更多操作" aria-label={`更多 ${holding.symbol} 操作`} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <MoreHorizontal size={17} aria-hidden="true" />
      </button>
      {open ? (
        <div className={styles.menu} role="menu">
          <button type="button" role="menuitem" onClick={() => run("sell")}><TrendingDown size={15} aria-hidden="true" />卖出调整</button>
          <button type="button" role="menuitem" onClick={() => run("correction")}><Pencil size={15} aria-hidden="true" />人工修正</button>
          <button type="button" role="menuitem" onClick={() => run("history")}><History size={15} aria-hidden="true" />调整历史</button>
          {holding.is_active ? <button className={styles.dangerItem} type="button" role="menuitem" onClick={() => run("archive")}><Archive size={15} aria-hidden="true" />归档持仓</button> : null}
        </div>
      ) : null}
    </div>
  );
}

function MarketValue({ value, status }: { value: string; status: string }) {
  return <div className={styles.marketValue}><span>{value}</span>{status === "valid" ? null : <small data-status={status}>{statusLabel(status)}</small>}</div>;
}

export function HoldingsTable({ holdings, assetClasses, analyticsById, incompleteById, showArchived, onCommand }: Props) {
  const assetNames = new Map(assetClasses.map((item) => [item.id, item.name]));
  const visible = holdings.filter((holding) => showArchived ? !holding.is_active : holding.is_active);

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">标的</th>
            <th scope="col">账户 / 类别</th>
            <th scope="col">币种</th>
            <th scope="col">份额</th>
            <th scope="col">成本价</th>
            <th scope="col">成本汇率</th>
            <th scope="col">当前价</th>
            <th scope="col">当前汇率</th>
            <th scope="col">市值</th>
            <th scope="col">浮动盈亏</th>
            <th scope="col"><span className={styles.srOnly}>操作</span></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((holding) => {
            const analytics = analyticsById.get(holding.id);
            const incomplete = incompleteById.get(holding.id) ?? [];
            const priceMissing = incomplete.some((item) => item.input === "price");
            const fxMissing = incomplete.some((item) => item.input === "fx");
            const anyMissing = priceMissing || fxMissing;
            return (
            <tr key={holding.id} data-archived={!holding.is_active || undefined}>
              <td><div className={styles.symbol}><strong>{holding.symbol}</strong><span>{holding.name}</span>{!holding.is_active ? <em>已归档</em> : null}</div></td>
              <td className={styles.secondaryColumn}><div className={styles.stack}><span>{holding.account_name}</span><small>{assetNames.get(holding.asset_class_id) ?? "未分类"}</small></div></td>
              <td className={styles.secondaryColumn}><span className={styles.currency}>{holding.trade_currency}</span></td>
              <td className={styles.numeric}>{holding.quantity}</td>
              <td className={`${styles.numeric} ${styles.costColumn}`}>{holding.average_cost_price}</td>
              <td className={`${styles.numeric} ${styles.costColumn}`}>{holding.cost_fx_to_cny}</td>
              <td className={`${styles.numeric} ${styles.marketColumn}`}>{analytics ? <MarketValue value={formatDecimal(analytics.current_price)} status={analytics.price_status} /> : <span className={styles.pendingData}>{priceMissing ? "数据缺失" : "--"}</span>}</td>
              <td className={`${styles.numeric} ${styles.marketColumn}`}>{analytics ? <MarketValue value={formatDecimal(analytics.current_fx_to_cny)} status={analytics.fx_status} /> : <span className={styles.pendingData}>{fxMissing ? "数据缺失" : "--"}</span>}</td>
              <td className={`${styles.numeric} ${styles.priorityMarket}`}>{analytics ? <><span className={styles.desktopAmount}>{formatAmount(analytics.market_value_cny, 2)}</span><span className={styles.mobileAmount}>{formatAmount(analytics.market_value_cny, 0)}</span></> : <span className={styles.pendingData}>{anyMissing ? "数据缺失" : "--"}</span>}</td>
              <td className={`${styles.numeric} ${styles.priorityMarket}`}>{analytics ? <><span className={styles.desktopAmount}>{formatSignedAmount(analytics.unrealized_pnl)}</span><span className={styles.mobileAmount}>{formatSignedAmount(analytics.unrealized_pnl, 0)}</span></> : <span className={styles.pendingData}>{anyMissing ? "数据缺失" : "--"}</span>}</td>
              <td>
                {holding.is_active ? (
                  <div className={styles.actions}>
                    <button className={`${styles.iconButton} ${styles.addButton}`} type="button" title="追加买入" aria-label={`追加买入 ${holding.symbol}`} onClick={() => onCommand(holding, "purchase")}>
                      <Plus size={17} aria-hidden="true" />
                    </button>
                    <ActionMenu holding={holding} onCommand={onCommand} />
                  </div>
                ) : <span className={styles.archivedActions}>已归档，无可用操作</span>}
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
      {visible.length === 0 ? <div className={styles.empty}>没有符合当前筛选条件的持仓。</div> : null}
    </div>
  );
}
