import { ApiError } from "../api/client";
import { AssetClassEditor } from "../features/assetClasses/AssetClassEditor";
import { useAssetClasses, useSaveAssetClasses } from "../features/assetClasses/api";
import pageState from "./PageState.module.css";

export function AssetClassesPage() {
  const classes = useAssetClasses();
  const save = useSaveAssetClasses();

  if (classes.isPending) return <div className={pageState.state}>正在载入资产配置...</div>;
  if (classes.isError) {
    const message = classes.error instanceof ApiError ? classes.error.message : "资产配置载入失败。";
    return <div className={`${pageState.state} ${pageState.error}`} role="alert">{message}</div>;
  }

  return (
    <AssetClassEditor
      initialItems={classes.data}
      saving={save.isPending}
      onSave={(items) => save.mutateAsync(items)}
    />
  );
}
