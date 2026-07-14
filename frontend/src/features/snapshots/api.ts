import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type { SnapshotCollection, SnapshotDetail, SnapshotType } from "../../api/types";

export const snapshotsQueryRoot = ["snapshots"] as const;

export type SnapshotFilters = {
  fromDate?: string;
  snapshotType?: SnapshotType;
  assetClass?: string;
  page?: number;
  pageSize?: number;
};

function collectionPath(filters: SnapshotFilters) {
  const params = new URLSearchParams();
  if (filters.fromDate) params.set("from_date", filters.fromDate);
  if (filters.snapshotType) params.set("snapshot_type", filters.snapshotType);
  if (filters.assetClass) params.set("asset_class", filters.assetClass);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 25));
  return `/api/snapshots?${params.toString()}`;
}

export function useSnapshots(filters: SnapshotFilters) {
  return useQuery({
    queryKey: [...snapshotsQueryRoot, filters],
    queryFn: () => apiRequest<SnapshotCollection>(collectionPath(filters)),
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
