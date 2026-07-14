import { Check } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { useSetMarketDataOverride } from "./api";
import styles from "./MarketData.module.css";

type Props = {
  marketKey: string;
  symbol: string;
  open: boolean;
  onClose: () => void;
};

export function OverrideDrawer({ marketKey, symbol, open, onClose }: Props) {
  const save = useSetMarketDataOverride();
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const isFx = marketKey.startsWith("fx:");
  const canSave = /^\d+(?:\.\d+)?$/.test(value) && Boolean(note.trim());

  async function submit() {
    if (!canSave) return;
    setError(null);
    try {
      await save.mutateAsync({
        key: marketKey,
        payload: {
          value,
          note: note.trim(),
          expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        },
      });
      onClose();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "手动覆盖保存失败。");
    }
  }

  return (
    <WorkDrawer
      open={open}
      title={`手动覆盖 · ${symbol}`}
      onClose={onClose}
      footer={<div className={styles.drawerFooter}><button type="button" className={styles.secondary} onClick={onClose}>取消</button><button type="button" className={styles.primary} disabled={!canSave || save.isPending} onClick={() => void submit()}><Check size={16} aria-hidden="true" />{isFx ? "启用手动汇率" : "启用手动价格"}</button></div>}
    >
      <div className={styles.drawerContent}>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        <p className={styles.overrideIntro}>手动值优先于自动行情，直到取消或到达失效时间。备注用于之后核对来源。</p>
        <FormField label="手动值" required><input aria-label="手动值" inputMode="decimal" value={value} onChange={(event) => setValue(event.target.value)} /></FormField>
        <FormField label="备注" required hint="例如：券商结算汇率、基金公司收盘净值"><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
        <FormField label="失效时间" hint="留空表示持续有效"><input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></FormField>
      </div>
    </WorkDrawer>
  );
}
