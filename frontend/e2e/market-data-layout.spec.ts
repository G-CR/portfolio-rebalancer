import { expect, test } from "@playwright/test";

import { seedPortfolio } from "./fixtures/portfolio";

test("provider controls align and effective-value row rules stay level", async ({ page }) => {
  await seedPortfolio(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/data-sources");

  const provider = page.getByRole("group", { name: "Tushare 设置" });
  const providerCells = provider.locator("[data-provider-cell]");
  await expect(providerCells).toHaveCount(4);
  const providerBottoms = await providerCells.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().bottom),
  );
  expect(Math.max(...providerBottoms) - Math.min(...providerBottoms)).toBeLessThanOrEqual(2);

  const row = page.getByRole("row", { name: /SPY/ });
  const rowCells = row.locator("th, td");
  const rowBottoms = await rowCells.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().bottom),
  );
  expect(Math.max(...rowBottoms) - Math.min(...rowBottoms)).toBeLessThanOrEqual(1);
});
