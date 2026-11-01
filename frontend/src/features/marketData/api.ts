import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import { portfolioAnalyticsKey } from "../../api/queryKeys";
import { holdingsQueryRoot } from "../holdings/api";
import { snapshotsQueryRoot } from "../snapshots/api";
import type { MarketDataCollection, MarketDataStatus } from "../../api/types";

export const marketDataQueryKey = ["market-data"] as const;
export const marketDataRefreshVersionKey = ["market-data-refresh-version"] as const;

export function useMarketData() {
  return useQuery({
    queryKey: marketDataQueryKey,
    queryFn: () => apiRequest<MarketDataCollection>("/api/market-data"),
  });
}

export function useMarketDataRefreshVersion() {
  return useQuery({
    queryKey: marketDataRefreshVersionKey,
    queryFn: async () => 0,
    initialData: 0,
    staleTime: Infinity,
  });
}

export function useRefreshMarketData() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<MarketDataCollection>("/api/market-data/refresh", { method: "POST" }),
    onSuccess: (data) => {
      queryClient.setQueryData(marketDataQueryKey, data);
      queryClient.setQueryData<number>(marketDataRefreshVersionKey, (current = 0) => current + 1);
      const hasIncompleteRequiredData = data.items.some(
        (item) => item.effective_value === null,
      );
      if (!hasIncompleteRequiredData) {
        void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
      }
      void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot });
      void queryClient.invalidateQueries({ queryKey: snapshotsQueryRoot });
    },
  });
}

export function useSetMarketDataOverride() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: { value: string; note: string; expires_at: string | null } }) => apiRequest<MarketDataStatus>(`/api/market-data/${key}/override`, {
      method: "POST",
      body: jsonBody(payload),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: marketDataQueryKey }),
  });
}

export function useDeleteMarketDataOverride() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => apiRequest<void>(`/api/market-data/${key}/override`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: marketDataQueryKey }),
  });
}
