import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { PnlPage } from "../src/pages/PnlPage";
import { portfolioFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";


describe("PnlPage", () => {
  it("keeps original currency period results visible when current FX is missing", async () => {
    renderWithProviders(<PnlPage />, { handlers: [
      http.get('/api/analytics/portfolio', () => HttpResponse.json({detail: {code: 'PORTFOLIO_DATA_INCOMPLETE', message: 'Missing FX', items: []}}, {status: 409})),
      http.get('/api/ledger/statistics', () => HttpResponse.json({period: {id: 'p', opened_on: '2026-10-01'}, currencies: [{currency: 'USD', unrealized: '10', realized: '3', dividends: '2', opening_unrealized: '4', period_pnl: '11', complete: true, incomplete_reasons: []}], reference_pnl_cny: null, incomplete_reasons: []})),
    ]});
    expect(await screen.findByRole('heading', {name: '期间投资损益 · 原币口径'})).toBeInTheDocument();
    expect(screen.getByRole('rowheader', {name: 'USD'})).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('盈亏数据不完整');
  });
  it("states the exact scope and switches between CNY and trading-currency views", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PnlPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(portfolioFixture))],
    });

    expect(await screen.findByText("当前持仓，不含已实现盈亏")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "持仓明细" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "持仓明细币种" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "人民币" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("columnheader", { name: "人民币市值" })).toBeInTheDocument();
    expect(screen.getByText("1,268,420.00")).toBeInTheDocument();
    expect(screen.getAllByText("盈利").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "交易币种" }));

    expect(screen.getByRole("button", { name: "交易币种" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("columnheader", { name: "交易币种市值" })).toBeInTheDocument();
    expect(screen.getByText("USD 7,085.04")).toBeInTheDocument();
    expect(screen.getAllByText("+ USD 962.04")).toHaveLength(2);
    expect(screen.getByText("1,268,420.00")).toBeInTheDocument();
    expect(screen.getByText("人民币口径")).toBeInTheDocument();
  });

  it("keeps boundary-size trading-currency text exact", async () => {
    const user = userEvent.setup();
    const boundary = {
      ...portfolioFixture,
      holdings: portfolioFixture.holdings.map((item) => ({
        ...item,
        unrealized_pnl_trade_currency: "9999999999999999.99",
      })),
    };
    renderWithProviders(<PnlPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(boundary))],
    });

    await user.click(await screen.findByRole("button", { name: "交易币种" }));

    expect(screen.getAllByText("+ USD 9,999,999,999,999,999.99")).toHaveLength(2);
  });

  it("shows an accessible incomplete-data state with retry", async () => {
    renderWithProviders(<PnlPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json({ detail: {
        code: "PORTFOLIO_DATA_INCOMPLETE",
        message: "Required portfolio market data is incomplete.",
        items: [{ holding_id: "h1", symbol: "QQQ", input: "fx", key: "fx:USD/CNY", status: "missing", value: null }],
      } }, { status: 409 }))],
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("盈亏数据不完整");
    expect(screen.getByRole("alert")).toHaveTextContent("QQQ");
    expect(screen.getByRole("button", { name: "重试载入盈亏" })).toBeInTheDocument();
  });
});
