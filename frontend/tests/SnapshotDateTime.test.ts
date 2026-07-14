import {
  PORTFOLIO_TIME_ZONE,
  formatSnapshotCapturedAt,
  formatSnapshotDate,
  snapshotRangeStart,
} from "../src/features/snapshots/dateTime";

function underBrowserTimezone<T>(timezone: string, operation: () => T) {
  const previous = process.env.TZ;
  process.env.TZ = timezone;
  try {
    return operation();
  } finally {
    process.env.TZ = previous;
  }
}

it.each(["Asia/Shanghai", "America/Los_Angeles"])(
  "builds portfolio calendar filters independently of browser TZ=%s",
  (browserTimezone) => {
    const result = underBrowserTimezone(browserTimezone, () =>
      snapshotRangeStart("30", new Date("2026-07-14T00:30:00Z")));

    expect(PORTFOLIO_TIME_ZONE).toBe("Asia/Shanghai");
    expect(result).toBe("2026-06-14");
  },
);

it.each(["Asia/Shanghai", "America/Los_Angeles"])(
  "renders snapshot calendar and time independently of browser TZ=%s",
  (browserTimezone) => {
    const rendered = underBrowserTimezone(browserTimezone, () => ({
      date: formatSnapshotDate("2026-07-14"),
      captured: formatSnapshotCapturedAt(
        "2026-07-13T16:30:00Z",
        "2026-07-14",
      ),
    }));

    expect(rendered).toEqual({ date: "07/14", captured: "07/14 00:30" });
  },
);
