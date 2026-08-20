# Market Data Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an open browser session discover backend-refreshed market data within 30 seconds, or immediately on focus/reconnect, and update dependent screens without a manual page reload.

**Architecture:** Keep `GET /api/market-data` as the only polling endpoint. Add a focused synchronization module that derives a stable revision, records the last applied revision in React Query, and centralizes downstream invalidation. Automatic observations deduplicate unchanged data while explicit manual refresh forces exactly one propagation; `AppShell` mounts the observer and query-specific options enable polling, focus refetch, and reconnect refetch.

**Tech Stack:** React 19, TypeScript 5.9, TanStack React Query 5, Vitest 3, Testing Library, MSW.

## Global Constraints

- Poll `GET /api/market-data` every 30 seconds while the page is visible.
- Refetch immediately when the window regains focus or the network reconnects.
- Do not poll in a hidden/background tab.
- Do not add backend endpoints, SSE, WebSockets, onboarding, or user settings.
- Automatic failures retain cached data and do not activate the manual-refresh error alert.
- Invalidate portfolio analytics only when every required item has an `effective_value`.
- Explicit manual refresh propagates exactly once even when its revision is unchanged.
- Do not change global React Query defaults.
- Tests use frontend mocks and fake timers only; do not run Docker, call external providers, or access the production database.

## File Map

- Create `frontend/src/features/marketData/synchronization.ts`: revision derivation and downstream invalidation.
- Modify `frontend/src/api/queryKeys.ts`: canonical holdings and snapshots query roots used without feature-module cycles.
- Modify `frontend/src/features/holdings/api.ts`: consume and re-export the canonical holdings root.
- Modify `frontend/src/features/snapshots/api.ts`: consume and re-export the canonical snapshots root.
- Modify `frontend/src/features/marketData/api.ts`: query timing, observer hook, and manual mutation delegation.
- Modify `frontend/src/components/AppShell/AppShell.tsx`: mount the observer.
- Create `frontend/tests/MarketDataAutoSync.test.tsx`: synchronization and timing coverage.
- Modify `frontend/tests/AppShell.test.tsx`: automatic rebalance invalidation coverage.
- Modify `frontend/tests/MarketDataPage.test.tsx`: manual one-shot propagation coverage.

---

### Task 1: Centralize Market-Data Revision Propagation

**Files:**
- Create: `frontend/src/features/marketData/synchronization.ts`
- Modify: `frontend/src/api/queryKeys.ts`
- Modify: `frontend/src/features/holdings/api.ts`
- Modify: `frontend/src/features/snapshots/api.ts`
- Modify: `frontend/src/features/marketData/api.ts`
- Create: `frontend/tests/MarketDataAutoSync.test.tsx`
- Modify: `frontend/tests/MarketDataPage.test.tsx`

**Interfaces:**
- Consumes: `MarketDataCollection`, `QueryClient`, and canonical roots from `frontend/src/api/queryKeys.ts`.
- Produces: `marketDataAppliedRevisionKey`, `marketDataRefreshVersionKey`, `marketDataRevision(data: MarketDataCollection): string`, and `synchronizeMarketDataDependents(queryClient: QueryClient, data: MarketDataCollection, mode: "observe" | "force"): boolean`. `api.ts` re-exports `marketDataRefreshVersionKey` to preserve existing imports.
- `observe` establishes a first baseline and ignores unchanged data; `force` propagates once. A propagation increments the refresh version, invalidates holdings and snapshots, and invalidates analytics only for complete data.

- [ ] **Step 1: Write failing synchronization tests**

Create `frontend/tests/MarketDataAutoSync.test.tsx` with a fresh query client and inactive downstream cache entries:

```tsx
import { QueryClient } from "@tanstack/react-query";
import { portfolioAnalyticsKey } from "../src/api/queryKeys";
import { holdingsQueryRoot } from "../src/features/holdings/api";
import { marketDataRefreshVersionKey } from "../src/features/marketData/api";
import {
  marketDataAppliedRevisionKey,
  marketDataRevision,
  synchronizeMarketDataDependents,
} from "../src/features/marketData/synchronization";
import { snapshotsQueryRoot } from "../src/features/snapshots/api";
import { marketDataCollectionFixture } from "./fixtures";

function preparedClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(portfolioAnalyticsKey, { cached: true });
  client.setQueryData([...holdingsQueryRoot, { includeArchived: false }], ["cached"]);
  client.setQueryData([...snapshotsQueryRoot, { page: 1 }], { items: [] });
  client.setQueryData(marketDataRefreshVersionKey, 0);
  return client;
}

it("derives one revision regardless of item order", () => {
  const reversed = { ...marketDataCollectionFixture, items: [...marketDataCollectionFixture.items].reverse() };
  expect(marketDataRevision(reversed)).toBe(marketDataRevision(marketDataCollectionFixture));
});

it("baselines first observation and ignores an unchanged observation", () => {
  const client = preparedClient();
  expect(synchronizeMarketDataDependents(client, marketDataCollectionFixture, "observe")).toBe(false);
  expect(client.getQueryData(marketDataAppliedRevisionKey)).toBe(marketDataRevision(marketDataCollectionFixture));
  expect(synchronizeMarketDataDependents(client, marketDataCollectionFixture, "observe")).toBe(false);
  expect(client.getQueryData(marketDataRefreshVersionKey)).toBe(0);
  expect(client.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(false);
});

it("propagates a changed complete observation", () => {
  const client = preparedClient();
  synchronizeMarketDataDependents(client, marketDataCollectionFixture, "observe");
  const changed = {
    ...marketDataCollectionFixture,
    items: marketDataCollectionFixture.items.map((item, index) => index === 0
      ? { ...item, effective_value: "652.00", fetched_at: "2026-08-21T00:00:00Z" }
      : item),
  };
  expect(synchronizeMarketDataDependents(client, changed, "observe")).toBe(true);
  expect(client.getQueryData(marketDataRefreshVersionKey)).toBe(1);
  expect(client.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(true);
  expect(client.getQueryState([...holdingsQueryRoot, { includeArchived: false }])?.isInvalidated).toBe(true);
  expect(client.getQueryState([...snapshotsQueryRoot, { page: 1 }])?.isInvalidated).toBe(true);
});

it("does not invalidate analytics for changed incomplete data", () => {
  const client = preparedClient();
  synchronizeMarketDataDependents(client, marketDataCollectionFixture, "observe");
  const incomplete = {
    ...marketDataCollectionFixture,
    items: marketDataCollectionFixture.items.map((item, index) => index === 0
      ? { ...item, effective_value: null, status: "failed" as const, fetched_at: "2026-08-21T00:00:00Z" }
      : item),
  };
  expect(synchronizeMarketDataDependents(client, incomplete, "observe")).toBe(true);
  expect(client.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(false);
  expect(client.getQueryData(marketDataRefreshVersionKey)).toBe(1);
});

it("forces one propagation for an unchanged explicit refresh", () => {
  const client = preparedClient();
  synchronizeMarketDataDependents(client, marketDataCollectionFixture, "observe");
  expect(synchronizeMarketDataDependents(client, marketDataCollectionFixture, "force")).toBe(true);
  expect(client.getQueryData(marketDataRefreshVersionKey)).toBe(1);
});
```

- [ ] **Step 2: Run the test and verify RED**

From `frontend`, run `npm test -- MarketDataAutoSync.test.tsx`.

Expected: FAIL because `synchronization.ts` and its exports do not exist.

- [ ] **Step 3: Implement the synchronization module**

First extend `frontend/src/api/queryKeys.ts`:

```ts
export const portfolioAnalyticsKey = ["portfolio-analytics"] as const;
export const holdingsQueryRoot = ["holdings"] as const;
export const snapshotsQueryRoot = ["snapshots"] as const;
```

In `frontend/src/features/holdings/api.ts`, import `holdingsQueryRoot` beside `portfolioAnalyticsKey`, remove its local declaration, and add `export { holdingsQueryRoot } from "../../api/queryKeys";`. In `frontend/src/features/snapshots/api.ts`, import `snapshotsQueryRoot`, remove its local declaration, and add `export { snapshotsQueryRoot } from "../../api/queryKeys";`. Existing callers keep their current import paths.

Create `frontend/src/features/marketData/synchronization.ts`:

```ts
import type { QueryClient } from "@tanstack/react-query";
import { holdingsQueryRoot, portfolioAnalyticsKey, snapshotsQueryRoot } from "../../api/queryKeys";
import type { MarketDataCollection } from "../../api/types";
export const marketDataAppliedRevisionKey = ["market-data-applied-revision"] as const;
export const marketDataRefreshVersionKey = ["market-data-refresh-version"] as const;

export function marketDataRevision(data: MarketDataCollection) {
  return JSON.stringify([...data.items]
    .sort((left, right) => left.key.localeCompare(right.key))
    .map((item) => [
      item.key, item.effective_value, item.status, item.source,
      item.market_time, item.fetched_at, item.error_summary, item.note,
    ]));
}

export function synchronizeMarketDataDependents(
  queryClient: QueryClient,
  data: MarketDataCollection,
  mode: "observe" | "force",
) {
  const revision = marketDataRevision(data);
  const applied = queryClient.getQueryData<string>(marketDataAppliedRevisionKey);
  queryClient.setQueryData(marketDataAppliedRevisionKey, revision);
  if (mode === "observe" && (applied === undefined || applied === revision)) return false;

  queryClient.setQueryData<number>(marketDataRefreshVersionKey, (current = 0) => current + 1);
  if (data.items.every((item) => item.effective_value !== null)) {
    void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
  }
  void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot });
  void queryClient.invalidateQueries({ queryKey: snapshotsQueryRoot });
  return true;
}
```

Remove the old key declaration from `api.ts` and add `export { marketDataRefreshVersionKey } from "./synchronization";`. Import the same canonical key from `./synchronization` inside `api.ts`; do not duplicate the key literal.

- [ ] **Step 4: Route explicit refresh through the helper**

In `frontend/src/features/marketData/api.ts`, replace inline invalidations with:

```ts
onSuccess: (data) => {
  queryClient.setQueryData(marketDataQueryKey, data);
  synchronizeMarketDataDependents(queryClient, data, "force");
},
```

Remove now-unused imports from `api.ts`.

- [ ] **Step 5: Strengthen manual mutation tests**

In `frontend/tests/MarketDataPage.test.tsx`, preserve complete/incomplete cases and spy on `queryClient.invalidateQueries`:

```tsx
const invalidate = vi.spyOn(queryClient, "invalidateQueries");
await act(() => result.current.mutateAsync());
expect(invalidate.mock.calls.filter(([filters]) => filters.queryKey === portfolioAnalyticsKey)).toHaveLength(1);
expect(queryClient.getQueryData(marketDataRefreshVersionKey)).toBe(1);
```

For incomplete data, assert zero analytics invalidations and exactly one each for holdings and snapshots.

- [ ] **Step 6: Run focused GREEN verification**

From `frontend`, run:

```powershell
npm test -- MarketDataAutoSync.test.tsx MarketDataPage.test.tsx
```

Expected: both files PASS with no unhandled MSW requests.

- [ ] **Step 7: Commit Task 1**

```powershell
git add frontend/src/api/queryKeys.ts frontend/src/features/holdings/api.ts frontend/src/features/snapshots/api.ts frontend/src/features/marketData/synchronization.ts frontend/src/features/marketData/api.ts frontend/tests/MarketDataAutoSync.test.tsx frontend/tests/MarketDataPage.test.tsx
git commit -m "refactor: centralize market data synchronization"
```

---

### Task 2: Add Polling, Focus, and Reconnect Synchronization

**Files:**
- Modify: `frontend/src/features/marketData/api.ts`
- Modify: `frontend/src/components/AppShell/AppShell.tsx`
- Modify: `frontend/tests/MarketDataAutoSync.test.tsx`
- Modify: `frontend/tests/AppShell.test.tsx`

**Interfaces:**
- Consumes: `synchronizeMarketDataDependents(queryClient, data, "observe")` from Task 1.
- Produces: `MARKET_DATA_SYNC_INTERVAL_MS = 30_000` and `useSynchronizeMarketData(data: MarketDataCollection | undefined): void`.
- The observer is mounted unconditionally in `AppShell`; initial data baselines, unchanged responses are no-ops, and changed responses propagate once.

- [ ] **Step 1: Write failing polling/focus/reconnect tests**

Extend `frontend/tests/MarketDataAutoSync.test.tsx` using MSW counters, `vi.useFakeTimers()`, and React Query's `focusManager` and `onlineManager`. Restore them after every case:

```tsx
afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
  onlineManager.setOnline(true);
});

it("polls visible market data every 30 seconds", async () => {
  vi.useFakeTimers();
  let requests = 0;
  renderShellWithMarketData(() => {
    requests += 1;
    return HttpResponse.json(marketDataCollectionFixture);
  });
  await vi.waitFor(() => expect(requests).toBe(1));
  await act(() => vi.advanceTimersByTimeAsync(29_999));
  expect(requests).toBe(1);
  await act(() => vi.advanceTimersByTimeAsync(1));
  await vi.waitFor(() => expect(requests).toBe(2));
});

it("pauses interval polling while unfocused and refetches on focus", async () => {
  vi.useFakeTimers();
  focusManager.setFocused(false);
  let requests = 0;
  renderShellWithMarketData(() => {
    requests += 1;
    return HttpResponse.json(marketDataCollectionFixture);
  });
  await vi.waitFor(() => expect(requests).toBe(1));
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(requests).toBe(1);
  act(() => focusManager.setFocused(true));
  await vi.waitFor(() => expect(requests).toBe(2));
});

it("refetches after reconnect", async () => {
  let requests = 0;
  renderShellWithMarketData(() => {
    requests += 1;
    return HttpResponse.json(marketDataCollectionFixture);
  });
  await waitFor(() => expect(requests).toBe(1));
  act(() => onlineManager.setOnline(false));
  act(() => onlineManager.setOnline(true));
  await waitFor(() => expect(requests).toBe(2));
});
```

Define the render helper in the same file so tests can inspect the query client:

```tsx
function renderShellWithMarketData(
  handler: Parameters<typeof http.get>[1],
) {
  return renderWithProviders(<AppShell />, {
    handlers: [
      http.get("/api/market-data", handler),
      http.post("/api/market-data/refresh", () => HttpResponse.json(marketDataCollectionFixture)),
    ],
  });
}
```

Add unchanged and changed interval cases. Seed inactive cache entries through the returned `queryClient`; the changed handler returns the baseline once and then a copy with a new value/time:

```tsx
it("propagates only a changed automatic response", async () => {
  vi.useFakeTimers();
  let requests = 0;
  const changed = {
    ...marketDataCollectionFixture,
    items: marketDataCollectionFixture.items.map((item, index) => index === 0
      ? { ...item, effective_value: "652.00", fetched_at: "2026-08-21T00:00:00Z" }
      : item),
  };
  const { queryClient } = renderShellWithMarketData(() => {
    requests += 1;
    return HttpResponse.json(requests === 1 ? marketDataCollectionFixture : changed);
  });
  queryClient.setQueryData(portfolioAnalyticsKey, { cached: true });
  queryClient.setQueryData([...holdingsQueryRoot, { includeArchived: false }], ["cached"]);
  queryClient.setQueryData([...snapshotsQueryRoot, { page: 1 }], { items: [] });
  await vi.waitFor(() => expect(requests).toBe(1));
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  await vi.waitFor(() => expect(queryClient.getQueryData(marketDataRefreshVersionKey)).toBe(1));
  expect(queryClient.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(true);
});

it("does not propagate unchanged automatic responses", async () => {
  vi.useFakeTimers();
  const { queryClient } = renderShellWithMarketData(() => HttpResponse.json(marketDataCollectionFixture));
  queryClient.setQueryData(marketDataRefreshVersionKey, 0);
  await vi.waitFor(() => expect(queryClient.getQueryData(marketDataAppliedRevisionKey)).toBeDefined());
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(queryClient.getQueryData(marketDataRefreshVersionKey)).toBe(0);
});
```

- [ ] **Step 2: Run the timing tests and verify RED**

From `frontend`, run `npm test -- MarketDataAutoSync.test.tsx`.

Expected: FAIL because no interval exists and `AppShell` does not observe revisions.

- [ ] **Step 3: Add query-specific refetch policy**

In `frontend/src/features/marketData/api.ts`:

```ts
export const MARKET_DATA_SYNC_INTERVAL_MS = 30_000;

export function useMarketData() {
  return useQuery({
    queryKey: marketDataQueryKey,
    queryFn: () => apiRequest<MarketDataCollection>("/api/market-data"),
    refetchInterval: MARKET_DATA_SYNC_INTERVAL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
}
```

Do not modify `frontend/src/app/providers.tsx`.

- [ ] **Step 4: Add and mount the observer hook**

In `api.ts`, import `useEffect` and add:

```ts
export function useSynchronizeMarketData(data: MarketDataCollection | undefined) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!data) return;
    synchronizeMarketDataDependents(queryClient, data, "observe");
  }, [data, queryClient]);
}
```

In `AppShell.tsx`, import the hook and call it unconditionally:

```tsx
const marketData = useMarketData();
useSynchronizeMarketData(marketData.data);
```

- [ ] **Step 5: Test quiet automatic failure**

Add this test while preserving the existing manual POST failure test in `AppShell.test.tsx`:

```tsx
it("keeps cached status quietly when automatic synchronization fails", async () => {
  vi.useFakeTimers();
  let requests = 0;
  renderShellWithMarketData(() => {
    requests += 1;
    return requests === 1
      ? HttpResponse.json(marketDataCollectionFixture)
      : HttpResponse.json({ detail: "unavailable" }, { status: 503 });
  });
  await vi.waitFor(() => expect(requests).toBe(1));
  expect(screen.getByText("数据有效")).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  await vi.waitFor(() => expect(requests).toBe(2));
  expect(screen.getByText("数据有效")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
```

- [ ] **Step 6: Test automatic rebalance invalidation**

In `frontend/tests/AppShell.test.tsx`, add an automatic counterpart to the topbar-refresh test. Return baseline data on the first GET and a changed `effective_value`/`fetched_at` on the interval GET. After a preview exists, advance 30 seconds and assert:

```tsx
expect(await screen.findByText("配置本次资金与约束后开始测算")).toBeInTheDocument();
expect(screen.queryByText("建议执行 4 笔交易")).not.toBeInTheDocument();
expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
```

For the existing in-progress test, replace its constant GET handler with a two-response handler and advance the interval after the plan starts:

```tsx
let marketRequests = 0;
http.get("/api/market-data", () => {
  marketRequests += 1;
  return HttpResponse.json(marketRequests === 1 ? marketDataCollectionFixture : {
    ...marketDataCollectionFixture,
    items: marketDataCollectionFixture.items.map((item, index) => index === 0
      ? { ...item, effective_value: "652.00", fetched_at: "2026-08-21T00:00:00Z" }
      : item),
  });
}),
```

After `再平衡进行中` appears:

```tsx
await act(() => vi.advanceTimersByTimeAsync(30_000));
await vi.waitFor(() => expect(marketRequests).toBe(2));
expect(await screen.findByText("再平衡进行中")).toBeInTheDocument();
expect(screen.getByRole("button", { name: "完成再平衡并建立新基准" })).toBeEnabled();
```

- [ ] **Step 7: Run focused GREEN verification**

From `frontend`, run:

```powershell
npm test -- MarketDataAutoSync.test.tsx AppShell.test.tsx MarketDataPage.test.tsx RebalancePage.test.tsx
```

Expected: all four files PASS; timers and focus/online managers are restored; MSW reports no unhandled request.

- [ ] **Step 8: Run full frontend verification**

From `frontend`, run:

```powershell
npm test
npm run build
```

Expected: full Vitest suite PASS and the Vite production build exits 0. No Docker command is used.

- [ ] **Step 9: Review and commit Task 2**

```powershell
git diff --check
git status --short
git diff -- frontend/src/features/marketData/api.ts frontend/src/components/AppShell/AppShell.tsx frontend/tests/MarketDataAutoSync.test.tsx frontend/tests/AppShell.test.tsx frontend/tests/MarketDataPage.test.tsx
git add frontend/src/features/marketData/api.ts frontend/src/components/AppShell/AppShell.tsx frontend/tests/MarketDataAutoSync.test.tsx frontend/tests/AppShell.test.tsx frontend/tests/MarketDataPage.test.tsx
git commit -m "feat: auto-sync refreshed market data"
```

Expected: `git diff --check` is silent and only planned frontend files are committed.

## Completion Gate

1. Re-run `npm test` and `npm run build` from `frontend` after the final commit.
2. Confirm `git diff --check` and `git status --short` are clean.
3. Confirm no Docker command, provider request, or production database access occurred.
4. Check every acceptance criterion in `docs/superpowers/specs/2026-08-21-market-data-auto-sync-design.md`.
5. Request final code review before offering branch integration options.
