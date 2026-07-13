import axe from "axe-core";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { portfolioAnalyticsKey } from "../src/api/queryKeys";
import { DashboardPage } from "../src/pages/DashboardPage";
import { PnlPage } from "../src/pages/PnlPage";
import { portfolioFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

it("keeps the portfolio analytics query key exact", () => {
  expect(portfolioAnalyticsKey).toEqual(["portfolio-analytics"]);
});

it.each([
  ["dashboard", <DashboardPage />, "保持现状"],
  ["P&L", <PnlPage />, "盈亏分析"],
])("has no serious axe violations in the %s page", async (_name, page, heading) => {
  renderWithProviders(page, {
    handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(portfolioFixture))],
  });
  await screen.findByRole("heading", { name: heading });
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical"))
    .toEqual([]);
});
