export function decimalNumber(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function formatAmount(value: string, digits = 0) {
  return decimalNumber(value).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatDecimal(value: string, maximumFractionDigits = 6) {
  return decimalNumber(value).toLocaleString("zh-CN", {
    maximumFractionDigits,
  });
}

export function formatSignedAmount(value: string, digits = 2) {
  const numeric = decimalNumber(value);
  const sign = numeric > 0 ? "+" : numeric < 0 ? "−" : "±";
  return `${sign}${Math.abs(numeric).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function formatPercent(value: string, digits = 1) {
  return `${(decimalNumber(value) * 100).toFixed(digits)}%`;
}

export function formatSignedPercent(value: string, digits = 1) {
  const numeric = decimalNumber(value) * 100;
  const sign = numeric > 0 ? "+" : numeric < 0 ? "−" : "±";
  return `${sign}${Math.abs(numeric).toFixed(digits)}%`;
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
