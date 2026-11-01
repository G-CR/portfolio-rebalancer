import { useMutation, useQuery } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type { RebalancePlan, RebalancePreviewJob, RebalancePreviewPayload } from "../../api/types";

export const rebalancePlansQueryKey = ["rebalance", "plans"] as const;
export const latestRebalancePreviewJobQueryKey = ["rebalance", "preview-job", "latest"] as const;

export function useRebalancePlans() {
  return useQuery({
    queryKey: rebalancePlansQueryKey,
    queryFn: () => apiRequest<{ items: RebalancePlan[] }>("/api/rebalance/plans"),
  });
}

export function useRebalancePreview() {
  return useMutation({
    mutationFn: (payload: RebalancePreviewPayload) => apiRequest<RebalancePreviewJob>("/api/rebalance/preview-jobs", {
      method: "POST",
      body: jsonBody(payload),
    }),
  });
}

export function useLatestRebalancePreviewJob() {
  return useQuery({
    queryKey: latestRebalancePreviewJobQueryKey,
    queryFn: () => apiRequest<RebalancePreviewJob | null>("/api/rebalance/preview-jobs/latest"),
  });
}

export function useRebalancePreviewJob(jobId: string | null) {
  return useQuery({
    queryKey: ["rebalance", "preview-job", jobId],
    enabled: jobId !== null,
    queryFn: () => apiRequest<RebalancePreviewJob>(`/api/rebalance/preview-jobs/${jobId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 1000;
    },
  });
}

export function useCreateRebalancePlan() {
  return useMutation({
    mutationFn: (payload: RebalancePreviewPayload & { idempotency_key: string; expected_input_signature?: string }) => apiRequest<RebalancePlan>("/api/rebalance/plans", {
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
