import { ReferenceArea, ReferenceDot, Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { SnapshotSummary } from "../../api/types";
import type { LedgerEntry } from "../ledger/api";
import { normalizeDecimalSeries } from "../analytics/chartScale";
import { formatAmount, formatPercent, formatSignedAmount } from "../analytics/format";
import { formatSnapshotDate } from "./dateTime";
import styles from "./Snapshots.module.css";

export type SnapshotMetric =
  | "market"
  | "cost"
  | "pnl"
  | "actual_weight"
  | "fx_neutral_weight"
  | "price_effect"
  | "fx_effect";

const metricConfig: Record<SnapshotMetric, { key: keyof SnapshotSummary; label: string; percent?: boolean; signed?: boolean }> = {
  market: { key: "total_market_value_cny", label: "核心池市值" },
  cost: { key: "total_cost_value_cny", label: "人民币成本" },
  pnl: { key: "total_unrealized_pnl_cny", label: "浮动盈亏", signed: true },
  actual_weight: { key: "actual_weight", label: "实际占比", percent: true },
  fx_neutral_weight: { key: "fx_neutral_weight", label: "剔汇率占比", percent: true },
  price_effect: { key: "total_price_effect_cny", label: "价格影响", signed: true },
  fx_effect: { key: "total_fx_effect_cny", label: "汇率影响", signed: true },
};

function metricValue(snapshot: SnapshotSummary, metric: SnapshotMetric) {
  const value = snapshot[metricConfig[metric].key];
  return typeof value === "string" ? value : "0";
}

function eventLabel(type: SnapshotSummary["snapshot_type"]) {
  if (type === "rebalance_before") return "再平衡前";
  if (type === "rebalance_after") return "再平衡后";
  return null;
}

export function SnapshotChart({ items, metric, events = [] }: { items: SnapshotSummary[]; metric: SnapshotMetric; events?: LedgerEntry[] }) {
  const ordered = [...items].sort((a, b) => a.captured_at.localeCompare(b.captured_at));
  const normalized = normalizeDecimalSeries(ordered.map((item) => metricValue(item, metric)));
  const chartData = ordered.map((item, index) => ({
    ...item,
    chartValue: normalized[index].scaled,
    originalValue: normalized[index].original,
    label: formatSnapshotDate(item.local_date),
  }));
  const pairs: { before: typeof chartData[number]; after: typeof chartData[number] }[] = [];
  let pendingBefore: typeof chartData[number] | null = null;
  for (const item of chartData) {
    if (item.snapshot_type === "rebalance_before") pendingBefore = item;
    if (item.snapshot_type === "rebalance_after" && pendingBefore) {
      pairs.push({ before: pendingBefore, after: item });
      pendingBefore = null;
    }
  }
  const config = metricConfig[metric];
  const reversed = new Set(events.map(event => event.reverses_id).filter(Boolean));
  const eventNames = {purchase: '买入', sale: '卖出', dividend: '现金分红', split: '份额折算'};
  const dates = chartData.map(item => item.local_date).sort();
  const visibleEvents = events.filter(event => event.kind in eventNames && !reversed.has(event.id) && event.occurred_on >= dates[0] && event.occurred_on <= dates[dates.length - 1]);
  const markers = chartData.filter((item, index) => chartData.findIndex(other => other.local_date === item.local_date) === index)
    .map(item => ({item, events: visibleEvents.filter(event => event.occurred_on === item.local_date)})).filter(marker => marker.events.length);
  const format = (value: string) => config.percent
    ? formatPercent(value, 2)
    : config.signed ? formatSignedAmount(value, 2) : formatAmount(value, 2);

  return (
    <section className={styles.chartSection} aria-labelledby="snapshot-chart-title">
      <div className={styles.sectionHeading}>
        <div><p>SNAPSHOT SERIES</p><h3 id="snapshot-chart-title">{config.label}</h3></div>
        <span>快照时点状态，不代表精确组合回报</span>
      </div>
      <div className={styles.chart} role="img" aria-label={`${config.label}历史曲线`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 26, right: 20, left: 4, bottom: 0 }}>
            <CartesianGrid stroke="var(--color-rule)" vertical={false} />
            <XAxis dataKey="captured_at" minTickGap={28} tickFormatter={(capturedAt) => chartData.find((item) => item.captured_at === capturedAt)?.label ?? capturedAt} tick={{ fontSize: 10 }} />
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Tooltip formatter={(_value, _name, item) => [format(item.payload.originalValue), config.label]} />
            {pairs.map(({ before, after }) => <ReferenceArea key={`${before.id}-${after.id}`} x1={before.captured_at} x2={after.captured_at} fill="var(--color-target)" fillOpacity={0.08} />)}
            {markers.map(({item, events: dayEvents}) => <ReferenceDot key={`ledger-${item.id}`} x={item.captured_at} y={item.chartValue} r={5} fill="var(--color-fx)" stroke="var(--color-surface)" label={{value: `投资事件 ${dayEvents.length} 笔`, position: 'bottom', fontSize: 10}} />)}
            {chartData.filter((item) => eventLabel(item.snapshot_type)).map((item) => (
              <ReferenceDot
                key={item.id}
                x={item.captured_at}
                y={item.chartValue}
                r={4}
                fill={item.snapshot_type === "rebalance_before" ? "var(--color-target)" : "var(--color-planned)"}
                stroke="var(--color-surface)"
                label={{ value: eventLabel(item.snapshot_type) ?? "", position: "top", fontSize: 10 }}
              />
            ))}
            <Line type="monotone" dataKey="chartValue" stroke="var(--color-actual)" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {visibleEvents.length ? <section aria-label="投资事件" className={styles.rebalancePair}>
        <p>投资事件按发生日期标记同日快照；快照市值变化包含交易现金流，不代表投资收益。</p>
        <ul>{visibleEvents.map(event => <li key={event.id}>{event.occurred_on} · {event.symbol} · {eventNames[event.kind as keyof typeof eventNames]} · {event.kind === 'dividend' ? `${event.currency} ${event.amount}` : event.kind === 'split' ? `× ${event.ratio}` : `${event.quantity} × ${event.price} ${event.currency}`}</li>)}</ul>
      </section> : null}
      {pairs.length ? (
        <div className={styles.rebalancePair} aria-label="再平衡事件配对">
          {pairs.map(({ before, after }) => <div className={styles.pairRow} key={`${before.id}-${after.id}`}><span><i className={styles.beforeMark} />再平衡前<small>{before.note || before.label}</small></span><b aria-hidden="true" /><span><i className={styles.afterMark} />再平衡后<small>{after.note || after.label}</small></span></div>)}
        </div>
      ) : null}
    </section>
  );
}
