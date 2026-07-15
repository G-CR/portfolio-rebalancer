import { ChevronDown, Plus } from "lucide-react";
import { Fragment, useState } from "react";

import type { AssetClass, Holding, HoldingAnalytics, PortfolioIncompleteItem } from "../../api/types";
import { formatAmount, formatDecimal, formatSignedAmount, statusLabel } from "../analytics/format";
import { HoldingActionMenu, type HoldingCommand } from "./HoldingActionMenu";
import styles from "./HoldingsTable.module.css";

export type { HoldingCommand } from "./HoldingActionMenu";

type Props = {
  holdings: Holding[];
  assetClasses: AssetClass[];
  analyticsById: Map<string, HoldingAnalytics>;
  incompleteById: Map<string, PortfolioIncompleteItem[]>;
  showArchived: boolean;
  onCommand: (holding: Holding, command: HoldingCommand) => void;
};

function MarketValue({ value, status }: { value: string; status: string }) {
  return <div className={styles.marketValue}><span>{value}</span>{status === "valid" ? null : <small data-status={status}>{statusLabel(status)}</small>}</div>;
}

function DetailMarketValue({
  value,
  status,
  fallbackStatus,
}: {
  value?: string;
  status?: string;
  fallbackStatus: string;
}) {
  const effectiveStatus = status ?? (fallbackStatus === "数据缺失" ? "missing" : "unavailable");
  return (
    <span className={styles.detailMarketValue}>
      <b>{value ?? "--"}</b>
      <small data-status={effectiveStatus}>{status ? statusLabel(status) : fallbackStatus}</small>
    </span>
  );
}

export function HoldingsTable({ holdings, assetClasses, analyticsById, incompleteById, showArchived, onCommand }: Props) {
  const assetNames = new Map(assetClasses.map((item) => [item.id, item.name]));
  const visible = holdings.filter((holding) => showArchived ? !holding.is_active : holding.is_active);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  function toggleDetail(holdingId: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(holdingId)) next.delete(holdingId);
      else next.add(holdingId);
      return next;
    });
  }

  return (
    <div className={styles.tableWrap} role="region" aria-label="持仓与成本表格" tabIndex={0}>
      <table className={styles.table}>
        <colgroup>
          <col className={styles.symbolCol} />
          <col className={styles.accountCol} />
          <col className={styles.currencyCol} />
          <col className={styles.quantityCol} />
          <col className={styles.costPriceCol} />
          <col className={styles.costFxCol} />
          <col className={styles.currentPriceCol} />
          <col className={styles.currentFxCol} />
          <col className={styles.marketValueCol} />
          <col className={styles.pnlCol} />
          <col className={styles.actionsCol} />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">标的</th>
            <th scope="col">账户 / 类别</th>
            <th scope="col">币种</th>
            <th className={styles.numericHeader} scope="col">份额</th>
            <th className={styles.numericHeader} scope="col">成本价</th>
            <th className={styles.numericHeader} scope="col">成本汇率</th>
            <th className={`${styles.numericHeader} ${styles.marketColumn}`} scope="col">当前价</th>
            <th className={`${styles.numericHeader} ${styles.marketColumn}`} scope="col">当前汇率</th>
            <th className={styles.numericHeader} scope="col">市值</th>
            <th className={styles.numericHeader} scope="col">浮动盈亏</th>
            <th className={styles.desktopActionsColumn} scope="col"><span className={styles.srOnly}>操作</span></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((holding) => {
            const analytics = analyticsById.get(holding.id);
            const incomplete = incompleteById.get(holding.id) ?? [];
            const priceMissing = incomplete.some((item) => item.input === "price");
            const fxMissing = incomplete.some((item) => item.input === "fx");
            const anyMissing = priceMissing || fxMissing;
            const expanded = expandedIds.has(holding.id);
            const detailId = `holding-detail-${holding.id}`;
            const priceFallback = priceMissing ? "数据缺失" : holding.is_active ? "暂无数据" : "已归档";
            const fxFallback = fxMissing ? "数据缺失" : holding.is_active ? "暂无数据" : "已归档";
            return (
              <Fragment key={holding.id}>
                <tr data-archived={!holding.is_active || undefined} data-mobile-summary="true">
                  <td>
                    <div className={styles.symbol}>
                      <div className={styles.symbolHeading}>
                        <strong>{holding.symbol}</strong>
                        <button
                          className={styles.mobileDisclosure}
                          type="button"
                          title={expanded ? "收起持仓详情" : "查看持仓详情"}
                          aria-label={`${expanded ? "收起" : "查看"} ${holding.symbol} 持仓详情`}
                          aria-expanded={expanded}
                          aria-controls={detailId}
                          data-mobile-disclosure="true"
                          onClick={() => toggleDetail(holding.id)}
                        >
                          <ChevronDown size={15} aria-hidden="true" />
                        </button>
                      </div>
                      <span>{holding.name}</span>
                      {!holding.is_active ? <em>已归档</em> : null}
                    </div>
                  </td>
                  <td className={styles.secondaryColumn}><div className={styles.stack}><span>{holding.account_name}</span><small>{assetNames.get(holding.asset_class_id) ?? "未分类"}</small></div></td>
                  <td className={styles.secondaryColumn}><span className={styles.currency}>{holding.trade_currency}</span></td>
                  <td className={styles.numeric}>{holding.quantity}</td>
                  <td className={`${styles.numeric} ${styles.costColumn}`}>{holding.average_cost_price}</td>
                  <td className={`${styles.numeric} ${styles.costColumn}`}>{holding.cost_fx_to_cny}</td>
                  <td className={`${styles.numeric} ${styles.marketColumn}`}>{analytics ? <MarketValue value={formatDecimal(analytics.current_price)} status={analytics.price_status} /> : <span className={styles.pendingData}>{priceMissing ? "数据缺失" : "--"}</span>}</td>
                  <td className={`${styles.numeric} ${styles.marketColumn}`}>{analytics ? <MarketValue value={formatDecimal(analytics.current_fx_to_cny)} status={analytics.fx_status} /> : <span className={styles.pendingData}>{fxMissing ? "数据缺失" : "--"}</span>}</td>
                  <td className={`${styles.numeric} ${styles.priorityMarket}`}>{analytics ? <><span className={styles.desktopAmount}>{formatAmount(analytics.market_value_cny, 2)}</span><span className={styles.mobileAmount}>{formatAmount(analytics.market_value_cny, 0)}</span></> : <span className={styles.pendingData}>{anyMissing ? "数据缺失" : "--"}</span>}</td>
                  <td className={`${styles.numeric} ${styles.priorityMarket}`}>{analytics ? <><span className={styles.desktopAmount}>{formatSignedAmount(analytics.unrealized_pnl)}</span><span className={styles.mobileAmount}>{formatSignedAmount(analytics.unrealized_pnl, 0)}</span></> : <span className={styles.pendingData}>{anyMissing ? "数据缺失" : "--"}</span>}</td>
                  <td className={styles.desktopActionsColumn}>
                    {holding.is_active ? (
                      <div className={styles.actions}>
                        <button className={`${styles.iconButton} ${styles.addButton}`} type="button" title="追加买入" aria-label={`追加买入 ${holding.symbol}`} onClick={() => onCommand(holding, "purchase")}>
                          <Plus size={17} aria-hidden="true" />
                        </button>
                        <HoldingActionMenu holding={holding} onCommand={onCommand} />
                      </div>
                    ) : <span className={styles.archivedActions}>已归档，无可用操作</span>}
                  </td>
                </tr>
                <tr
                  id={detailId}
                  className={styles.mobileDetailRow}
                  data-mobile-detail="true"
                  data-archived={!holding.is_active || undefined}
                  hidden={!expanded}
                >
                  <td className={styles.mobileDetailCell} colSpan={11}>
                    {expanded ? (
                      <section className={styles.detailSurface} aria-label={`${holding.symbol} 持仓详情`}>
                        <dl className={styles.detailGrid}>
                          <div><dt>账户</dt><dd>{holding.account_name}</dd></div>
                          <div><dt>资产类别</dt><dd>{assetNames.get(holding.asset_class_id) ?? "未分类"}</dd></div>
                          <div><dt>币种 / 市场</dt><dd>{holding.trade_currency} / {holding.market}</dd></div>
                          <div><dt>平均成本价</dt><dd>{holding.average_cost_price}</dd></div>
                          <div><dt>成本汇率</dt><dd>{holding.cost_fx_to_cny}</dd></div>
                          <div><dt>当前价</dt><dd><DetailMarketValue value={analytics ? formatDecimal(analytics.current_price) : undefined} status={analytics?.price_status} fallbackStatus={priceFallback} /></dd></div>
                          <div><dt>当前汇率</dt><dd><DetailMarketValue value={analytics ? formatDecimal(analytics.current_fx_to_cny) : undefined} status={analytics?.fx_status} fallbackStatus={fxFallback} /></dd></div>
                          <div><dt>调整偏好</dt><dd>{holding.is_rebalance_preferred ? "默认调整标的" : "非默认调整标的"}</dd></div>
                          <div><dt>持仓状态</dt><dd>{holding.is_active ? "启用持仓" : "已归档"}</dd></div>
                        </dl>
                        <div className={styles.detailActions} aria-label="持仓操作">
                          {holding.is_active ? (
                            <>
                              <button className={`${styles.iconButton} ${styles.addButton}`} type="button" title="追加买入" aria-label={`追加买入 ${holding.symbol}`} onClick={() => onCommand(holding, "purchase")}>
                                <Plus size={17} aria-hidden="true" />
                              </button>
                              <HoldingActionMenu holding={holding} onCommand={onCommand} />
                            </>
                          ) : <span className={styles.archivedActions}>已归档，无可用操作</span>}
                        </div>
                      </section>
                    ) : null}
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {visible.length === 0 ? <div className={styles.empty}>没有符合当前筛选条件的持仓。</div> : null}
    </div>
  );
}
