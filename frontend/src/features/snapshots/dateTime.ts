export const PORTFOLIO_TIME_ZONE = "Asia/Shanghai";

export type SnapshotRange = "30" | "90" | "all";

function dateParts(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return { year: Number(part("year")), month: Number(part("month")), day: Number(part("day")) };
}

function calendarDate(year: number, month: number, day: number) {
  return [year.toString().padStart(4, "0"), month.toString().padStart(2, "0"), day.toString().padStart(2, "0")].join("-");
}

export function snapshotRangeStart(
  range: SnapshotRange,
  now = new Date(),
  timeZone = PORTFOLIO_TIME_ZONE,
) {
  if (range === "all") return undefined;
  const current = dateParts(now, timeZone);
  const shifted = new Date(Date.UTC(current.year, current.month - 1, current.day - Number(range)));
  return calendarDate(shifted.getUTCFullYear(), shifted.getUTCMonth() + 1, shifted.getUTCDate());
}

export function formatSnapshotDate(localDate: string) {
  const match = localDate.match(/^\d{4}-(\d{2})-(\d{2})$/);
  return match ? `${match[1]}/${match[2]}` : localDate;
}

export function formatSnapshotCapturedAt(
  capturedAt: string,
  localDate: string,
  timeZone = PORTFOLIO_TIME_ZONE,
) {
  const time = new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(capturedAt));
  return `${formatSnapshotDate(localDate)} ${time}`;
}
