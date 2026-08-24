import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiRequest, apiUpload, jsonBody } from "../../api/client";
import type { BackupOperation, BackupPreview, SafetyBackup } from "../../api/types";

export const backupKeys = {
  root: ["backups"] as const,
  safety: ["backups", "safety"] as const,
  operation: (id: string) => ["backups", "operations", id] as const,
};

export function useStartBackupExport() {
  return useMutation({ mutationFn: () => apiRequest<BackupOperation>("/api/backups/export", { method: "POST" }) });
}

export function useBackupUpload() {
  return useMutation({ mutationFn: (file: File) => apiUpload<BackupPreview>("/api/backups/upload", file) });
}

export function useSafetyPreview() {
  return useMutation({ mutationFn: (id: string) => apiRequest<BackupPreview>(`/api/backups/safety/${id}/preview`, { method: "POST" }) });
}

export function useStartBackupRestore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ token, confirmation }: { token: string; confirmation: string }) => apiRequest<BackupOperation>("/api/backups/restore", {
      method: "POST",
      body: jsonBody({ restore_token: token, confirmation }),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: backupKeys.safety }),
  });
}

export function useBackupOperation(id: string | null) {
  return useQuery({
    queryKey: id ? backupKeys.operation(id) : [...backupKeys.root, "operations", "idle"],
    queryFn: () => apiRequest<BackupOperation>(`/api/backups/operations/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 1000 : false;
    },
    retry: false,
  });
}

export function useSafetyBackups(enabled: boolean) {
  return useQuery({
    queryKey: backupKeys.safety,
    queryFn: () => apiRequest<SafetyBackup[]>("/api/backups/safety"),
    enabled,
    retry: false,
  });
}

export function useDeleteSafetyBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/api/backups/safety/${id}?confirm=true`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: backupKeys.safety }),
  });
}

export async function saveBackupDownload(path: string) {
  const { blob, filename } = await apiDownload(path);
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.style.display = "none";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
