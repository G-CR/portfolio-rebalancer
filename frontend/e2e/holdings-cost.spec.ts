import { expect, test } from "@playwright/test";

import { seedPortfolio } from "./fixtures/portfolio";
import { holdingFixture } from "../tests/fixtures";

test("cost drawer remains reachable at compact width", async ({ page }) => {
  await seedPortfolio(page);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/holdings");
  await page.getByRole("button", { name: "追加买入 SPY" }).click();
  await expect(page.getByRole("heading", { name: "追加买入 SPY" })).toBeVisible();
  await expect(page.getByRole("button", { name: "更新 SPY 持仓" })).toBeInViewport();
});

test("numeric headings align and the final row menu stays in the viewport", async ({ page }) => {
  const holdings = [
    holdingFixture,
    { ...holdingFixture, id: "20000000-0000-4000-8000-000000000002", symbol: "QQQ", name: "Invesco QQQ Trust", account_name: "成长账户" },
    { ...holdingFixture, id: "20000000-0000-4000-8000-000000000003", symbol: "SPY-B", name: "SPY secondary lot", account_name: "备用账户" },
  ];
  await seedPortfolio(page, "balanced", { holdings });
  await page.setViewportSize({ width: 1440, height: 520 });
  await page.goto("/holdings");

  const table = page.getByRole("region", { name: "持仓与成本表格" });
  const firstRow = table.locator('tbody tr[data-mobile-summary="true"]').first();
  for (const [label, index] of [["份额", 3], ["成本价", 4], ["成本汇率", 5], ["当前价", 6], ["当前汇率", 7], ["市值", 8], ["浮动盈亏", 9]] as const) {
    const headingRight = await page.getByRole("columnheader", { name: label }).evaluate((element) => element.getBoundingClientRect().right);
    const cellRight = await firstRow.locator("td").nth(index).evaluate((element) => element.getBoundingClientRect().right);
    expect(Math.abs(headingRight - cellRight)).toBeLessThanOrEqual(1);
  }

  const finalTrigger = page.getByRole("button", { name: "更多 SPY-B 操作" });
  await finalTrigger.click();
  await expect(page.getByRole("menu")).toBeInViewport();
  await expect(page.getByRole("menuitem", { name: "调整历史" })).toBeInViewport();
});

test("the portal menu follows horizontal scrolling and restores keyboard focus", async ({ page }) => {
  await seedPortfolio(page);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/holdings");

  const table = page.getByRole("region", { name: "持仓与成本表格" });
  await table.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  const trigger = page.getByRole("button", { name: "更多 SPY 操作" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const triggerRight = await trigger.evaluate((element) => element.getBoundingClientRect().right);
  const menuRight = await page.getByRole("menu").evaluate((element) => element.getBoundingClientRect().right);
  expect(Math.abs(triggerRight - menuRight)).toBeLessThanOrEqual(1);
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("failed automatic refresh exposes recovery actions", async ({ page }) => {
  let refreshCalls = 0;
  await seedPortfolio(page, "balanced", {
    analyticsStatus: 409,
    analytics: { detail: {
      code: "PORTFOLIO_DATA_INCOMPLETE",
      message: "Required portfolio market data is incomplete.",
      items: [{ holding_id: holdingFixture.id, symbol: "SPY", input: "price", key: "price:SPY", status: "missing", value: null }],
    } },
    refreshResult: { items: [{
      key: "price:SPY", data_type: "price", symbol: "SPY", currency: "USD",
      effective_value: null, source: "yahoo", status: "failed", market_time: null,
      fetched_at: "2026-07-15T01:00:00Z",
      error_summary: "yahoo: provider_request_failed; alpha_vantage: provider_not_configured",
      note: null,
    }], diagnostics: [] },
    onRefresh: () => { refreshCalls += 1; },
  });
  const refreshResponse = page.waitForResponse((response) => response.url().endsWith("/api/market-data/refresh"));
  await page.goto("/holdings");
  const response = await refreshResponse;
  expect(await response.json()).toMatchObject({ items: [{ key: "price:SPY", status: "failed" }] });
  expect(refreshCalls).toBe(1);

  await expect(page.getByRole("alert")).toContainText("Yahoo 请求失败");
  await expect(page.getByRole("button", { name: "立即重试" })).toBeVisible();
  await expect(page.getByRole("button", { name: "手动录入" })).toBeVisible();
  expect(refreshCalls).toBe(1);
});

test("mobile details retain the action menu entry", async ({ page }) => {
  await seedPortfolio(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/holdings");

  await page.getByRole("button", { name: "查看 SPY 持仓详情" }).click();
  await expect(page.getByRole("button", { name: "更多 SPY 操作" })).toBeVisible();
});

test("replacement fixture rejects an unknown exact source id", async ({ page }) => {
  await seedPortfolio(page);
  await page.goto("/holdings");

  const status = await page.evaluate(async () => {
    const response = await fetch("/api/holdings/not-the-source/replace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: "WRONG" }),
    });
    return response.status;
  });

  expect(status).toBe(404);
  await expect(page.getByText("SPY", { exact: true })).toBeVisible();
});

test("replacement fixture enforces production replacement invariants", async ({ page }) => {
  const source = { ...holdingFixture, is_rebalance_preferred: false };
  const priorPreferred = {
    ...holdingFixture,
    id: "20000000-0000-4000-8000-000000000002",
    symbol: "IVV",
    name: "iShares Core S&P 500 ETF",
    is_rebalance_preferred: true,
  };
  await seedPortfolio(page, "balanced", { holdings: [source, priorPreferred] });
  await page.goto("/holdings");

  const result = await page.evaluate(async ({ sourceId, sourceVersion }) => {
    const payload = {
      source_version: sourceVersion,
      symbol: "VOO",
      name: "Vanguard S&P 500 ETF",
      market: "US",
      account_name: "长期账户",
      trade_currency: "USD",
      quantity: "8",
      average_cost_price: "625.40",
      cost_fx_to_cny: "7.18",
      baseline_fx_to_cny: "7.15",
      lot_size: "1",
      quantity_precision: 4,
      preferred_data_source: null,
      note: null,
    };
    const post = (body: object) => fetch(`/api/holdings/${sourceId}/replace`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const stale = await post({ ...payload, source_version: sourceVersion - 1 });
    const replaced = await post(payload);
    const replacement = await replaced.json();
    const archivedRetry = await post(payload);
    const holdingsResponse = await fetch("/api/holdings?include_archived=true");
    const plansResponse = await fetch("/api/rebalance/plans");
    return {
      staleStatus: stale.status,
      replacedStatus: replaced.status,
      replacement,
      archivedRetryStatus: archivedRetry.status,
      holdings: await holdingsResponse.json(),
      plansStatus: plansResponse.status,
      plans: await plansResponse.json(),
    };
  }, { sourceId: source.id, sourceVersion: source.version });

  expect(result.staleStatus).toBe(409);
  expect(result.replacedStatus).toBe(200);
  expect(result.replacement.source).toMatchObject({
    id: source.id,
    quantity: "0.0000",
    average_cost_price: source.average_cost_price,
    cost_fx_to_cny: source.cost_fx_to_cny,
    is_active: false,
    is_rebalance_preferred: false,
    version: source.version + 1,
  });
  expect(result.archivedRetryStatus).toBe(404);
  expect(result.holdings.find((item: typeof priorPreferred) => item.id === priorPreferred.id)).toMatchObject({
    is_rebalance_preferred: false,
  });
  expect(result.plansStatus).toBe(200);
  expect(result.plans).toEqual({ items: [] });
});

test("fully replaces SPY with VOO and retains archived SPY", async ({ page }) => {
  await seedPortfolio(page, "balanced");
  await page.goto("/holdings");
  await page.getByRole("button", { name: "更多 SPY 操作" }).click();
  await page.getByRole("menuitem", { name: "替换标的" }).click();
  await page.getByRole("textbox", { name: "目标代码" }).fill("VOO");
  await page.getByRole("textbox", { name: "目标名称" }).fill("Vanguard S&P 500 ETF");
  await page.getByRole("textbox", { name: "目标份额" }).fill("8");
  await page.getByRole("textbox", { name: "平均成本价" }).fill("625.40");
  await page.getByRole("button", { name: "确认替换为 VOO" }).click();
  const table = page.getByRole("region", { name: "持仓与成本表格" });
  await expect(table.getByText("VOO", { exact: true })).toBeVisible();
  await expect(table.getByText("SPY", { exact: true })).not.toBeVisible();
  await page.getByRole("checkbox", { name: "仅显示已归档持仓" }).check();
  await expect(table.getByText("SPY", { exact: true })).toBeVisible();
  const archivedSpyRow = table.locator('tbody tr[data-mobile-summary="true"][data-archived="true"]', { hasText: "SPY" });
  await expect(archivedSpyRow).toHaveCount(1);
  await expect(archivedSpyRow).toContainText("已归档");
  await expect(archivedSpyRow.locator("td").nth(3)).toHaveText("0.0000");
  await expect(table.getByText("VOO", { exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "再平衡" }).click();
  await page.getByRole("button", { name: "开始测算" }).click();
  const suggestion = page.getByRole("row", { name: "VOO 卖出" });
  await expect(suggestion).toBeVisible();
  await expect(suggestion).toContainText("Vanguard S&P 500 ETF");
});
