import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { RebalancePage } from "../src/pages/RebalancePage";
import { assetClassFixtures, holdingFixture, rebalanceDefaultsFixture, rebalancePlanFixture, rebalancePreviewFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function handlers() {
  return [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
    http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
    http.put("/api/settings/rebalance-defaults", async ({ request }) => HttpResponse.json({ ...await request.json() as object, updated_at: "2026-07-15T00:00:00Z" })),
    http.get("/api/rebalance/plans", () => HttpResponse.json({ items: [] })),
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

  await user.click(await screen.findByRole("button", { name: "开始测算" }));
  await screen.findByText("建议执行 4 笔交易");
  await user.click(screen.getByRole("button", { name: "保存方案" }));
  expect(await screen.findByText("方案已保存，尚未开始")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "开始本次再平衡" }));
  expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
  expect(screen.getByText("系统没有向券商提交订单")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "人民币" })).toBeDisabled();
  expect(screen.getByRole("radio", { name: "实际占比" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "重新测算" })).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "完成再平衡并建立新基准" }));
  expect(await screen.findByText("本次再平衡已完成，新汇率基准已建立")).toBeInTheDocument();
});

it("shows four ordered execution steps and completion safeguards only while a plan is in progress", async () => {
  renderWithProviders(<RebalancePage />, { handlers: handlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));
  await screen.findByText("建议执行 4 笔交易");
  await user.click(screen.getByRole("button", { name: "保存方案" }));

  expect(screen.queryByRole("list", { name: "再平衡执行清单" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "开始本次再平衡" }));

  const checklist = await screen.findByRole("list", { name: "再平衡执行清单" });
  expect(within(checklist).getAllByRole("listitem")).toHaveLength(4);
  expect(checklist).toHaveTextContent("按方案完成券商交易");
  expect(checklist).toHaveTextContent("更新实际持仓数量");
  expect(checklist).toHaveTextContent("核对调整结果");
  expect(checklist).toHaveTextContent("完成再平衡并建立新基准");
  expect(screen.getByText("完成后会创建调仓后快照，并将当前汇率重置为新的汇率基准；不会修改成本价或成本汇率。")).toBeInTheDocument();
});

it("can start directly by creating a plan first", async () => {
  renderWithProviders(<RebalancePage />, { handlers: handlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));
  await screen.findByText("建议执行 4 笔交易");
  await user.click(screen.getByRole("button", { name: "开始本次再平衡" }));

  expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
});

it("restores an in-progress plan so it can be completed after returning to rebalance", async () => {
  let completed = false;
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/rebalance/plans", () => HttpResponse.json({
        items: [{
          ...rebalancePlanFixture,
          status: "in_progress",
          valuation_basis: "fx_neutral",
          tolerance: "0.0075",
          before_snapshot_id: "30000000-0000-4000-8000-000000000010",
        }],
      })),
      http.post(`/api/rebalance/plans/${rebalancePlanFixture.id}/complete`, () => {
        completed = true;
        return HttpResponse.json({
          ...rebalancePlanFixture,
          status: "completed",
          before_snapshot_id: "30000000-0000-4000-8000-000000000010",
          after_snapshot_id: "30000000-0000-4000-8000-000000000011",
          baseline_reset_at: "2026-07-14T00:20:00+00:00",
        });
      }),
      ...handlers(),
    ],
  });
  const user = userEvent.setup();

  expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
  expect(screen.getByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByText("剔汇率模拟")).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "剔汇率口径" })).toBeChecked();
  expect(screen.getByRole("radio", { name: "剔汇率口径" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "允许偏离" })).toHaveValue("0.75");
  expect(screen.getByRole("textbox", { name: "允许偏离" })).toBeDisabled();
  expect(screen.getAllByTestId("tolerance-band")[0]).toHaveAccessibleName("允许偏离目标正负 0.8 个百分点");
  await user.click(screen.getByRole("button", { name: "完成再平衡并建立新基准" }));

  expect(await screen.findByText("本次再平衡已完成，新汇率基准已建立")).toBeInTheDocument();
  expect(completed).toBe(true);
});
