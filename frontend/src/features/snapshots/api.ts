import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type { SnapshotCollection, SnapshotDetail, SnapshotType } from "../../api/types";

export const snapshotsQueryRoot = ["snapshots"] as const;
const SERIES_PAGE_SIZE = 100;
const MAX_SERIES_PAGES = 100;

export type SnapshotFilters = {
  fromDate?: string;
  snapshotType?: SnapshotType;
  assetClass?: string;
};

function collectionPath(filters: SnapshotFilters, page: number) {
  const params = new URLSearchParams();
  if (filters.fromDate) params.set("from_date", filters.fromDate);
  if (filters.snapshotType) params.set("snapshot_type", filters.snapshotType);
  if (filters.assetClass) params.set("asset_class", filters.assetClass);
  params.set("page", String(page));
  params.set("page_size", String(SERIES_PAGE_SIZE));
  return `/api/snapshots?${params.toString()}`;
}

async function fetchSnapshotSeries(filters: SnapshotFilters, signal: AbortSignal) {
  const first = await apiRequest<SnapshotCollection>(collectionPath(filters, 1), { signal });
  const pageCount = Math.ceil(first.total / SERIES_PAGE_SIZE);
  if (pageCount > MAX_SERIES_PAGES) {
    throw new Error("Filtered snapshot series is too large to load safely.");
  }

  const items = [...first.items];
  for (let page = 2; page <= pageCount; page += 1) {
    const response = await apiRequest<SnapshotCollection>(collectionPath(filters, page), { signal });
    items.push(...response.items);
  }
  if (items.length < first.total) {
    throw new Error("Snapshot series ended before all filtered rows were returned.");
  }
  return { items: items.slice(0, first.total), page: 1, page_size: SERIES_PAGE_SIZE, total: first.total };
}

export function useSnapshots(filters: SnapshotFilters) {
  return useQuery({
    queryKey: [...snapshotsQueryRoot, filters],
    queryFn: ({ signal }) => fetchSnapshotSeries(filters, signal),
  });
}

export function useSnapshotDetail(snapshotId: string | null) {
  return useQuery({
    queryKey: [...snapshotsQueryRoot, "detail", snapshotId],
    queryFn: () => apiRequest<SnapshotDetail>(`/api/snapshots/${snapshotId}`),
    enabled: Boolean(snapshotId),
  });
}

export function useCreateManualSnapshot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { note: string | null }) => apiRequest<SnapshotDetail>("/api/snapshots/manual", {
      method: "POST",
      body: jsonBody(payload),
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: snapshotsQueryRoot });
    },
  });
}
