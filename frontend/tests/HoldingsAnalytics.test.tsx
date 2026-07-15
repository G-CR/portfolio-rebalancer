import { StrictMode } from "react";
import { screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";

import { HoldingsPage } from "../src/pages/HoldingsPage";
import { assetClassFixtures, holdingFixture, marketDataCollectionFixture, portfolioFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";


describe("holdings analytics join", () => {
  it("joins analytics by holding id and retains stale/manual values", async () => {
    const analytics = {
      ...portfolioFixture,
      has_stale_data: true,
      holdings: portfolioFixture.holdings.map((item) => ({ ...item, price_status: "stale", fx_status: "manual" })),
    };
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/analytics/portfolio", () => HttpResponse.json(analytics)),
    ] });

    expect(await screen.findByText("590.42")).toBeInTheDocument();
    expect(screen.getByText("7.2")).toBeInTheDocument();
    expect(screen.getByText("51,012.29")).toBeInTheDocument();
    expect(screen.getByText("51,012")).toBeInTheDocument();
    expect(screen.getByText("+7,049.15")).toBeInTheDocument();
    expect(screen.getByText("+7,049")).toBeInTheDocument();
    expect(screen.getByText("数据已过期")).toBeInTheDocument();
    expect(screen.getByText("手动值")).toBeInTheDocument();
  });

  it("automatically refreshes missing data once and reloads analytics", async () => {
    let refreshCalls = 0;
    let refreshed = false;
    const incompletePortfolio = { detail: {
      code: "PORTFOLIO_DATA_INCOMPLETE",
      message: "Required portfolio market data is incomplete.",
      items: [{ holding_id: holdingFixture.id, symbol: "SPY", input: "price", key: "price:SPY", status: "missing", value: null }],
    } };
    renderWithProviders(<StrictMode><HoldingsPage /></StrictMode>, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/analytics/portfolio", () => refreshed
        ? HttpResponse.json(portfolioFixture)
        : HttpResponse.json(incompletePortfolio, { status: 409 })),
      http.post("/api/market-data/refresh", async () => {
        refreshCalls += 1;
        await delay(80);
        refreshed = true;
        return HttpResponse.json(marketDataCollectionFixture);
      }),
    ] });

    expect(await screen.findByText("正在获取 SPY 行情…")).toBeInTheDocument();
    expect(await screen.findByText("51,012.29")).toBeInTheDocument();
    expect(refreshCalls).toBe(1);
  });

  it("offers retry and manual input after automatic refresh still fails", async () => {
    let refreshCalls = 0;
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/analytics/portfolio", () => HttpResponse.json({ detail: {
        code: "PORTFOLIO_DATA_INCOMPLETE",
        message: "Required portfolio market data is incomplete.",
        items: [{ holding_id: holdingFixture.id, symbol: "SPY", input: "price", key: "price:SPY", status: "missing", value: null }],
      } }, { status: 409 })),
      http.post("/api/market-data/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({ items: [{
          key: "price:SPY",
          data_type: "price",
          symbol: "SPY",
          currency: "USD",
          effective_value: null,
          source: "yahoo",
          status: "failed",
          market_time: null,
          fetched_at: "2026-07-15T01:00:00Z",
          error_summary: "yahoo: provider_request_failed; alpha_vantage: provider_not_configured",
          note: null,
        }], diagnostics: [] });
      }),
    ] });

    expect(await screen.findByRole("alert")).toHaveTextContent("Yahoo 请求失败");
    expect(screen.getByRole("button", { name: "立即重试" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "手动录入" })).toBeInTheDocument();
    await waitFor(() => expect(refreshCalls).toBe(1));
  });
});
