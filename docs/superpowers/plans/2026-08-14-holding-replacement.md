# Holding Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an atomic guided workflow that fully sells and archives a source holding, creates its replacement, and makes the replacement the asset class's preferred rebalance instrument.

**Architecture:** A dedicated FastAPI command endpoint owns one database transaction and delegates the full-sale ledger entry to the cost-adjustment service. React exposes a replacement drawer from each positive active holding, submits once, then invalidates every holdings-derived view. Market-data refresh remains outside the transaction.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, async SQLAlchemy, PostgreSQL, pytest/httpx, React 19, TypeScript, TanStack Query, Vitest, Testing Library, MSW, Playwright.

## Global Constraints

- Keep production code generic; never hard-code SPY, VOO, or 标普 500.
- Replacement is full only: source quantity becomes zero and the row is archived atomically with target creation.
- Never rename the source or rewrite historical snapshots.
- Do not calculate realized P&L, proceeds, tax, fees, or cash flow.
- The target becomes the source asset class's only active preferred rebalance holding.
- Any failure leaves the source and its adjustment history unchanged.
- Never call a market-data provider inside the replacement transaction.
- Preserve decimals as strings across HTTP and TypeScript boundaries.
- Use focused red-green tests and commit after every independently reviewable task.

## File Structure

- `backend/app/schemas/holding.py`: replacement request and response contracts.
- `backend/app/services/cost_adjustments.py`: transaction-local full-sale ledger helper.
- `backend/app/services/holdings.py`: locks, orchestration, target creation, invariants.
- `backend/app/api/routes/holdings.py`: replacement endpoint and error transport.
- `backend/tests/integration/test_holdings_api.py`: atomic behavior and error coverage.
- `frontend/src/api/types.ts`: client contracts.
- `frontend/src/features/holdings/api.ts`: mutation and invalidation.
- `frontend/src/components/WorkDrawer/WorkDrawer.tsx`: pending close lock.
- `frontend/tests/WorkDrawer.test.tsx`: close-lock behavior.
- `frontend/src/features/holdings/ReplacementDrawer.tsx`: guided form and summary.
- `frontend/src/features/holdings/HoldingActionMenu.tsx`: replacement command.
- `frontend/src/pages/HoldingsPage.tsx`: drawer lifecycle.
- `frontend/src/features/holdings/Holdings.module.css`: replacement presentation.
- `frontend/tests/HoldingsPage.test.tsx`: form, request, failure, success, caches.
- `frontend/tests/HoldingsTableMobileDetails.test.tsx`: mobile command reachability.
- `frontend/e2e/fixtures/portfolio.ts`: stateful mock replacement.
- `frontend/e2e/holdings-cost.spec.ts`: complete user workflow.
- `docs/user-guide.md`: supported workflow and accounting boundary.

---

### Task 1: Atomic replacement backend command

**Files:**
- Modify: `backend/app/schemas/holding.py`
- Modify: `backend/app/services/cost_adjustments.py`
- Modify: `backend/app/services/holdings.py`
- Modify: `backend/app/api/routes/holdings.py`
- Test: `backend/tests/integration/test_holdings_api.py`

**Interfaces:**
- Produces: `HoldingReplacementRequest`, `HoldingReplacementResponse`.
- Produces: `record_full_sale(session, holding, note) -> CostAdjustment`; caller owns the row lock.
- Produces: `replace_holding(session, holding_id, payload) -> HoldingReplacementResponse`.
- Produces: `POST /api/holdings/{holding_id}/replace`.

- [ ] **Step 1: Write the failing happy-path and ledger test**

```python
from decimal import Decimal

from app.db.models import CostAdjustment


def _replacement_payload(source_version: int = 1, **overrides: object):
    payload = {
        "source_version": source_version,
        "symbol": "VOO",
        "name": "Vanguard S&P 500 ETF",
        "market": "US",
        "account_name": "港资券商",
        "trade_currency": "USD",
        "quantity": "8",
        "average_cost_price": "625.40",
        "cost_fx_to_cny": "7.18",
        "baseline_fx_to_cny": "7.15",
        "lot_size": "1",
        "quantity_precision": 0,
        "preferred_data_source": "yahoo",
        "note": "全部卖出 SPY 后换入 VOO",
    }
    payload.update(overrides)
    return payload


async def test_replace_holding_records_sale_archives_source_and_prefers_target(
    api_client, asset_class_id, db_session
):
    source = (await api_client.post(
        "/api/holdings", json=_holding_payload(asset_class_id)
    )).json()
    response = await api_client.post(
        f"/api/holdings/{source['id']}/replace",
        json=_replacement_payload(source["version"]),
    )
    assert response.status_code == 200
    result = response.json()
    assert (result["source"]["symbol"], result["source"]["quantity"],
            result["source"]["is_active"]) == ("SPY", "0", False)
    assert (result["target"]["symbol"], result["target"]["quantity"],
            result["target"]["is_rebalance_preferred"]) == ("VOO", "8", True)
    assert [item["symbol"] for item in (await api_client.get("/api/holdings")).json()] == ["VOO"]
    history = list(await db_session.scalars(select(CostAdjustment).where(
        CostAdjustment.holding_id == source["id"])))
    assert [(history[0].operation_type, history[0].before_quantity,
             history[0].after_quantity, history[0].note)] == [
        ("SELL", Decimal("10"), Decimal("0"), "全部卖出 SPY 后换入 VOO")
    ]
```

- [ ] **Step 2: Run it and verify the endpoint is red**

Run:

```powershell
docker compose exec api pytest tests/integration/test_holdings_api.py::test_replace_holding_records_sale_archives_source_and_prefers_target -q
```

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Add the exact backend contracts**

Add an independent request model; do not expose `asset_class_id` or `is_rebalance_preferred`:

```python
class HoldingReplacementRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)
    source_version: int
    symbol: str
    name: str
    market: str
    account_name: str
    trade_currency: str
    quantity: DecimalString
    average_cost_price: DecimalString
    cost_fx_to_cny: DecimalString
    baseline_fx_to_cny: DecimalString
    lot_size: DecimalString
    quantity_precision: int
    preferred_data_source: Literal[
        "yahoo", "sina", "akshare", "tushare", "alpha_vantage"
    ] | None = None
    note: str | None = None

    @field_validator("market")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        try:
            return normalize_market_code(value)
        except ValueError as exc:
            raise PydanticCustomError("holding_market_invalid",
                "Market must be one of US, SH, or SZ.", {"field": "market"}) from exc

    @field_validator("trade_currency")
    @classmethod
    def normalize_trade_currency(cls, value: str) -> str:
        try:
            return normalize_currency_code(value)
        except ValueError as exc:
            raise PydanticCustomError("holding_trade_currency_invalid",
                "Trade currency must be exactly three ASCII letters.",
                {"field": "trade_currency"}) from exc

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise PydanticCustomError("holding_replacement_quantity_invalid",
                "Replacement quantity must be positive.", {"field": "quantity"})
        return value

    @field_validator("average_cost_price", "cost_fx_to_cny",
                     "baseline_fx_to_cny", "lot_size")
    @classmethod
    def non_negative_decimal(cls, value: Decimal, info) -> Decimal:
        return _ensure_non_negative(value, info.field_name)

    @field_validator("source_version", "quantity_precision")
    @classmethod
    def non_negative_integer(cls, value: int, info) -> int:
        if value < 0:
            raise PydanticCustomError("negative_numeric_field",
                "{field} must be non-negative.", {"field": info.field_name})
        return value


class HoldingReplacementResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: HoldingResponse
    target: HoldingResponse
```

- [ ] **Step 4: Add a single full-sale ledger helper**

```python
async def record_full_sale(session: AsyncSession, holding: Holding,
                           note: str | None) -> CostAdjustment:
    before = _holding_cost_basis(holding)
    if before.quantity <= 0:
        raise ServiceError(409, "HOLDING_REPLACEMENT_SOURCE_EMPTY",
                           "Replacement requires a positive source quantity.")
    after = _storage_basis(sell_quantity(before, before.quantity))
    normalized_note = _normalized_optional_note(note)
    holding.quantity = after.quantity
    holding.average_cost_price = after.average_price
    holding.cost_fx_to_cny = after.cost_fx
    holding.updated_at = utcnow()
    adjustment = CostAdjustment(
        holding_id=holding.id, operation_type="SELL",
        before_quantity=before.quantity,
        before_average_cost_price=before.average_price,
        before_cost_fx_to_cny=before.cost_fx,
        after_quantity=after.quantity,
        after_average_cost_price=after.average_price,
        after_cost_fx_to_cny=after.cost_fx,
        input_summary={"quantity": _decimal_string(before.quantity),
                       "note": normalized_note, "reason": "holding_replacement"},
        note=normalized_note, created_at=utcnow(),
    )
    session.add(adjustment)
    await session.flush()
    return adjustment
```

- [ ] **Step 5: Implement locked orchestration**

```python
async def replace_holding(session: AsyncSession, holding_id: UUID,
                          payload: HoldingReplacementRequest
                          ) -> HoldingReplacementResponse:
    await _lock_active_asset_classes(session)
    source = await _get_active_holding(session, holding_id, lock=True)
    if source.version != payload.source_version:
        raise ServiceError(409, "HOLDING_VERSION_CONFLICT",
            "Holding was modified after replacement was opened.",
            {"current_version": source.version})
    if source.quantity <= 0:
        raise ServiceError(409, "HOLDING_REPLACEMENT_SOURCE_EMPTY",
                           "Replacement requires a positive source quantity.")
    await _get_active_holdings_for_asset_class(session, source.asset_class_id, lock=True)
    cost_fx, baseline_fx = _normalized_fx_values(
        payload.trade_currency, payload.cost_fx_to_cny, payload.baseline_fx_to_cny)
    await record_full_sale(session, source, payload.note)
    source.is_active = False
    source.is_rebalance_preferred = False
    target = Holding(
        asset_class_id=source.asset_class_id, symbol=payload.symbol,
        name=payload.name, market=payload.market,
        account_name=payload.account_name, trade_currency=payload.trade_currency,
        quantity=payload.quantity, average_cost_price=payload.average_cost_price,
        cost_fx_to_cny=cost_fx, baseline_fx_to_cny=baseline_fx,
        lot_size=payload.lot_size, quantity_precision=payload.quantity_precision,
        preferred_data_source=payload.preferred_data_source,
        is_rebalance_preferred=True,
    )
    session.add(target)
    await session.flush()
    await _enforce_preferred_holding(session, source.asset_class_id, target)
    await session.flush()
    return HoldingReplacementResponse(
        source=HoldingResponse.model_validate(source),
        target=HoldingResponse.model_validate(target),
    )
```

- [ ] **Step 6: Register the route using the existing transaction wrapper**

```python
@router.post("/holdings/{holding_id}/replace",
             response_model=HoldingReplacementResponse)
async def post_replace_holding(
    holding_id: UUID, payload: HoldingReplacementRequest,
    session: AsyncSession = Depends(get_session),
) -> HoldingReplacementResponse:
    return await _run_write(
        session, lambda: replace_holding(session, holding_id, payload))
```

Broaden `_run_write`'s annotation to the union response type; keep its existing `ServiceError`, `StaleDataError`, and unique-index mapping.

- [ ] **Step 7: Run happy-path and ledger regressions**

```powershell
docker compose exec api pytest tests/integration/test_holdings_api.py::test_replace_holding_records_sale_archives_source_and_prefers_target tests/integration/test_cost_adjustments_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Add validation and rollback tests**

```python
async def test_replace_duplicate_target_rolls_back_source(api_client, asset_class_id):
    source = (await api_client.post(
        "/api/holdings", json=_holding_payload(asset_class_id))).json()
    await api_client.post("/api/holdings", json=_holding_payload(
        asset_class_id, symbol="VOO", name="Vanguard S&P 500 ETF",
        is_rebalance_preferred=False))
    response = await api_client.post(
        f"/api/holdings/{source['id']}/replace",
        json=_replacement_payload(source["version"]))
    assert response.status_code == 409
    active = (await api_client.get("/api/holdings")).json()
    spy = next(item for item in active if item["id"] == source["id"])
    assert (spy["quantity"], spy["is_active"]) == ("10", True)
    assert (await api_client.get(
        f"/api/cost-adjustments/{source['id']}")).json()["items"] == []
```

Add exact cases for zero target quantity (422), empty source (409 `HOLDING_REPLACEMENT_SOURCE_EMPTY`), stale version (409 `HOLDING_VERSION_CONFLICT`), invalid market/currency/FX, CNY FX normalization, and concurrent source modification. Every failed case must assert SPY is still active and no replacement sale exists.

- [ ] **Step 9: Run the complete backend file**

```powershell
docker compose exec api pytest tests/integration/test_holdings_api.py -q
```

Expected: PASS with no transaction leakage.

- [ ] **Step 10: Commit**

```powershell
git add backend/app/schemas/holding.py backend/app/services/cost_adjustments.py backend/app/services/holdings.py backend/app/api/routes/holdings.py backend/tests/integration/test_holdings_api.py
git commit -m "feat: replace holdings atomically"
```

---

### Task 2: Prevent drawer closure while submitting

**Files:**
- Modify: `frontend/src/components/WorkDrawer/WorkDrawer.tsx`
- Test: `frontend/tests/WorkDrawer.test.tsx`

**Interfaces:**
- Produces: optional `closeDisabled?: boolean`.
- Guarantees: button, backdrop, and Escape cannot close the top drawer while true.

- [ ] **Step 1: Write the failing close-lock test**

```tsx
it("blocks every close path while closeDisabled is true", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  render(<WorkDrawer open title="替换标的 · SPY" onClose={onClose} closeDisabled>内容</WorkDrawer>);
  expect(screen.getByRole("button", { name: "关闭工作抽屉" })).toBeDisabled();
  await user.keyboard("{Escape}");
  await user.click(document.querySelector(".work-drawer-backdrop")!);
  expect(onClose).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run it red**

```powershell
cd frontend
npm test -- WorkDrawer.test.tsx
```

Expected: FAIL because the prop is absent.

- [ ] **Step 3: Implement the guarded close path**

```tsx
type WorkDrawerProps = PropsWithChildren<{
  open: boolean; title: string; onClose: () => void;
  footer?: React.ReactNode; closeDisabled?: boolean;
}>;
```

Keep the registered callback current without rebuilding the drawer stack entry:

```tsx
const closeDisabledRef = useRef(closeDisabled);
useEffect(() => { closeDisabledRef.current = closeDisabled; }, [closeDisabled]);

function requestClose() {
  if (!closeDisabledRef.current && isTopDrawer(drawerIdentity)) {
    onCloseRef.current();
  }
}
```

Use `requestClose` for the registered Escape callback, backdrop, and close button. Add `disabled={closeDisabled}` to the close button. Default false so existing drawers do not change.

- [ ] **Step 4: Run the complete WorkDrawer test file**

```powershell
cd frontend
npm test -- WorkDrawer.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/WorkDrawer/WorkDrawer.tsx frontend/tests/WorkDrawer.test.tsx
git commit -m "feat: lock work drawer while submitting"
```

---

### Task 3: Client contract and invalidation

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/holdings/api.ts`
- Test: `frontend/tests/HoldingsPage.test.tsx`

**Interfaces:**
- Produces: `HoldingReplacementRequest`, `HoldingReplacementResponse`, `useReplaceHolding()`.
- Invalidates: holdings, source adjustment history, analytics, market data, snapshots.

- [ ] **Step 1: Add a failing hook-harness invalidation test**

```tsx
function ReplaceHarness({ holding }: { holding: Holding }) {
  const replace = useReplaceHolding();
  return <button onClick={() => void replace.mutateAsync({
    holdingId: holding.id,
    payload: { source_version: holding.version, symbol: "VOO",
      name: "Vanguard S&P 500 ETF", market: "US",
      account_name: holding.account_name, trade_currency: "USD", quantity: "8",
      average_cost_price: "625.40", cost_fx_to_cny: "7.18",
      baseline_fx_to_cny: "7.15", lot_size: "1", quantity_precision: 0,
      preferred_data_source: "yahoo", note: null },
  })}>替换</button>;
}
```

Seed and assert invalidation for `holdingsQueryKey(false)`, `holdingsQueryKey(true)`, `costAdjustmentsQueryKey(id)`, `portfolioAnalyticsKey`, `marketDataQueryKey`, and `[...snapshotsQueryRoot, {}]`.

- [ ] **Step 2: Run it red**

```powershell
cd frontend
npm test -- HoldingsPage.test.tsx
```

Expected: FAIL because replacement types/hook are absent.

- [ ] **Step 3: Add exact client types**

```ts
export interface HoldingReplacementRequest {
  source_version: number; symbol: string; name: string; market: string;
  account_name: string; trade_currency: string; quantity: DecimalString;
  average_cost_price: DecimalString; cost_fx_to_cny: DecimalString;
  baseline_fx_to_cny: DecimalString; lot_size: DecimalString;
  quantity_precision: number; preferred_data_source: ProviderName | null;
  note: string | null;
}
export interface HoldingReplacementResponse { source: Holding; target: Holding; }
```

- [ ] **Step 4: Implement the mutation**

```ts
export function useReplaceHolding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ holdingId, payload }: { holdingId: string; payload: HoldingReplacementRequest }) =>
      apiRequest<HoldingReplacementResponse>(`/api/holdings/${holdingId}/replace`, {
        method: "POST", body: jsonBody(payload),
      }),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: holdingsQueryRoot });
      void queryClient.invalidateQueries({ queryKey: costAdjustmentsQueryKey(variables.holdingId) });
      void queryClient.invalidateQueries({ queryKey: portfolioAnalyticsKey });
      void queryClient.invalidateQueries({ queryKey: marketDataQueryKey });
      void queryClient.invalidateQueries({ queryKey: snapshotsQueryRoot });
    },
  });
}
```

Rebalance previews/plans are mutations, not persistent queries; do not invent a cache key.

- [ ] **Step 5: Run test and typecheck**

```powershell
cd frontend
npm test -- HoldingsPage.test.tsx
npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/api/types.ts frontend/src/features/holdings/api.ts frontend/tests/HoldingsPage.test.tsx
git commit -m "feat: add holding replacement client"
```

---

### Task 4: Guided replacement UI

**Files:**
- Create: `frontend/src/features/holdings/ReplacementDrawer.tsx`
- Modify: `frontend/src/features/holdings/HoldingActionMenu.tsx`
- Modify: `frontend/src/pages/HoldingsPage.tsx`
- Modify: `frontend/src/features/holdings/Holdings.module.css`
- Test: `frontend/tests/HoldingsPage.test.tsx`
- Test: `frontend/tests/HoldingsTableMobileDetails.test.tsx`

**Interfaces:**
- Consumes: `useReplaceHolding()` and `WorkDrawer.closeDisabled`.
- Produces: `ReplacementDrawer({ holding, open, onClose, onReplaced })`.
- Extends: `HoldingCommand` with `"replace"`.

- [ ] **Step 1: Write failing menu/default tests**

```tsx
await user.click(await screen.findByRole("button", { name: "更多 SPY 操作" }));
await user.click(screen.getByRole("menuitem", { name: "替换标的" }));
expect(screen.getByRole("dialog", { name: "替换标的 · SPY" })).toBeInTheDocument();
expect(screen.getByText("SPY → 新标的")).toBeInTheDocument();
expect(screen.getByRole("textbox", { name: "账户名称" })).toHaveValue(holdingFixture.account_name);
expect(screen.getByRole("textbox", { name: "上市市场" })).toHaveValue("US");
expect(screen.getByRole("combobox", { name: "交易币种" })).toHaveValue("USD");
```

Add a mobile-detail test that reaches the same menu item. Add a zero-quantity fixture assertion that no replacement menu item is rendered.

- [ ] **Step 2: Run tests red**

```powershell
cd frontend
npm test -- HoldingsPage.test.tsx HoldingsTableMobileDetails.test.tsx
```

Expected: FAIL because the command is absent.

- [ ] **Step 3: Add the command and page lifecycle**

```ts
export type HoldingCommand = "purchase" | "sell" | "correction" |
  "history" | "replace" | "archive";
```

Render a `RefreshCw` menu item only for active positive holdings. Mount the drawer in `HoldingsPage`:

```tsx
{notice ? <div className={styles.notice} role="status">{notice}</div> : null}
{selected ? <ReplacementDrawer holding={selected} open={drawer === "replace"}
  onClose={closeDrawer} onReplaced={(target) => {
    closeDrawer(); setShowArchived(false);
    setNotice(`${target.symbol} 已成为新的默认调整标的。`);
  }} /> : null}
```

Add `const [notice, setNotice] = useState<string | null>(null)` and clear it before starting another command. Change the drawer callback signature to `onReplaced: (target: Holding) => void`, passing `result.target` after `mutateAsync` succeeds.

- [ ] **Step 4: Build the controlled drawer**

Create states for target symbol/name/quantity/cost, inherited account/market/currency/FX/lot/precision/provider, optional note, advanced toggle, and server error. Submit the exact request:

```tsx
const result = await replace.mutateAsync({ holdingId: holding.id, payload: {
  source_version: holding.version,
  symbol: symbol.trim().toUpperCase(), name: name.trim(),
  market, account_name: accountName, trade_currency: currency,
  quantity, average_cost_price: averageCost,
  cost_fx_to_cny: currency === "CNY" ? "1" : costFx,
  baseline_fx_to_cny: currency === "CNY" ? "1" : baselineFx,
  lot_size: lotSize, quantity_precision: Number.parseInt(precision, 10),
  preferred_data_source: preferredDataSource || null,
  note: note.trim() || null,
}});
onReplaced(result.target);
```

Use `WorkDrawer closeDisabled={replace.isPending}`. Show a read-only source summary, basic target fields, expandable inherited settings, and explicit outcomes: source sold/archived, target created/preferred, snapshots unchanged, no realized P&L. Button text is `正在替换` or `确认替换为 ${symbol || "新标的"}`.

- [ ] **Step 5: Add pending and failure-retention tests**

```tsx
expect(screen.getByRole("button", { name: "正在替换" })).toBeDisabled();
expect(screen.getByRole("button", { name: "关闭工作抽屉" })).toBeDisabled();
response.resolve(HttpResponse.json({ detail: {
  code: "HOLDING_ALREADY_EXISTS", message: "该账户已存在 VOO。"
}}, { status: 409 }));
expect(await screen.findByRole("alert")).toHaveTextContent("该账户已存在 VOO");
expect(screen.getByRole("textbox", { name: "目标代码" })).toHaveValue("VOO");
```

- [ ] **Step 6: Add success/body assertions**

Capture POST JSON, return `{ source, target }`, mutate the MSW holdings state, and assert `source_version`, inherited settings, unchanged decimal strings, optional note, active VOO, hidden active SPY, and the status message `VOO 已成为新的默认调整标的。`.

- [ ] **Step 7: Run focused UI verification**

```powershell
cd frontend
npm test -- HoldingsPage.test.tsx HoldingsTableMobileDetails.test.tsx WorkDrawer.test.tsx
npm run typecheck
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/features/holdings/ReplacementDrawer.tsx frontend/src/features/holdings/HoldingActionMenu.tsx frontend/src/pages/HoldingsPage.tsx frontend/src/features/holdings/Holdings.module.css frontend/tests/HoldingsPage.test.tsx frontend/tests/HoldingsTableMobileDetails.test.tsx
git commit -m "feat: guide full holding replacement"
```

---

### Task 5: End-to-end workflow and user guide

**Files:**
- Modify: `frontend/e2e/fixtures/portfolio.ts`
- Modify: `frontend/e2e/holdings-cost.spec.ts`
- Modify: `docs/user-guide.md`

**Interfaces:**
- Produces: stateful mocked replacement and user-facing instructions.

- [ ] **Step 1: Add a failing E2E scenario**

```ts
test("fully replaces SPY with VOO and retains archived SPY", async ({ page }) => {
  await seedPortfolio(page, "balanced");
  await page.goto("/holdings");
  await page.getByRole("button", { name: "更多 SPY 操作" }).click();
  await page.getByRole("menuitem", { name: "替换标的" }).click();
  await page.getByRole("textbox", { name: "目标代码" }).fill("VOO");
  await page.getByRole("textbox", { name: "目标名称" }).fill("Vanguard S&P 500 ETF");
  await page.getByRole("textbox", { name: "实际买入份额" }).fill("8");
  await page.getByRole("textbox", { name: "平均成本价" }).fill("625.40");
  await page.getByRole("button", { name: "确认替换为 VOO" }).click();
  await expect(page.getByText("VOO")).toBeVisible();
  await expect(page.getByText("SPY")).not.toBeVisible();
  await page.getByRole("checkbox", { name: "仅显示已归档持仓" }).check();
  await expect(page.getByText("SPY")).toBeVisible();
});
```

- [ ] **Step 2: Run it red**

```powershell
cd frontend
npx playwright test e2e/holdings-cost.spec.ts --grep "fully replaces"
```

Expected: FAIL because the fixture does not mutate holdings.

- [ ] **Step 3: Add stateful fixture behavior**

Make holdings mutable; filter GET by `include_archived`; handle the replacement POST:

```ts
if (/^\/api\/holdings\/[^/]+\/replace$/.test(path) && route.request().method() === "POST") {
  const payload = route.request().postDataJSON();
  const sourceIndex = holdings.findIndex((item: any) => path.includes(item.id));
  const source = { ...holdings[sourceIndex] as any, quantity: "0",
    average_cost_price: "0", cost_fx_to_cny: "0",
    is_active: false, is_rebalance_preferred: false };
  const target = { ...payload, id: "holding-voo",
    asset_class_id: source.asset_class_id, is_active: true,
    is_rebalance_preferred: true, version: 1 };
  holdings.splice(sourceIndex, 1, source, target);
  return route.fulfill({ json: { source, target } });
}
```

- [ ] **Step 4: Document usage and accounting scope**

```markdown
## 完整替换持仓标的

如果已经在券商中全部卖出旧标的并买入同类新标的，请在旧持仓的“更多操作”中选择“替换标的”。填写新标的实际份额、平均成本价和成本汇率后，系统会在一次操作中将旧持仓归零并归档、创建新持仓，并把新持仓设为该资产类别的默认调整标的。

替换不会重命名或改写旧持仓和历史快照，也不会计算卖出收入、税费或已实现盈亏。若只卖出了部分旧持仓，请分别使用“卖出调整”和“添加持仓”。
```

- [ ] **Step 5: Run feature and full suites**

```powershell
cd frontend
npx playwright test e2e/holdings-cost.spec.ts
npm test
npm run typecheck
cd ..
docker compose exec api pytest -q
```

Expected: every command exits 0.

- [ ] **Step 6: Commit**

```powershell
git add frontend/e2e/fixtures/portfolio.ts frontend/e2e/holdings-cost.spec.ts docs/user-guide.md
git commit -m "test: cover holding replacement workflow"
```

---

### Task 6: Final verification and review

**Files:**
- Review: all files changed in Tasks 1–5.

**Interfaces:**
- Produces: verification evidence and a review-ready branch.

- [ ] **Step 1: Verify scope and cleanliness**

```powershell
git status --short
git log --oneline -8
git diff HEAD~5 --check
```

Expected: clean tree, five feature commits, no whitespace errors.

- [ ] **Step 2: Run final verification**

```powershell
docker compose exec api pytest -q
cd frontend
npm test
npm run typecheck
npx playwright test e2e/holdings-cost.spec.ts
```

Expected: every command exits 0.

- [ ] **Step 3: Inspect behavior safely**

Use automated fixtures or a temporary database to verify `SPY → VOO`: active VOO, archived zero-quantity SPY, VOO preferred for rebalancing. Never run a replacement against the user's real portfolio merely as a test.

- [ ] **Step 4: Request review**

Use `requesting-code-review`. Review spec compliance first, then code quality, emphasizing transaction rollback, unique preferred-holding invariants, stale source versions, cache invalidation, and form-input retention.

- [ ] **Step 5: Resolve accepted findings with regression tests**

For each finding, write or update a failing focused test, implement the smallest correction, rerun the focused test, then rerun Task 6 Step 2.
