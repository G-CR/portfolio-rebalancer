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
  const absolute = value.units < 0n ? -value.units : value.units;
  const rounded = (absolute + divisor / 2n) / divisor;
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
  return cents(product) === cents(parsedTotal);
}
