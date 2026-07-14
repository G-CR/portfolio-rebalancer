import type { SnapshotSummary } from "../../api/types";

type SnapshotCompleteness = Pick<SnapshotSummary, "data_complete" | "has_stale_data" | "has_manual_data">;

export function snapshotCompletenessLabel(item: SnapshotCompleteness) {
  if (!item.data_complete) return "数据不完整";
  if (item.has_stale_data && item.has_manual_data) return "含过期与手动值";
  if (item.has_stale_data) return "含过期数据";
  if (item.has_manual_data) return "含手动值";
  return "数据完整";
}
