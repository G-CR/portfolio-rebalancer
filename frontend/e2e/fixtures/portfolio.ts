import type { Page } from "@playwright/test";

import type { Holding, HoldingReplacementRequest } from "../../src/api/types";
import { assetClassFixtures, generalSettingsFixture, holdingFixture, holdingReplacementResponseFixture, marketDataCollectionFixture, portfolioFixture, providerSettingsFixture, rebalanceDefaultsFixture, rebalancePlanFixture, rebalancePreviewFixture } from "../../tests/fixtures";

type SeedPortfolioOptions = {
  holdings?: Holding[];
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
  let rebalancePlan: Record<string, unknown> | null = null;
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
    if (path === "/api/decision") return route.fulfill({ json: {
      status: state === "empty" ? "setup" : "normal", title: state === "empty" ? "开始建立组合" : "配置正常",
      reason: "按月复核配置，等待有效日终观察。", classes: [], issues: [], has_manual_data: false,
      latest_valid_date: null, last_checked_at: null, active_plan_id: null,
      review_date: "2026-10-01", review_due: false, last_reviewed_at: null,
    } });
    if (path === "/api/ledger/statistics") return route.fulfill({ json: {
      period: null, currencies: [], reference_pnl_cny: null, incomplete_reasons: [], holdings: [],
    } });
    if (path === "/api/ledger/entries") return route.fulfill({ json: [] });
    if (path === "/api/holdings" && route.request().method() === "GET") {
      const includeArchived = url.searchParams.get("include_archived") === "true";
      return route.fulfill({ json: includeArchived ? holdings : holdings.filter((item: any) => item.is_active) });
    }
    const replacementMatch = path.match(/^\/api\/holdings\/([^/]+)\/replace$/);
    if (replacementMatch && route.request().method() === "POST") {
      const payload = route.request().postDataJSON() as HoldingReplacementRequest;
      const sourceId = decodeURIComponent(replacementMatch[1]);
      const sourceIndex = holdings.findIndex((item: any) => item.id === sourceId);
      const source = holdings[sourceIndex];
      if (!source?.is_active) {
        return route.fulfill({
          status: 404,
          json: { detail: { code: "HOLDING_NOT_FOUND", message: "Active holding was not found." } },
        });
      }
      if (payload.source_version !== source.version) {
        return route.fulfill({
          status: 409,
          json: { detail: { code: "HOLDING_VERSION_CONFLICT", message: "Holding was modified after replacement was opened." } },
        });
      }
      const replacement = holdingReplacementResponseFixture(source, payload);
      for (let index = 0; index < holdings.length; index += 1) {
        const item = holdings[index];
        if (item.id !== source.id && item.asset_class_id === source.asset_class_id && item.is_rebalance_preferred) {
          holdings[index] = { ...item, is_rebalance_preferred: false, version: item.version + 1 };
        }
      }
      holdings.splice(sourceIndex, 1, replacement.source, replacement.target);
      return route.fulfill({ json: replacement });
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
    if (path === "/api/rebalance/plans" && route.request().method() === "GET") {
      return route.fulfill({ json: { items: rebalancePlan ? [rebalancePlan] : [] } });
    }
    if (path === "/api/rebalance/plans" && route.request().method() === "POST") {
      const payload = route.request().postDataJSON();
      const preview = rebalancePreviewFromHoldings();
      const holdingVersions = Object.fromEntries(
        holdings.filter((item: any) => item.is_active).map((item: any) => [item.id, item.version]),
      );
      rebalancePlan = {
        ...rebalancePlanFixture,
        status: planStatus,
        valuation_basis: payload.valuation_basis,
        available_cny: payload.available_cny,
        available_usd: payload.available_usd,
        minimum_trade_cny: null,
        allow_sell: payload.allow_sell ?? rebalanceDefaults.allow_sell,
        allow_fx: payload.allow_fx ?? rebalanceDefaults.allow_fx,
        acknowledge_stale_data: payload.acknowledge_stale_data,
        tolerance: payload.tolerance ?? rebalanceDefaults.tolerance,
        holding_versions: holdingVersions,
        result: preview.result,
        fx_comparison: preview.fx_comparison,
      };
      return route.fulfill({ status: 201, json: rebalancePlan });
    }
    if (path.endsWith("/start")) {
      planStatus = "in_progress";
      rebalancePlan = { ...(rebalancePlan ?? rebalancePlanFixture), status: planStatus, before_snapshot_id: "snapshot-before" };
      return route.fulfill({ json: rebalancePlan });
    }
    if (path.endsWith("/complete")) {
      planStatus = "completed";
      rebalancePlan = { ...(rebalancePlan ?? rebalancePlanFixture), status: planStatus, before_snapshot_id: "snapshot-before", after_snapshot_id: "snapshot-after", baseline_reset_at: new Date().toISOString() };
      return route.fulfill({ json: rebalancePlan });
    }
    if (path.includes("/cost-adjustments/") && route.request().method() === "GET") return route.fulfill({ json: { holding_id: holdingFixture.id, holding_version: 1, defaults: null, items: [] } });
    return route.fulfill({ status: 204 });
  });
}
