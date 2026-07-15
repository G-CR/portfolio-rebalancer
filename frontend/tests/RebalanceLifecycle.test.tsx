import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { RebalancePage } from "../src/pages/RebalancePage";
import { assetClassFixtures, holdingFixture, rebalancePlanFixture, rebalancePreviewFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function handlers() {
  return [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
    http.post("/api/rebalance/preview", () => HttpResponse.json(rebalancePreviewFixture)),
    http.post("/api/rebalance/plans", () => HttpResponse.json(rebalancePlanFixture, { status: 201 })),
    http.post(`/api/rebalance/plans/${rebalancePlanFixture.id}/start`, () => HttpResponse.json({
      ...rebalancePlanFixture,
      status: "in_progress",
      before_snapshot_id: "30000000-0000-4000-8000-000000000010",
    })),
    http.post(`/api/rebalance/plans/${rebalancePlanFixture.id}/complete`, () => HttpResponse.json({
      ...rebalancePlanFixture,
      status: "completed",
      before_snapshot_id: "30000000-0000-4000-8000-000000000010",
      after_snapshot_id: "30000000-0000-4000-8000-000000000011",
      baseline_reset_at: "2026-07-14T00:20:00+00:00",
    })),
  ];
}

it("saves, starts, and completes a formal rebalance plan", async () => {
  renderWithProviders(<RebalancePage />, { handlers: handlers() });
  const user = userEvent.setup();

  await screen.findByText("建议执行 4 笔交易");
  await user.click(screen.getByRole("button", { name: "保存方案" }));
  expect(await screen.findByText("方案已保存，尚未开始")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "开始本次再平衡" }));
  expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
  expect(screen.getByText("系统没有向券商提交订单")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "完成再平衡并建立新基准" }));
  expect(await screen.findByText("本次再平衡已完成，新汇率基准已建立")).toBeInTheDocument();
});

it("can start directly by creating a plan first", async () => {
  renderWithProviders(<RebalancePage />, { handlers: handlers() });
  const user = userEvent.setup();

  await screen.findByText("建议执行 4 笔交易");
  await user.click(screen.getByRole("button", { name: "开始本次再平衡" }));

  expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
});
