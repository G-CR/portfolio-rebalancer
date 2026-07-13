import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { DashboardPage } from "../src/pages/DashboardPage";
import { portfolioFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";


describe("DashboardPage", () => {
  it("shows the ordered decision, metrics, five rails, P&L, and data status", async () => {
    renderWithProviders(<DashboardPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(portfolioFixture))],
    });

    const decision = await screen.findByRole("heading", { name: "保持现状" });
    const value = screen.getByText("1,268,420");
    expect(decision.compareDocumentPosition(value) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByLabelText(/资产校准尺$/)).toHaveLength(5);
    expect(screen.getByRole("heading", { name: "盈亏拆分" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "数据状态" })).toBeInTheDocument();
  });

  it("labels stale data without clearing values", async () => {
    const stale = {
      ...portfolioFixture,
      data_status: "stale",
      has_stale_data: true,
      data_inputs: portfolioFixture.data_inputs.map((item, index) => index === 0 ? { ...item, status: "stale" } : item),
    };
    renderWithProviders(<DashboardPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(stale))],
    });

    expect((await screen.findAllByText("数据已过期")).length).toBeGreaterThan(0);
    expect(screen.getByText("1,268,420")).toBeInTheDocument();
    expect(screen.getByText("590.42")).toBeInTheDocument();
  });

  it("formats calibration percentage labels from exact decimal strings", async () => {
    const exact = {
      ...portfolioFixture,
      tolerance: "0.0015",
      asset_classes: portfolioFixture.asset_classes.map((item, index) => index === 0 ? {
        ...item,
        target_weight: "0.0015",
        actual_weight: "0.0025",
        fx_neutral_weight: "0.0035",
        drift: "0.0010",
      } : item),
    };
    renderWithProviders(<DashboardPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(exact))],
    });

    expect(await screen.findByText("允许偏离 ±0.2pp")).toBeInTheDocument();
    expect(screen.getByText("目标 0.2%")).toBeInTheDocument();
    expect(screen.getByText("实际 0.3%")).toBeInTheDocument();
    expect(screen.getByText("剔汇率 0.4%")).toBeInTheDocument();
    expect(screen.getByText("+0.1pp")).toBeInTheDocument();
  });

  it("presents a structured incomplete state with retry", async () => {
    renderWithProviders(<DashboardPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json({ detail: {
        code: "PORTFOLIO_DATA_INCOMPLETE",
        message: "Required portfolio market data is incomplete.",
        items: [{ holding_id: "h1", symbol: "SPY", input: "price", key: "price:SPY", status: "failed", value: null, market_time: null, source: "yahoo", error_summary: "Market-data provider request failed." }],
      } }, { status: 409 }))],
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("组合数据不完整");
    expect(screen.getByRole("alert")).toHaveTextContent("SPY");
    expect(screen.getByRole("button", { name: "重试载入分析" })).toBeInTheDocument();
  });

  it("offers setup action for an empty portfolio", async () => {
    renderWithProviders(<DashboardPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json({
        ...portfolioFixture,
        data_status: "setup",
        cost_cny: "0",
        market_value_cny: "0",
        fx_neutral_value_cny: "0",
        unrealized_pnl: "0",
        price_effect: "0",
        fx_effect: "0",
        overseas_weight: "0",
        decision: { status: "setup", title: "开始建立组合", reason: "添加第一个持仓后即可查看配置偏离与盈亏拆分。", max_drift: "0", fx_contribution: "0", primary_action: "add_holding" },
        asset_classes: [], holdings: [], data_inputs: [],
      }))],
    });

    expect(await screen.findByRole("link", { name: "添加第一个持仓" })).toHaveAttribute("href", "/holdings");
  });
});
