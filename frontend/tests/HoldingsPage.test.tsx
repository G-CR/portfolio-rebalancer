import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HoldingsPage } from "../src/pages/HoldingsPage";
import { assetClassFixtures, holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

describe("HoldingsPage", () => {
  it("refetches archived rows and shows only archived results with disabled actions", async () => {
    const user = userEvent.setup();
    const archived = { ...holdingFixture, id: "20000000-0000-4000-8000-000000000002", symbol: "VOO", is_active: false };
    const requests: string[] = [];
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", ({ request }) => {
        requests.push(request.url);
        return HttpResponse.json(request.url.includes("include_archived=true")
          ? [holdingFixture, archived]
          : [holdingFixture]);
      }),
    ] });

    expect(await screen.findAllByRole("table")).toHaveLength(1);
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.queryByText("VOO")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "追加买入 SPY" })).toHaveAttribute("title", "追加买入");
    expect(screen.getByRole("button", { name: "更多 SPY 操作" })).toHaveAttribute("title", "更多操作");

    await user.click(screen.getByRole("checkbox", { name: "仅显示已归档持仓" }));
    expect(await screen.findByText("VOO")).toBeInTheDocument();
    expect(screen.queryByText("SPY")).not.toBeInTheDocument();
    expect(screen.getByText("已归档，无可用操作")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "追加买入 VOO" })).not.toBeInTheDocument();
    expect(requests.some((url) => url.includes("include_archived=true"))).toBe(true);
  });

  it("distinguishes an empty archived filter from an empty portfolio", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
    ] });

    await screen.findByText("SPY");
    await user.click(screen.getByRole("checkbox", { name: "仅显示已归档持仓" }));
    expect(await screen.findByText("没有已归档持仓")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加第一个持仓" })).not.toBeInTheDocument();
  });

  it("opens a functional create workflow and preserves decimal strings", async () => {
    const user = userEvent.setup();
    let created = false;
    let body: unknown;
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json(created ? [holdingFixture] : [])),
      http.post("/api/holdings", async ({ request }) => {
        body = await request.json();
        created = true;
        return HttpResponse.json(holdingFixture, { status: 201 });
      }),
    ] });

    await user.click(await screen.findByRole("button", { name: "添加第一个持仓" }));
    expect(screen.getByRole("dialog", { name: "添加持仓" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "创建持仓" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请完整填写标的代码、名称、市场和账户");
    expect(body).toBeUndefined();
    await user.type(screen.getByRole("textbox", { name: "标的代码" }), "SPY");
    await user.type(screen.getByRole("textbox", { name: "标的名称" }), "SPDR S&P 500 ETF Trust");
    await user.type(screen.getByRole("textbox", { name: "上市市场" }), "US");
    await user.type(screen.getByRole("textbox", { name: "账户名称" }), "长期账户");
    await user.click(screen.getByRole("button", { name: "创建持仓" }));

    await waitFor(() => expect(body).toBeDefined());
    expect(body).toMatchObject({
      asset_class_id: assetClassFixtures[0].id,
      symbol: "SPY",
      quantity: "0",
      average_cost_price: "0",
      cost_fx_to_cny: "1",
      baseline_fx_to_cny: "1",
      lot_size: "1",
    });
    expect(await screen.findByText("SPY")).toBeInTheDocument();
  });
});
