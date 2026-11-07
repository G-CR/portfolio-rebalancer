import { useEffect, useRef, useState } from "react";
import type { CostAdjustmentPreview } from "../../api/types";

export function useAutomaticPreview<T>(payload: T, enabled: boolean, request: (payload: T) => Promise<CostAdjustmentPreview>) {
  const key = JSON.stringify(payload);
  const requestRef = useRef(request);
  requestRef.current = request;
  const [result, setResult] = useState<{ key: string; preview: CostAdjustmentPreview } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    if (!enabled || blocked) return;
    let active = true;
    setPending(true);
    setError(null);
    const timer = window.setTimeout(() => {
      void requestRef.current(JSON.parse(key) as T).then((preview) => {
        if (active) setResult({ key, preview });
      }).catch((cause) => {
        if (active) { setResult(null); setError(cause); }
      }).finally(() => { if (active) setPending(false); });
    }, 350);
    return () => { active = false; window.clearTimeout(timer); };
  }, [key, enabled, blocked]);

  return {
    preview: enabled && !blocked && result?.key === key ? result.preview : null,
    error,
    pending: enabled && !blocked && pending,
    invalidate: () => { setBlocked(true); setResult(null); },
    retry: () => setBlocked(false),
  };
}
