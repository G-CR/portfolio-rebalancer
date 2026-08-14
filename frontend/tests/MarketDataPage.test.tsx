import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import axe from "axe-core";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { portfolioAnalyticsKey } from "../src/api/queryKeys";
import { createQueryClient } from "../src/app/providers";
import { holdingsQueryRoot } from "../src/features/holdings/api";
import { OverrideDrawer } from "../src/features/marketData/OverrideDrawer";
import { marketDataQueryKey, useRefreshMarketData } from "../src/features/marketData/api";
import { snapshotsQueryRoot } from "../src/features/snapshots/api";
import { MarketDataPage } from "../src/pages/MarketDataPage";
import { emailSettingsFixture, generalSettingsFixture, marketDataCollectionFixture, providerSettingsFixture } from "./fixtures";
import { renderWithProviders, server } from "./testProviders";

function pageHandlers() {
  return [
    http.get("/api/market-data", () => HttpResponse.json(marketDataCollectionFixture)),
    http.get("/api/settings/providers", () => HttpResponse.json(providerSettingsFixture)),
    http.get("/api/settings/general", () => HttpResponse.json(generalSettingsFixture)),
    http.get("/api/settings/email", () => HttpResponse.json(emailSettingsFixture)),
    http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)),
  ];
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
}

it("updates market data and invalidates dependent portfolio queries after refresh", async () => {
  server.use(http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)));
  const queryClient = createQueryClient();
  queryClient.setQueryData(portfolioAnalyticsKey, { portfolio: "cached" });
  queryClient.setQueryData([...holdingsQueryRoot, { includeArchived: false }], ["cached"]);
  queryClient.setQueryData([...snapshotsQueryRoot, { page: 1 }], { items: [] });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRefreshMarketData(), { wrapper });

  await act(() => result.current.mutateAsync());

  expect(queryClient.getQueryData(marketDataQueryKey)).toEqual(marketDataCollectionFixture);
  expect(queryClient.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState([...holdingsQueryRoot, { includeArchived: false }])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState([...snapshotsQueryRoot, { page: 1 }])?.isInvalidated).toBe(true);
});

it("does not invalidate analytics when refreshed market data is still incomplete", async () => {
  const incompleteRefresh = {
    ...marketDataCollectionFixture,
    items: marketDataCollectionFixture.items.map((item, index) => index === 0
      ? { ...item, effective_value: null, status: "failed" as const }
      : item),
  };
  server.use(http.post("/api/market-data/refresh", () => HttpResponse.json(incompleteRefresh)));
  const queryClient = createQueryClient();
  queryClient.setQueryData(portfolioAnalyticsKey, { portfolio: "cached" });
  queryClient.setQueryData([...holdingsQueryRoot, { includeArchived: false }], ["cached"]);
  queryClient.setQueryData([...snapshotsQueryRoot, { page: 1 }], { items: [] });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRefreshMarketData(), { wrapper });

  await act(() => result.current.mutateAsync());

  expect(queryClient.getQueryData(marketDataQueryKey)).toEqual(incompleteRefresh);
  expect(queryClient.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(false);
  expect(queryClient.getQueryState([...holdingsQueryRoot, { includeArchived: false }])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState([...snapshotsQueryRoot, { page: 1 }])?.isInvalidated).toBe(true);
});

it("keeps the last value visible when a source failed", async () => {
  renderWithProviders(<MarketDataPage />, { handlers: pageHandlers() });

  const row = await screen.findByRole("row", { name: /SPY/ });
  expect(within(row).getByText("651.28")).toBeInTheDocument();
  expect(within(row).getByText("数据已过期")).toBeInTheDocument();
  expect(within(row).getByText("Yahoo 请求超时，当前使用 07\/10 收盘值")).toBeInTheDocument();
});

it("uses consistent credential and status columns for every provider", async () => {
  renderWithProviders(<MarketDataPage />, { handlers: pageHandlers() });

  for (const name of ["AKShare", "Tushare"]) {
    const provider = await screen.findByRole("group", { name: `${name} 设置` });
    expect(within(provider).getByText("凭据")).toBeInTheDocument();
    expect(within(provider).getByText("状态")).toBeInTheDocument();
  }
});

it("requires a note for a manual override", async () => {
  renderWithProviders(<OverrideDrawer marketKey="fx:USD/CNY" symbol="USD/CNY" open onClose={() => undefined} />);
  const user = userEvent.setup();
  const dialog = screen.getByRole("dialog");

  await user.type(within(dialog).getByLabelText("手动值"), "7.18");

  expect(within(dialog).getByRole("button", { name: "启用手动汇率" })).toBeDisabled();
});

it("saves provider keys without rendering plaintext after the request", async () => {
  let receivedKey = "";
  renderWithProviders(<MarketDataPage />, {
    handlers: [
      ...pageHandlers(),
      http.put("/api/settings/providers/tushare", async ({ request }) => {
        const payload = await request.json() as { api_key: string };
        receivedKey = payload.api_key;
        return HttpResponse.json({
          ...providerSettingsFixture.find((item) => item.provider === "tushare")!,
          enabled: true,
          key_status: "configured",
          masked_key: "****oken",
        });
      }),
    ],
  });
  const user = userEvent.setup();

  const provider = await screen.findByRole("group", { name: "Tushare 设置" });
  await user.type(within(provider).getByLabelText("API 密钥"), "tushare-secret-token");
  await user.click(within(provider).getByRole("button", { name: "保存 Tushare" }));

  expect(await within(provider).findByText("****oken")).toBeInTheDocument();
  expect(receivedKey).toBe("tushare-secret-token");
  expect(screen.queryByDisplayValue("tushare-secret-token")).not.toBeInTheDocument();
});

it("opens the correct override drawer from the status table", async () => {
  renderWithProviders(<MarketDataPage />, { handlers: pageHandlers() });
  const user = userEvent.setup();

  const row = await screen.findByRole("row", { name: /USD\/CNY/ });
  await user.click(within(row).getByRole("button", { name: "覆盖 USD/CNY" }));

  expect(screen.getByRole("heading", { name: "手动覆盖 · USD/CNY" })).toBeInTheDocument();
});

it("opens and clears a deep-linked override", async () => {
  renderWithProviders(<><MarketDataPage /><LocationProbe /></>, {
    route: "/data-sources?override=price%3ASPY",
    handlers: pageHandlers(),
  });
  const user = userEvent.setup();

  const dialog = await screen.findByRole("dialog", { name: "手动覆盖 · SPY" });
  expect(screen.getByTestId("location-search")).toHaveTextContent("override=price%3ASPY");

  await user.click(within(dialog).getByRole("button", { name: "取消" }));

  expect(screen.queryByRole("dialog", { name: "手动覆盖 · SPY" })).not.toBeInTheDocument();
  expect(screen.getByTestId("location-search")).toHaveTextContent("");
});

it("has no serious accessibility violations", async () => {
  renderWithProviders(<MarketDataPage />, { handlers: pageHandlers() });
  await screen.findByRole("group", { name: "Tushare 设置" });

  const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical")).toEqual([]);
});
