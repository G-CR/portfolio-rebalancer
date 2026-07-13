type ParsedDecimal = { units: bigint; scale: number };

function parseUnsignedDecimal(value: string): ParsedDecimal | null {
  const normalized = value.trim();
  if (!/^\d+(?:\.\d*)?$/.test(normalized)) return null;
  const [integer, fraction = ""] = normalized.split(".");
  return {
    units: BigInt(`${integer}${fraction}` || "0"),
    scale: fraction.length,
  };
}

function pow10(exponent: number) {
  return 10n ** BigInt(exponent);
}

function formatUnits(units: bigint, scale: number, minimumFractionDigits = 0) {
  const negative = units < 0n;
  const absolute = negative ? -units : units;
  const raw = absolute.toString().padStart(scale + 1, "0");
  const integer = scale === 0 ? raw : raw.slice(0, -scale);
  let fraction = scale === 0 ? "" : raw.slice(-scale);
  while (fraction.length > minimumFractionDigits && fraction.endsWith("0")) {
    fraction = fraction.slice(0, -1);
  }
  while (fraction.length < minimumFractionDigits) fraction += "0";
  return `${negative ? "-" : ""}${integer}${fraction ? `.${fraction}` : ""}`;
}

export function sumPercent(values: string[]) {
  const parsed = values.map(parseUnsignedDecimal);
  if (parsed.some((value) => value === null)) return null;
  const valid = parsed as ParsedDecimal[];
  const scale = Math.max(1, ...valid.map((value) => value.scale));
  const units = valid.reduce(
    (total, value) => total + value.units * pow10(scale - value.scale),
    0n,
  );
  return { units, scale, display: formatUnits(units, scale, 1) };
}

export function percentDifference(values: string[]) {
  const total = sumPercent(values);
  if (!total) return null;
  const target = 100n * pow10(total.scale);
  const difference = target - total.units;
  return {
    valid: difference === 0n,
    deficit: difference > 0n,
    display: formatUnits(difference > 0n ? difference : -difference, total.scale, 1),
    total: total.display,
  };
}

export function ratioToPercent(value: string) {
  const parsed = parseUnsignedDecimal(value);
  if (!parsed) return value;
  if (parsed.scale >= 2) return formatUnits(parsed.units, parsed.scale - 2, 1);
  return formatUnits(parsed.units * pow10(2 - parsed.scale), 0, 1);
}

export function percentToRatio(value: string) {
  const parsed = parseUnsignedDecimal(value);
  if (!parsed) return value;
  const outputScale = Math.max(8, parsed.scale + 2);
  const units = parsed.units * pow10(outputScale - parsed.scale - 2);
  return formatUnits(units, outputScale, 8);
}
