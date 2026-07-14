import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { createQueryClient } from "../src/app/providers";
import { useCreateManualSnapshot, snapshotsQueryRoot } from "../src/features/snapshots/api";
import { SnapshotsPage } from "../src/pages/SnapshotsPage";
import { assetClassFixtures } from "./fixtures";
import { renderWithProviders, server } from "./testProviders";

const summaries = [
  {
    id: "30000000-0000-4000-8000-000000000004",
    snapshot_type: "manual",
    local_date: "2026-07-14",
    captured_at: "2026-07-14T02:00:00Z",
    note: "季度复核",
    data_complete: true,
    has_stale_data: false,
    has_manual_data: true,
    total_market_value_cny: "9007199254740993.120000000000",
    total_fx_neutral_value_cny: "9007199254740000.120000000000",
    total_cost_value_cny: "8000000000000000.000000000000",
    total_unrealized_pnl_cny: "1007199254740993.120000000000",
    total_price_effect_cny: "1000000000000000.000000000000",
    total_fx_effect_cny: "7199254740993.120000000000",
    actual_weight: "0.300000000000",
    fx_neutral_weight: "0.295000000000",
    target_weight: "0.300000000000",
  },
  {
    id: "30000000-0000-4000-8000-000000000003",
    snapshot_type: "rebalance_after",
    local_date: "2026-07-13",
    captured_at: "2026-07-13T02:10:00Z",
    note: "完成 2026 Q3 再平衡",
    data_complete: true,
    has_stale_data: false,
    has_manual_data: false,
    total_market_value_cny: "684220.000000000000",
    total_fx_neutral_value_cny: "680000.000000000000",
    total_cost_value_cny: "620000.000000000000",
    total_unrealized_pnl_cny: "64220.000000000000",
    total_price_effect_cny: "60000.000000000000",
    total_fx_effect_cny: "4220.000000000000",
    actual_weight: "0.300000000000",
    fx_neutral_weight: "0.298000000000",
    target_weight: "0.300000000000",
  },
  {
    id: "30000000-0000-4000-8000-000000000002",
    snapshot_type: "rebalance_before",
    local_date: "2026-07-13",
    captured_at: "2026-07-13T01:40:00Z",
    note: "开始 2026 Q3 再平衡",
    data_complete: true,
    has_stale_data: false,
    has_manual_data: false,
    total_market_value_cny: "680000.000000000000",
    total_fx_neutral_value_cny: "675000.000000000000",
    total_cost_value_cny: "620000.000000000000",
    total_unrealized_pnl_cny: "60000.000000000000",
    total_price_effect_cny: "55000.000000000000",
    total_fx_effect_cny: "5000.000000000000",
    actual_weight: "0.327000000000",
    fx_neutral_weight: "0.320000000000",
    target_weight: "0.300000000000",
  },
  {
    id: "30000000-0000-4000-8000-000000000001",
    snapshot_type: "daily",
    local_date: "2026-07-12",
    captured_at: "2026-07-12T00:05:00Z",
    note: null,
    data_complete: true,
    has_stale_data: false,
    has_manual_data: false,
    total_market_value_cny: "670000.000000000000",
    total_fx_neutral_value_cny: "666000.000000000000",
    total_cost_value_cny: "620000.000000000000",
    total_unrealized_pnl_cny: "50000.000000000000",
    total_price_effect_cny: "46000.000000000000",
    total_fx_effect_cny: "4000.000000000000",
    actual_weight: "0.325000000000",
    fx_neutral_weight: "0.319000000000",
    target_weight: "0.300000000000",
  },
] as const;

const collection = { items: summaries, page: 1, page_size: 25, total: summaries.length };
const detail = {
  ...summaries[0],
  items: [{
    id: "31000000-0000-4000-8000-000000000001",
    holding_id: "20000000-0000-4000-8000-000000000001",
    asset_class_name: "海外股票",
    holding_name: "SPDR S&P 500 ETF Trust",
    symbol: "SPY",
    account_name: "USD account",
    trade_currency: "USD",
    quantity: "3.000000000000",
    market_price: "590.420000000000",
    current_fx_to_cny: "7.200000000000",
    baseline_fx_to_cny: "6.800000000000",
    average_cost_price: "510.250000000000",
    cost_fx_to_cny: "7.180000000000",
    target_weight: "0.300000000000",
    market_value_cny: "127530.720000000000",
    fx_neutral_value_cny: "120445.680000000000",
    cost_value_cny: "109907.850000000000",
    unrealized_pnl_amount_cny: "17622.870000000000",
    unrealized_pnl_rate: "0.160342000000",
    price_effect_cny: "16800.000000000000",
    fx_effect_cny: "822.870000000000",
    actual_weight: "0.186389000000",
    fx_neutral_weight: "0.177126000000",
    price_status: "valid",
    fx_status: "manual",
  }],
};

function manySummaries(count: number) {
  return Array.from({ length: count }, (_, index) => {
    const capturedAt = new Date(Date.UTC(2026, 6, 14, 2, 0) - index * 60_000);
    const snapshotType = index === 120
      ? "rebalance_after"
      : index === 121 ? "rebalance_before" : "manual";
    return {
      ...summaries[0],
      id: `snapshot-${index + 1}`,
      snapshot_type: snapshotType,
      local_date: capturedAt.toISOString().slice(0, 10),
      captured_at: capturedAt.toISOString(),
      note: snapshotType === "rebalance_before"
        ? "第二页再平衡前"
        : snapshotType === "rebalance_after" ? "第二页再平衡后" : `事件 ${index + 1}`,
      has_manual_data: false,
      total_market_value_cny: `${100000 + index}.000000000000`,
    };
  });
}

function handlers(onList?: (url: URL) => void) {
  return [
    http.get("/api/snapshots", ({ request }) => {
      onList?.(new URL(request.url));
      return HttpResponse.json(collection);
    }),
    http.get(`/api/snapshots/${detail.id}`, () => HttpResponse.json(detail)),
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
  ];
}

describe("SnapshotsPage", () => {
  it("presents snapshot metrics accurately and never calls them portfolio return", async () => {
    renderWithProviders(<SnapshotsPage />, { handlers: handlers() });

    expect(await screen.findByRole("heading", { name: "历史快照" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "核心池市值" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "人民币成本" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "浮动盈亏" })).toBeInTheDocument();
    expect(screen.queryByText("组合收益率")).not.toBeInTheDocument();
    expect(screen.getByText("快照时点状态，不代表精确组合回报")).toBeInTheDocument();
  });

  it("pairs before and after rebalance events in chart and table", async () => {
    renderWithProviders(<SnapshotsPage />, { handlers: handlers() });

    expect(await screen.findAllByText("再平衡前")).not.toHaveLength(0);
    expect(screen.getAllByText("再平衡后")).not.toHaveLength(0);
    expect(screen.getByLabelText("再平衡事件配对")).toHaveTextContent("开始 2026 Q3 再平衡");
    expect(screen.getByLabelText("再平衡事件配对")).toHaveTextContent("完成 2026 Q3 再平衡");
  });

  it("applies time, type, and asset-class filters to the query", async () => {
    const user = userEvent.setup();
    const requests: URL[] = [];
    renderWithProviders(<SnapshotsPage />, { handlers: handlers((url) => requests.push(url)) });
    await screen.findByRole("heading", { name: "历史快照" });

    await user.click(screen.getByRole("button", { name: "全部时间" }));
    await user.selectOptions(screen.getByLabelText("快照类型"), "manual");
    await user.selectOptions(screen.getByLabelText("资产类别"), "标普 500");

    await waitFor(() => {
      const latest = requests.at(-1);
      expect(latest?.searchParams.get("snapshot_type")).toBe("manual");
      expect(latest?.searchParams.get("asset_class")).toBe("标普 500");
      expect(latest?.searchParams.has("from_date")).toBe(false);
    });
  });

  it("opens responsive detail content and preserves exact Decimal display", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SnapshotsPage />, { handlers: handlers() });

    const row = await screen.findByRole("row", { name: /季度复核/ });
    await user.click(within(row).getByRole("button", { name: "查看详情" }));

    const dialog = await screen.findByRole("dialog", { name: "快照详情" });
    expect(dialog).toHaveTextContent("SPY");
    expect(dialog).toHaveTextContent("590.420000000000");
    expect(dialog).toHaveTextContent("7.200000000000");
    expect(dialog).toHaveTextContent("0.186389000000");
  });

  it("shows stable empty and error states", async () => {
    const empty = renderWithProviders(<SnapshotsPage />, { handlers: [
      http.get("/api/snapshots", () => HttpResponse.json({ items: [], page: 1, page_size: 25, total: 0 })),
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    ] });
    expect(await screen.findByText("还没有历史快照")).toBeInTheDocument();
    empty.unmount();

    renderWithProviders(<SnapshotsPage />, { handlers: [
      http.get("/api/snapshots", () => HttpResponse.json({ detail: { code: "SNAPSHOT_STORAGE_ERROR", message: "Snapshot storage operation failed." } }, { status: 500 })),
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    ] });
    expect(await screen.findByRole("alert")).toHaveTextContent("历史快照无法载入");
    expect(screen.getByRole("button", { name: "重试载入历史" })).toBeInTheDocument();
  });

  it("fetches the complete filtered series sequentially and pages only the event table", async () => {
    const user = userEvent.setup();
    const allItems = manySummaries(205);
    const requests: { page: number; pageSize: number }[] = [];
    let activeRequests = 0;
    let maximumActiveRequests = 0;
    renderWithProviders(<SnapshotsPage />, { handlers: [
      http.get("/api/snapshots", async ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page"));
        const pageSize = Number(url.searchParams.get("page_size"));
        requests.push({ page, pageSize });
        activeRequests += 1;
        maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
        await new Promise((resolve) => setTimeout(resolve, 2));
        activeRequests -= 1;
        const start = (page - 1) * pageSize;
        return HttpResponse.json({
          items: allItems.slice(start, start + pageSize),
          page,
          page_size: pageSize,
          total: allItems.length,
        });
      }),
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    ] });

    expect(await screen.findByText("第 1 / 21 页 · 共 205 条")).toBeInTheDocument();
    expect(screen.getByLabelText("再平衡事件配对")).toHaveTextContent("第二页再平衡前");
    expect(screen.getByLabelText("再平衡事件配对")).toHaveTextContent("第二页再平衡后");
    expect(requests).toEqual([
      { page: 1, pageSize: 100 },
      { page: 2, pageSize: 100 },
      { page: 3, pageSize: 100 },
    ]);
    expect(maximumActiveRequests).toBe(1);
    expect(screen.getAllByRole("row")).toHaveLength(11);

    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByText("第 2 / 21 页 · 共 205 条")).toBeInTheDocument();
    expect(screen.getByText("事件 11")).toBeInTheDocument();
  });

  it("resets the event table to page one when filters change", async () => {
    const user = userEvent.setup();
    const allItems = manySummaries(35);
    renderWithProviders(<SnapshotsPage />, { handlers: [
      http.get("/api/snapshots", ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page"));
        const pageSize = Number(url.searchParams.get("page_size"));
        const start = (page - 1) * pageSize;
        return HttpResponse.json({ items: allItems.slice(start, start + pageSize), page, page_size: pageSize, total: allItems.length });
      }),
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    ] });

    expect(await screen.findByText("第 1 / 4 页 · 共 35 条")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByText("第 2 / 4 页 · 共 35 条")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("快照类型"), "manual");

    expect(await screen.findByText("第 1 / 4 页 · 共 35 条")).toBeInTheDocument();
    expect(screen.getByText("事件 1")).toBeInTheDocument();
  });

  it("uses the same combined completeness label in table and detail", async () => {
    const user = userEvent.setup();
    const combined = { ...summaries[0], has_stale_data: true, has_manual_data: true };
    renderWithProviders(<SnapshotsPage />, { handlers: [
      http.get("/api/snapshots", () => HttpResponse.json({ items: [combined], page: 1, page_size: 100, total: 1 })),
      http.get(`/api/snapshots/${combined.id}`, () => HttpResponse.json({ ...detail, ...combined })),
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    ] });

    const row = await screen.findByRole("row", { name: /季度复核/ });
    expect(row).toHaveTextContent("含过期与手动值");
    await user.click(within(row).getByRole("button", { name: "查看详情" }));

    expect(await screen.findByRole("dialog", { name: "快照详情" })).toHaveTextContent("含过期与手动值");
  });

  it("opens the manual capture workflow from the shell command URL", async () => {
    renderWithProviders(<SnapshotsPage />, { route: "/history?capture=manual", handlers: handlers() });

    expect(await screen.findByRole("dialog", { name: "保存手动快照" })).toBeInTheDocument();
    expect(screen.getByLabelText("快照备注")).toBeInTheDocument();
  });

  it("has no serious accessibility violations", async () => {
    renderWithProviders(<SnapshotsPage />, { handlers: handlers() });
    await screen.findByRole("heading", { name: "历史快照" });
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical"))
      .toEqual([]);
  });
});

it("invalidates every snapshot query after manual capture", async () => {
  server.use(http.post("/api/snapshots/manual", () => HttpResponse.json(detail, { status: 201 })));
  const queryClient = createQueryClient();
  queryClient.setQueryData([...snapshotsQueryRoot, { page: 1 }], collection);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const mutation = renderHook(() => useCreateManualSnapshot(), { wrapper });

  await act(() => mutation.result.current.mutateAsync({ note: "季度复核" }));

  expect(queryClient.getQueryState([...snapshotsQueryRoot, { page: 1 }])?.isInvalidated).toBe(true);
});
