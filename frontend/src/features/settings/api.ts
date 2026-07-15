import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type { GeneralSettings, ProviderName, ProviderSetting, RebalanceDefaults } from "../../api/types";

export const providerSettingsQueryKey = ["settings", "providers"] as const;
export const generalSettingsQueryKey = ["settings", "general"] as const;
export const rebalanceDefaultsQueryKey = ["settings", "rebalance-defaults"] as const;

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
    mutationFn: (payload: Omit<GeneralSettings, "updated_at">) => apiRequest<GeneralSettings>("/api/settings/general", {
      method: "PUT",
      body: jsonBody(payload),
    }),
    onSuccess: (saved) => queryClient.setQueryData(generalSettingsQueryKey, saved),
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
    mutationFn: (payload: Omit<RebalanceDefaults, "updated_at">) => apiRequest<RebalanceDefaults>("/api/settings/rebalance-defaults", {
      method: "PUT",
      body: jsonBody(payload),
    }),
    onSuccess: (saved) => {
      queryClient.setQueryData(rebalanceDefaultsQueryKey, saved);
      queryClient.setQueryData<GeneralSettings>(generalSettingsQueryKey, (current) => current ? {
        ...current,
        default_tolerance: saved.tolerance,
        minimum_trade_amount_cny: saved.minimum_trade_cny,
        allow_sell: saved.allow_sell,
        allow_fx: saved.allow_fx,
        updated_at: saved.updated_at,
      } : current);
    },
  });
}
