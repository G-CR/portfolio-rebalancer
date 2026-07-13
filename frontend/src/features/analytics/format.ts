export function boundedRatioPercent(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && Math.abs(parsed) <= 1 ? parsed * 100 : 0;
}

type ParsedDecimal = {
  negative: boolean;
  coefficient: bigint;
  scale: number;
};

function parseDecimal(value: string): ParsedDecimal | null {
  const match = value.trim().match(/^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))$/);
  if (!match) return null;
  const fraction = match[3] ?? match[4] ?? "";
  const integer = match[2] ?? "0";
  return {
    negative: match[1] === "-",
    coefficient: BigInt(`${integer}${fraction}` || "0"),
    scale: fraction.length,
  };
}

function normalizedDigits(digits: number) {
  return Math.max(0, Math.trunc(digits));
}

function roundedCoefficient(value: ParsedDecimal, digits: number, decimalShift = 0) {
  const exponent = digits + decimalShift - value.scale;
  if (exponent >= 0) return value.coefficient * (10n ** BigInt(exponent));
  const divisor = 10n ** BigInt(-exponent);
  const quotient = value.coefficient / divisor;
  const remainder = value.coefficient % divisor;
  return quotient + (remainder * 2n >= divisor ? 1n : 0n);
}

function groupedInteger(value: string) {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function formatCoefficient(coefficient: bigint, digits: number, trimFraction = false) {
  const raw = coefficient.toString().padStart(digits + 1, "0");
  const integer = digits === 0 ? raw : raw.slice(0, -digits);
  let fraction = digits === 0 ? "" : raw.slice(-digits);
  if (trimFraction) fraction = fraction.replace(/0+$/, "");
  return `${groupedInteger(integer)}${fraction ? `.${fraction}` : ""}`;
}

function formatExact(
  value: string,
  digits: number,
  { signed = false, trimFraction = false, decimalShift = 0, suffix = "" } = {},
) {
  const parsed = parseDecimal(value);
  if (!parsed) return value;
  const fractionDigits = normalizedDigits(digits);
  const coefficient = roundedCoefficient(parsed, fractionDigits, decimalShift);
  const sign = signed
    ? coefficient === 0n ? "±" : parsed.negative ? "−" : "+"
    : parsed.negative && coefficient !== 0n ? "-" : "";
  return `${sign}${formatCoefficient(coefficient, fractionDigits, trimFraction)}${suffix}`;
}

export function decimalSign(value: string): -1 | 0 | 1 {
  const parsed = parseDecimal(value);
  if (!parsed || parsed.coefficient === 0n) return 0;
  return parsed.negative ? -1 : 1;
}

export function formatAmount(value: string, digits = 0) {
  return formatExact(value, digits);
}

export function formatDecimal(value: string, maximumFractionDigits = 6) {
  return formatExact(value, maximumFractionDigits, { trimFraction: true });
}

export function formatSignedAmount(value: string, digits = 2) {
  return formatExact(value, digits, { signed: true });
}

export function formatPercent(value: string, digits = 1) {
  return formatExact(value, digits, { decimalShift: 2, suffix: "%" });
}

export function formatSignedPercent(value: string, digits = 1) {
  return formatExact(value, digits, { signed: true, decimalShift: 2, suffix: "%" });
}

export function formatPercentagePoints(value: string, digits = 1) {
  return formatExact(value, digits, { decimalShift: 2, suffix: "pp" });
}

export function formatSignedPercentagePoints(value: string, digits = 1) {
  return formatExact(value, digits, { signed: true, decimalShift: 2, suffix: "pp" });
}

export function formatDataTime(value: string | null) {
  if (!value) return "暂无时间";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function statusLabel(status: string) {
  if (status === "stale") return "数据已过期";
  if (status === "manual") return "手动值";
  if (status === "failed") return "获取失败";
  if (status === "missing") return "数据缺失";
  return "有效";
}
