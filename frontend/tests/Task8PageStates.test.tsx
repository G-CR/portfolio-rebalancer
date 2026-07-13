import { delay, http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssetClassesPage } from "../src/pages/AssetClassesPage";
import { HoldingsPage } from "../src/pages/HoldingsPage";
import { assetClassFixtures, holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

it("keeps a stable asset table skeleton while loading", () => {
  renderWithProviders(<AssetClassesPage />, { handlers: [
    http.get("/api/asset-classes", async () => { await delay("infinite"); }),
    http.get("/api/holdings", async () => { await delay("infinite"); }),
  ] });

  expect(screen.getByRole("status", { name: "正在载入资产配置" })).toBeInTheDocument();
  expect(screen.getAllByTestId("asset-skeleton-row")).toHaveLength(5);
});

it("keeps a stable holdings table skeleton while loading", () => {
  renderWithProviders(<HoldingsPage />, { handlers: [
    http.get("/api/asset-classes", async () => { await delay("infinite"); }),
    http.get("/api/holdings", async () => { await delay("infinite"); }),
  ] });

  expect(screen.getByRole("status", { name: "正在载入持仓与成本" })).toBeInTheDocument();
  expect(screen.getAllByTestId("holding-skeleton-row")).toHaveLength(4);
});

it("retries an actionable holdings load error", async () => {
  const user = userEvent.setup();
  let attempts = 0;
  renderWithProviders(<HoldingsPage />, { handlers: [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => {
      attempts += 1;
      return attempts === 1
        ? HttpResponse.json({ detail: { code: "DB_UNAVAILABLE", message: "Database unavailable." } }, { status: 503 })
        : HttpResponse.json([holdingFixture]);
    }),
  ] });

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Database unavailable.");
  expect(alert).toHaveTextContent("检查本机 API 服务后重试");
  await user.click(screen.getByRole("button", { name: "重试载入持仓" }));
  expect(await screen.findByText("SPY")).toBeInTheDocument();
});

it("retries an actionable asset configuration load error", async () => {
  const user = userEvent.setup();
  let attempts = 0;
  renderWithProviders(<AssetClassesPage />, { handlers: [
    http.get("/api/asset-classes", () => {
      attempts += 1;
      return attempts === 1
        ? HttpResponse.json({ detail: { code: "DB_UNAVAILABLE", message: "Database unavailable." } }, { status: 503 })
        : HttpResponse.json(assetClassFixtures);
    }),
    http.get("/api/holdings", () => HttpResponse.json([])),
  ] });

  expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable.");
  await user.click(screen.getByRole("button", { name: "重试载入资产配置" }));
  expect(await screen.findByRole("heading", { name: "资产配置" })).toBeInTheDocument();
});
