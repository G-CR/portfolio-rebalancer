import { expect, test } from "@playwright/test";

import { seedPortfolio } from "./fixtures/portfolio";

test("dashboard matches calibration desk at supported widths", async ({ page }) => {
  await seedPortfolio(page, "balanced");
  for (const viewport of [
    { width: 1440, height: 900, name: "desktop" },
    { width: 1024, height: 768, name: "compact" },
    { width: 390, height: 844, name: "mobile" },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "保持现状" })).toBeVisible();
    await expect(page).toHaveScreenshot(`dashboard-${viewport.name}.png`, { animations: "disabled", maxDiffPixelRatio: 0.01, fullPage: true });
  }
});

test("empty portfolio keeps the asset configuration entry point", async ({ page }) => {
  await seedPortfolio(page, "empty");
  await page.goto("/");
  await expect(page.getByText("开始建立组合")).toBeVisible();
  await page.getByRole("link", { name: "资产配置" }).click();
  await expect(page.getByRole("heading", { name: "资产配置", level: 1 })).toBeVisible();
});
