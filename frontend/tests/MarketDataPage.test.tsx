import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import axe from "axe-core";
import { useLocation } from "react-router-dom";

import { OverrideDrawer } from "../src/features/marketData/OverrideDrawer";
import { MarketDataPage } from "../src/pages/MarketDataPage";
import { generalSettingsFixture, marketDataCollectionFixture, providerSettingsFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function pageHandlers() {
  return [
    http.get("/api/market-data", () => HttpResponse.json(marketDataCollectionFixture)),
    http.get("/api/settings/providers", () => HttpResponse.json(providerSettingsFixture)),
    http.get("/api/settings/general", () => HttpResponse.json(generalSettingsFixture)),
    http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)),
  ];
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
}

it("keeps the last value visible when a source failed", async () => {
  renderWithProviders(<MarketDataPage />, { handlers: pageHandlers() });

  const row = await screen.findByRole("row", { name: /SPY/ });
  expect(within(row).getByText("651.28")).toBeInTheDocument();
  expect(within(row).getByText("数据已过期")).toBeInTheDocument();
  expect(within(row).getByText("Yahoo 请求超时，当前使用 07\/10 收盘值")).toBeInTheDocument();
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
          ...providerSettingsFixture[2],
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
