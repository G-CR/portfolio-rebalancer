import { Eye } from "lucide-react";

import type { SnapshotSummary } from "../../api/types";
import { formatAmount, formatDataTime } from "../analytics/format";
import styles from "./Snapshots.module.css";

export function snapshotTypeLabel(type: SnapshotSummary["snapshot_type"]) {
  if (type === "daily") return "日终快照";
  if (type === "manual") return "手动快照";
  if (type === "rebalance_before") return "再平衡前";
  return "再平衡后";
}

function completeness(item: SnapshotSummary) {
  if (!item.data_complete) return "数据不完整";
  if (item.has_stale_data && item.has_manual_data) return "含过期与手动值";
  if (item.has_stale_data) return "含过期数据";
  if (item.has_manual_data) return "含手动值";
  return "数据完整";
}

export function SnapshotTable({ items, onSelect }: { items: SnapshotSummary[]; onSelect: (id: string) => void }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} aria-label="快照事件">
        <thead><tr><th scope="col">时间</th><th scope="col">类型</th><th scope="col">备注</th><th scope="col">数据完整性</th><th scope="col">核心池市值</th><th scope="col"><span className={styles.srOnly}>操作</span></th></tr></thead>
        <tbody>{items.map((item) => (
          <tr key={item.id}>
            <td data-label="时间"><time dateTime={item.captured_at}>{formatDataTime(item.captured_at)}</time></td>
            <td data-label="类型"><span className={styles.typeLabel} data-type={item.snapshot_type}>{snapshotTypeLabel(item.snapshot_type)}</span></td>
            <td data-label="备注">{item.note || "无备注"}</td>
            <td data-label="数据完整性"><span className={styles.completeness}>{completeness(item)}</span></td>
            <td data-label="核心池市值" className={styles.numeric}>{formatAmount(item.total_market_value_cny, 2)}</td>
            <td><button className={styles.iconButton} type="button" title="查看详情" aria-label="查看详情" onClick={() => onSelect(item.id)}><Eye size={16} aria-hidden="true" /></button></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
