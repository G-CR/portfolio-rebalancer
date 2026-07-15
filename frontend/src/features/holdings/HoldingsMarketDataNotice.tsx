import { Pencil, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { MarketDataStatus, PortfolioIncompleteItem } from "../../api/types";
import { useRefreshMarketData } from "../marketData/api";
import styles from "./HoldingsMarketDataNotice.module.css";

const providerLabels: Record<string, string> = {
  akshare: "AKShare",
  yahoo: "Yahoo",
  tushare: "Tushare",
  alpha_vantage: "Alpha Vantage",
};

const categoryLabels: Record<string, string> = {
  provider_not_configured: "未配置",
  provider_payload_invalid: "返回数据无效",
  provider_request_failed: "请求失败",
  provider_internal_error: "运行失败",
};

function symbolsFor(items: PortfolioIncompleteItem[]) {
  return [...new Set(items.map((item) => item.symbol))].join("、");
}

function failedStatusFor(
  items: PortfolioIncompleteItem[],
  refreshedItems: MarketDataStatus[] | undefined,
) {
  if (!refreshedItems) return undefined;
  const keys = new Set(items.map((item) => item.key));
  return refreshedItems.find(
    (item) => keys.has(item.key) && item.effective_value === null,
  );
}

export function formatMarketDataFailure(summary: string | null | undefined) {
  if (!summary) return "自动获取失败";
  const labels = summary.split(";").map((attempt) => {
    const [rawProvider, rawCategory] = attempt.trim().split(":", 2);
    const provider = providerLabels[rawProvider];
    const category = categoryLabels[rawCategory?.trim()];
    return provider && category ? `${provider} ${category}` : null;
  });
  if (labels.some((label) => label === null)) return "自动获取失败";
  return labels.join("；");
}

export function HoldingsMarketDataNotice({ items }: { items: PortfolioIncompleteItem[] }) {
  const navigate = useNavigate();
  const refresh = useRefreshMarketData();
  const automaticStarted = useRef(false);
  const [attempted, setAttempted] = useState(false);
  const symbols = symbolsFor(items);

  useEffect(() => {
    if (automaticStarted.current) return;
    automaticStarted.current = true;
    setAttempted(true);
    refresh.mutate();
  }, [refresh]);

  const failedStatus = failedStatusFor(items, refresh.data?.items);
  const refreshing = !attempted || refresh.isPending || (
    refresh.isSuccess && !failedStatus
  );

  if (refreshing) {
    return (
      <div className={`${styles.notice} ${styles.refreshing}`} role="status">
        <div className={styles.message}>
          <RefreshCw size={15} aria-hidden="true" />
          <span>正在获取 {symbols} 行情…</span>
        </div>
      </div>
    );
  }

  const reason = refresh.isError
    ? "自动获取请求失败"
    : formatMarketDataFailure(failedStatus?.error_summary);
  const firstItem = items[0];

  return (
    <div className={`${styles.notice} ${styles.failed}`} role="alert">
      <div className={styles.message}>
        <span>{symbols} 行情获取失败。{reason}。</span>
      </div>
      <div className={styles.actions}>
        <button type="button" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          <RefreshCw size={14} aria-hidden="true" />立即重试
        </button>
        <button type="button" onClick={() => navigate(`/data-sources?override=${encodeURIComponent(firstItem.key)}`)}>
          <Pencil size={14} aria-hidden="true" />手动录入
        </button>
      </div>
    </div>
  );
}
