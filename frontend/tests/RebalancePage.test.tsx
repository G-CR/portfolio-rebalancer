import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import axe from "axe-core";

import { RebalancePage } from "../src/pages/RebalancePage";
import { assetClassFixtures, rebalancePreviewFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function previewHandlers() {
  return [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.post("/api/rebalance/preview", async ({ request }) => {
      const payload = await request.json() as { valuation_basis: string };
      return HttpResponse.json({
        ...rebalancePreviewFixture,
        valuation_basis: payload.valuation_basis,
        fx_comparison: {
          ...rebalancePreviewFixture.fx_comparison,
          valuation_basis: payload.valuation_basis === "actual" ? "fx_neutral" : "actual",
        },
      });
    }),
  ];
}

it("keeps inputs visible after recalculation", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();
  const cny = await screen.findByLabelText("人民币");

  await user.clear(cny);
  await user.type(cny, "20000");
  await user.click(screen.getByRole("button", { name: "重新测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByLabelText("人民币")).toHaveValue("20000");
});

it("distinguishes current and projected allocation markers", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });

  expect(await screen.findAllByLabelText(/当前占比/)).toHaveLength(5);
  expect(screen.getAllByLabelText(/预计占比/)).toHaveLength(5);
});

it("shows a reason for every sell suggestion", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });

  const sellRow = await screen.findByRole("row", { name: /SPY 卖出/ });
  expect(within(sellRow).getByText("新增资金不足以消除高配")).toBeInTheDocument();
});

it("requests a fresh preview when valuation basis changes", async () => {
  const requestedBases: string[] = [];
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.post("/api/rebalance/preview", async ({ request }) => {
        const payload = await request.json() as { valuation_basis: string };
        requestedBases.push(payload.valuation_basis);
        return HttpResponse.json({ ...rebalancePreviewFixture, valuation_basis: payload.valuation_basis });
      }),
    ],
  });
  const user = userEvent.setup();

  await screen.findByText("建议执行 4 笔交易");
  await user.click(screen.getByRole("radio", { name: "剔汇率口径" }));

  await waitFor(() => expect(requestedBases).toEqual(["actual", "fx_neutral"]));
});

it("requires stale-data acknowledgement before saving", async () => {
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.post("/api/rebalance/preview", () => HttpResponse.json({
        detail: {
          code: "REBALANCE_STALE_DATA_ACK_REQUIRED",
          message: "Stale market data requires explicit acknowledgement before previewing a rebalance plan.",
          status: "stale",
          items: ["price:SPY"],
        },
      }, { status: 409 })),
    ],
  });

  expect(await screen.findByText("部分行情数据已过期")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
});

it("requires recalculation after any strategy input changes", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await screen.findByText("建议执行 4 笔交易");
  await user.clear(screen.getByLabelText("人民币"));
  await user.type(screen.getByLabelText("人民币"), "30000");

  expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新测算" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "保存方案" })).toBeEnabled());
});

it("has no serious accessibility violations", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  await screen.findByText("建议执行 4 笔交易");

  const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical")).toEqual([]);
});
