import { expect, test } from "@playwright/test";

import { seedPortfolio } from "./fixtures/portfolio";
import { rebalancePreviewFixture } from "../tests/fixtures";

test("rebalance workflow switches basis and completes baseline lifecycle", async ({ page }) => {
  await seedPortfolio(page);
  await page.route("**/api/rebalance/preview", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rebalancePreviewFixture) });
  });
  await page.goto("/rebalance");
  await expect(page.getByText("配置本次资金与约束后开始测算")).toBeVisible();
  await page.getByRole("textbox", { name: "人民币" }).fill("12500");
  await page.getByRole("checkbox", { name: /允许卖出/ }).uncheck();
  await page.getByRole("radio", { name: "剔汇率口径" }).click();
  await expect(page.getByText("剔汇率模拟")).toBeVisible();
  await page.getByRole("button", { name: "开始测算" }).click();
  await expect(page.getByText("新增资金不足以消除高配")).toBeVisible();
  await page.getByRole("button", { name: "保存方案" }).click();
  await expect(page.getByText("方案已保存，尚未开始")).toBeVisible();
  await page.getByRole("button", { name: "开始本次再平衡" }).click();
  await expect(page.getByText("再平衡进行中")).toBeVisible();
  await page.getByRole("button", { name: "完成再平衡并建立新基准" }).click();
  await expect(page.getByText("本次再平衡已完成，新汇率基准已建立")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("textbox", { name: "人民币" })).toHaveValue("12500");
  await expect(page.getByRole("radio", { name: "剔汇率口径" })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /允许卖出/ })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "开始测算" })).toBeVisible();
  await expect(page.getByText("配置本次资金与约束后开始测算")).toBeVisible();
});
