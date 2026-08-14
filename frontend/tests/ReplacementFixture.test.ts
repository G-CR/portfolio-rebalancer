import { describe, expect, it } from "vitest";

import {
  holdingFixture,
  holdingReplacementRequestFixture,
  holdingReplacementResponseFixture,
} from "./fixtures";

describe("holdingReplacementResponseFixture", () => {
  it.each([
    ["9007199254740993", 0, "9007199254740993"],
    ["1.015", 2, "1.02"],
  ])("scales quantity %s exactly at precision %i", (quantity, quantityPrecision, expected) => {
    const payload = holdingReplacementRequestFixture(holdingFixture, {
      quantity,
      quantity_precision: quantityPrecision,
    });

    expect(holdingReplacementResponseFixture(holdingFixture, payload).target.quantity).toBe(expected);
  });
});
