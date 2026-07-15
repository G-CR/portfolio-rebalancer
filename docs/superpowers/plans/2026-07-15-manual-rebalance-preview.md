# Manual Rebalance Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use subagents for this project. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop automatic rebalance calculation on page entry and valuation-basis changes so users can configure all constraints before explicitly starting a preview.

**Architecture:** Keep the form and preview mutation in `RebalancePage`, but remove both automatic mutation triggers. `RebalanceInputs` receives whether a preview exists so it can label the command `开始测算` before the first result and `重新测算` afterward. Existing dirty-state and lifecycle behavior remains the source of truth after a preview exists.

**Tech Stack:** React 19, TypeScript, TanStack Query mutations, Vitest, Testing Library, MSW, Playwright, Docker Compose.

---

### Task 1: Specify Manual Initial Calculation Behavior

**Files:**
- Modify: `frontend/tests/RebalancePage.test.tsx`

- [ ] **Step 1: Add a failing test for the initial state**

Add a request counter and verify no preview request is made until the command is clicked:

```tsx
it("waits for an explicit command before the first preview", async () => {
  let previewRequests = 0;
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.post("/api/rebalance/preview", () => {
        previewRequests += 1;
        return HttpResponse.json(rebalancePreviewFixture);
      }),
    ],
  });
  const user = userEvent.setup();

  expect(await screen.findByRole("button", { name: "开始测算" })).toBeEnabled();
  expect(screen.getByText("配置本次资金与约束后开始测算")).toBeInTheDocument();
  expect(previewRequests).toBe(0);

  await user.click(screen.getByRole("button", { name: "开始测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(previewRequests).toBe(1);
  expect(screen.getByRole("button", { name: "重新测算" })).toBeEnabled();
});
```

- [ ] **Step 2: Add a failing test for valuation-basis changes**

Replace the current automatic basis request expectation with:

```tsx
it("keeps valuation-basis changes local until calculation is requested", async () => {
  const requestedBases: string[] = [];
  renderWithProviders(<RebalancePage />, {
    handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.post("/api/rebalance/preview", async ({ request }) => {
        const payload = await request.json() as { valuation_basis: string };
        requestedBases.push(payload.valuation_basis);
        return HttpResponse.json({ ...rebalancePreviewFixture, valuation_basis: payload.valuation_basis });
      }),
    ],
  });
  const user = userEvent.setup();

  await user.click(screen.getByRole("radio", { name: "剔汇率口径" }));
  expect(screen.getByText("剔汇率模拟")).toBeInTheDocument();
  expect(requestedBases).toEqual([]);

  await user.click(screen.getByRole("button", { name: "开始测算" }));
  await waitFor(() => expect(requestedBases).toEqual(["fx_neutral"]));
});
```

- [ ] **Step 3: Run the focused tests and verify they fail for the intended reason**

Run:

```bash
cd frontend
npm test -- --run tests/RebalancePage.test.tsx
```

Expected: the new tests fail because the current page immediately requests a preview and the button is labeled `重新测算`.

- [ ] **Step 4: Commit the failing tests**

```bash
git add frontend/tests/RebalancePage.test.tsx
git commit -m "test: require manual initial rebalance preview"
```

### Task 2: Remove Automatic Preview Triggers

**Files:**
- Modify: `frontend/src/pages/RebalancePage.tsx`
- Modify: `frontend/src/features/rebalance/RebalanceInputs.tsx`
- Modify: `frontend/src/features/rebalance/Rebalance.module.css`

- [ ] **Step 1: Remove the mount-time preview**

In `RebalancePage.tsx`, remove `useEffect` from the React import and delete:

```tsx
useEffect(() => {
  void runPreview(initialForm);
}, []);
```

- [ ] **Step 2: Make basis changes local-only**

Replace `changeBasis` with:

```tsx
const changeBasis = (valuationBasis: RebalanceValuationBasis) => {
  setForm((current) => ({ ...current, valuationBasis }));
  setIsDirty(Boolean(preview.data));
  setPlan(null);
};
```

Update the general input callback so pre-preview edits do not create a meaningless dirty state:

```tsx
onChange={(next) => {
  setForm(next);
  setIsDirty(Boolean(currentPreview));
  setPlan(null);
}}
```

- [ ] **Step 3: Render the initial result prompt**

Inside the result area, before loading and error content, add:

```tsx
{!preview.isPending && !currentPreview && !preview.error ? (
  <div className={styles.previewPrompt}>
    <Calculator size={18} aria-hidden="true" />
    <div>
      <strong>配置本次资金与约束后开始测算</strong>
      <span>行情刷新将在你点击开始测算后执行。</span>
    </div>
  </div>
) : null}
```

Import `Calculator` from `lucide-react`. Add styling that uses the existing unframed result surface:

```css
.previewPrompt { display: flex; min-height: 180px; align-items: center; justify-content: center; gap: var(--space-3); color: var(--color-muted); }
.previewPrompt div { display: grid; gap: var(--space-1); }
.previewPrompt strong { color: var(--color-ink); font-size: 13px; }
.previewPrompt span { font-size: 11px; }
```

- [ ] **Step 4: Make the calculation button state-aware**

Add `hasPreview: boolean` to `RebalanceInputs` props and render:

```tsx
<Calculator size={16} aria-hidden="true" />
{pending ? "测算中" : hasPreview ? "重新测算" : "开始测算"}
```

Pass it from `RebalancePage`:

```tsx
<RebalanceInputs
  value={form}
  pending={preview.isPending}
  hasPreview={Boolean(currentPreview)}
  onChange={...}
  onBasisChange={changeBasis}
  onSubmit={() => void runPreview()}
/>
```

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```bash
cd frontend
npm test -- --run tests/RebalancePage.test.tsx
```

Expected: all `RebalancePage` tests pass after remaining auto-preview assumptions are updated in Task 3.

### Task 3: Update Existing Workflows To Start Explicitly

**Files:**
- Modify: `frontend/tests/RebalancePage.test.tsx`
- Modify: `frontend/tests/RebalanceLifecycle.test.tsx`
- Modify: `frontend/e2e/rebalance.spec.ts`

- [ ] **Step 1: Add a test helper for explicit first calculation**

In component tests, use:

```tsx
async function startPreview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "开始测算" }));
  await screen.findByText("建议执行 4 笔交易");
}
```

Call this helper before assertions that require preview results. For stale-data tests, click `开始测算` and wait for the stale warning instead of waiting for the trade summary.

- [ ] **Step 2: Update lifecycle tests**

In each lifecycle test, click `开始测算` before saving or starting:

```tsx
const user = userEvent.setup();
await user.click(await screen.findByRole("button", { name: "开始测算" }));
await screen.findByText("建议执行 4 笔交易");
```

- [ ] **Step 3: Update the Playwright workflow**

After `page.goto("/rebalance")`, assert the manual initial state and start it explicitly:

```tsx
await expect(page.getByText("配置本次资金与约束后开始测算")).toBeVisible();
await page.getByRole("radio", { name: "剔汇率口径" }).click();
await expect(page.getByText("剔汇率模拟")).toBeVisible();
await page.getByRole("button", { name: "开始测算" }).click();
await expect(page.getByText("新增资金不足以消除高配")).toBeVisible();
```

Do not expect the basis radio click itself to issue a preview.

- [ ] **Step 4: Run all affected tests**

```bash
cd frontend
npm test -- --run tests/RebalancePage.test.tsx tests/RebalanceLifecycle.test.tsx
npx playwright test e2e/rebalance.spec.ts
```

Expected: all affected component and browser tests pass.

- [ ] **Step 5: Commit the implementation**

```bash
git add frontend/src frontend/tests frontend/e2e/rebalance.spec.ts
git commit -m "fix: wait for manual rebalance calculation"
```

### Task 4: Full Verification And Deployment

**Files:**
- No source files expected.

- [ ] **Step 1: Run complete frontend verification**

```bash
cd frontend
npm test -- --run
npm run build
npx playwright test
```

Expected: all Vitest tests, the production build, and all Playwright tests pass.

- [ ] **Step 2: Check repository state**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and no uncommitted implementation changes.

- [ ] **Step 3: Push `master`**

```bash
git push origin master
```

Expected: the new design, tests, and implementation commits are present on `origin/master`.

- [ ] **Step 4: Back up and rebuild production**

```bash
backup="backups/predeploy-manual-rebalance-$(date +%Y%m%d-%H%M%S).sql"
docker exec portfolio-v1-db-1 pg_dump -U portfolio -d portfolio > "$backup"
COMPOSE_PROJECT_NAME=portfolio-v1 PORTFOLIO_PORT=55113 docker compose up -d --build
```

Expected: existing volumes remain attached and all services restart successfully.

- [ ] **Step 5: Verify the deployed behavior**

```bash
curl -fsS http://127.0.0.1:55113/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:55113/api/analytics/portfolio
```

Open `http://127.0.0.1:55113/rebalance` at 1440x900 and verify:

- The page remains idle on entry.
- All inputs and both constraint checkboxes are editable.
- Switching valuation basis does not start calculation.
- `开始测算` starts the preview with the selected values.
- The command changes to `重新测算` after results appear.
