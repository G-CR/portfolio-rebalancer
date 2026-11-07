import { render, screen, within } from "@testing-library/react";

import { TradeSuggestions } from "../src/features/rebalance/TradeSuggestions";
import { rebalancePreviewFixture } from "./fixtures";

const trades = rebalancePreviewFixture.result.trades;

it("shows separate buy and sell totals in CNY for a mixed plan", () => {
  render(<TradeSuggestions trades={[...trades]} holdingNames={{}} />);

  expect(screen.getByText("预计买入金额").parentElement).toHaveTextContent("¥15,900.00");
  expect(screen.getByText("预计卖出金额").parentElement).toHaveTextContent("¥8,500.00");
  expect(screen.getByText(/不含手续费；换汇不重复计入/)).toBeInTheDocument();
  expect(within(screen.getByRole("row", { name: "510880 买入" })).getByText("3,600.00", { selector: '[data-label="人民币参考"]' })).toBeInTheDocument();
});

it("sums exact amounts before rounding and omits the sell total for a buy-only plan", () => {
  const buys = [
    { ...trades[0], amount_cny: "9007199254740993.005" },
    { ...trades[1], amount_cny: "0.005" },
  ];
  render(<TradeSuggestions trades={buys} holdingNames={{}} />);

  expect(screen.getByText("预计买入金额").parentElement).toHaveTextContent("¥9,007,199,254,740,993.01");
  expect(screen.queryByText("预计卖出金额")).not.toBeInTheDocument();
});

it("shows the existing empty state when there are no trades", () => {
  render(<TradeSuggestions trades={[]} holdingNames={{}} />);
  expect(screen.getByText("当前口径下不需要产生交易。")).toBeInTheDocument();
  expect(screen.queryByText("预计买入金额")).not.toBeInTheDocument();
});

it("shows zero purchases and the sale amount for a sell-only plan", () => {
  render(<TradeSuggestions trades={[trades[2]]} holdingNames={{}} />);
  expect(screen.getByText("预计买入金额").parentElement).toHaveTextContent("¥0.00");
  expect(screen.getByText("预计卖出金额").parentElement).toHaveTextContent("¥8,500.00");
});
