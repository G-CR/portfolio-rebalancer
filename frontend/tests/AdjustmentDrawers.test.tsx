import { http, HttpResponse } from "msw";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdjustmentHistoryDrawer } from "../src/features/holdings/AdjustmentHistoryDrawer";
import { CorrectionDrawer } from "../src/features/holdings/CorrectionDrawer";
import { SaleDrawer } from "../src/features/holdings/SaleDrawer";
import { holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

const basis = {
  quantity: "12.0000",
  average_cost_price: "510.25",
  cost_fx_to_cny: "7.18",
  total_cost_cny: "43963.14",
};

describe("sale, correction, and history drawers", () => {
  it("uses a distinct sale command and never presents realized P&L", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SaleDrawer holding={holdingFixture} open onClose={() => undefined} />, {
      handlers: [
        http.post(`/api/cost-adjustments/${holdingFixture.id}/preview-sell`, () => HttpResponse.json({
          holding_id: holdingFixture.id,
          holding_version: 1,
          operation: "sell",
          before: basis,
          after: { ...basis, quantity: "10.0000", total_cost_cny: "36635.95" },
          fee: null,
          note: "降低仓位",
          adjustment_id: null,
        })),
      ],
    });

    await user.type(screen.getByRole("textbox", { name: "卖出份额" }), "2");
    await user.click(screen.getByRole("button", { name: "预览卖出调整" }));
    expect(await screen.findByRole("button", { name: "确认卖出调整" })).toBeEnabled();
    expect(screen.queryByText(/已实现|realized/i)).not.toBeInTheDocument();
  });

  it("requires a correction note and uses a correction-specific command", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CorrectionDrawer holding={holdingFixture} open onClose={() => undefined} />);

    await user.clear(screen.getByRole("textbox", { name: "修正后份额" }));
    await user.type(screen.getByRole("textbox", { name: "修正后份额" }), "11");
    await user.click(screen.getByRole("button", { name: "预览人工修正" }));
    expect(screen.getByText("请填写修正原因")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认人工修正" })).toBeDisabled();
    expect(screen.queryByText(/已实现|realized/i)).not.toBeInTheDocument();
  });

  it("shows immutable history and restore opens a new correction preview", async () => {
    const user = userEvent.setup();
    const historyItem = {
      id: "50000000-0000-4000-8000-000000000001",
      operation_type: "PURCHASE",
      before: basis,
      after: { ...basis, quantity: "17.0000", total_cost_cny: "62281.12" },
      input_summary: { quantity: "5" },
      note: "定投",
      created_at: "2026-07-14T02:30:00Z",
    };
    renderWithProviders(
      <AdjustmentHistoryDrawer holding={holdingFixture} open onClose={() => undefined} />,
      { handlers: [
        http.get(`/api/cost-adjustments/${holdingFixture.id}`, () => HttpResponse.json({
          holding_id: holdingFixture.id,
          holding_version: 2,
          defaults: null,
          items: [historyItem],
        })),
        http.post(
          `/api/cost-adjustments/${holdingFixture.id}/preview-restore/${historyItem.id}`,
          () => HttpResponse.json({
            holding_id: holdingFixture.id,
            holding_version: 2,
            operation: "restore",
            before: { ...basis, quantity: "9.0000" },
            after: historyItem.after,
            fee: null,
            note: "恢复到此状态",
            adjustment_id: null,
          }),
        ),
      ] },
    );

    const item = await screen.findByRole("article", { name: "追加买入调整" });
    expect(within(item).getByText("2026-07-14 10:30")).toBeInTheDocument();
    expect(within(item).getByText("定投")).toBeInTheDocument();
    expect(within(item).getByText("12.0000")).toBeInTheDocument();
    expect(within(item).getByText("17.0000")).toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: "恢复到此状态" }));

    const restoreDialog = await screen.findByRole("dialog", { name: "恢复 SPY 成本状态" });
    expect(within(restoreDialog).getByText("将新增一条人工修正记录，原历史不会删除。"))
      .toBeInTheDocument();
    expect(within(restoreDialog).getByRole("button", { name: "确认恢复为新修正" })).toBeEnabled();
  });
});
