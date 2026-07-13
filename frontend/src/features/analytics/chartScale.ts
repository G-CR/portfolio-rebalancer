const DEFAULT_MAX_MAGNITUDE = 1_000_000;
const DIVISION_DIGITS = 48;

type ParsedDecimal = {
  coefficient: bigint;
  scale: number;
};

export type ExactChartValue = {
  original: string;
  scaled: number;
};

function parseDecimal(value: string): ParsedDecimal {
  const match = value.trim().match(/^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))$/);
  if (!match) throw new TypeError(`Invalid decimal chart value: ${value}`);
  const fraction = match[3] ?? match[4] ?? "";
  const integer = match[2] ?? "0";
  const magnitude = BigInt(`${integer}${fraction}` || "0");
  return {
    coefficient: match[1] === "-" && magnitude !== 0n ? -magnitude : magnitude,
    scale: fraction.length,
  };
}

function absolute(value: bigint) {
  return value < 0n ? -value : value;
}

function alignedCoefficients(values: readonly string[]) {
  const parsed = values.map(parseDecimal);
  const commonScale = parsed.reduce((maximum, item) => Math.max(maximum, item.scale), 0);
  return parsed.map((item) => item.coefficient * (10n ** BigInt(commonScale - item.scale)));
}

function exactRatioNumber(numerator: bigint, denominator: bigint) {
  if (numerator === 0n || denominator === 0n) return 0;
  const integer = numerator / denominator;
  let remainder = numerator % denominator;
  let fraction = "";
  for (let index = 0; index < DIVISION_DIGITS && remainder !== 0n; index += 1) {
    remainder *= 10n;
    fraction += (remainder / denominator).toString();
    remainder %= denominator;
  }
  return Number(fraction ? `${integer}.${fraction}` : integer.toString());
}

export function normalizeDecimalSeries(
  values: readonly string[],
  maxMagnitude = DEFAULT_MAX_MAGNITUDE,
): ExactChartValue[] {
  if (!Number.isSafeInteger(maxMagnitude) || maxMagnitude <= 0 || maxMagnitude > DEFAULT_MAX_MAGNITUDE) {
    throw new RangeError(`Chart magnitude must be a positive safe integer no greater than ${DEFAULT_MAX_MAGNITUDE}.`);
  }
  const coefficients = alignedCoefficients(values);
  const denominator = coefficients.reduce((maximum, value) => {
    const magnitude = absolute(value);
    return magnitude > maximum ? magnitude : maximum;
  }, 0n);
  if (denominator === 0n) return values.map((original) => ({ original, scaled: 0 }));

  return values.map((original, index) => {
    const coefficient = coefficients[index];
    const magnitude = exactRatioNumber(absolute(coefficient) * BigInt(maxMagnitude), denominator);
    return { original, scaled: coefficient < 0n ? -magnitude : magnitude };
  });
}

export function proportionDecimalSeries(
  values: readonly string[],
  total = 100,
): ExactChartValue[] {
  if (!Number.isSafeInteger(total) || total <= 0) {
    throw new RangeError("Chart proportion total must be a positive safe integer.");
  }
  const coefficients = alignedCoefficients(values);
  const denominator = coefficients.reduce((sum, value) => sum + absolute(value), 0n);
  if (denominator === 0n) return values.map((original) => ({ original, scaled: 0 }));
  return values.map((original, index) => ({
    original,
    scaled: exactRatioNumber(absolute(coefficients[index]) * BigInt(total), denominator),
  }));
}
