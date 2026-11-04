import { normalizeDecimalSeries } from "../src/features/analytics/chartScale";

describe("chartScale", () => {
  it("normalizes boundary, negative, and tiny values without unsafe chart numbers", () => {
    const values = normalizeDecimalSeries([
      "9999999999999999.999999999999",
      "-4999999999999999.999999999999",
      "0.000000000001",
    ]);

    expect(values.map((item) => item.original)).toEqual([
      "9999999999999999.999999999999",
      "-4999999999999999.999999999999",
      "0.000000000001",
    ]);
    expect(values[0].scaled).toBe(1_000_000);
    expect(values[1].scaled).toBe(-500_000);
    expect(values[2].scaled).toBeGreaterThan(0);
    expect(values[2].scaled).toBeLessThan(values[0].scaled);
    expect(values.every((item) => Number.isFinite(item.scaled))).toBe(true);
    expect(values.every((item) => Math.abs(item.scaled) <= 1_000_000)).toBe(true);
  });

  it("handles all-zero and negative-zero series deterministically", () => {
    expect(normalizeDecimalSeries(["0", "0.000000000000", "-0.000000000000"])).toEqual([
      { original: "0", scaled: 0 },
      { original: "0.000000000000", scaled: 0 },
      { original: "-0.000000000000", scaled: 0 },
    ]);
  });

});
