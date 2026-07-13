import axe from "axe-core";
import { http, HttpResponse } from "msw";
import { waitFor } from "@testing-library/react";

import { AssetClassesPage } from "../src/pages/AssetClassesPage";
import { HoldingsPage } from "../src/pages/HoldingsPage";
import { PurchaseDrawer } from "../src/features/holdings/PurchaseDrawer";
import { assetClassesQueryKey } from "../src/features/assetClasses/api";
import { costAdjustmentsQueryKey, holdingsQueryKey } from "../src/features/holdings/api";
import { assetClassFixtures, holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

const context = {
  holding_id: holdingFixture.id,
  holding_version: 1,
  defaults: null,
  items: [],
};

it("keeps the planned TanStack Query keys exact", () => {
  expect(assetClassesQueryKey).toEqual(["asset-classes"]);
  expect(holdingsQueryKey).toEqual(["holdings"]);
  expect(costAdjustmentsQueryKey(holdingFixture.id)).toEqual([
    "cost-adjustments",
    holdingFixture.id,
  ]);
});

it.each([
  ["asset configuration", <AssetClassesPage />],
  ["holdings table", <HoldingsPage />],
])("has no serious axe violations in the %s page", async (_name, page) => {
  renderWithProviders(page, { handlers: [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
  ] });
  await waitFor(() => expect(document.querySelector("table")).toBeInTheDocument());
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical"))
    .toEqual([]);
});

it("has no serious axe violations in the purchase drawer", async () => {
  renderWithProviders(<PurchaseDrawer holding={holdingFixture} open onClose={() => undefined} />, {
    handlers: [
      http.get(`/api/cost-adjustments/${holdingFixture.id}`, () => HttpResponse.json(context)),
    ],
  });
  await waitFor(() => expect(document.querySelector('[role="dialog"]')).toBeInTheDocument());
  await waitFor(() => expect(document.body).not.toHaveTextContent("正在载入费用默认值..."));
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical"))
    .toEqual([]);
});
