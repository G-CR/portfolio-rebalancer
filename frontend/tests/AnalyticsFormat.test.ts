import {
  decimalSign,
  formatAmount,
  formatDecimal,
  formatPercent,
  formatSignedAmount,
  formatSignedPercent,
} from "../src/features/analytics/format";

describe("exact analytics decimal formatting", () => {
  it("groups and rounds the full NUMERIC(28,12) boundary without precision loss", () => {
    expect(formatAmount("9999999999999999.99", 2)).toBe("9,999,999,999,999,999.99");
    expect(formatAmount("9999999999999999.999999999999", 2))
      .toBe("10,000,000,000,000,000.00");
    expect(formatDecimal("9999999999999999.999999999999", 6))
      .toBe("10,000,000,000,000,000");
  });

  it("formats signed amounts and collapses rounded negative zero", () => {
    expect(formatSignedAmount("9999999999999999.99", 2))
      .toBe("+9,999,999,999,999,999.99");
    expect(formatSignedAmount("-9999999999999999.99", 2))
      .toBe("−9,999,999,999,999,999.99");
    expect(formatSignedAmount("-0.004", 2)).toBe("±0.00");
    expect(formatSignedAmount("+0", 0)).toBe("±0");
  });

  it("scales fractional percentages exactly before rounding", () => {
    expect(formatPercent("0.123456789012", 8)).toBe("12.34567890%");
    expect(formatPercent("0.000000000005", 10)).toBe("0.0000000005%");
    expect(formatSignedPercent("-0.123456789012", 8)).toBe("−12.34567890%");
    expect(formatSignedPercent("-0.0000001", 2)).toBe("±0.00%");
  });

  it("preserves nonfinancial fallback text and compares decimal signs exactly", () => {
    expect(formatAmount("--", 2)).toBe("--");
    expect(formatDecimal("暂无数据", 4)).toBe("暂无数据");
    expect(formatPercent("not-applicable", 2)).toBe("not-applicable");
    expect(formatSignedAmount("--", 2)).toBe("--");
    expect(decimalSign("0.000000000001")).toBe(1);
    expect(decimalSign("-0.000000000001")).toBe(-1);
    expect(decimalSign("-0.000000000000")).toBe(0);
    expect(decimalSign("--")).toBe(0);
  });
});
