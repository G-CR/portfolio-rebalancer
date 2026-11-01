import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "../src/components/AppShell/AppShell";
import { FormField } from "../src/components/FormField/FormField";
import type { MarketDataCollection } from "../src/api/types";
import { formatDataTime } from "../src/features/analytics/format";
import { RebalancePage } from "../src/pages/RebalancePage";
import { assetClassFixtures, holdingFixture, marketDataCollectionFixture, rebalanceDefaultsFixture, rebalancePlanFixture, rebalancePreviewFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

const mobileQuery = "(max-width: 760px)";

function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const mediaQuery = {
    get matches() {
      return matches;
    },
    media: mobileQuery,
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    addListener: (listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeListener: (listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    dispatchEvent: () => true,
  } as MediaQueryList;

  vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));

  return {
    setMatches(nextMatches: boolean) {
      matches = nextMatches;
      const event = { matches, media: mobileQuery } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

const routeNames = [
  "总览",
  "资产配置",
  "持仓与成本",
  "盈亏分析",
  "再平衡",
  "历史快照",
  "数据源",
];

function renderShell(
  route = "/",
  marketData: MarketDataCollection = marketDataCollectionFixture,
  handlers: Parameters<typeof renderWithProviders>[1]["handlers"] = [],
) {
  return renderWithProviders(<AppShell />, {
    route,
    handlers: [
      ...handlers,
      http.get("/api/market-data", () => HttpResponse.json(marketData)),
      http.post("/api/market-data/refresh", () => HttpResponse.json(marketData)),
    ],
  });
}

describe("AppShell", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the seven confirmed routes as labelled links", () => {
    installMatchMedia(false);
    renderShell();

    for (const name of routeNames) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: "总览" })).toBeInTheDocument();
  });

  it("does not expose manual snapshot capture as a global command", () => {
    installMatchMedia(false);
    renderShell();

    expect(screen.queryByRole("button", { name: "保存快照" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("保存当前快照")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
  });

  it("focuses the first route and isolates the background when mobile navigation opens", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderShell("/holdings");

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);

    expect(screen.getByRole("link", { name: "总览" })).toHaveFocus();
    expect(screen.getByRole("dialog", { name: "主导航" })).toBeInTheDocument();
    expect(screen.getByRole("banner", { hidden: true })).toHaveAttribute("inert");
    expect(screen.getByRole("banner", { hidden: true })).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");
  });

  it("traps Tab and Shift+Tab within mobile navigation and close controls", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);

    const closeButton = screen.getByRole("button", { name: "关闭导航" });
    const firstRoute = screen.getByRole("link", { name: "总览" });
    const lastRoute = screen.getByRole("link", { name: "数据源" });
    expect(firstRoute).toHaveFocus();
    await user.tab({ shift: true });
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(lastRoute).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab();
    expect(firstRoute).toHaveFocus();
  });

  it("closes mobile navigation with Escape and restores trigger focus", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
  });

  it("closes mobile navigation after a route click and restores trigger focus", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    await user.click(screen.getByRole("link", { name: "再平衡" }));

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it("clears modal state without focusing the hidden trigger at the desktop breakpoint", async () => {
    const media = installMatchMedia(true);
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    const firstRoute = screen.getByRole("link", { name: "总览" });
    expect(firstRoute).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "关闭导航" })).toHaveFocus();

    act(() => media.setMatches(false));

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    expect(firstRoute).toHaveFocus();
  });

  it("displays the latest available market time", async () => {
    installMatchMedia(false);
    const latestMarketTime = "2026-07-15T01:30:00Z";
    renderShell("/", {
      ...marketDataCollectionFixture,
      items: marketDataCollectionFixture.items.map((item, index) => ({
        ...item,
        market_time: index === 0 ? "2026-07-10T20:00:00Z" : latestMarketTime,
      })).concat({
        ...marketDataCollectionFixture.items[0],
        key: "price:EMPTY",
        market_time: null,
      }),
    });

    expect(await screen.findByText(formatDataTime(latestMarketTime))).toBeInTheDocument();
  });

  it("prioritizes incomplete data over stale and manual values", async () => {
    installMatchMedia(false);
    renderShell("/", {
      ...marketDataCollectionFixture,
      items: marketDataCollectionFixture.items.map((item, index) => ({
        ...item,
        status: index === 0 ? "missing" : "manual",
      })),
    });

    expect(await screen.findByText("\u6570\u636e\u9700\u5904\u7406")).toBeInTheDocument();
  });

  it("does not describe an empty market-data collection as valid", async () => {
    installMatchMedia(false);
    renderShell("/", { ...marketDataCollectionFixture, items: [] });

    expect(await screen.findByText("尚无市场数据")).toBeInTheDocument();
    expect(screen.queryByText("数据有效")).not.toBeInTheDocument();
  });

  it("shows pending refresh state and prevents duplicate refreshes", async () => {
    installMatchMedia(false);
    let resolveRefresh: ((response: HttpResponse) => void) | undefined;
    const refreshResponse = new Promise<HttpResponse>((resolve) => {
      resolveRefresh = resolve;
    });
    renderShell("/", marketDataCollectionFixture, [
      http.post("/api/market-data/refresh", () => refreshResponse),
    ]);
    const user = userEvent.setup();

    const refreshButton = await screen.findByRole("button", { name: "\u5237\u65b0" });
    await user.click(refreshButton);

    expect(await screen.findByRole("button", { name: "\u6b63\u5728\u5237\u65b0" })).toBeDisabled();
    resolveRefresh?.(HttpResponse.json(marketDataCollectionFixture));
    expect(await screen.findByRole("button", { name: "\u5237\u65b0" })).toBeEnabled();
  });

  it("clears the displayed rebalance preview and plan after a topbar market refresh", async () => {
    installMatchMedia(false);
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="rebalance" element={<RebalancePage />} />
        </Route>
      </Routes>,
      {
        route: "/rebalance",
        handlers: [
          http.get("/api/market-data", () => HttpResponse.json(marketDataCollectionFixture)),
          http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)),
          http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
          http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
          http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
          http.get("/api/rebalance/plans", () => HttpResponse.json({ items: [] })),
          http.post("/api/rebalance/preview", () => HttpResponse.json(rebalancePreviewFixture)),
          http.post("/api/rebalance/plans", () => HttpResponse.json(rebalancePlanFixture, { status: 201 })),
        ],
      },
    );

    await user.click(await screen.findByRole("button", { name: "开始测算" }));
    await screen.findByText("建议执行 4 笔交易");
    await user.click(screen.getByRole("button", { name: "保存方案" }));
    await screen.findByText("方案已保存，尚未开始");

    await user.click(screen.getByRole("button", { name: "刷新" }));

    expect(await screen.findByText("配置本次资金与约束后开始测算")).toBeInTheDocument();
    expect(screen.queryByText("建议执行 4 笔交易")).not.toBeInTheDocument();
    expect(screen.queryByText("方案已保存，尚未开始")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
  });

  it("keeps an in-progress rebalance available after a topbar market refresh", async () => {
    installMatchMedia(false);
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="rebalance" element={<RebalancePage />} />
        </Route>
      </Routes>,
      {
        route: "/rebalance",
        handlers: [
          http.get("/api/market-data", () => HttpResponse.json(marketDataCollectionFixture)),
          http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)),
          http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
          http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
          http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
          http.get("/api/rebalance/plans", () => HttpResponse.json({ items: [] })),
          http.post("/api/rebalance/preview", () => HttpResponse.json(rebalancePreviewFixture)),
          http.post("/api/rebalance/plans", () => HttpResponse.json(rebalancePlanFixture, { status: 201 })),
          http.post(`/api/rebalance/plans/${rebalancePlanFixture.id}/start`, () => HttpResponse.json({
            ...rebalancePlanFixture,
            status: "in_progress",
            before_snapshot_id: "30000000-0000-4000-8000-000000000010",
          })),
        ],
      },
    );

    await user.click(await screen.findByRole("button", { name: "开始测算" }));
    await screen.findByText("建议执行 4 笔交易");
    await user.click(screen.getByRole("button", { name: "开始本次再平衡" }));
    await screen.findByText("再平衡进行中");

    await user.click(screen.getByRole("button", { name: "刷新" }));

    expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "再平衡执行清单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成再平衡并建立新基准" })).toBeEnabled();
  });

  it("waits for delayed plan restoration even when market refresh finishes first", async () => {
    installMatchMedia(false);
    const user = userEvent.setup();
    let resolvePlans!: (response: Response) => void;
    const delayedPlans = new Promise<Response>((resolve) => { resolvePlans = resolve; });
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="rebalance" element={<RebalancePage />} />
        </Route>
      </Routes>,
      {
        route: "/rebalance",
        handlers: [
          http.get("/api/market-data", () => HttpResponse.json(marketDataCollectionFixture)),
          http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)),
          http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
          http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
          http.get("/api/settings/rebalance-defaults", () => HttpResponse.json(rebalanceDefaultsFixture)),
          http.get("/api/rebalance/plans", () => delayedPlans),
        ],
      },
    );

    expect(await screen.findByRole("button", { name: "开始测算" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "刷新" }));
    await act(async () => {
      resolvePlans(HttpResponse.json({
        items: [{
          ...rebalancePlanFixture,
          status: "in_progress",
          tolerance: "0.02",
          before_snapshot_id: "30000000-0000-4000-8000-000000000010",
        }],
      }));
    });

    expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成再平衡并建立新基准" })).toBeEnabled();
  });

  it("links to data sources when refresh fails without discarding cached status", async () => {
    installMatchMedia(false);
    renderShell("/", {
      ...marketDataCollectionFixture,
      items: marketDataCollectionFixture.items.map((item) => ({ ...item, status: "valid" })),
    }, [
      http.post("/api/market-data/refresh", () => HttpResponse.json({ detail: "unavailable" }, { status: 503 })),
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "\u5237\u65b0" }));

    await screen.findByRole("alert");
    expect(screen.getByText("\u6570\u636e\u6709\u6548")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "\u67e5\u770b\u6570\u636e\u6e90" })).toHaveAttribute("href", "/data-sources");
  });
});

describe("shared form surfaces", () => {
  it("connects field help and errors to the control", () => {
    render(
      <FormField label="允许偏离" hint="目标上下浮动范围" error="请输入有效比例" required>
        <input id="tolerance" />
      </FormField>,
    );

    const input = screen.getByRole("textbox", { name: "允许偏离" });
    expect(input).toHaveAccessibleDescription("目标上下浮动范围 请输入有效比例");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-required", "true");
  });
});
