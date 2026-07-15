import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import { portfolioAnalyticsKey } from "../../api/queryKeys";
import type { MarketDataCollection, MarketDataStatus } from "../../api/types";

export const marketDataQueryKey = ["market-data"] as const;

export function useMarketData() {
  return useQuery({
    queryKey: marketDataQueryKey,
    queryFn: () => apiRequest<MarketDataCollection>("/api/market-data"),
  });
}

export function useRefreshMarketData() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<MarketDataCollection>("/api/market-data/refresh", { method: "POST" }),
    onSuccess: (data) => {
      queryClient.setQueryData(marketDataQueryKey, data);
      void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
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
