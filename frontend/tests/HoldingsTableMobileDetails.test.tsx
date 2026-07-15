import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Holding, HoldingAnalytics, PortfolioIncompleteItem } from "../src/api/types";
import { calculateMenuPosition } from "../src/features/holdings/HoldingActionMenu";
import { HoldingsTable } from "../src/features/holdings/HoldingsTable";
import styles from "../src/features/holdings/HoldingsTable.module.css";
import tableCss from "../src/features/holdings/HoldingsTable.module.css?raw";
import { assetClassFixtures, holdingFixture, portfolioFixture } from "./fixtures";

const secondHolding = {
  ...holdingFixture,
  id: "20000000-0000-4000-8000-000000000002",
  asset_class_id: assetClassFixtures[3].id,
  symbol: "QQQ",
  name: "Invesco QQQ Trust",
  account_name: "成长账户",
  is_rebalance_preferred: false,
} as const;

const spyAnalytics = {
  ...portfolioFixture.holdings[0],
  price_status: "stale",
  fx_status: "manual",
} satisfies HoldingAnalytics;

const qqqAnalytics = {
  ...spyAnalytics,
  holding_id: secondHolding.id,
  asset_class_id: secondHolding.asset_class_id,
  symbol: secondHolding.symbol,
  name: secondHolding.name,
  current_price: "500",
  current_fx_to_cny: "7.2",
  market_value_cny: "42000",
  unrealized_pnl: "-1200",
} satisfies HoldingAnalytics;

function renderTable({
  holdings = [holdingFixture],
  analytics = [spyAnalytics],
  incomplete = [],
  showArchived = false,
  onCommand = vi.fn(),
}: {
  holdings?: Holding[];
  analytics?: HoldingAnalytics[];
  incomplete?: PortfolioIncompleteItem[];
  showArchived?: boolean;
  onCommand?: ReturnType<typeof vi.fn>;
} = {}) {
  const incompleteById = new Map<string, PortfolioIncompleteItem[]>();
  for (const item of incomplete) {
    incompleteById.set(item.holding_id, [...(incompleteById.get(item.holding_id) ?? []), item]);
  }
  render(
    <HoldingsTable
      holdings={holdings}
      assetClasses={[...assetClassFixtures]}
      analyticsById={new Map(analytics.map((item) => [item.holding_id, item]))}
      incompleteById={incompleteById}
      showArchived={showArchived}
      onCommand={onCommand}
    />,
  );
  return { onCommand };
}

describe("HoldingsTable mobile row details", () => {
  it("places action menus on the side with usable viewport space", () => {
    const nearTop = { top: 20, bottom: 52, right: 980 } as DOMRect;
    const nearBottom = { top: 720, bottom: 752, right: 980 } as DOMRect;

    expect(calculateMenuPosition(nearTop, { width: 142, height: 150 }, { width: 1024, height: 768 })).toEqual({
      top: 56,
      left: 838,
      placement: "bottom",
    });
    expect(calculateMenuPosition(nearBottom, { width: 142, height: 150 }, { width: 1024, height: 768 })).toEqual({
      top: 566,
      left: 838,
      placement: "top",
    });
  });

  it("portals the action menu and restores trigger focus after Escape", async () => {
    const user = userEvent.setup();
    renderTable();
    const trigger = screen.getByRole("button", { name: "更多 SPY 操作" });

    await user.click(trigger);

    const menu = screen.getByRole("menu");
    expect(menu.parentElement).toBe(document.body);
    expect(screen.getByRole("menuitem", { name: "卖出调整" })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps the four summary values visible and details collapsed initially", () => {
    renderTable();

    const disclosure = screen.getByRole("button", { name: "查看 SPY 持仓详情" });
    const detailId = disclosure.getAttribute("aria-controls")!;
    const detailRow = document.getElementById(detailId)!;
    const summaryRow = screen.getByText("SPY").closest("tr")!;

    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(disclosure).toHaveAttribute("title", "查看持仓详情");
    expect(detailRow).toHaveAttribute("hidden");
    expect(detailRow).toHaveAttribute("data-mobile-detail", "true");
    expect(summaryRow).toHaveAttribute("data-mobile-summary", "true");
    expect(within(summaryRow).getByText("12.0000")).toBeInTheDocument();
    expect(within(summaryRow).getByText("51,012")).toBeInTheDocument();
    expect(within(summaryRow).getByText("+7,049")).toBeInTheDocument();
  });

  it("shares fixed columns and right-aligns every numeric heading", () => {
    renderTable();

    expect(document.querySelectorAll("colgroup col")).toHaveLength(11);
    for (const label of ["份额", "成本价", "成本汇率", "当前价", "当前汇率", "市值", "浮动盈亏"]) {
      expect(screen.getByRole("columnheader", { name: label })).toHaveClass(styles.numericHeader);
    }
    expect(tableCss).toMatch(/\.numericHeader[^\{]*\{[^}]*text-align:\s*right/s);
  });

  it("expands all hidden fields and routes mobile actions without changing table semantics", async () => {
    const user = userEvent.setup();
    const { onCommand } = renderTable();
    const disclosure = screen.getByRole("button", { name: "查看 SPY 持仓详情" });

    await user.click(disclosure);

    const detailRow = document.getElementById(disclosure.getAttribute("aria-controls")!)!;
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(disclosure).toHaveAttribute("aria-label", "收起 SPY 持仓详情");
    expect(detailRow).not.toHaveAttribute("hidden");
    expect(detailRow.tagName).toBe("TR");
    expect(detailRow.querySelector("td")).toHaveAttribute("colspan", "11");
    expect(detailRow).toHaveTextContent("长期账户");
    expect(detailRow).toHaveTextContent("标普 500");
    expect(detailRow).toHaveTextContent("USD / US");
    expect(detailRow).toHaveTextContent("510.25");
    expect(detailRow).toHaveTextContent("7.18");
    expect(detailRow).toHaveTextContent("590.42");
    expect(detailRow).toHaveTextContent("7.2");
    expect(detailRow).toHaveTextContent("默认调整标的");
    expect(detailRow).toHaveTextContent("启用持仓");

    const purchase = detailRow.querySelector<HTMLButtonElement>('button[aria-label="追加买入 SPY"]')!;
    fireEvent.click(purchase);
    expect(onCommand).toHaveBeenCalledWith(holdingFixture, "purchase");
  });

  it("uses unique independent controls for multiple rows", async () => {
    const user = userEvent.setup();
    renderTable({ holdings: [holdingFixture, secondHolding], analytics: [spyAnalytics, qqqAnalytics] });
    const spy = screen.getByRole("button", { name: "查看 SPY 持仓详情" });
    const qqq = screen.getByRole("button", { name: "查看 QQQ 持仓详情" });

    expect(spy.getAttribute("aria-controls")).not.toBe(qqq.getAttribute("aria-controls"));
    await user.click(spy);
    expect(spy).toHaveAttribute("aria-expanded", "true");
    expect(qqq).toHaveAttribute("aria-expanded", "false");
    await user.click(qqq);
    expect(spy).toHaveAttribute("aria-expanded", "true");
    expect(qqq).toHaveAttribute("aria-expanded", "true");
  });

  it("toggles the native disclosure button with keyboard input", async () => {
    const user = userEvent.setup();
    renderTable();
    const disclosure = screen.getByRole("button", { name: "查看 SPY 持仓详情" });
    disclosure.focus();

    await user.keyboard("{Enter}");
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await user.keyboard(" ");
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
  });

  it("shows stale, manual, and missing labels inside expanded details", async () => {
    const user = userEvent.setup();
    const missing: PortfolioIncompleteItem = {
      holding_id: secondHolding.id,
      symbol: secondHolding.symbol,
      input: "price",
      key: "price:QQQ",
      status: "missing",
      value: null,
    };
    renderTable({ holdings: [holdingFixture, secondHolding], analytics: [spyAnalytics], incomplete: [missing] });

    await user.click(screen.getByRole("button", { name: "查看 SPY 持仓详情" }));
    await user.click(screen.getByRole("button", { name: "查看 QQQ 持仓详情" }));
    const spyDetail = document.getElementById(screen.getByRole("button", { name: "收起 SPY 持仓详情" }).getAttribute("aria-controls")!)!;
    const qqqDetail = document.getElementById(screen.getByRole("button", { name: "收起 QQQ 持仓详情" }).getAttribute("aria-controls")!)!;

    expect(within(spyDetail).getByText("数据已过期")).toBeInTheDocument();
    expect(within(spyDetail).getByText("手动值")).toBeInTheDocument();
    expect(within(qqqDetail).getByText("数据缺失")).toHaveAttribute("data-status", "missing");
  });

  it("keeps archived context expandable without active actions", async () => {
    const user = userEvent.setup();
    const archived = { ...holdingFixture, is_active: false };
    renderTable({ holdings: [archived], analytics: [], showArchived: true });

    const disclosure = screen.getByRole("button", { name: "查看 SPY 持仓详情" });
    await user.click(disclosure);
    const detail = document.getElementById(disclosure.getAttribute("aria-controls")!)!;
    expect(detail).toHaveTextContent("已归档");
    expect(detail.querySelector('button[aria-label="追加买入 SPY"]')).toBeNull();
  });

  it("defines mobile-only disclosure, detail-row, hidden-column, and four-column hooks below 760px", () => {
    expect(styles.mobileDisclosure).toBeTruthy();
    expect(styles.mobileDetailRow).toBeTruthy();
    expect(styles.desktopActionsColumn).toBeTruthy();
    expect(tableCss).toMatch(/@media \(max-width: 759px\)/);
    expect(tableCss).toMatch(/\.mobileDisclosure\s*\{[^}]*display:\s*inline-grid/s);
    expect(tableCss).toMatch(/\.mobileDetailRow:not\(\[hidden\]\)\s*\{[^}]*display:\s*table-row/s);
    expect(tableCss).toMatch(/\.desktopActionsColumn\s*\{[^}]*display:\s*none/s);
    expect(tableCss).toContain(".table th:nth-child(2)");
    expect(tableCss).toContain(".accountCol");
    expect(tableCss).toContain(".marketValueCol, .pnlCol");
  });
});
