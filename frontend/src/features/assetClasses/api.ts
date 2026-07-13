import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, jsonBody } from "../../api/client";
import type { AssetClass, AssetClassUpdate } from "../../api/types";

export const assetClassesQueryKey = ["asset-classes"] as const;

export function useAssetClasses() {
  return useQuery({
    queryKey: assetClassesQueryKey,
    queryFn: () => apiRequest<AssetClass[]>("/api/asset-classes"),
  });
}

export function useSaveAssetClasses() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AssetClassUpdate[]) => apiRequest<AssetClass[]>("/api/asset-classes", {
      method: "PUT",
      body: jsonBody(payload),
    }),
    onSuccess: (items) => {
      queryClient.setQueryData(assetClassesQueryKey, items);
      void queryClient.invalidateQueries({ queryKey: assetClassesQueryKey });
    },
  });
}
