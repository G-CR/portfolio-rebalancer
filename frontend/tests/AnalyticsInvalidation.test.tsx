import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { createQueryClient } from "../src/app/providers";
import { portfolioAnalyticsKey } from "../src/api/queryKeys";
import { useSaveAssetClasses } from "../src/features/assetClasses/api";
import {
  useArchiveHolding,
  useConfirmAdjustment,
  useCreateHolding,
  useUpdateHolding,
} from "../src/features/holdings/api";
import type { PurchasePayload } from "../src/api/types";
import { assetClassFixtures, holdingFixture, portfolioFixture } from "./fixtures";
import { server } from "./testProviders";

function renderMutationHook<TResult>(hook: () => TResult) {
  const queryClient = createQueryClient();
  queryClient.setQueryData(portfolioAnalyticsKey, portfolioFixture);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, ...renderHook(hook, { wrapper }) };
}

function expectAnalyticsInvalidated(queryClient: ReturnType<typeof createQueryClient>) {
  expect(queryClient.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(true);
}

const createPayload = {
  asset_class_id: holdingFixture.asset_class_id,
  symbol: holdingFixture.symbol,
  name: holdingFixture.name,
  market: holdingFixture.market,
  account_name: holdingFixture.account_name,
  trade_currency: holdingFixture.trade_currency,
  quantity: holdingFixture.quantity,
  average_cost_price: holdingFixture.average_cost_price,
  cost_fx_to_cny: holdingFixture.cost_fx_to_cny,
  baseline_fx_to_cny: holdingFixture.baseline_fx_to_cny,
  lot_size: holdingFixture.lot_size,
  quantity_precision: holdingFixture.quantity_precision,
  is_rebalance_preferred: holdingFixture.is_rebalance_preferred,
};

const purchasePayload: PurchasePayload = {
  quantity: "1",
  price: "600",
  fx: "7.2",
  fee_currency: "USD",
  commission_rate: null,
  minimum_commission: null,
  per_share_fee: null,
  fixed_fee: null,
  actual_fee: "0",
  save_fee_defaults: false,
  note: null,
};

it("invalidates portfolio analytics after holding create and archive", async () => {
  server.use(
    http.post("/api/holdings", () => HttpResponse.json(holdingFixture, { status: 201 })),
    http.post(`/api/holdings/${holdingFixture.id}/archive`, () => HttpResponse.json({
      ...holdingFixture,
      is_active: false,
    })),
  );

  const created = renderMutationHook(() => useCreateHolding());
  await act(() => created.result.current.mutateAsync(createPayload));
  expectAnalyticsInvalidated(created.queryClient);

  const archived = renderMutationHook(() => useArchiveHolding());
  await act(() => archived.result.current.mutateAsync(holdingFixture.id));
  expectAnalyticsInvalidated(archived.queryClient);
});

it("invalidates portfolio analytics after holding update", async () => {
  server.use(http.patch(`/api/holdings/${holdingFixture.id}`, () => HttpResponse.json({
    ...holdingFixture,
    quantity: "20.0000",
  })));
  const updated = renderMutationHook(() => useUpdateHolding());

  await act(() => updated.result.current.mutateAsync({
    holdingId: holdingFixture.id,
    payload: { quantity: "20.0000" },
  }));

  expectAnalyticsInvalidated(updated.queryClient);
});

it.each(["purchase", "sell", "manual_correction", "restore"] as const)(
  "invalidates portfolio analytics after %s adjustment confirm",
  async (operation) => {
  server.use(http.post(`/api/cost-adjustments/${holdingFixture.id}/confirm`, () =>
    HttpResponse.json({ holding_id: holdingFixture.id, holding_version: 2 })));
  const confirmed = renderMutationHook(() => useConfirmAdjustment<PurchasePayload>(holdingFixture.id));

  await act(() => confirmed.result.current.mutateAsync({
    expected_version: 1,
    operation,
    payload: purchasePayload,
  }));

  expectAnalyticsInvalidated(confirmed.queryClient);
  },
);

it("invalidates portfolio analytics while recovering from a stale adjustment preview", async () => {
  server.use(http.post(`/api/cost-adjustments/${holdingFixture.id}/confirm`, () => HttpResponse.json({
    detail: { code: "STALE_COST_PREVIEW", message: "Holding changed." },
  }, { status: 409 })));
  const stale = renderMutationHook(() => useConfirmAdjustment<PurchasePayload>(holdingFixture.id));

  await act(async () => {
    await expect(stale.result.current.mutateAsync({
      expected_version: 1,
      operation: "purchase",
      payload: purchasePayload,
    })).rejects.toMatchObject({ code: "STALE_COST_PREVIEW" });
  });

  await waitFor(() => expectAnalyticsInvalidated(stale.queryClient));
});

it("invalidates portfolio analytics after asset-class changes", async () => {
  server.use(http.put("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)));
  const saved = renderMutationHook(() => useSaveAssetClasses());

  await act(() => saved.result.current.mutateAsync([...assetClassFixtures]));

  expectAnalyticsInvalidated(saved.queryClient);
});
