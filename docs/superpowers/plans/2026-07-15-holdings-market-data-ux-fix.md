# Holdings Market Data UX Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use multi-agent execution for this project. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make domestic ETF quotes operational in Docker, automatically recover missing holdings data, align numeric table columns, and render row actions in an unclipped adaptive portal menu.

**Architecture:** Keep the existing market-data refresh endpoint and provider order. Add the missing AKShare runtime dependency, preserve safe diagnostics for every attempted provider, and let the holdings page perform one non-blocking refresh per mount when analytics reports required data as incomplete. Split the recovery notice and floating action menu into focused frontend components; keep calculations and holding mutation contracts unchanged.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, AKShare 1.18.x, pytest, React 19, TypeScript, TanStack Query, React Router, CSS Modules, Vitest, Testing Library, Playwright, Docker Compose.

---

## File Map

**Backend**

- Modify `backend/pyproject.toml` and `backend/uv.lock`: install AKShare in development and production images.
- Modify `backend/app/services/market_data.py`: retain ordered safe provider attempts and select the actionable failure source.
- Modify `backend/tests/unit/test_provider_normalization.py`: cover the runtime dependency and provider-attempt diagnostics.
- Modify `backend/tests/integration/test_market_data_api.py`: verify diagnostics survive database write/read without exposing secrets.

**Frontend data recovery**

- Modify `frontend/src/features/marketData/api.ts`: invalidate portfolio analytics after refresh.
- Create `frontend/src/features/holdings/HoldingsMarketDataNotice.tsx`: own one-shot automatic refresh and recovery actions.
- Modify `frontend/src/pages/HoldingsPage.tsx` and `frontend/src/pages/HoldingsPage.module.css`: render the recovery notice instead of the current raw error strip.
- Modify `frontend/src/pages/MarketDataPage.tsx`: open the requested manual override from an `override` query parameter.
- Modify `frontend/tests/HoldingsAnalytics.test.tsx` and `frontend/tests/MarketDataPage.test.tsx`: cover refresh state and deep linking.

**Frontend table interaction**

- Create `frontend/src/features/holdings/HoldingActionMenu.tsx`: portal rendering, viewport-aware placement, keyboard and focus behavior.
- Modify `frontend/src/features/holdings/HoldingsTable.tsx` and `frontend/src/features/holdings/HoldingsTable.module.css`: shared column definitions, numeric header alignment, and portal menu integration.
- Modify `frontend/tests/HoldingsTableMobileDetails.test.tsx`: cover columns and menu behavior.
- Modify `frontend/e2e/holdings-cost.spec.ts` and `frontend/e2e/fixtures/portfolio.ts`: browser-level alignment and clipping checks.

**Documentation**

- Modify `docs/user-guide.md`: describe immediate automatic refresh and recovery actions.
- Modify `docs/operations.md`: document the AKShare runtime and safe failure diagnostics.

---

### Task 1: Install And Verify AKShare Runtime

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Test: `backend/tests/unit/test_provider_normalization.py`

- [ ] **Step 1: Write the failing runtime dependency test**

Add this test beside `test_akshare_normalizes_cn_etf_code`:

```python
def test_akshare_runtime_dependency_is_installed() -> None:
    import akshare

    assert callable(akshare.fund_etf_spot_em)
```

- [ ] **Step 2: Run the test against the current Docker image and verify it fails**

Run:

```bash
docker compose build api
docker compose run --rm --no-deps api \
  uv run pytest tests/unit/test_provider_normalization.py::test_akshare_runtime_dependency_is_installed -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'akshare'`.

- [ ] **Step 3: Add and lock the dependency**

Run from `backend/`:

```bash
uv add "akshare>=1.18.64,<2"
```

Confirm `backend/pyproject.toml` contains the new dependency and `backend/uv.lock` is updated by uv rather than manually edited.

- [ ] **Step 4: Rebuild and verify the dependency test passes**

Run:

```bash
docker compose build api
docker compose run --rm --no-deps api \
  uv run pytest tests/unit/test_provider_normalization.py::test_akshare_runtime_dependency_is_installed -v
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the dependency fix**

```bash
git add backend/pyproject.toml backend/uv.lock backend/tests/unit/test_provider_normalization.py
git commit -m "fix: install akshare market data runtime"
```

### Task 2: Preserve Actionable Provider Diagnostics

**Files:**
- Modify: `backend/app/services/market_data.py`
- Modify: `backend/tests/unit/test_provider_normalization.py`
- Modify: `backend/tests/integration/test_market_data_api.py`

- [ ] **Step 1: Write failing unit tests for ordered provider attempts**

Import `ProviderRegistry`, `ProviderSelectionError`, and `_safe_failure_summary` from `app.services.market_data`. Add test providers and the test:

```python
class _FailedPriceProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def fetch_price(self, symbol: str):
        raise self.error


@pytest.mark.asyncio
async def test_provider_selection_keeps_primary_failure_when_backup_is_unconfigured() -> None:
    registry = ProviderRegistry()
    registry._providers["akshare"] = _FailedPriceProvider(
        ProviderRequestError("request contains https://secret.invalid")
    )
    registry._providers["tushare"] = _FailedPriceProvider(
        ProviderNotConfigured("token SECRET is missing")
    )

    with pytest.raises(ProviderSelectionError) as exc_info:
        await registry.fetch_price("563020", market="SH")

    assert exc_info.value.provider_name == "akshare"
    assert [(item.provider_name, item.failure_category) for item in exc_info.value.attempts] == [
        ("akshare", "provider_request_failed"),
        ("tushare", "provider_not_configured"),
    ]
    summary = _safe_failure_summary(exc_info.value)
    assert summary == "akshare: provider_request_failed; tushare: provider_not_configured"
    assert "secret.invalid" not in summary
    assert "SECRET" not in summary
```

- [ ] **Step 2: Run the unit test and verify the current last-error behavior fails**

Run:

```bash
docker compose run --rm --no-deps api \
  uv run pytest tests/unit/test_provider_normalization.py::test_provider_selection_keeps_primary_failure_when_backup_is_unconfigured -v
```

Expected: FAIL because `ProviderSelectionError` has no `attempts` and reports `tushare`.

- [ ] **Step 3: Implement ordered safe attempts**

Add the immutable attempt type and update `ProviderSelectionError`:

```python
@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider_name: str
    failure_category: str


class ProviderSelectionError(ProviderError):
    def __init__(self, attempts: list[ProviderAttempt]) -> None:
        super().__init__("No market-data provider returned a valid quote.")
        self.attempts = tuple(attempts)
        actionable = next(
            (item for item in attempts if item.failure_category != "provider_not_configured"),
            attempts[0],
        )
        self.provider_name = actionable.provider_name
        self.failure_category = actionable.failure_category
```

In both `fetch_price` and `fetch_fx`, append `ProviderAttempt(provider_name, _provider_failure_category(exc))` for every `ProviderError`, then raise `ProviderSelectionError(attempts)` after the loop.

Update safe formatting:

```python
def _safe_failure_summary(exc: Exception) -> str:
    if isinstance(exc, ProviderSelectionError):
        return "; ".join(
            f"{item.provider_name}: {item.failure_category}"
            for item in exc.attempts
        )[:_ERROR_SUMMARY_LIMIT]
    return _format_failure_summary(_provider_failure_category(exc))
```

Update `_sanitize_error_text` so it accepts only known provider names and known categories from semicolon-separated entries. Invalid or legacy text must still become the existing `legacy_refresh_error` summary.

- [ ] **Step 4: Add an integration round-trip test**

In `test_market_data_api.py`, configure a registry whose AKShare request fails and whose Tushare provider is unconfigured. Refresh, then GET `/api/market-data` and assert:

```python
assert item["source"] == "akshare"
assert item["status"] == "failed"
assert item["error_summary"] == (
    "akshare: provider_request_failed; tushare: provider_not_configured"
)
assert "SECRET" not in response.text
assert "http" not in item["error_summary"]
```

- [ ] **Step 5: Run focused backend tests**

```bash
docker compose run --rm --no-deps api uv run pytest \
  tests/unit/test_provider_normalization.py \
  tests/integration/test_market_data_api.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 6: Commit provider diagnostics**

```bash
git add backend/app/services/market_data.py \
  backend/tests/unit/test_provider_normalization.py \
  backend/tests/integration/test_market_data_api.py
git commit -m "fix: preserve market provider failure diagnostics"
```

### Task 3: Add One-Shot Holdings Data Recovery

**Files:**
- Modify: `frontend/src/features/marketData/api.ts`
- Create: `frontend/src/features/holdings/HoldingsMarketDataNotice.tsx`
- Modify: `frontend/src/pages/HoldingsPage.tsx`
- Modify: `frontend/src/pages/HoldingsPage.module.css`
- Test: `frontend/tests/HoldingsAnalytics.test.tsx`

- [ ] **Step 1: Write failing tests for automatic refresh and recovery actions**

Extend `HoldingsAnalytics.test.tsx` with an MSW handler that returns incomplete analytics before refresh and complete analytics after refresh. Track refresh calls:

```tsx
it("automatically refreshes missing data once and reloads analytics", async () => {
  let refreshCalls = 0;
  let refreshed = false;
  const incompletePortfolio = { detail: {
    code: "PORTFOLIO_DATA_INCOMPLETE",
    message: "Required portfolio market data is incomplete.",
    items: [{
      holding_id: holdingFixture.id,
      symbol: holdingFixture.symbol,
      input: "price",
      key: `price:${holdingFixture.symbol}`,
      status: "missing",
      value: null,
    }],
  } };
  renderWithProviders(
    <StrictMode><HoldingsPage /></StrictMode>,
    { handlers: [
      http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
      http.get("/api/holdings", () => HttpResponse.json([holdingFixture])),
      http.get("/api/analytics/portfolio", () => refreshed
        ? HttpResponse.json(portfolioFixture)
        : HttpResponse.json(incompletePortfolio, { status: 409 })),
      http.post("/api/market-data/refresh", () => {
        refreshCalls += 1;
        refreshed = true;
        return HttpResponse.json(marketDataCollectionFixture);
      }),
    ] },
  );

  expect(await screen.findByText("正在获取 SPY 行情…")).toBeInTheDocument();
  expect(await screen.findByText("51,012.29")).toBeInTheDocument();
  expect(refreshCalls).toBe(1);
});
```

Add a second test whose refresh response contains a failed `price:SPY` item. Assert the notice shows `立即重试`, `手动录入`, and the Chinese-safe provider explanation.

- [ ] **Step 2: Run the tests and verify they fail**

```bash
cd frontend
npm test -- --run tests/HoldingsAnalytics.test.tsx
```

Expected: FAIL because the page does not call the refresh endpoint or render recovery actions.

- [ ] **Step 3: Invalidate analytics after every refresh**

Update `useRefreshMarketData`:

```tsx
import { portfolioAnalyticsKey } from "../../api/queryKeys";

onSuccess: (data) => {
  queryClient.setQueryData(marketDataQueryKey, data);
  void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
},
```

- [ ] **Step 4: Implement `HoldingsMarketDataNotice`**

The component accepts `items: PortfolioIncompleteItem[]`. Use a `useRef(false)` guard inside `useEffect` to call `refresh.mutate()` once per mount. Derive the current failed item from `refresh.data?.items` by matching `item.key`.

Render these exact states:

```tsx
if (!attempted.current || refresh.isPending) {
  return <div className={styles.refreshing} role="status">正在获取 {symbols} 行情…</div>;
}

return (
  <div className={styles.alert} role="alert">
    <span>{failureMessage}</span>
    <div className={styles.alertActions}>
      <button type="button" onClick={() => refresh.mutate()}>立即重试</button>
      <button type="button" onClick={() => navigate(`/data-sources?override=${encodeURIComponent(items[0].key)}`)}>手动录入</button>
    </div>
  </div>
);
```

Map safe categories to Chinese without parsing arbitrary text:

```tsx
const categoryLabels = {
  provider_not_configured: "未配置",
  provider_payload_invalid: "返回数据无效",
  provider_request_failed: "请求失败",
  provider_internal_error: "运行失败",
} as const;
```

Unknown text becomes `自动获取失败`.

- [ ] **Step 5: Replace the raw incomplete alert**

In `HoldingsPage.tsx`, replace the current `analyticsIncomplete` alert with:

```tsx
{analyticsIncomplete ? <HoldingsMarketDataNotice items={incompleteItems} /> : null}
```

Add `.refreshing`, `.alertActions`, and responsive button styles to `HoldingsPage.module.css`. The refreshing state uses muted/neutral colors; only the final failed state uses `--color-fx`.

- [ ] **Step 6: Run focused frontend tests**

```bash
cd frontend
npm test -- --run tests/HoldingsAnalytics.test.tsx
```

Expected: all tests in the file PASS and `refreshCalls` remains `1` under StrictMode.

- [ ] **Step 7: Commit one-shot recovery**

```bash
git add frontend/src/features/marketData/api.ts \
  frontend/src/features/holdings/HoldingsMarketDataNotice.tsx \
  frontend/src/pages/HoldingsPage.tsx \
  frontend/src/pages/HoldingsPage.module.css \
  frontend/tests/HoldingsAnalytics.test.tsx
git commit -m "fix: recover missing holdings market data"
```

### Task 4: Deep-Link Manual Market Overrides

**Files:**
- Modify: `frontend/src/pages/MarketDataPage.tsx`
- Test: `frontend/tests/MarketDataPage.test.tsx`

- [ ] **Step 1: Write the failing deep-link test**

Render `MarketDataPage` through a memory router at `/data-sources?override=price%3ASPY`. After market data loads, assert the drawer opens:

```tsx
expect(await screen.findByRole("heading", { name: "手动覆盖 · SPY" })).toBeInTheDocument();
```

Close the drawer and assert the `override` parameter is removed so it does not reopen after refetch.

- [ ] **Step 2: Run the focused test and verify it fails**

```bash
cd frontend
npm test -- --run tests/MarketDataPage.test.tsx
```

Expected: FAIL because `MarketDataPage` ignores query parameters.

- [ ] **Step 3: Implement query-parameter selection**

Use `useSearchParams`:

```tsx
const [searchParams, setSearchParams] = useSearchParams();
const requestedOverride = searchParams.get("override");

useEffect(() => {
  if (!requestedOverride || !marketData.data) return;
  const match = marketData.data.items.find((item) => item.key === requestedOverride);
  if (match) setOverrideItem(match);
}, [marketData.data, requestedOverride]);

function closeOverride() {
  setOverrideItem(null);
  setSearchParams((current) => {
    current.delete("override");
    return current;
  }, { replace: true });
}
```

Use `closeOverride` for both manual and deep-linked drawers.

- [ ] **Step 4: Run the focused test**

```bash
cd frontend
npm test -- --run tests/MarketDataPage.test.tsx
```

Expected: all tests in the file PASS.

- [ ] **Step 5: Commit deep linking**

```bash
git add frontend/src/pages/MarketDataPage.tsx frontend/tests/MarketDataPage.test.tsx
git commit -m "feat: deep link market data overrides"
```

### Task 5: Align Holdings Columns With Shared Definitions

**Files:**
- Modify: `frontend/src/features/holdings/HoldingsTable.tsx`
- Modify: `frontend/src/features/holdings/HoldingsTable.module.css`
- Test: `frontend/tests/HoldingsTableMobileDetails.test.tsx`

- [ ] **Step 1: Write failing structural and alignment assertions**

Add a test that renders the table and asserts:

```tsx
expect(document.querySelectorAll("colgroup col")).toHaveLength(11);
for (const label of ["份额", "成本价", "成本汇率", "当前价", "当前汇率", "市值", "浮动盈亏"]) {
  expect(screen.getByRole("columnheader", { name: label })).toHaveClass(styles.numericHeader);
}
expect(tableCss).toMatch(/\.numericHeader\s*\{[^}]*text-align:\s*right/s);
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd frontend
npm test -- --run tests/HoldingsTableMobileDetails.test.tsx
```

Expected: FAIL because there is no `colgroup` or `numericHeader` class.

- [ ] **Step 3: Add shared columns and numeric headers**

Add this table structure before `<thead>`:

```tsx
<colgroup>
  <col className={styles.symbolCol} />
  <col className={styles.accountCol} />
  <col className={styles.currencyCol} />
  <col className={styles.quantityCol} />
  <col className={styles.costPriceCol} />
  <col className={styles.costFxCol} />
  <col className={styles.currentPriceCol} />
  <col className={styles.currentFxCol} />
  <col className={styles.marketValueCol} />
  <col className={styles.pnlCol} />
  <col className={styles.actionsCol} />
</colgroup>
```

Apply `className={styles.numericHeader}` to the seven numeric headers. Move desktop widths from `th:nth-child(...)` selectors to the `col` classes. Keep responsive hiding selectors on matching `th` and `td` because `display: none` on `col` is not consistently supported.

- [ ] **Step 4: Run the table tests**

```bash
cd frontend
npm test -- --run tests/HoldingsTableMobileDetails.test.tsx
```

Expected: all tests PASS.

- [ ] **Step 5: Commit column alignment**

```bash
git add frontend/src/features/holdings/HoldingsTable.tsx \
  frontend/src/features/holdings/HoldingsTable.module.css \
  frontend/tests/HoldingsTableMobileDetails.test.tsx
git commit -m "fix: align holdings table columns"
```

### Task 6: Render Holdings Actions In An Adaptive Portal

**Files:**
- Create: `frontend/src/features/holdings/HoldingActionMenu.tsx`
- Modify: `frontend/src/features/holdings/HoldingsTable.tsx`
- Modify: `frontend/src/features/holdings/HoldingsTable.module.css`
- Test: `frontend/tests/HoldingsTableMobileDetails.test.tsx`

- [ ] **Step 1: Write failing tests for placement and keyboard behavior**

Export a pure helper:

```tsx
export function calculateMenuPosition(
  trigger: DOMRect,
  menu: { width: number; height: number },
  viewport: { width: number; height: number },
): { top: number; left: number; placement: "top" | "bottom" }
```

Add unit assertions for a trigger near the bottom and one near the top. Add a component test that opens `更多 SPY 操作`, verifies the menu exists under `document.body`, presses `Escape`, and verifies focus returns to the trigger.

- [ ] **Step 2: Run the tests and verify they fail**

```bash
cd frontend
npm test -- --run tests/HoldingsTableMobileDetails.test.tsx
```

Expected: FAIL because `calculateMenuPosition` and portal behavior do not exist.

- [ ] **Step 3: Implement deterministic placement**

Use an 8px viewport margin and 4px trigger gap:

```tsx
const margin = 8;
const gap = 4;
const below = viewport.height - trigger.bottom - margin;
const above = trigger.top - margin;
const placement = below >= menu.height || below >= above ? "bottom" : "top";
const top = placement === "bottom"
  ? Math.min(trigger.bottom + gap, viewport.height - menu.height - margin)
  : Math.max(margin, trigger.top - menu.height - gap);
const left = Math.min(
  Math.max(margin, trigger.right - menu.width),
  viewport.width - menu.width - margin,
);
return { top, left, placement };
```

- [ ] **Step 4: Implement the portal component**

Move the existing action menu buttons into `HoldingActionMenu`. Render the menu with `createPortal(menu, document.body)`, apply `position: fixed`, and recalculate after opening with `useLayoutEffect`.

Register listeners while open:

- `window.resize`
- capture-phase `window.scroll` so table and page scrolling both reposition
- document `mousedown` for outside clicks
- document `keydown` for `Escape`

Focus the first `[role="menuitem"]` after placement. On close, call `triggerRef.current?.focus()` only when closure came from `Escape` or a completed command; outside-click closure keeps the clicked target's focus.

- [ ] **Step 5: Remove the clipped menu styles**

Delete `.menuRoot { position: relative; }` and the absolute positioning from `.menu`. Add `.portalMenu` with fixed positioning, z-index above drawers' page surface but below modal drawers, and the existing border/background/shadow tokens.

- [ ] **Step 6: Run table interaction tests**

```bash
cd frontend
npm test -- --run tests/HoldingsTableMobileDetails.test.tsx
```

Expected: all tests PASS, including top/bottom placement and `Escape` focus restoration.

- [ ] **Step 7: Commit the portal menu**

```bash
git add frontend/src/features/holdings/HoldingActionMenu.tsx \
  frontend/src/features/holdings/HoldingsTable.tsx \
  frontend/src/features/holdings/HoldingsTable.module.css \
  frontend/tests/HoldingsTableMobileDetails.test.tsx
git commit -m "fix: float holdings actions above table overflow"
```

### Task 7: Add Browser Acceptance For Alignment And Menus

**Files:**
- Modify: `frontend/e2e/fixtures/portfolio.ts`
- Modify: `frontend/e2e/holdings-cost.spec.ts`

- [ ] **Step 1: Extend the fixture for multiple holdings and failed refreshes**

Add an options argument and use it in the three affected routes:

```tsx
import type { Holding, MarketDataCollection, PortfolioAnalytics } from "../../src/api/types";

type SeedPortfolioOptions = {
  holdings?: Holding[];
  analytics?: PortfolioAnalytics;
  refreshResult?: MarketDataCollection;
  onRefresh?: () => void;
};

export async function seedPortfolio(
  page: Page,
  state: "balanced" | "empty" = "balanced",
  options: SeedPortfolioOptions = {},
) {
  const holdings = options.holdings ?? (state === "empty" ? [] : [holdingFixture]);
  const analytics = options.analytics ?? (
    state === "empty" ? emptyPortfolioFixture : portfolioFixture
  );
  // Inside the existing route handler:
  if (path === "/api/holdings") return route.fulfill({ json: holdings });
  if (path === "/api/analytics/portfolio") return route.fulfill({ json: analytics });
  if (path === "/api/market-data/refresh" && route.request().method() === "POST") {
    options.onRefresh?.();
    return route.fulfill({ json: options.refreshResult ?? marketDataCollectionFixture });
  }
}
```

Extract the current empty analytics object into `emptyPortfolioFixture` in the same fixture file so both the default path and options path use one value.

- [ ] **Step 2: Write the failing desktop acceptance test**

Add a test with at least three holdings so one trigger is near the bottom of the visible table. Assert each numeric heading's right edge is within 2px of its corresponding cell's right edge:

```tsx
const headingBox = await page.getByRole("columnheader", { name: "份额" }).boundingBox();
const valueBox = await page.getByText("12.0000", { exact: true }).boundingBox();
expect(Math.abs((headingBox!.x + headingBox!.width) - (valueBox!.x + valueBox!.width))).toBeLessThanOrEqual(2);
```

Open the final row's menu and assert:

```tsx
await expect(page.getByRole("menu")).toBeInViewport();
await expect(page.getByRole("menuitem", { name: "调整历史" })).toBeInViewport();
```

- [ ] **Step 3: Run Playwright and verify the new test fails**

```bash
cd frontend
npx playwright test e2e/holdings-cost.spec.ts
```

Expected: FAIL on header alignment or menu viewport visibility before the fixes.

- [ ] **Step 4: Add horizontal-scroll and keyboard assertions**

At 1024x768, horizontally scroll the table region, open the menu, and assert it remains adjacent to the trigger. Press `Escape` and assert the trigger is focused. At 390x844, verify the existing detail disclosure still exposes the action trigger.

- [ ] **Step 5: Run the browser acceptance suite**

```bash
cd frontend
npx playwright test e2e/holdings-cost.spec.ts
```

Expected: all holdings-cost tests PASS.

- [ ] **Step 6: Commit browser coverage**

```bash
git add frontend/e2e/fixtures/portfolio.ts frontend/e2e/holdings-cost.spec.ts
git commit -m "test: cover holdings alignment and action menus"
```

### Task 8: Update Guidance And Run Full Verification

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/operations.md`

- [ ] **Step 1: Update user guidance**

Document that adding a holding or opening a holdings page with missing required data triggers one automatic refresh. Explain `立即重试` and `手动录入`, and state that a failed automatic refresh does not alter cost fields.

- [ ] **Step 2: Update operations guidance**

Document that AKShare is bundled in the API image for domestic ETF prices. Explain that failure summaries contain provider names and safe categories only, and that external network availability can still require manual override.

- [ ] **Step 3: Run the complete isolated backend suite**

```bash
make test-backend
```

Expected: all backend tests PASS; the temporary Compose project and volumes are removed on exit.

- [ ] **Step 4: Run the complete frontend suite and production build**

```bash
cd frontend
npm ci
npm test -- --run
npm run build
npx playwright test
```

Expected: all Vitest and Playwright tests PASS and Vite exits successfully.

- [ ] **Step 5: Verify the production container imports AKShare**

```bash
docker compose build api
docker compose run --rm --no-deps api \
  uv run python -c 'import akshare; print(akshare.__version__)'
```

Expected: prints an AKShare 1.18.x version and exits 0.

- [ ] **Step 6: Rebuild an isolated application and inspect `563020`**

Run this isolated acceptance script from the repository root:

```bash
set -euo pipefail
export COMPOSE_PROJECT_NAME=portfolio-holdings-acceptance
export PORTFOLIO_PORT=0
cleanup() { docker compose down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker compose up -d --build

port="$(docker compose port frontend 80 | awk -F: '{print $NF}')"
base_url="http://127.0.0.1:${port}"
until curl -fsS "${base_url}/api/health" >/dev/null; do sleep 1; done

asset_id="$(curl -fsS "${base_url}/api/asset-classes" | \
  ruby -rjson -e 'puts JSON.parse(STDIN.read).first.fetch("id")')"

curl -fsS -X POST "${base_url}/api/holdings" \
  -H 'Content-Type: application/json' \
  --data "{\"asset_class_id\":\"${asset_id}\",\"symbol\":\"563020\",\"name\":\"红利低波ETF易方达\",\"market\":\"SH\",\"account_name\":\"验收账户\",\"trade_currency\":\"CNY\",\"quantity\":\"100\",\"average_cost_price\":\"1.103\",\"cost_fx_to_cny\":\"1\",\"baseline_fx_to_cny\":\"1\",\"lot_size\":\"100\",\"quantity_precision\":0,\"is_rebalance_preferred\":true}" >/dev/null

curl -fsS -X POST "${base_url}/api/market-data/refresh" > /tmp/portfolio-563020-refresh.json
ruby -rjson -e '
  item = JSON.parse(File.read("/tmp/portfolio-563020-refresh.json"))
    .fetch("items").find { |row| row.fetch("key") == "price:563020" }
  abort "missing price:563020" unless item
  if item.fetch("status") == "valid"
    abort "unexpected provider" unless item.fetch("source") == "akshare"
    abort "missing value" unless item.fetch("effective_value").to_f.positive?
  else
    summary = item.fetch("error_summary")
    abort "wrong failure source" unless item.fetch("source") == "akshare"
    abort "unsafe summary" if summary.match?(/https?:|secret|token|traceback/i)
    abort "missing safe category" unless summary.include?("provider_")
  end
'
```

Acceptance is either:

- `status=valid`, `source=akshare`, and a positive value; or
- `status=failed` with `source=akshare`, a safe provider-category summary, and no exception text, URL, or credentials.

Always remove the isolated project with `docker compose down -v --remove-orphans`.

- [ ] **Step 7: Run final repository checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intended documentation changes remain.

- [ ] **Step 8: Commit documentation and final evidence**

```bash
git add docs/user-guide.md docs/operations.md
git commit -m "docs: explain holdings market data recovery"
```

## Final Checkpoint

Before integration, manually inspect the holdings page at desktop and 390px widths with:

- a valid AKShare price;
- a failed automatic refresh;
- a menu opened from the first row;
- a menu opened from the final visible row;
- a horizontally scrolled table;
- keyboard-only menu opening and closing.

Do not merge until the missing-data notice, numeric alignment, and menu placement match the approved option A interaction.
