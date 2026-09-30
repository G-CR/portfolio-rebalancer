import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import axe from "axe-core";
import { useState } from "react";

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

function succeededPreviewJob(result = rebalancePreviewFixture) {
  return { id: "preview-job-test", status: "succeeded", result, error: null };
}

function restorableJob(status: "calculating" | "succeeded", isCurrent: boolean | null = null) {
  return {
    id: "restored-preview-job",
    status,
    result: status === "succeeded" ? { ...rebalancePreviewFixture, input_signature: "signature-1" } : null,
    error: null,
    payload: {
      session_token: "original-session",
      request_token: "original-request",
      available_cny: "2468",
      available_usd: "0",
      valuation_basis: "actual",
      allow_sell: true,
      allow_fx: true,
      tolerance: "0.02",
      acknowledge_stale_data: false,
    },
    created_at: "2026-09-30T10:00:00Z",
    finished_at: status === "succeeded" ? "2026-09-30T10:01:00Z" : null,
    is_current: isCurrent,
  };
}

it("continues showing a background job after leaving and returning", async () => {
  let latest = restorableJob("calculating");
  function PageSwitcher() {
    const [visible, setVisible] = useState(true);
    return <><button onClick={() => setVisible((value) => !value)}>切换页面</button>{visible ? <RebalancePage /> : <p>其他页面</p>}</>;
  }
  renderWithProviders(<PageSwitcher />, {
    handlers: [
      ...previewHandlers(),
      http.get("/api/rebalance/preview-jobs/latest", () => HttpResponse.json(latest)),
      http.get("/api/rebalance/preview-jobs/:jobId", () => HttpResponse.json(latest)),
    ],
  });
  const user = userEvent.setup();

  expect(await screen.findByText("正在计算方案")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "切换页面" }));
  expect(screen.getByText("其他页面")).toBeInTheDocument();
  latest = restorableJob("succeeded", true);
  await user.click(screen.getByRole("button", { name: "切换页面" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByLabelText("人民币")).toHaveValue("2468");
});

it("restores the last result and blocks formal actions when its inputs changed", async () => {
  renderWithProviders(<RebalancePage />, {
    handlers: [
      ...previewHandlers(),
      http.get("/api/rebalance/preview-jobs/latest", () => HttpResponse.json(restorableJob("succeeded", false))),
    ],
  });

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByLabelText("人民币")).toHaveValue("2468");
  expect(screen.getByText(/上次测算结果/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "开始本次再平衡" })).toBeDisabled();
});

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
  expect(screen.queryByLabelText("最小交易金额")).not.toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "剔汇率口径" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /允许卖出/ })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /允许换汇/ })).not.toBeChecked();
  expect(screen.getByText("人民币与美元可按需要双向净换汇")).toBeInTheDocument();
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
      http.post("/api/rebalance/preview-jobs", async ({ request }) => {
        previewPayload = await request.json() as Record<string, unknown>;
        return HttpResponse.json(succeededPreviewJob());
      }),
    ],
  });
  const user = userEvent.setup();

  await waitFor(() => expect(screen.getByRole("button", { name: "开始测算" })).toBeEnabled());
  await user.clear(screen.getByLabelText("人民币"));
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
  expect(savedDefaults).not.toHaveProperty("minimum_trade_cny");
  expect(previewPayload).not.toHaveProperty("minimum_trade_cny");
});

it("continues calculating when persisted defaults cannot be saved", async () => {
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
      http.put("/api/settings/rebalance-defaults", () => HttpResponse.json({ detail: "failed" }, { status: 500 })),
      http.post("/api/rebalance/preview-jobs", () => HttpResponse.json(succeededPreviewJob())),
    ],
  });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByText("测算任务已提交，但默认配置保存失败。")).toBeInTheDocument();
});

it("waits for an explicit command before the first preview", async () => {
  let previewRequests = 0;
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
      http.post("/api/rebalance/preview-jobs", () => {
        previewRequests += 1;
        return HttpResponse.json(succeededPreviewJob());
      }),
    ],
  });
  const user = userEvent.setup();

  await waitFor(() => expect(screen.getByRole("button", { name: "开始测算" })).toBeEnabled());
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

  await waitFor(() => expect(cny).toBeEnabled());
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

it("explains the certified drift path and net FX before execution", async () => {
  renderWithProviders(<RebalancePage />, { handlers: previewHandlers() });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("最大偏离 4.00pp → 0.20pp")).toBeInTheDocument();
  expect(screen.getByText("纯补仓 0.60pp，卖出转配后 0.20pp")).toBeInTheDocument();
  expect(screen.getByText("已在 1bp 精度内认证")).toBeInTheDocument();
  expect(screen.getByText("净换汇：人民币换美元 ¥7,200")).toBeInTheDocument();
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
      http.post("/api/rebalance/preview-jobs", async ({ request }) => {
        const payload = await request.json() as { valuation_basis: string };
        requestedBases.push(payload.valuation_basis);
        return HttpResponse.json(succeededPreviewJob({ ...rebalancePreviewFixture, valuation_basis: payload.valuation_basis }));
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
      http.post("/api/rebalance/preview-jobs", () => HttpResponse.json({
        id: "preview-job-stale",
        status: "failed",
        result: null,
        error: {
          code: "REBALANCE_STALE_DATA_ACK_REQUIRED",
          message: "Stale market data requires explicit acknowledgement before previewing a rebalance plan.",
          status: "stale",
          items: ["price:SPY"],
        },
      })),
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
