import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type {
  ConfirmAdjustmentRequest,
  CorrectionPayload,
  CostAdjustmentCollection,
  CostAdjustmentPreview,
  Holding,
  HoldingCreate,
  PurchasePayload,
  RestorePayload,
  SellPayload,
} from "../../api/types";

export const holdingsQueryKey = ["holdings"] as const;
export const costAdjustmentsQueryKey = (holdingId: string) =>
  ["cost-adjustments", holdingId] as const;

export function useHoldings(includeArchived = false) {
  return useQuery({
    queryKey: holdingsQueryKey,
    queryFn: () => apiRequest<Holding[]>(
      includeArchived ? "/api/holdings?include_archived=true" : "/api/holdings",
    ),
  });
}

export function useCreateHolding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: HoldingCreate) => apiRequest<Holding>("/api/holdings", {
      method: "POST",
      body: jsonBody(payload),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: holdingsQueryKey }),
  });
}

export function useArchiveHolding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (holdingId: string) => apiRequest<Holding>(`/api/holdings/${holdingId}/archive`, {
      method: "POST",
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: holdingsQueryKey }),
  });
}

export function useCostAdjustments(holdingId: string, enabled = true) {
  return useQuery({
    queryKey: costAdjustmentsQueryKey(holdingId),
    queryFn: () => apiRequest<CostAdjustmentCollection>(`/api/cost-adjustments/${holdingId}`),
    enabled: enabled && Boolean(holdingId),
  });
}

function usePreview<TPayload>(holdingId: string, action: string) {
  return useMutation({
    mutationFn: (payload: TPayload) => apiRequest<CostAdjustmentPreview>(
      `/api/cost-adjustments/${holdingId}/${action}`,
      { method: "POST", body: jsonBody(payload) },
    ),
  });
}

export function usePurchasePreview(holdingId: string) {
  return usePreview<PurchasePayload>(holdingId, "preview-purchase");
}

export function useSellPreview(holdingId: string) {
  return usePreview<SellPayload>(holdingId, "preview-sell");
}

export function useCorrectionPreview(holdingId: string) {
  return usePreview<CorrectionPayload>(holdingId, "preview-correction");
}

export function useRestorePreview(holdingId: string) {
  return useMutation({
    mutationFn: ({ adjustmentId, note }: { adjustmentId: string; note: string | null }) =>
      apiRequest<CostAdjustmentPreview>(
        `/api/cost-adjustments/${holdingId}/preview-restore/${adjustmentId}`,
        { method: "POST", body: jsonBody({ note }) },
      ),
  });
}

export function useConfirmAdjustment<TPayload>(holdingId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ConfirmAdjustmentRequest<TPayload>) =>
      apiRequest<CostAdjustmentPreview>(`/api/cost-adjustments/${holdingId}/confirm`, {
        method: "POST",
        body: jsonBody(request),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: holdingsQueryKey });
      void queryClient.invalidateQueries({ queryKey: costAdjustmentsQueryKey(holdingId) });
    },
  });
}

export type { PurchasePayload, SellPayload, CorrectionPayload, RestorePayload };
