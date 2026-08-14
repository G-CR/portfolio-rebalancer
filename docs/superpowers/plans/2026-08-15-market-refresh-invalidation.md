# Market Refresh Invalidation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent incomplete market-data refresh responses from restarting portfolio analytics and looping the holdings-page automatic refresh, while retaining all dependent invalidation for complete responses.

**Architecture:** Keep the policy in the shared `useRefreshMarketData` mutation. Every successful HTTP response updates the market-data cache and invalidates holdings and snapshots; portfolio analytics is invalidated only when every returned item has a non-null `effective_value`.

**Tech Stack:** React 19, TypeScript, TanStack Query, Vitest, Testing Library, MSW, Playwright.

## Global Constraints

- HTTP failures must continue to preserve cached market data and use the existing mutation error path.
- Successful responses containing any `effective_value: null` must not invalidate portfolio analytics.
- Holdings and snapshots must be invalidated after every successful refresh response.
- No new global refresh state or page-local copy of server error state.
- Push `master` only after the merged-result verification commands complete with the documented baseline exceptions.

---

### Task 1: Guard Analytics Invalidation for Incomplete Refresh Results

**Files:**
- Modify: `frontend/tests/MarketDataPage.test.tsx`
- Modify: `frontend/src/features/marketData/api.ts`

**Interfaces:**
- Consumes: `useRefreshMarketData(): UseMutationResult<MarketDataCollection, ...>`, `portfolioAnalyticsKey`, `holdingsQueryRoot`, and `snapshotsQueryRoot`.
- Produces: unchanged `useRefreshMarketData` public API with conditional portfolio-analytics invalidation.

- [ ] **Step 1: Write the failing unit test**

Add this test after the existing successful-refresh invalidation test in `frontend/tests/MarketDataPage.test.tsx`:

```tsx
it("does not invalidate analytics when refreshed market data is still incomplete", async () => {
  const incompleteRefresh = {
    ...marketDataCollectionFixture,
    items: marketDataCollectionFixture.items.map((item, index) => index === 0
      ? { ...item, effective_value: null, status: "failed" as const }
      : item),
  };
  server.use(http.post("/api/market-data/refresh", () => HttpResponse.json(incompleteRefresh)));
  const queryClient = createQueryClient();
  queryClient.setQueryData(portfolioAnalyticsKey, { portfolio: "cached" });
  queryClient.setQueryData([...holdingsQueryRoot, { includeArchived: false }], ["cached"]);
  queryClient.setQueryData([...snapshotsQueryRoot, { page: 1 }], { items: [] });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRefreshMarketData(), { wrapper });

  await act(() => result.current.mutateAsync());

  expect(queryClient.getQueryData(marketDataQueryKey)).toEqual(incompleteRefresh);
  expect(queryClient.getQueryState(portfolioAnalyticsKey)?.isInvalidated).toBe(false);
  expect(queryClient.getQueryState([...holdingsQueryRoot, { includeArchived: false }])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState([...snapshotsQueryRoot, { page: 1 }])?.isInvalidated).toBe(true);
});
```

- [ ] **Step 2: Run the unit test and verify RED**

Run:

```powershell
cd frontend
npx vitest run tests/MarketDataPage.test.tsx --reporter=verbose
```

Expected: the new test fails because `portfolioAnalyticsKey` has `isInvalidated === true`; the existing complete-response test passes.

- [ ] **Step 3: Implement the minimal condition**

Replace the unconditional analytics invalidation inside `useRefreshMarketData.onSuccess` in `frontend/src/features/marketData/api.ts` with:

```ts
const hasIncompleteRequiredData = data.items.some(
  (item) => item.effective_value === null,
);
if (!hasIncompleteRequiredData) {
  void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
}
```

Leave the market-data cache update, refresh-version increment, holdings invalidation, and snapshots invalidation unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
cd frontend
npx vitest run tests/MarketDataPage.test.tsx tests/HoldingsAnalytics.test.tsx --reporter=verbose
npx playwright test e2e/holdings-cost.spec.ts --reporter=line
```

Expected: both Vitest files pass; all 7 Playwright tests pass, including one failed automatic refresh call followed by a stable alert and recovery actions.

- [ ] **Step 5: Commit the fix**

```powershell
git add -- frontend/tests/MarketDataPage.test.tsx frontend/src/features/marketData/api.ts
git commit -m "fix: prevent incomplete market refresh loop"
```

---

### Task 2: Verify and Publish the Merged Master Branch

**Files:**
- Verify only: repository-wide frontend, backend, and browser suites.
- Git state: `master`, `origin/master`, `.worktrees/usability-optimization`, `.worktrees/holding-replacement`.

**Interfaces:**
- Consumes: Task 1 commit on local `master` and the two existing merge commits.
- Produces: verified `origin/master` containing usability optimization, atomic holding replacement, and the refresh-loop fix.

- [ ] **Step 1: Run the complete frontend suite**

```powershell
cd frontend
npx vitest run --reporter=dot
```

Expected: all frontend test files and tests pass with exit code 0.

- [ ] **Step 2: Run the merged browser workflow**

```powershell
cd frontend
npx playwright test e2e/holdings-cost.spec.ts --reporter=line
```

Expected: 7 passed.

- [ ] **Step 3: Run the backend suite with the documented Saturday-only exclusions**

```powershell
docker compose run --rm api uv run pytest -q -k "not test_digest_sends_anomaly_email_when_data_incomplete and not test_digest_sends_full_analysis_email"
```

Expected: 286 passed, 3 skipped, 2 deselected. Separately report that the two excluded tests expect an email on Saturday even though production intentionally skips weekends.

- [ ] **Step 4: Record TypeScript baseline accurately**

```powershell
cd frontend
npx tsc --noEmit --pretty false
```

Expected baseline: non-zero exit with the already documented diagnostics outside this fix. Confirm that `frontend/src/features/marketData/api.ts` and `frontend/tests/MarketDataPage.test.tsx` add no diagnostic.

- [ ] **Step 5: Verify Git state and push**

```powershell
git status --short
git diff --check
git log --oneline --decorate -8
git push origin master
git fetch origin
git rev-list --left-right --count master...origin/master
```

Expected: clean status, clean diff check, successful push, and final divergence `0 0`.

- [ ] **Step 6: Remove merged worktrees and branches**

From the main repository root, only after the push succeeds:

```powershell
git worktree remove "C:\Users\12067\Documents\code\portfolio-rebalancer\.worktrees\holding-replacement"
git worktree remove "C:\Users\12067\Documents\code\portfolio-rebalancer\.worktrees\usability-optimization"
git worktree prune
git branch -d codex/holding-replacement codex/usability-optimization
```

Expected: both managed worktrees are removed, both fully merged local branches are deleted, and `master` remains checked out in the main repository.
