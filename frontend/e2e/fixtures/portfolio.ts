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
  const holdings = [...(options.holdings ?? (state === "empty" ? [] : [holdingFixture]))];
  const initialPreferredSymbolByAssetClass = new Map(
    holdings
      .filter((item: any) => item.is_active && item.is_rebalance_preferred)
      .map((item: any) => [item.asset_class_id, item.symbol]),
  );
  const rebalancePreviewFromHoldings = () => {
    const preferredByOriginalSymbol = new Map(
      holdings
        .filter((item: any) => item.is_active && item.is_rebalance_preferred)
        .map((item: any) => [
          initialPreferredSymbolByAssetClass.get(item.asset_class_id),
          { holdingId: item.id, name: item.name, symbol: item.symbol },
        ]),
    );
    const replaceTradeSymbols = (trades: readonly any[]) => trades.map((trade) => {
      const preferred = preferredByOriginalSymbol.get(trade.symbol);
      return preferred ? { ...trade, symbol: preferred.symbol } : { ...trade };
    });
    return {
      ...rebalancePreviewFixture,
      result: {
        ...rebalancePreviewFixture.result,
        trades: replaceTradeSymbols(rebalancePreviewFixture.result.trades),
      },
      fx_comparison: {
        ...rebalancePreviewFixture.fx_comparison,
        result: {
          ...rebalancePreviewFixture.fx_comparison.result,
          trades: replaceTradeSymbols(rebalancePreviewFixture.fx_comparison.result.trades),
        },
      },
    };
  };
  const analytics = options.analytics ?? (state === "empty" ? { ...portfolioFixture, decision: { ...portfolioFixture.decision, status: "setup", title: "开始建立组合", primary_action: "add_holding" }, asset_classes: [], holdings: [] } : portfolioFixture);
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (!path.startsWith("/api/")) return route.continue();
    if (path === "/api/asset-classes") return route.fulfill({ json: assetClassFixtures });
    if (path === "/api/holdings" && route.request().method() === "GET") {
      const includeArchived = url.searchParams.get("include_archived") === "true";
      return route.fulfill({ json: includeArchived ? holdings : holdings.filter((item: any) => item.is_active) });
    }
    const replacementMatch = path.match(/^\/api\/holdings\/([^/]+)\/replace$/);
    if (replacementMatch && route.request().method() === "POST") {
      const payload = route.request().postDataJSON();
      const sourceId = decodeURIComponent(replacementMatch[1]);
      const sourceIndex = holdings.findIndex((item: any) => item.id === sourceId);
      if (sourceIndex < 0) {
        return route.fulfill({
          status: 404,
          json: { detail: { code: "HOLDING_NOT_FOUND", message: "Active holding was not found." } },
        });
      }
      const source = { ...holdings[sourceIndex] as any, quantity: "0", average_cost_price: "0", cost_fx_to_cny: "0", is_active: false, is_rebalance_preferred: false };
      const target = { ...payload, id: "holding-voo", asset_class_id: source.asset_class_id, is_active: true, is_rebalance_preferred: true, version: 1 };
      holdings.splice(sourceIndex, 1, source, target);
      return route.fulfill({ json: { source, target } });
    }
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
    if (path === "/api/rebalance/preview") return route.fulfill({ json: rebalancePreviewFromHoldings() });
    if (path === "/api/rebalance/plans" && route.request().method() === "POST") {
      const preview = rebalancePreviewFromHoldings();
      const holdingVersions = Object.fromEntries(
        holdings.filter((item: any) => item.is_active).map((item: any) => [item.id, item.version]),
      );
      return route.fulfill({ status: 201, json: { ...rebalancePlanFixture, status: planStatus, holding_versions: holdingVersions, result: preview.result, fx_comparison: preview.fx_comparison } });
    }
    if (path.endsWith("/start")) { planStatus = "in_progress"; return route.fulfill({ json: { ...rebalancePlanFixture, status: planStatus, before_snapshot_id: "snapshot-before" } }); }
    if (path.endsWith("/complete")) { planStatus = "completed"; return route.fulfill({ json: { ...rebalancePlanFixture, status: planStatus, before_snapshot_id: "snapshot-before", after_snapshot_id: "snapshot-after", baseline_reset_at: new Date().toISOString() } }); }
    if (path.includes("/cost-adjustments/") && route.request().method() === "GET") return route.fulfill({ json: { holding_id: holdingFixture.id, holding_version: 1, defaults: null, items: [] } });
    return route.fulfill({ status: 204 });
  });
}
