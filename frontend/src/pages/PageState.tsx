import { RefreshCw } from "lucide-react";

import styles from "./PageState.module.css";

type LoadingProps = {
  kind: "assets" | "holdings";
};

export function PageLoading({ kind }: LoadingProps) {
  const assetRows = kind === "assets" ? 5 : 4;
  const label = kind === "assets" ? "正在载入资产配置" : "正在载入持仓与成本";
  return (
    <section className={styles.loading} role="status" aria-label={label}>
      <div className={styles.loadingHeader}><span /><span /></div>
      <div className={styles.loadingTable}>
        {Array.from({ length: assetRows }, (_, index) => (
          <div
            className={styles.loadingRow}
            data-testid={kind === "assets" ? "asset-skeleton-row" : "holding-skeleton-row"}
            key={index}
          >
            <span /><span /><span /><span />
          </div>
        ))}
      </div>
      <span className={styles.srOnly}>{label}</span>
    </section>
  );
}

type ErrorProps = {
  title: string;
  message: string;
  retryLabel: string;
  onRetry: () => void;
};

export function PageError({ title, message, retryLabel, onRetry }: ErrorProps) {
  return (
    <section className={`${styles.state} ${styles.error}`} role="alert">
      <strong>{title}</strong>
      <p>{message}</p>
      <p>检查本机 API 服务后重试；已输入的数据不会在此页面丢失。</p>
      <button type="button" onClick={onRetry}>
        <RefreshCw size={16} aria-hidden="true" />
        {retryLabel}
      </button>
    </section>
  );
}
