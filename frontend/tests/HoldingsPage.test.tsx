import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HoldingsPage } from "../src/pages/HoldingsPage";
import { holdingsQueryKey } from "../src/features/holdings/api";
import { assetClassFixtures, holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

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

  it("keeps an accessible add command available when holdings already exist", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
    ] });

    await screen.findByText("SPY");
    await user.click(screen.getByRole("button", { name: "添加持仓" }));
    expect(screen.getByRole("dialog", { name: "添加持仓" })).toBeInTheDocument();
  });

  it("routes delayed filter responses to separate caches without replacing the active view", async () => {
    const user = userEvent.setup();
    const archivedResponse = deferred<Response>();
    const archived = { ...holdingFixture, id: "20000000-0000-4000-8000-000000000002", symbol: "VOO", is_active: false };
    const requests: string[] = [];
    const { queryClient } = renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", ({ request }) => {
        requests.push(request.url);
        if (request.url.includes("include_archived=true")) return archivedResponse.promise;
        return HttpResponse.json([holdingFixture]);
      }),
    ] });
    await screen.findByText("SPY");
    const filter = screen.getByRole("checkbox", { name: "仅显示已归档持仓" });
    await user.click(filter);
    expect(screen.getByRole("status")).toHaveTextContent("正在载入已归档持仓");
    await user.click(filter);
    expect(await screen.findByText("SPY")).toBeInTheDocument();

    archivedResponse.resolve(HttpResponse.json([holdingFixture, archived]));
    await waitFor(() => expect(requests.filter((url) => url.includes("include_archived=true"))).toHaveLength(1));
    await waitFor(() => expect(queryClient.getQueryData(holdingsQueryKey(true))).toEqual([holdingFixture, archived]));
    expect(queryClient.getQueryData(holdingsQueryKey(false))).toEqual([holdingFixture]);
    expect(screen.queryByText("VOO")).not.toBeInTheDocument();
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
    const { queryClient } = renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json(created ? [holdingFixture] : [])),
      http.post("/api/holdings", async ({ request }) => {
        body = await request.json();
        created = true;
        return HttpResponse.json(holdingFixture, { status: 201 });
      }),
    ] });
    queryClient.setQueryData(holdingsQueryKey(true), []);

    await user.click(await screen.findByRole("button", { name: "添加第一个持仓" }));
    expect(screen.getByRole("dialog", { name: "添加持仓" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "创建持仓" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请完整填写标的代码、名称、市场和账户");
    expect(body).toBeUndefined();
    await user.type(screen.getByRole("textbox", { name: "标的代码" }), "SPY");
    await user.type(screen.getByRole("textbox", { name: "标的名称" }), "SPDR S&P 500 ETF Trust");
    await user.type(screen.getByRole("textbox", { name: "上市市场" }), "US");
    await user.type(screen.getByRole("textbox", { name: "账户名称" }), "长期账户");
    expect(screen.getByRole("combobox", { name: "首选行情来源" })).toHaveValue("");
    await user.selectOptions(screen.getByRole("combobox", { name: "首选行情来源" }), "yahoo");
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
      preferred_data_source: "yahoo",
    });
    expect(await screen.findByText("SPY")).toBeInTheDocument();
    expect(queryClient.getQueryState(holdingsQueryKey(true))?.isInvalidated).toBe(true);
  });

  it("resets the add drawer on close and successful creation while preserving failed input", async () => {
    const user = userEvent.setup();
    let shouldFail = true;
    let created = false;
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json(created ? [holdingFixture] : [])),
      http.post("/api/holdings", () => {
        if (shouldFail) {
          return HttpResponse.json({ detail: { code: "DUPLICATE_HOLDING", message: "该持仓已存在。" } }, { status: 409 });
        }
        created = true;
        return HttpResponse.json(holdingFixture, { status: 201 });
      }),
    ] });

    await user.click(await screen.findByRole("button", { name: "添加第一个持仓" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "所属资产类别" }), assetClassFixtures[1].id);
    await user.type(screen.getByRole("textbox", { name: "标的代码" }), "QQQ");
    await user.type(screen.getByRole("textbox", { name: "标的名称" }), "Nasdaq ETF");
    await user.type(screen.getByRole("textbox", { name: "上市市场" }), "US");
    await user.type(screen.getByRole("textbox", { name: "账户名称" }), "交易账户");
    await user.clear(screen.getByRole("textbox", { name: "初始份额" }));
    await user.type(screen.getByRole("textbox", { name: "初始份额" }), "1.2500");
    await user.click(screen.getByRole("button", { name: "创建持仓" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("该持仓已存在");
    expect(screen.getByRole("textbox", { name: "标的代码" })).toHaveValue("QQQ");
    expect(screen.getByRole("textbox", { name: "初始份额" })).toHaveValue("1.2500");

    await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "添加第一个持仓" }));
    expect(screen.getByRole("textbox", { name: "标的代码" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "初始份额" })).toHaveValue("0");
    expect(screen.getByRole("combobox", { name: "所属资产类别" })).toHaveValue(assetClassFixtures[0].id);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "标的代码" }), "SPY");
    await user.type(screen.getByRole("textbox", { name: "标的名称" }), "SPDR S&P 500 ETF Trust");
    await user.type(screen.getByRole("textbox", { name: "上市市场" }), "US");
    await user.type(screen.getByRole("textbox", { name: "账户名称" }), "长期账户");
    shouldFail = false;
    await user.click(screen.getByRole("button", { name: "创建持仓" }));
    expect(await screen.findByText("SPY")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "添加持仓" }));
    expect(screen.getByRole("textbox", { name: "标的代码" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "初始份额" })).toHaveValue("0");
    expect(screen.getByRole("button", { name: "创建持仓" })).toBeEnabled();
  });

  it("starts a fresh drawer session after closing an in-flight create", async () => {
    const user = userEvent.setup();
    const response = deferred<Response>();
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([])),
      http.post("/api/holdings", () => response.promise),
    ] });

    await user.click(await screen.findByRole("button", { name: "添加第一个持仓" }));
    await user.type(screen.getByRole("textbox", { name: "标的代码" }), "SPY");
    await user.type(screen.getByRole("textbox", { name: "标的名称" }), "SPDR S&P 500 ETF Trust");
    await user.type(screen.getByRole("textbox", { name: "上市市场" }), "US");
    await user.type(screen.getByRole("textbox", { name: "账户名称" }), "长期账户");
    await user.click(screen.getByRole("button", { name: "创建持仓" }));
    expect(screen.getByRole("button", { name: "正在创建" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "添加第一个持仓" }));
    expect(screen.getByRole("button", { name: "创建持仓" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "标的代码" })).toHaveValue("");

    response.resolve(HttpResponse.json(holdingFixture, { status: 201 }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "添加持仓" })).toBeInTheDocument());
  });
});
