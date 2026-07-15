import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import axe from "axe-core";

import { RebalancePage } from "../src/pages/RebalancePage";
import { assetClassFixtures, holdingFixture, rebalanceDefaultsFixture, rebalancePreviewFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function previewHandlers() {
  return [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
    http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
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

it("loads persisted defaults without starting a preview", async () => {
  let previewRequests = 0;
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json({
        ...rebalanceDefaultsFixture,
        available_cny: "12000.5",
        available_usd: "800.25",
        valuation_basis: "fx_neutral",
        tolerance: "0.035",
        minimum_trade_cny: "900",
        allow_sell: false,
        allow_fx: false,
      })),
      http.post("/api/rebalance/preview", () => {
        previewRequests += 1;
        return HttpResponse.json(rebalancePreviewFixture);
      }),
    ],
  });

  await waitFor(() => expect(screen.getByLabelText("人民币")).toHaveValue("12000.5"));
  expect(screen.getByLabelText("美元")).toHaveValue("800.25");
  expect(screen.getByLabelText("允许偏离")).toHaveValue("3.5");
  expect(screen.getByLabelText("最小交易金额")).toHaveValue("900");
  expect(screen.getByRole("radio", { name: "剔汇率口径" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /允许卖出/ })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /允许换汇/ })).not.toBeChecked();
  expect(previewRequests).toBe(0);
});

it("saves the current defaults before calculating", async () => {
  let savedDefaults: Record<string, unknown> | null = null;
  let previewPayload: Record<string, unknown> | null = null;
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
      http.put("/api/settings/rebalance-defaults", async ({ request }) => {
        savedDefaults = await request.json() as Record<string, unknown>;
        return HttpResponse.json({ ...savedDefaults, updated_at: "2026-07-15T00:00:00Z" });
      }),
      http.post("/api/rebalance/preview", async ({ request }) => {
        previewPayload = await request.json() as Record<string, unknown>;
        return HttpResponse.json(rebalancePreviewFixture);
      }),
    ],
  });
  const user = userEvent.setup();

  await user.clear(await screen.findByLabelText("人民币"));
  await user.type(screen.getByLabelText("人民币"), "25000");
  await user.click(screen.getByRole("checkbox", { name: /允许卖出/ }));
  await user.click(await screen.findByRole("radio", { name: "剔汇率口径" }));
  await user.click(screen.getByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(savedDefaults).toMatchObject({
    available_cny: "25000",
    valuation_basis: "fx_neutral",
    allow_sell: false,
    tolerance: "0.02",
  });
  expect(previewPayload).toMatchObject({
    available_cny: "25000",
    valuation_basis: "fx_neutral",
    allow_sell: false,
    tolerance: "0.02",
  });
});

it("continues calculating when persisted defaults cannot be saved", async () => {
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
      http.put("/api/settings/rebalance-defaults", () => HttpResponse.json({ detail: "failed" }, { status: 500 })),
      http.post("/api/rebalance/preview", () => HttpResponse.json(rebalancePreviewFixture)),
    ],
  });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByText("测算成功，但默认配置保存失败。")).toBeInTheDocument();
});

it("waits for an explicit command before the first preview", async () => {
  let previewRequests = 0;
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
      http.post("/api/rebalance/preview", () => {
        previewRequests += 1;
        return HttpResponse.json(rebalancePreviewFixture);
      }),
    ],
  });
  const user = userEvent.setup();

  expect(await screen.findByRole("button", { name: "开始测算" })).toBeEnabled();
  expect(screen.getByText("配置本次资金与约束后开始测算")).toBeInTheDocument();
  expect(previewRequests).toBe(0);

  await user.click(screen.getByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(previewRequests).toBe(1);
  expect(screen.getByRole("button", { name: "重新测算" })).toBeEnabled();
});

it("keeps inputs visible after recalculation", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();
  const cny = await screen.findByLabelText("人民币");

  await user.clear(cny);
  await user.type(cny, "20000");
  await user.click(screen.getByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByLabelText("人民币")).toHaveValue("20000");
});

it("distinguishes current and projected allocation markers", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  expect(await screen.findAllByLabelText(/当前占比/)).toHaveLength(5);
  expect(screen.getAllByLabelText(/预计占比/)).toHaveLength(5);
});

it("shows a reason for every sell suggestion", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  const sellRow = await screen.findByRole("row", { name: /SPY 卖出/ });
  expect(within(sellRow).getByText("新增资金不足以消除高配")).toBeInTheDocument();
});

it("shows the user-entered holding name beside the trade symbol", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  const sellRow = await screen.findByRole("row", { name: /SPY 卖出/ });
  expect(within(sellRow).getByText("SPDR S&P 500 ETF Trust")).toBeInTheDocument();
});

it("formats the comparison drift as a percentage", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("0.30%")).toBeInTheDocument();
});

it("keeps valuation-basis changes local until calculation is requested", async () => {
  const requestedBases: string[] = [];
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
      http.post("/api/rebalance/preview", async ({ request }) => {
        const payload = await request.json() as { valuation_basis: string };
        requestedBases.push(payload.valuation_basis);
        return HttpResponse.json({ ...rebalancePreviewFixture, valuation_basis: payload.valuation_basis });
      }),
    ],
  });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("radio", { name: "剔汇率口径" }));
  expect(screen.getByText("剔汇率模拟")).toBeInTheDocument();
  expect(requestedBases).toEqual([]);

  await user.click(screen.getByRole("button", { name: "开始测算" }));
  await waitFor(() => expect(requestedBases).toEqual(["fx_neutral"]));
});

it("requires stale-data acknowledgement before saving", async () => {
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
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
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("部分行情数据已过期")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
});

it("requires recalculation after any strategy input changes", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));
  await screen.findByText("建议执行 4 笔交易");
  await user.clear(screen.getByLabelText("人民币"));
  await user.type(screen.getByLabelText("人民币"), "30000");

  expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新测算" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "保存方案" })).toBeEnabled());
});

it("has no serious accessibility violations", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "开始测算" }));
  await screen.findByText("建议执行 4 笔交易");

  const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical")).toEqual([]);
});
