import { render, screen } from "@testing-library/react";

import type { RebalancePreview, RebalanceResult } from "../src/api/types";
import { RebalanceSummary } from "../src/features/rebalance/RebalanceSummary";
import { rebalancePreviewFixture } from "./fixtures";

function previewWith(overrides: Partial<RebalanceResult>): RebalancePreview {
  return {
    ...rebalancePreviewFixture,
    result: {
      ...rebalancePreviewFixture.result,
      ...overrides,
    },
  } as RebalancePreview;
}

it("shows the before and final drift for a buy-only plan", () => {
  render(<RebalanceSummary preview={previewWith({
    max_drift_before: "0.032",
    max_drift_after: "0.014",
    buy_only_max_drift: "0.014",
    sell_phase_used: false,
  })} />);

  expect(screen.getByText("最大偏离 3.20pp → 1.40pp")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "最大偏离变化：测算前 3.20pp，最终 1.40pp" })).toBeInTheDocument();
  expect(screen.queryByText(/纯补仓/)).not.toBeInTheDocument();
});

it("explains the intermediate buy-only drift when the sell phase is used", () => {
  render(<RebalanceSummary preview={previewWith({
    max_drift_before: "0.032",
    buy_only_max_drift: "0.023",
    max_drift_after: "0.014",
    sell_phase_used: true,
  })} />);

  expect(screen.getByText("最大偏离 3.20pp → 1.40pp")).toBeInTheDocument();
  expect(screen.getByText("纯补仓 2.30pp，卖出转配后 1.40pp")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "最大偏离变化：测算前 3.20pp，纯补仓 2.30pp，最终 1.40pp" })).toBeInTheDocument();
});

it("states CNY-to-USD net FX as one direction", () => {
  render(<RebalanceSummary preview={previewWith({
    net_fx_direction: "cny_to_usd",
    net_fx_amount_cny: "5000",
  })} />);

  expect(screen.getByText("净换汇：人民币换美元 ¥5,000")).toBeInTheDocument();
  expect(screen.queryByText(/美元换人民币/)).not.toBeInTheDocument();
});

it("states USD-to-CNY net FX as one direction", () => {
  render(<RebalanceSummary preview={previewWith({
    net_fx_direction: "usd_to_cny",
    net_fx_amount_cny: "5000",
  })} />);

  expect(screen.getByText("净换汇：美元换人民币 ¥5,000")).toBeInTheDocument();
  expect(screen.queryByText(/人民币换美元/)).not.toBeInTheDocument();
});

it("keeps a small nonzero optimality gap visible in certification detail", () => {
  render(<RebalanceSummary preview={previewWith({
    optimization_certified: true,
    optimization_precision: "0.0001",
    optimality_gap: "0.00003",
  })} />);

  expect(screen.getByText("已在 1bp 精度内认证")).toBeInTheDocument();
  expect(screen.getByText("最优性差距 0.3bp")).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "优化器认证：已在 1bp 精度内认证；最优性差距 0.3bp" })).toBeInTheDocument();
});

it("labels historical results that lack optimizer certification", () => {
  render(<RebalanceSummary preview={previewWith({
    optimization_certified: false,
  })} />);

  expect(screen.getByText("历史方案未经过新优化器认证")).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "历史方案未经过新优化器认证" })).toBeInTheDocument();
  expect(screen.queryByText(/精度内认证/)).not.toBeInTheDocument();
});
