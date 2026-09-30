import { portfolioAnalyticsKey } from "../../api/queryKeys";
import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type {
  EmailDigestTriggerResult,
  EmailSettings,
  EmailTestResult,
  GeneralSettings,
  GeneralSettingsUpdate,
  ProviderName,
  ProviderSetting,
  RebalanceDefaults,
  RebalanceDefaultsUpdate,
} from "../../api/types";

export const providerSettingsQueryKey = ["settings", "providers"] as const;
export const generalSettingsQueryKey = ["settings", "general"] as const;
export const rebalanceDefaultsQueryKey = ["settings", "rebalance-defaults"] as const;
export const emailSettingsQueryKey = ["settings", "email"] as const;
const emailDigestMutationKey = ["email", "digest"] as const;

export function useProviderSettings() {
  return useQuery({
    queryKey: providerSettingsQueryKey,
    queryFn: () => apiRequest<ProviderSetting[]>("/api/settings/providers"),
  });
}

export function useSaveProviderSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, apiKey, priority, enabled }: { provider: ProviderName; apiKey: string | null; priority: number; enabled: boolean }) => apiRequest<ProviderSetting>(`/api/settings/providers/${provider}`, {
      method: "PUT",
      body: jsonBody({ api_key: apiKey || null, priority, enabled }),
    }),
    onSuccess: (saved) => {
      queryClient.setQueryData<ProviderSetting[]>(providerSettingsQueryKey, (current) => {
        const items = current?.map((item) => item.provider === saved.provider ? saved : item) ?? [saved];
        const moved = items.filter((item) => item.provider !== saved.provider);
        moved.splice(Math.max(0, saved.priority - 1), 0, saved);
        return moved.map((item, index) => ({ ...item, priority: index + 1 }));
      });
      queryClient.setQueryData<GeneralSettings>(generalSettingsQueryKey, (current) => {
        if (!current) return current;
        const priority = current.provider_priority.filter((provider) => provider !== saved.provider);
        priority.splice(Math.max(0, saved.priority - 1), 0, saved.provider);
        return { ...current, provider_priority: priority };
      });
    },
  });
}

export function useTestProviderSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: ProviderName) => apiRequest<ProviderSetting>(`/api/settings/providers/${provider}/test`, { method: "POST" }),
    onSuccess: (saved) => queryClient.setQueryData<ProviderSetting[]>(providerSettingsQueryKey, (current) => current?.map((item) => item.provider === saved.provider ? saved : item) ?? [saved]),
  });
}

export function useGeneralSettings() {
  return useQuery({
    queryKey: generalSettingsQueryKey,
    queryFn: () => apiRequest<GeneralSettings>("/api/settings/general"),
  });
}

export function useSaveGeneralSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GeneralSettingsUpdate) => {
      const request: GeneralSettingsUpdate = {
        refresh_time: payload.refresh_time,
        provider_priority: payload.provider_priority,
        default_tolerance: payload.default_tolerance,
        allow_sell: payload.allow_sell,
        allow_fx: payload.allow_fx,
      };
      return apiRequest<GeneralSettings>("/api/settings/general", { method: "PUT", body: jsonBody(request) });
    },
    onSuccess: (saved) => { queryClient.setQueryData(generalSettingsQueryKey, saved); void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey }); },
  });
}

export function useRebalanceDefaults() {
  return useQuery({
    queryKey: rebalanceDefaultsQueryKey,
    queryFn: () => apiRequest<RebalanceDefaults>("/api/settings/rebalance-defaults"),
  });
}

export function useSaveRebalanceDefaults() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RebalanceDefaultsUpdate) => {
      const request: RebalanceDefaultsUpdate = {
        available_cny: payload.available_cny,
        available_usd: payload.available_usd,
        valuation_basis: payload.valuation_basis,
        tolerance: payload.tolerance,
        allow_sell: payload.allow_sell,
        allow_fx: payload.allow_fx,
      };
      return apiRequest<RebalanceDefaults>("/api/settings/rebalance-defaults", { method: "PUT", body: jsonBody(request) });
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(rebalanceDefaultsQueryKey, saved);
      void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
      queryClient.setQueryData<GeneralSettings>(generalSettingsQueryKey, (current) => current ? {
        ...current,
        default_tolerance: saved.tolerance,
        allow_sell: saved.allow_sell,
        allow_fx: saved.allow_fx,
        updated_at: saved.updated_at,
      } : current);
    },
  });
}

export function useEmailSettings() {
  return useQuery({
    queryKey: emailSettingsQueryKey,
    queryFn: () => apiRequest<EmailSettings>("/api/settings/email"),
  });
}

export function useSaveEmailSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Omit<EmailSettings, "password_masked" | "updated_at"> & { password: string | null }) =>
      apiRequest<EmailSettings>("/api/settings/email", { method: "PUT", body: jsonBody(payload) }),
    onSuccess: (saved) => queryClient.setQueryData(emailSettingsQueryKey, saved),
  });
}

export function useTestEmailSettings() {
  return useMutation({
    mutationFn: () => apiRequest<EmailTestResult>("/api/settings/email/test", { method: "POST" }),
  });
}

export function useTriggerEmailDigest() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationKey: emailDigestMutationKey,
    gcTime: 60 * 60 * 1000,
    mutationFn: () => apiRequest<EmailDigestTriggerResult>("/api/email/digest", { method: "POST" }),
  });
  const states = useMutationState({
    filters: { mutationKey: emailDigestMutationKey, exact: true },
    select: (item) => ({
      status: item.state.status,
      data: item.state.data as EmailDigestTriggerResult | undefined,
      error: item.state.error,
    }),
  });
  const latest = states.at(-1);

  return {
    isPending: latest?.status === "pending",
    isError: latest?.status === "error",
    data: latest?.data,
    error: latest?.error,
    mutate: () => {
      const pending = queryClient.getMutationCache().find({
        mutationKey: emailDigestMutationKey, exact: true, status: "pending",
      });
      if (!pending) mutation.mutate();
    },
  };
}
