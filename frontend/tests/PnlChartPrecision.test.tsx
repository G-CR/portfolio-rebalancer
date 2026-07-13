import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { PnlPage } from "../src/pages/PnlPage";
import { portfolioFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

type TooltipFormatter = (value: unknown, name: string, item: { payload: Record<string, unknown> }) => string;

const rechartsCapture = vi.hoisted(() => ({
  data: [] as Array<Record<string, unknown>>,
  tooltipFormatter: undefined as undefined | TooltipFormatter,
  yAxisCalls: 0,
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  BarChart: ({ data, children }: { data: Array<Record<string, unknown>>; children: ReactNode }) => {
    rechartsCapture.data = data;
    return <div data-testid="bar-chart">{children}</div>;
  },
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => {
    rechartsCapture.yAxisCalls += 1;
    return null;
  },
  Tooltip: ({ formatter }: { formatter: typeof rechartsCapture.tooltipFormatter }) => {
    rechartsCapture.tooltipFormatter = formatter;
    return null;
  },
  Bar: () => null,
}));

describe("PnlPage chart precision", () => {
  it("passes only bounded normalized geometry while retaining exact tooltip values", async () => {
    rechartsCapture.data = [];
    rechartsCapture.tooltipFormatter = undefined;
    rechartsCapture.yAxisCalls = 0;
    const boundary = {
      ...portfolioFixture,
      asset_classes: portfolioFixture.asset_classes.map((item, index) => ({
        ...item,
        price_effect: index === 0 ? "9999999999999999.999999999999" : index === 1 ? "-5000000000000000.005" : "0",
        fx_effect: index === 0 ? "0.000000000001" : "0",
      })),
    };
    renderWithProviders(<PnlPage />, {
      handlers: [http.get("/api/analytics/portfolio", () => HttpResponse.json(boundary))],
    });

    expect(await screen.findByTestId("bar-chart")).toBeInTheDocument();
    const numericGeometry = rechartsCapture.data.flatMap((item) => [item.price, item.fx]) as number[];
    expect(numericGeometry.every(Number.isFinite)).toBe(true);
    expect(numericGeometry.every((value) => Math.abs(value) <= 1_000_000)).toBe(true);
    expect(rechartsCapture.data[0]).toMatchObject({
      priceOriginal: "9999999999999999.999999999999",
      fxOriginal: "0.000000000001",
    });
    expect(rechartsCapture.data[1].price).toBeLessThan(0);
    expect(rechartsCapture.data[0].fx).toBeGreaterThan(0);
    expect(rechartsCapture.yAxisCalls).toBe(0);

    const formatter = rechartsCapture.tooltipFormatter as TooltipFormatter | undefined;
    expect(formatter).toBeDefined();
    if (!formatter) throw new Error("Expected Recharts tooltip formatter to be registered.");
    expect(formatter(rechartsCapture.data[0].price, "价格影响", { payload: rechartsCapture.data[0] })).toBe(
      "+10,000,000,000,000,000.00",
    );
    expect(formatter(rechartsCapture.data[0].fx, "汇率影响", { payload: rechartsCapture.data[0] })).toBe("±0.00");
  });
});
