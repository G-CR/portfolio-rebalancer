import { ArrowRight, CircleCheck, CircleDotDashed, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

import type { PortfolioDecision } from "../../api/types";
import { formatPercent } from "./format";
import styles from "./Analytics.module.css";

const icons = {
  setup: CircleDotDashed,
  hold: CircleCheck,
  contribute: CircleDotDashed,
  rebalance: TriangleAlert,
};

export function DecisionBanner({ decision }: { decision: PortfolioDecision }) {
  const Icon = icons[decision.status];
  const action = decision.primary_action === "add_holding"
    ? { to: "/holdings", label: "添加第一个持仓" }
    : decision.primary_action === "view_rebalance"
      ? { to: "/rebalance", label: "查看再平衡建议" }
      : { to: "/rebalance", label: "测算新增资金" };

  return (
    <section className={styles.decision} data-status={decision.status} aria-labelledby="decision-title">
      <Icon size={22} aria-hidden="true" />
      <div className={styles.decisionCopy}>
        <p>当前行动判断</p>
        <h2 id="decision-title">{decision.title}</h2>
        <span>{decision.reason}</span>
      </div>
      <dl className={styles.decisionFacts}>
        <div><dt>最大偏离</dt><dd>{formatPercent(decision.max_drift)}</dd></div>
        <div><dt>汇率贡献</dt><dd>{formatPercent(decision.fx_contribution)}</dd></div>
      </dl>
      <Link className={styles.decisionAction} to={action.to}>{action.label}<ArrowRight size={15} aria-hidden="true" /></Link>
    </section>
  );
}
