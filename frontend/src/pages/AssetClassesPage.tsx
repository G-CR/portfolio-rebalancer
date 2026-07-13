import { ApiError } from "../api/client";
import { AssetClassEditor } from "../features/assetClasses/AssetClassEditor";
import { useAssetClasses, useSaveAssetClasses } from "../features/assetClasses/api";
import { useHoldings } from "../features/holdings/api";
import { PageError, PageLoading } from "./PageState";

export function AssetClassesPage() {
  const classes = useAssetClasses();
  const holdings = useHoldings(true);
  const save = useSaveAssetClasses();

  if (classes.isPending || holdings.isPending) return <PageLoading kind="assets" />;
  if (classes.isError || holdings.isError) {
    const error = classes.error ?? holdings.error;
    const message = error instanceof ApiError ? error.message : "资产配置载入失败。";
    return (
      <PageError
        title="资产配置无法载入"
        message={message}
        retryLabel="重试载入资产配置"
        onRetry={() => { void classes.refetch(); void holdings.refetch(); }}
      />
    );
  }

  const holdingImpact = holdings.data.reduce<Record<string, number>>((counts, holding) => {
    counts[holding.asset_class_id] = (counts[holding.asset_class_id] ?? 0) + 1;
    return counts;
  }, {});

  return (
    <AssetClassEditor
      initialItems={classes.data}
      saving={save.isPending}
      holdingImpact={holdingImpact}
      onSave={(items) => save.mutateAsync(items)}
    />
  );
}
