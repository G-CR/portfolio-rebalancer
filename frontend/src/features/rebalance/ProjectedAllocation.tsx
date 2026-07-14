import type { AssetClass, RebalancePreview } from "../../api/types";
import { CalibrationRail } from "../../components/CalibrationRail/CalibrationRail";
import { boundedRatioPercent, formatPercent, formatPercentagePoints, formatSignedPercentagePoints } from "../analytics/format";
import styles from "./Rebalance.module.css";

export function ProjectedAllocation({ preview, assetClasses, tolerance }: { preview: RebalancePreview; assetClasses: AssetClass[]; tolerance: string }) {
  const names = new Map(assetClasses.map((item) => [item.id, item.name]));
  return (
    <section className={styles.allocation} aria-labelledby="projected-allocation-title">
      <header className={styles.sectionHeading}><div><p>PROJECTED ALLOCATION</p><h2 id="projected-allocation-title">调整前后配置</h2></div><span>计划绿表示预计占比</span></header>
      <div className={styles.railGrid}>
        {preview.result.projected_weights.map((item) => <div key={item.asset_class_id} className={styles.railItem}>
          <span className={styles.srOnly} role="img" aria-label={`当前占比 ${formatPercent(item.before)}`} />
          <span className={styles.srOnly} role="img" aria-label={`预计占比 ${formatPercent(item.after)}`} />
          <CalibrationRail
            assetName={names.get(item.asset_class_id) ?? "资产类别"}
            target={boundedRatioPercent(item.target)}
            actual={boundedRatioPercent(item.before)}
            planned={boundedRatioPercent(item.after)}
            tolerance={boundedRatioPercent(tolerance)}
            targetText={formatPercent(item.target)}
            actualText={formatPercent(item.before)}
            plannedText={formatPercent(item.after)}
            deviationText={formatSignedPercentagePoints(String(Number(item.before) - Number(item.target)))}
            toleranceValueText={formatPercentagePoints(tolerance).replace(/pp$/, "")}
          />
        </div>)}
      </div>
    </section>
  );
}
