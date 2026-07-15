import type { Page } from "@playwright/test";

import { assetClassFixtures, generalSettingsFixture, holdingFixture, marketDataCollectionFixture, portfolioFixture, providerSettingsFixture, rebalanceDefaultsFixture, rebalancePlanFixture, rebalancePreviewFixture } from "../../tests/fixtures";

type SeedPortfolioOptions = {
  holdings?: object[];
  analytics?: object;
  analyticsStatus?: number;
  refreshResult?: object;
  onRefresh?: () => void;
};

export async function seedPortfolio(
  page: Page,
  state: "balanced" | "empty" = "balanced",
  options: SeedPortfolioOptions = {},
) {
  let planStatus = "draft";
  let rebalanceDefaults = { ...rebalanceDefaultsFixture };
  const holdings = options.holdings ?? (state === "empty" ? [] : [holdingFixture]);
  const analytics = options.analytics ?? (state === "empty" ? { ...portfolioFixture, decision: { ...portfolioFixture.decision, status: "setup", title: "开始建立组合", primary_action: "add_holding" }, asset_classes: [], holdings: [] } : portfolioFixture);
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (!path.startsWith("/api/")) return route.continue();
    if (path === "/api/asset-classes") return route.fulfill({ json: assetClassFixtures });
    if (path === "/api/holdings") return route.fulfill({ json: holdings });
    if (path === "/api/analytics/portfolio") return route.fulfill({ status: options.analyticsStatus ?? 200, json: analytics });
    if (path === "/api/market-data/refresh" && route.request().method() === "POST") {
      options.onRefresh?.();
      return route.fulfill({ json: options.refreshResult ?? marketDataCollectionFixture });
    }
    if (path === "/api/market-data") return route.fulfill({ json: marketDataCollectionFixture });
    if (path === "/api/settings/providers") return route.fulfill({ json: providerSettingsFixture });
    if (path === "/api/settings/general") return route.fulfill({ json: generalSettingsFixture });
    if (path === "/api/settings/rebalance-defaults" && route.request().method() === "PUT") {
      rebalanceDefaults = { ...rebalanceDefaults, ...route.request().postDataJSON(), updated_at: new Date().toISOString() };
      return route.fulfill({ json: rebalanceDefaults });
    }
    if (path === "/api/settings/rebalance-defaults") return route.fulfill({ json: rebalanceDefaults });
    if (path === "/api/rebalance/preview") return route.fulfill({ json: rebalancePreviewFixture });
    if (path === "/api/rebalance/plans" && route.request().method() === "POST") return route.fulfill({ status: 201, json: { ...rebalancePlanFixture, status: planStatus } });
    if (path.endsWith("/start")) { planStatus = "in_progress"; return route.fulfill({ json: { ...rebalancePlanFixture, status: planStatus, before_snapshot_id: "snapshot-before" } }); }
    if (path.endsWith("/complete")) { planStatus = "completed"; return route.fulfill({ json: { ...rebalancePlanFixture, status: planStatus, before_snapshot_id: "snapshot-before", after_snapshot_id: "snapshot-after", baseline_reset_at: new Date().toISOString() } }); }
    if (path.includes("/cost-adjustments/") && route.request().method() === "GET") return route.fulfill({ json: { holding_id: holdingFixture.id, holding_version: 1, defaults: null, items: [] } });
    return route.fulfill({ status: 204 });
  });
}
