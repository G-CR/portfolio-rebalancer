import { expect, test } from "@playwright/test";

import { seedPortfolio } from "./fixtures/portfolio";

test("cost drawer remains reachable at compact width", async ({ page }) => {
  await seedPortfolio(page);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/holdings");
  await page.getByRole("button", { name: "追加买入 SPY" }).click();
  await expect(page.getByRole("heading", { name: "追加买入 SPY" })).toBeVisible();
  await expect(page.getByRole("button", { name: "更新 SPY 持仓" })).toBeInViewport();
});
