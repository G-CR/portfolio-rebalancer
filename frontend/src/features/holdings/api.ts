import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiRequest, jsonBody } from "../../api/client";
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

export const holdingsQueryRoot = ["holdings"] as const;
export const holdingsQueryKey = (includeArchived: boolean) =>
  ["holdings", { includeArchived }] as const;
export const costAdjustmentsQueryKey = (holdingId: string) =>
  ["cost-adjustments", holdingId] as const;

export function isStaleCostPreview(
  error: unknown,
): error is ApiError & { code: "STALE_COST_PREVIEW" } {
  return error instanceof ApiError && error.code === "STALE_COST_PREVIEW";
}

export function useHoldings(includeArchived = false) {
  return useQuery({
    queryKey: holdingsQueryKey(includeArchived),
    queryFn: ({ queryKey }) => apiRequest<Holding[]>(
      queryKey[1].includeArchived
        ? "/api/holdings?include_archived=true"
        : "/api/holdings",
    ),
    placeholderData: (previousData) => previousData,
  });
}

export function useCreateHolding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: HoldingCreate) => apiRequest<Holding>("/api/holdings", {
      method: "POST",
      body: jsonBody(payload),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot }),
  });
}

export function useArchiveHolding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (holdingId: string) => apiRequest<Holding>(`/api/holdings/${holdingId}/archive`, {
      method: "POST",
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot }),
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
      void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot });
      void queryClient.invalidateQueries({ queryKey: costAdjustmentsQueryKey(holdingId) });
    },
    onError: (error) => {
      if (!isStaleCostPreview(error)) return;
      void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot });
      void queryClient.invalidateQueries({ queryKey: costAdjustmentsQueryKey(holdingId) });
    },
  });
}

export type { PurchasePayload, SellPayload, CorrectionPayload, RestorePayload };
