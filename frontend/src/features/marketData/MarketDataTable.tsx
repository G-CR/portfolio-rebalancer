import { Pencil, RotateCcw, Trash2 } from "lucide-react";

import type { MarketDataStatus } from "../../api/types";
import { formatDataTime, formatDecimal, statusLabel } from "../analytics/format";
import { useDeleteMarketDataOverride } from "./api";
import styles from "./MarketData.module.css";

export function MarketDataTable({ items, onOverride }: { items: MarketDataStatus[]; onOverride: (item: MarketDataStatus) => void }) {
  const remove = useDeleteMarketDataOverride();
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>数据项</th><th>有效值</th><th>来源</th><th>市场时间</th><th>抓取时间</th><th>状态与说明</th><th>操作</th></tr></thead>
        <tbody>{items.map((item) => <tr key={item.key}>
          <th scope="row"><strong>{item.symbol}</strong><span>{item.data_type === "fx" ? "汇率" : "行情"} · {item.currency}</span></th>
          <td>{item.effective_value === null ? "-" : formatDecimal(item.effective_value, 6)}</td>
          <td>{item.source === "manual" ? "手动覆盖" : item.source ?? "-"}</td>
          <td>{formatDataTime(item.market_time)}</td><td>{formatDataTime(item.fetched_at)}</td>
          <td><strong className={item.status === "stale" || item.status === "failed" ? styles.badStatus : item.status === "manual" ? styles.manualStatus : styles.goodStatus}>{statusLabel(item.status)}</strong>{item.error_summary ? <small>{item.error_summary}</small> : item.note ? <small>{item.note}</small> : null}</td>
          <td><div className={styles.rowActions}><button type="button" title={`覆盖 ${item.symbol}`} aria-label={`覆盖 ${item.symbol}`} onClick={() => onOverride(item)}><Pencil size={15} aria-hidden="true" /></button>{item.status === "manual" ? <button type="button" title={`取消 ${item.symbol} 手动覆盖`} aria-label={`取消 ${item.symbol} 手动覆盖`} onClick={() => void remove.mutateAsync(item.key)}><Trash2 size={15} aria-hidden="true" /></button> : <span title="自动数据"><RotateCcw size={14} aria-hidden="true" /></span>}</div></td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}
