import { useMutation } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type { RebalancePlan, RebalancePreview, RebalancePreviewPayload } from "../../api/types";

export function useRebalancePreview() {
  return useMutation({
    mutationFn: (payload: RebalancePreviewPayload) => apiRequest<RebalancePreview>("/api/rebalance/preview", {
      method: "POST",
      body: jsonBody(payload),
    }),
  });
}

export function useCreateRebalancePlan() {
  return useMutation({
    mutationFn: (payload: RebalancePreviewPayload & { idempotency_key: string }) => apiRequest<RebalancePlan>("/api/rebalance/plans", {
      method: "POST",
      body: jsonBody(payload),
    }),
  });
}

type Transition = { planId: string; idempotencyKey: string };

function transition(path: "start" | "cancel" | "complete") {
  return ({ planId, idempotencyKey }: Transition) => apiRequest<RebalancePlan>(`/api/rebalance/plans/${planId}/${path}`, {
    method: "POST",
    body: jsonBody({ idempotency_key: idempotencyKey }),
  });
}

export function useStartRebalancePlan() {
  return useMutation({ mutationFn: transition("start") });
}

export function useCancelRebalancePlan() {
  return useMutation({ mutationFn: transition("cancel") });
}

export function useCompleteRebalancePlan() {
  return useMutation({ mutationFn: transition("complete") });
}
