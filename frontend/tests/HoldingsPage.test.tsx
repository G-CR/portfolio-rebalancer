import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { portfolioAnalyticsKey } from "../src/api/queryKeys";
import type { Holding } from "../src/api/types";
import { marketDataQueryKey } from "../src/features/marketData/api";
import { snapshotsQueryRoot } from "../src/features/snapshots/api";
import { HoldingsPage } from "../src/pages/HoldingsPage";
import {
  costAdjustmentsQueryKey,
  holdingsQueryKey,
  useReplaceHolding,
} from "../src/features/holdings/api";
import { assetClassFixtures, holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function ReplaceHarness({ holding }: { holding: Holding }) {
  const replace = useReplaceHolding();

  return <button onClick={() => void replace.mutateAsync({
    holdingId: holding.id,
    payload: {
      source_version: holding.version,
      symbol: "VOO",
      name: "Vanguard S&P 500 ETF",
      market: "US",
      account_name: holding.account_name,
      trade_currency: "USD",
      quantity: "8",
      average_cost_price: "625.40",
      cost_fx_to_cny: "7.18",
      baseline_fx_to_cny: "7.15",
      lot_size: "1",
      quantity_precision: 0,
      preferred_data_source: "yahoo",
      note: null,
    },
  })}>Replace</button>;
}

describe("HoldingsPage", () => {
  it("opens replacement from an active holding with inherited defaults", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
    ] });

    await user.click(await screen.findByRole("button", { name: "更多 SPY 操作" }));
    await user.click(screen.getByRole("menuitem", { name: "替换标的" }));

    expect(screen.getByRole("dialog", { name: "替换标的 · SPY" })).toBeInTheDocument();
    expect(screen.getByText("SPY → 新标的")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "账户名称" })).toHaveValue(holdingFixture.account_name);
    expect(screen.getByRole("textbox", { name: "上市市场" })).toHaveValue("US");
    expect(screen.getByRole("combobox", { name: "交易币种" })).toHaveValue("USD");
    expect(screen.getByText("原标的将按当前份额全部卖出并归档")).toBeInTheDocument();
    expect(screen.getByText("新标的将创建并成为默认调整标的")).toBeInTheDocument();
    expect(screen.getByText("已有历史快照保持不变")).toBeInTheDocument();
    expect(screen.getByText("本次替换不记录已实现盈亏")).toBeInTheDocument();
  });

  it("does not offer replacement when an active holding has no quantity", async () => {
    const user = userEvent.setup();
    const emptyHolding = { ...holdingFixture, quantity: "0.0000" };
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([emptyHolding])),
    ] });

    await user.click(await screen.findByRole("button", { name: "更多 SPY 操作" }));

    expect(screen.queryByRole("menuitem", { name: "替换标的" })).not.toBeInTheDocument();
  });

  it("locks the replacement drawer while pending and retains input after a server failure", async () => {
    const user = userEvent.setup();
    const response = deferred<Response>();
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.post(`/api/holdings/${holdingFixture.id}/replace`, () => response.promise),
    ] });

    await user.click(await screen.findByRole("button", { name: "更多 SPY 操作" }));
    await user.click(screen.getByRole("menuitem", { name: "替换标的" }));
    await user.type(screen.getByRole("textbox", { name: "目标代码" }), "VOO");
    await user.type(screen.getByRole("textbox", { name: "目标名称" }), "Vanguard S&P 500 ETF");
    await user.click(screen.getByRole("button", { name: "确认替换为 VOO" }));

    expect(screen.getByRole("button", { name: "正在替换" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "关闭工作抽屉" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();

    response.resolve(HttpResponse.json({ detail: {
      code: "HOLDING_ALREADY_EXISTS",
      message: "该账户已存在 VOO。",
    } }, { status: 409 }));

    expect(await screen.findByRole("alert")).toHaveTextContent("该账户已存在 VOO");
    expect(screen.getByRole("textbox", { name: "目标代码" })).toHaveValue("VOO");
    expect(screen.getByRole("textbox", { name: "目标名称" })).toHaveValue("Vanguard S&P 500 ETF");
    expect(screen.getByRole("button", { name: "确认替换为 VOO" })).toBeEnabled();
  });

  it("submits inherited replacement values and shows only the active target on success", async () => {
    const user = userEvent.setup();
    let body: unknown;
    let currentHoldings: Holding[] = [holdingFixture];
    const target: Holding = {
      ...holdingFixture,
      id: "20000000-0000-4000-8000-000000000099",
      symbol: "VOO",
      name: "Vanguard S&P 500 ETF",
      is_rebalance_preferred: true,
      version: 1,
    };
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", ({ request }) => HttpResponse.json(
        request.url.includes("include_archived=true")
          ? currentHoldings
          : currentHoldings.filter((holding) => holding.is_active),
      )),
      http.post(`/api/holdings/${holdingFixture.id}/replace`, async ({ request }) => {
        body = await request.json();
        const source = {
          ...holdingFixture,
          is_active: false,
          is_rebalance_preferred: false,
          version: holdingFixture.version + 1,
        };
        currentHoldings = [source, target];
        return HttpResponse.json({ source, target });
      }),
    ] });

    await user.click(await screen.findByRole("button", { name: "更多 SPY 操作" }));
    await user.click(screen.getByRole("menuitem", { name: "替换标的" }));
    await user.type(screen.getByRole("textbox", { name: "目标代码" }), "voo");
    await user.type(screen.getByRole("textbox", { name: "目标名称" }), "Vanguard S&P 500 ETF");
    await user.clear(screen.getByRole("textbox", { name: "账户名称" }));
    await user.type(screen.getByRole("textbox", { name: "账户名称" }), "  长期账户  ");
    await user.clear(screen.getByRole("textbox", { name: "上市市场" }));
    await user.type(screen.getByRole("textbox", { name: "上市市场" }), " US ");
    await user.type(screen.getByRole("textbox", { name: "替换备注" }), "降低管理费");
    await user.click(screen.getByRole("button", { name: "确认替换为 VOO" }));

    await waitFor(() => expect(body).toEqual({
      source_version: holdingFixture.version,
      symbol: "VOO",
      name: "Vanguard S&P 500 ETF",
      market: " US ",
      account_name: "  长期账户  ",
      trade_currency: holdingFixture.trade_currency,
      quantity: holdingFixture.quantity,
      average_cost_price: holdingFixture.average_cost_price,
      cost_fx_to_cny: holdingFixture.cost_fx_to_cny,
      baseline_fx_to_cny: holdingFixture.baseline_fx_to_cny,
      lot_size: holdingFixture.lot_size,
      quantity_precision: holdingFixture.quantity_precision,
      preferred_data_source: holdingFixture.preferred_data_source,
      note: "降低管理费",
    }));
    expect(await screen.findByRole("status")).toHaveTextContent("VOO 已成为新的默认调整标的。");
    expect(await screen.findByText("VOO")).toBeInTheDocument();
    expect(screen.queryByText("SPY")).not.toBeInTheDocument();
  });

  it("moves focus to the stable success status after the source row unmounts", async () => {
    const user = userEvent.setup();
    let currentHoldings: Holding[] = [holdingFixture];
    const target: Holding = {
      ...holdingFixture,
      id: "20000000-0000-4000-8000-000000000099",
      symbol: "VOO",
      name: "Vanguard S&P 500 ETF",
      is_rebalance_preferred: true,
      version: 1,
    };
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json(currentHoldings.filter((holding) => holding.is_active))),
      http.post(`/api/holdings/${holdingFixture.id}/replace`, () => {
        currentHoldings = [{ ...holdingFixture, is_active: false }, target];
        return HttpResponse.json({ source: currentHoldings[0], target });
      }),
    ] });

    const opener = await screen.findByRole("button", { name: "更多 SPY 操作" });
    await user.click(opener);
    await user.click(screen.getByRole("menuitem", { name: "替换标的" }));
    await user.type(screen.getByRole("textbox", { name: "目标代码" }), "VOO");
    await user.type(screen.getByRole("textbox", { name: "目标名称" }), "Vanguard S&P 500 ETF");
    await user.click(screen.getByRole("button", { name: "确认替换为 VOO" }));

    const status = await screen.findByText("VOO 已成为新的默认调整标的。");
    await waitFor(() => expect(opener).not.toBeInTheDocument());
    expect(status).toHaveFocus();
  });

  it("replaces a holding with decimal string payload and invalidates dependent caches", async () => {
    const user = userEvent.setup();
    let payload: unknown;
    const { queryClient } = renderWithProviders(<ReplaceHarness holding={holdingFixture} />, {
      handlers: [
        http.post(`/api/holdings/${holdingFixture.id}/replace`, async ({ request }) => {
          payload = await request.json();
          return HttpResponse.json({
            source: { ...holdingFixture, is_active: false },
            target: { ...holdingFixture, symbol: "VOO", name: "Vanguard S&P 500 ETF" },
          });
        }),
      ],
    });
    queryClient.setQueryData(holdingsQueryKey(false), [holdingFixture]);
    queryClient.setQueryData(holdingsQueryKey(true), [holdingFixture]);
    queryClient.setQueryData(costAdjustmentsQueryKey(holdingFixture.id), {});
    queryClient.setQueryData(portfolioAnalyticsKey, {});
    queryClient.setQueryData(marketDataQueryKey, {});
    queryClient.setQueryData([...snapshotsQueryRoot, {}], {});

    await user.click(screen.getByRole("button", { name: "Replace" }));

    await waitFor(() => expect(payload).toEqual({
      source_version: holdingFixture.version,
      symbol: "VOO",
      name: "Vanguard S&P 500 ETF",
      market: "US",
      account_name: holdingFixture.account_name,
      trade_currency: "USD",
      quantity: "8",
      average_cost_price: "625.40",
      cost_fx_to_cny: "7.18",
      baseline_fx_to_cny: "7.15",
      lot_size: "1",
      quantity_precision: 0,
      preferred_data_source: "yahoo",
      note: null,
    }));
    await waitFor(() => {
      expect(queryClient.getQueryState(holdingsQueryKey(false))?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(holdingsQueryKey(true))?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(costAdjustmentsQueryKey(holdingFixture.id))?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(marketDataQueryKey)?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState([...snapshotsQueryRoot, {}])?.isInvalidated).toBe(true);
    });
  });

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
