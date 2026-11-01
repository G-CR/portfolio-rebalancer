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

it("hides drift and FX facts for a hold decision", async () => {
  renderWithProviders(<DashboardPage />, {
    handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(portfolioFixture))],
  });

  await screen.findByRole("heading", { name: "保持现状" });

  expect(screen.queryByText("最大偏离")).not.toBeInTheDocument();
  expect(screen.queryByText("汇率贡献")).not.toBeInTheDocument();
});

it("shows facts and its action for a contribute decision", async () => {
  const contributionFixture = {
    ...portfolioFixture,
    decision: {
      ...portfolioFixture.decision,
      status: "contribute" as const,
      title: "新增资金",
      primary_action: "simulate_contribution" as const,
    },
  };
  renderWithProviders(<DashboardPage />, {
    handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(contributionFixture))],
  });

  await screen.findByRole("heading", { name: "新增资金" });

  expect(screen.getByText("最大偏离")).toBeInTheDocument();
  expect(screen.getByText("汇率贡献")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "测算新增资金" })).toHaveAttribute("href", "/rebalance");
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
