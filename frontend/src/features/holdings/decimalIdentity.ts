type DecimalValue = { units: bigint; scale: number };

function parseDecimal(value: string): DecimalValue | null {
  const normalized = value.trim();
  const match = normalized.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) return null;
  const fraction = match[3] ?? "";
  const units = BigInt(`${match[2]}${fraction}`) * (match[1] === "-" ? -1n : 1n);
  return { units, scale: fraction.length };
}

function cents(value: DecimalValue) {
  if (value.scale <= 2) return value.units * 10n ** BigInt(2 - value.scale);
  const divisor = 10n ** BigInt(value.scale - 2);
  // round-half-even (banker's rounding) to match Python Decimal quantize default
  const absolute = value.units < 0n ? -value.units : value.units;
  const half = divisor / 2n;
  const remainder = absolute % divisor;
  const isMidpoint = remainder === half;
  const rounded = isMidpoint
    ? ((absolute / divisor) % 2n === 0n ? absolute / divisor : absolute / divisor + 1n)
    : (absolute + half) / divisor;
  return value.units < 0n ? -rounded : rounded;
}

export function costBasisIdentityMatches(
  quantity: string,
  averagePrice: string,
  costFx: string,
  totalCostCny: string,
) {
  const values = [quantity, averagePrice, costFx, totalCostCny].map(parseDecimal);
  if (values.some((value) => value === null)) return false;
  const [parsedQuantity, parsedPrice, parsedFx, parsedTotal] = values as DecimalValue[];
  const product = {
    units: parsedQuantity.units * parsedPrice.units * parsedFx.units,
    scale: parsedQuantity.scale + parsedPrice.scale + parsedFx.scale,
  };
  const productCents = cents(product);
  const totalCents = cents(parsedTotal);
  if (productCents === totalCents) return true;

  // Quantity is rounded for display (_scale_decimal rounds to N decimal places).
  // Max quantity error = 0.5 × 10^(−scale). Tolerate the resulting error in total.
  if (parsedQuantity.scale > 0) {
    // maxErrorCents = ceil(0.5 × 10^(−qtyScale) × price × fx × 100)
    //               = ceil(50 × priceUnits × fxUnits / 10^(qtyScale + priceScale + fxScale))
    const totalScale = parsedQuantity.scale + parsedPrice.scale + parsedFx.scale;
    const denominator = 10n ** BigInt(totalScale);
    const numerator = 50n * parsedPrice.units * parsedFx.units;
    const maxErrorCents = (numerator + denominator - 1n) / denominator + 1n;
    const diff = productCents > totalCents ? productCents - totalCents : totalCents - productCents;
    return diff <= maxErrorCents;
  }

  return false;
}
