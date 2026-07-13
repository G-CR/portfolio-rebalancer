import styles from "./CalibrationRail.module.css";

type CalibrationRailProps = {
  assetName: string;
  target: number;
  actual: number;
  tolerance: number;
  fxNeutral?: number;
  planned?: number;
};

type MarkerKind = "actual" | "fxNeutral" | "planned";

const HALF_RANGE = 4;

const markerLabels: Record<MarkerKind, string> = {
  actual: "实际",
  fxNeutral: "剔汇率",
  planned: "计划",
};

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function formatDeviation(value: number) {
  const normalized = Math.abs(value) < 0.05 ? 0 : value;
  return `${normalized >= 0 ? "+" : ""}${normalized.toFixed(1)}pp`;
}

function markerPosition(value: number, target: number) {
  const raw = ((value - (target - HALF_RANGE)) / (HALF_RANGE * 2)) * 100;
  return Math.min(100, Math.max(0, raw));
}

function overflowSide(value: number, target: number) {
  if (value < target - HALF_RANGE) return "left";
  if (value > target + HALF_RANGE) return "right";
  return undefined;
}

function toleranceDescription(inputTolerance: number, displayedTolerance: number) {
  const displayed = displayedTolerance.toFixed(1);
  if (inputTolerance > HALF_RANGE) {
    return `允许偏离目标正负 ${displayed} 个百分点；输入值 ${inputTolerance.toFixed(1)} 个百分点超出可见刻度，已按正负 ${displayed} 个百分点显示`;
  }
  if (inputTolerance < 0) {
    return `允许偏离目标正负 ${displayed} 个百分点；输入值 ${inputTolerance.toFixed(1)} 个百分点已按 ${displayed} 个百分点显示`;
  }
  return `允许偏离目标正负 ${displayed} 个百分点`;
}

function Marker({ kind, value, target }: { kind: MarkerKind; value: number; target: number }) {
  const side = overflowSide(value, target);
  const label = markerLabels[kind];
  const testId = kind === "fxNeutral" ? "fx-neutral-marker" : `${kind}-marker`;
  const overflowLabel = side
    ? `${label}占比超出${side === "left" ? "左" : "右"}侧刻度，真实值 ${formatPercent(value)}`
    : undefined;

  return (
    <span
      className={`${styles.marker} ${styles[kind]} ${side ? styles.overflow : ""}`}
      style={{ left: `${markerPosition(value, target)}%` }}
      data-testid={testId}
      aria-label={overflowLabel}
    >
      {side ? <span className={styles.overflowArrow} aria-hidden="true">{side === "left" ? "←" : "→"}</span> : null}
      <span className={styles.markerShape} aria-hidden="true" />
    </span>
  );
}

export function CalibrationRail({
  assetName,
  target,
  actual,
  tolerance,
  fxNeutral,
  planned,
}: CalibrationRailProps) {
  const toleranceWidth = Math.min(HALF_RANGE, Math.max(0, tolerance));
  const toleranceText = toleranceDescription(tolerance, toleranceWidth);
  const bandLeft = markerPosition(target - toleranceWidth, target);
  const bandRight = markerPosition(target + toleranceWidth, target);

  return (
    <article className={styles.calibration} aria-label={`${assetName}资产校准尺`}>
      <header className={styles.header}>
        <div>
          <h3>{assetName}</h3>
          <span className={styles.targetText}>目标 {formatPercent(target)}</span>
        </div>
        <strong className={styles.deviation}>{formatDeviation(actual - target)}</strong>
      </header>

      <div className={styles.scaleLabels} aria-hidden="true">
        <span>{formatDeviation(-HALF_RANGE)}</span>
        <span>目标</span>
        <span>{formatDeviation(HALF_RANGE)}</span>
      </div>
      <div className={styles.rail}>
        <span
          className={styles.toleranceBand}
          style={{ left: `${bandLeft}%`, width: `${bandRight - bandLeft}%` }}
          aria-label={toleranceText}
          data-testid="tolerance-band"
        />
        <span className={styles.targetLine} aria-hidden="true" />
        <Marker kind="actual" value={actual} target={target} />
        {fxNeutral === undefined ? null : <Marker kind="fxNeutral" value={fxNeutral} target={target} />}
        {planned === undefined ? null : <Marker kind="planned" value={planned} target={target} />}
      </div>

      <p className={styles.toleranceDescription}>{toleranceText}</p>

      <div className={styles.values} aria-label="校准值">
        <div className={styles.valueActual}>
          <span aria-hidden="true" />实际 {formatPercent(actual)}
        </div>
        {fxNeutral === undefined ? null : (
          <div className={styles.valueFx}>
            <span aria-hidden="true" />剔汇率 {formatPercent(fxNeutral)}
          </div>
        )}
        {planned === undefined ? null : (
          <div className={styles.valuePlanned}>
            <span aria-hidden="true" />计划 {formatPercent(planned)}
          </div>
        )}
      </div>
    </article>
  );
}
