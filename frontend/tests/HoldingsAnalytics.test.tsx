import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { HoldingsPage } from "../src/pages/HoldingsPage";
import { assetClassFixtures, holdingFixture, portfolioFixture } from "./fixtures";
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

  it("keeps raw holdings visible when analytics is incomplete", async () => {
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/analytics/portfolio", () => HttpResponse.json({ detail: {
        code: "PORTFOLIO_DATA_INCOMPLETE",
        message: "Required portfolio market data is incomplete.",
        items: [{ holding_id: holdingFixture.id, symbol: "SPY", input: "price", key: "price:SPY", status: "missing", value: null }],
      } }, { status: 409 })),
    ] });

    expect(await screen.findByText("SPY")).toBeInTheDocument();
    expect(screen.getAllByText("数据缺失").length).toBeGreaterThan(0);
    expect(screen.getByRole("alert")).toHaveTextContent("SPY 行情数据不完整");
  });
});
