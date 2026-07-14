import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { seedPortfolio } from "./fixtures/portfolio";

test("critical pages have no serious accessibility violations", async ({ page }) => {
  await seedPortfolio(page);
  for (const path of ["/", "/holdings", "/rebalance"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
    expect(results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
  }
});

test("reduced motion removes calibration marker transitions", async ({ page }) => {
  await seedPortfolio(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const duration = await page.getByTestId("actual-marker").first().evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(Number.parseFloat(duration)).toBeLessThanOrEqual(0.001);
});
