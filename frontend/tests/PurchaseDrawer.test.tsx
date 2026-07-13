import { http, HttpResponse } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PurchaseDrawer } from "../src/features/holdings/PurchaseDrawer";
import { holdingFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

const context = {
  holding_id: holdingFixture.id,
  holding_version: 1,
  defaults: {
    fee_currency: "USD",
    commission_rate: "0.0005",
    minimum_commission: "1.00",
    per_share_fee: "0.005",
    fixed_fee: "0.30",
  },
  items: [],
};

const preview = {
  holding_id: holdingFixture.id,
  holding_version: 1,
  operation: "purchase",
  before: {
    quantity: "12.0000",
    average_cost_price: "510.25",
    cost_fx_to_cny: "7.18",
    total_cost_cny: "43963.14",
  },
  after: {
    quantity: "17.0000",
    average_cost_price: "551.478529411765",
    cost_fx_to_cny: "7.181846190522",
    total_cost_cny: "67330.78",
  },
  fee: { mode: "actual", currency: "USD", amount: "2.30", amount_cny: "16.53" },
  note: null,
  adjustment_id: null,
};

async function fillTransaction(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole("textbox", { name: "新增份额" }), "5.000000000001");
  expect(screen.getByLabelText(/成交日期/)).toHaveValue("2026-07-14");
  await user.type(screen.getByRole("textbox", { name: "成交价" }), "650.200000000001");
  await user.type(screen.getByRole("textbox", { name: "本次汇率" }), "7.185000000001");
}

describe("PurchaseDrawer", () => {
  it("loads per-holding defaults, uses actual fees, and preserves decimal strings", async () => {
    const user = userEvent.setup();
    const previewBodies: unknown[] = [];
    const confirmBodies: unknown[] = [];
    renderWithProviders(
      <PurchaseDrawer holding={holdingFixture} open onClose={() => undefined} />,
      { handlers: [
        http.get(`/api/cost-adjustments/${holdingFixture.id}`, () => HttpResponse.json(context)),
        http.post(`/api/cost-adjustments/${holdingFixture.id}/preview-purchase`, async ({ request }) => {
          previewBodies.push(await request.json());
          return HttpResponse.json(preview);
        }),
        http.post(`/api/cost-adjustments/${holdingFixture.id}/confirm`, async ({ request }) => {
          confirmBodies.push(await request.json());
          return HttpResponse.json({ ...preview, holding_version: 2 });
        }),
      ] },
    );

    await waitFor(() => expect(screen.getByRole("textbox", { name: "佣金费率" })).toHaveValue("0.0005"));
    await fillTransaction(user);
    await user.click(screen.getByRole("tab", { name: "录入实际费用" }));
    await user.type(screen.getByRole("textbox", { name: "实际费用" }), "2.300000000001");
    await user.click(screen.getByRole("button", { name: "生成成本预览" }));

    const previewRegion = await screen.findByRole("region", { name: "成本预览" });
    expect(within(previewRegion).getByText("17.0000")).toBeInTheDocument();
    expect(screen.getByText("实际费用 2.30 USD")).toBeInTheDocument();
    expect(screen.getByText("份额 × 成本价 × 成本汇率 = 人民币成本")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新 SPY 持仓" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "更新 SPY 持仓" }));
    await waitFor(() => expect(confirmBodies).toHaveLength(1));
    expect(previewBodies[0]).toMatchObject({
      quantity: "5.000000000001",
      price: "650.200000000001",
      fx: "7.185000000001",
      actual_fee: "2.300000000001",
      commission_rate: "0.0005",
      minimum_commission: "1.00",
      per_share_fee: "0.005",
      fixed_fee: "0.30",
    });
    expect(confirmBodies[0]).toMatchObject({
      expected_version: 1,
      operation: "purchase",
      payload: { quantity: "5.000000000001", actual_fee: "2.300000000001" },
    });
  });

  it("uses estimated fee mode and allows saving complete defaults", async () => {
    const user = userEvent.setup();
    let body: Record<string, unknown> | undefined;
    renderWithProviders(
      <PurchaseDrawer holding={holdingFixture} open onClose={() => undefined} />,
      { handlers: [
        http.get(`/api/cost-adjustments/${holdingFixture.id}`, () => HttpResponse.json(context)),
        http.post(`/api/cost-adjustments/${holdingFixture.id}/preview-purchase`, async ({ request }) => {
          body = await request.json() as Record<string, unknown>;
          return HttpResponse.json({
            ...preview,
            fee: { mode: "estimated", currency: "USD", amount: "1.93", amount_cny: "13.87" },
          });
        }),
      ] },
    );

    await screen.findByRole("textbox", { name: "佣金费率" });
    await fillTransaction(user);
    await user.click(screen.getByRole("checkbox", { name: "保存为 SPY 的费用默认值" }));
    await user.click(screen.getByRole("button", { name: "生成成本预览" }));

    expect(await screen.findByText("预估费用 1.93 USD")).toBeInTheDocument();
    expect(body).toMatchObject({ actual_fee: null, save_fee_defaults: true });
  });

  it("invalidates a stale preview after any transaction input changes", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <PurchaseDrawer holding={holdingFixture} open onClose={() => undefined} />,
      { handlers: [
        http.get(`/api/cost-adjustments/${holdingFixture.id}`, () => HttpResponse.json(context)),
        http.post(`/api/cost-adjustments/${holdingFixture.id}/preview-purchase`, () => HttpResponse.json(preview)),
      ] },
    );

    await screen.findByRole("textbox", { name: "佣金费率" });
    await fillTransaction(user);
    await user.click(screen.getByRole("button", { name: "生成成本预览" }));
    expect(await screen.findByRole("button", { name: "更新 SPY 持仓" })).toBeEnabled();

    await user.type(screen.getByRole("textbox", { name: "新增份额" }), "9");
    expect(screen.getByText("输入已变化，请重新生成成本预览")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新 SPY 持仓" })).toBeDisabled();
  });

  it("shows a stale-preview server error and requires a new preview", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <PurchaseDrawer holding={holdingFixture} open onClose={() => undefined} />,
      { handlers: [
        http.get(`/api/cost-adjustments/${holdingFixture.id}`, () => HttpResponse.json(context)),
        http.post(`/api/cost-adjustments/${holdingFixture.id}/preview-purchase`, () => HttpResponse.json(preview)),
        http.post(`/api/cost-adjustments/${holdingFixture.id}/confirm`, () => HttpResponse.json({
          detail: { code: "STALE_COST_PREVIEW", message: "Holding was modified after the preview was generated." },
        }, { status: 409 })),
      ] },
    );

    await screen.findByRole("textbox", { name: "佣金费率" });
    await fillTransaction(user);
    await user.click(screen.getByRole("button", { name: "生成成本预览" }));
    await user.click(await screen.findByRole("button", { name: "更新 SPY 持仓" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("持仓已发生变化，请重新生成预览");
    expect(screen.getByRole("button", { name: "更新 SPY 持仓" })).toBeDisabled();
  });
});
