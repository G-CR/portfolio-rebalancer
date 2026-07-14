import { Eye } from "lucide-react";

import type { SnapshotSummary } from "../../api/types";
import { formatAmount } from "../analytics/format";
import { snapshotCompletenessLabel } from "./completeness";
import { formatSnapshotCapturedAt } from "./dateTime";
import styles from "./Snapshots.module.css";

export function snapshotTypeLabel(type: SnapshotSummary["snapshot_type"]) {
  if (type === "daily") return "日终快照";
  if (type === "manual") return "手动快照";
  if (type === "rebalance_before") return "再平衡前";
  return "再平衡后";
}

type SnapshotTableProps = {
  items: SnapshotSummary[];
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onSelect: (id: string) => void;
};

export function SnapshotTable({ items, page, pageSize, onPageChange, onSelect }: SnapshotTableProps) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const pageItems = items.slice((page - 1) * pageSize, page * pageSize);
  return (
    <section aria-label="快照事件表">
      <div className={styles.tableWrap}>
        <table className={styles.table} aria-label="快照事件">
          <thead><tr><th scope="col">时间</th><th scope="col">类型</th><th scope="col">备注</th><th scope="col">数据完整性</th><th scope="col">核心池市值</th><th scope="col"><span className={styles.srOnly}>操作</span></th></tr></thead>
          <tbody>{pageItems.map((item) => (
            <tr key={item.id}>
              <td data-label="时间"><time dateTime={item.captured_at}>{formatSnapshotCapturedAt(item.captured_at, item.local_date)}</time></td>
              <td data-label="类型"><span className={styles.typeLabel} data-type={item.snapshot_type}>{snapshotTypeLabel(item.snapshot_type)}</span></td>
              <td data-label="备注">{item.note || "无备注"}</td>
              <td data-label="数据完整性"><span className={styles.completeness}>{snapshotCompletenessLabel(item)}</span></td>
              <td data-label="核心池市值" className={styles.numeric}>{formatAmount(item.total_market_value_cny, 2)}</td>
              <td><button className={styles.iconButton} type="button" title="查看详情" aria-label="查看详情" onClick={() => onSelect(item.id)}><Eye size={16} aria-hidden="true" /></button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <nav className={styles.pagination} aria-label="快照事件分页">
        <span>{`第 ${page} / ${pageCount} 页 · 共 ${items.length} 条`}</span>
        <div>
          <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</button>
          <button type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>下一页</button>
        </div>
      </nav>
    </section>
  );
}
