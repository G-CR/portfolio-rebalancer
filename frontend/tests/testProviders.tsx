import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { RequestHandler } from "msw";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { createQueryClient } from "../src/app/providers";

export const server = setupServer(
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
