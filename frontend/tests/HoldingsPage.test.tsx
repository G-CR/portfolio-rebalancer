import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HoldingsPage } from "../src/pages/HoldingsPage";
import { assetClassFixtures, holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

describe("HoldingsPage", () => {
  it("renders one scannable table, icon actions, and an archived filter", async () => {
    const user = userEvent.setup();
    const archived = { ...holdingFixture, id: "20000000-0000-4000-8000-000000000002", symbol: "VOO", is_active: false };
    renderWithProviders(<HoldingsPage />, { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture, archived])),
    ] });

    expect(await screen.findAllByRole("table")).toHaveLength(1);
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.queryByText("VOO")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "追加买入 SPY" })).toHaveAttribute("title", "追加买入");
    expect(screen.getByRole("button", { name: "更多 SPY 操作" })).toHaveAttribute("title", "更多操作");

    await user.click(screen.getByRole("checkbox", { name: "显示已归档持仓" }));
    expect(screen.getByText("VOO")).toBeInTheDocument();
  });
});
