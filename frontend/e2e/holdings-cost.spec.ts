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
