import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { RequestHandler } from "msw";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { createQueryClient } from "../src/app/providers";
import { rebalancePreviewFixture } from "./fixtures";

export const decisionFixture = { status: "normal", title: "配置正常", reason: "全部类别在允许偏离区间内。", classes: [], issues: [], has_manual_data: false, latest_valid_date: "2026-09-30", last_checked_at: null, active_plan_id: null, review_date: "2026-10-01", review_due: false, last_reviewed_at: null };
export const server = setupServer(
  http.get('/api/ledger/entries', () => HttpResponse.json([])),
  http.get('/api/ledger/statistics', () => HttpResponse.json({period: null, currencies: [], reference_pnl_cny: null, incomplete_reasons: [], holdings: []})),
  http.get("/api/decision", () => HttpResponse.json(decisionFixture)),
  http.get("/api/decision/settings", () => HttpResponse.json({ review_day: 1, notification_mode: "daily", monthly_email: false, last_checked_at: null, last_reviewed_at: null })),
  http.get("/api/settings/rebalance-defaults", () => HttpResponse.json({
    available_cny: "0",
    available_usd: "0",
    valuation_basis: "actual",
    tolerance: "0.02",
    minimum_trade_cny: "500",
    allow_sell: true,
    allow_fx: true,
    updated_at: "2026-07-14T00:00:00Z",
  })),
  http.put("/api/settings/rebalance-defaults", async ({ request }) => HttpResponse.json({
    ...await request.json() as object,
    updated_at: "2026-07-15T00:00:00Z",
  })),
  http.get("/api/rebalance/plans", () => HttpResponse.json({ items: [] })),
  http.get("/api/rebalance/preview-jobs/latest", () => HttpResponse.json(null)),
  http.post("/api/rebalance/preview-jobs", () => HttpResponse.json({
    id: "preview-job-test",
    status: "succeeded",
    result: rebalancePreviewFixture,
    error: null,
  })),
  http.get("/api/rebalance/preview-jobs/:jobId", () => HttpResponse.json({
    id: "preview-job-test",
    status: "succeeded",
    result: rebalancePreviewFixture,
    error: null,
  })),
  http.get("/api/analytics/portfolio", () => HttpResponse.json({
    as_of: null,
    data_status: "setup",
    has_stale_data: false,
    has_manual_data: false,
    tolerance: "0.02",
    cost_cny: "0",
    market_value_cny: "0",
    fx_neutral_value_cny: "0",
    unrealized_pnl: "0",
    unrealized_return: "0",
    price_effect: "0",
    fx_effect: "0",
    overseas_weight: "0",
    decision: { status: "setup", title: "开始建立组合", reason: "添加第一个持仓后即可查看配置偏离与盈亏拆分。", max_drift: "0", fx_contribution: "0", primary_action: "add_holding" },
    asset_classes: [], holdings: [], data_inputs: [],
  })),
);

type TestProviderOptions = Omit<RenderOptions, "wrapper"> & {
  route?: string;
  handlers?: RequestHandler[];
};

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", handlers = [], ...renderOptions }: TestProviderOptions = {},
) {
  const queryClient = createQueryClient();
  server.use(...handlers);

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }

  return {
    queryClient,
    ...render(ui, { wrapper: Wrapper, ...renderOptions }),
  };
}
