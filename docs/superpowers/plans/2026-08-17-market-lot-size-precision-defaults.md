# Market Lot Size and Quantity Precision Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the broken holdings response, give US and A-share holdings safe editable market defaults, and prevent invalid lot sizes or quantity precision from entering any holding write path.

**Architecture:** Keep market defaults in the add-holding UI because they are editable presentation defaults, while enforcing market-independent safety bounds in all three backend request schemas. Verify both layers independently, then deploy the merged code and repair only the affected production holding through the normal PATCH API.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, FastAPI, Pydantic v2, SQLAlchemy async, pytest, Docker Compose, PostgreSQL 17

## Global Constraints

- Supported markets remain exactly `US`, `SH`, and `SZ`; do not add Hong Kong or HKD support.
- Market defaults are `US -> lot_size="0.01", quantity_precision=2`, `SH/SZ -> lot_size="100", quantity_precision=0`.
- Defaults remain editable; the backend must preserve every legal custom value instead of overwriting it from `market`.
- Every holding write path requires `lot_size > 0` and integer `0 <= quantity_precision <= 12`.
- Do not add a database migration, database constraint, or batch rewrite.
- Repair only holding `9855dbdf-42fb-4dc9-853f-e08477809c93` (`563020`) after the validated code is merged and deployed.
- The repair changes only `lot_size: 1 -> 100` and `quantity_precision: 100 -> 0`; the normal API may increment `version` once and update `updated_at`.
- Preserve quantity `15000`, identity, asset class, cost, FX, provider, preference, active state, and every other business field.
- Production must remain attached to `portfolio-rebalancer_postgres_data`; never run `down -v`, truncate tables, or operate tests against the production Compose project.
- Backend database tests run only through `make test-backend` with the isolated `portfolio_test` database.

---

### Task 1: Enforce Backend Holding Bounds on Create, Update, and Replacement

**Files:**
- Modify: `backend/app/schemas/holding.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/integration/test_holdings_api.py`

**Interfaces:**
- Consumes: existing `HoldingCreate`, `HoldingUpdate`, and `HoldingReplacementRequest` Pydantic models.
- Produces: `_ensure_positive_lot_size(value: Decimal) -> Decimal` and `_ensure_quantity_precision(value: int) -> int`; structured `HOLDING_LOT_SIZE_INVALID` and `HOLDING_QUANTITY_PRECISION_INVALID` API errors.

- [ ] **Step 1: Add failing backend tests for all write paths and serializer boundaries**

Add these focused contracts to `backend/tests/integration/test_holdings_api.py` next to the existing negative-number and replacement precision tests:

```python
@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"lot_size": "0"}, "HOLDING_LOT_SIZE_INVALID", "lot_size"),
        ({"lot_size": "-1"}, "HOLDING_LOT_SIZE_INVALID", "lot_size"),
        (
            {"quantity_precision": 13},
            "HOLDING_QUANTITY_PRECISION_INVALID",
            "quantity_precision",
        ),
    ],
)
async def test_create_holding_rejects_unsafe_trade_unit_fields(
    api_client,
    asset_class_id,
    overrides: dict[str, object],
    code: str,
    field: str,
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(asset_class_id, **overrides),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["field"] == field
    assert (await api_client.get("/api/holdings")).json() == []


@pytest.mark.parametrize(
    ("payload", "code", "field"),
    [
        ({"lot_size": "0"}, "HOLDING_LOT_SIZE_INVALID", "lot_size"),
        ({"lot_size": "-1"}, "HOLDING_LOT_SIZE_INVALID", "lot_size"),
        (
            {"quantity_precision": 13},
            "HOLDING_QUANTITY_PRECISION_INVALID",
            "quantity_precision",
        ),
    ],
)
async def test_patch_holding_rejects_unsafe_trade_unit_fields_without_mutation(
    api_client,
    asset_class_id,
    payload: dict[str, object],
    code: str,
    field: str,
) -> None:
    created = (
        await api_client.post("/api/holdings", json=_holding_payload(asset_class_id))
    ).json()

    response = await api_client.patch(
        f"/api/holdings/{created['id']}",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["field"] == field
    assert (await api_client.get("/api/holdings")).json() == [created]


@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"lot_size": "0"}, "HOLDING_LOT_SIZE_INVALID", "lot_size"),
        ({"lot_size": "-1"}, "HOLDING_LOT_SIZE_INVALID", "lot_size"),
        (
            {"quantity_precision": 13},
            "HOLDING_QUANTITY_PRECISION_INVALID",
            "quantity_precision",
        ),
    ],
)
async def test_replace_holding_rejects_unsafe_trade_unit_fields_without_mutation(
    api_client,
    asset_class_id,
    overrides: dict[str, object],
    code: str,
    field: str,
) -> None:
    source = (
        await api_client.post("/api/holdings", json=_holding_payload(asset_class_id))
    ).json()

    response = await api_client.post(
        f"/api/holdings/{source['id']}/replace",
        json=_replacement_payload(source["version"], **overrides),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["field"] == field
    await _assert_source_active_without_adjustments(api_client, source["id"])
    assert (await api_client.get("/api/holdings")).json()[0]["version"] == 1


@pytest.mark.parametrize(
    ("quantity_precision", "expected_quantity"),
    [(0, "15000"), (12, "15000.000000000000")],
)
async def test_holding_quantity_precision_boundaries_serialize(
    api_client,
    asset_class_id,
    quantity_precision: int,
    expected_quantity: str,
) -> None:
    response = await api_client.post(
        "/api/holdings",
        json=_holding_payload(
            asset_class_id,
            quantity="15000",
            lot_size="0.01",
            quantity_precision=quantity_precision,
        ),
    )

    assert response.status_code == 201
    assert response.json()["quantity"] == expected_quantity
```

Replace the existing single-purpose `test_replace_rejects_quantity_precision_above_response_limit_without_changing_source` with the parametrized replacement contract above to avoid duplicate coverage.

- [ ] **Step 2: Run the backend holding suite and verify RED**

Run from PowerShell:

```powershell
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/market-holding-defaults `
  /usr/bin/make test-backend "PYTEST_ARGS=-q tests/integration/test_holdings_api.py"
```

Expected: new create and patch cases accept `quantity_precision=13`; all three paths accept `lot_size=0`, while negative lot sizes use the old generic non-negative error; response bodies do not contain the new stable structured error codes. Existing valid tests remain green.

- [ ] **Step 3: Add reusable backend validators**

Add near `_ensure_non_negative` in `backend/app/schemas/holding.py`:

```python
MAX_QUANTITY_PRECISION = 12


def _ensure_positive_lot_size(value: Decimal) -> Decimal:
    if value <= 0:
        raise PydanticCustomError(
            "holding_lot_size_invalid",
            "Lot size must be positive.",
            {"field": "lot_size"},
        )
    return value


def _ensure_quantity_precision(value: int) -> int:
    if value < 0:
        raise PydanticCustomError(
            "negative_numeric_field",
            "{field} must be non-negative.",
            {"field": "quantity_precision"},
        )
    if value > MAX_QUANTITY_PRECISION:
        raise PydanticCustomError(
            "holding_quantity_precision_invalid",
            "Quantity precision must be between 0 and 12.",
            {"field": "quantity_precision"},
        )
    return value
```

For each of `HoldingReplacementRequest`, `HoldingCreate`, and `HoldingUpdate`:

- remove `lot_size` from the non-negative multi-field validator;
- add a `lot_size` validator that returns `_ensure_positive_lot_size(value)` (return `None` unchanged for `HoldingUpdate`);
- route `quantity_precision` through `_ensure_quantity_precision` (return `None` unchanged for `HoldingUpdate`);
- remove `Field(le=12)` from `HoldingReplacementRequest.quantity_precision` so the shared custom validator owns both bounds;
- keep `source_version` on its existing non-negative validation path.

Use these exact validator shapes for the required and optional models:

```python
@field_validator("lot_size")
@classmethod
def validate_lot_size(cls, value: Decimal) -> Decimal:
    return _ensure_positive_lot_size(value)

@field_validator("quantity_precision")
@classmethod
def validate_quantity_precision(cls, value: int) -> int:
    return _ensure_quantity_precision(value)
```

```python
@field_validator("lot_size")
@classmethod
def validate_lot_size(cls, value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _ensure_positive_lot_size(value)

@field_validator("quantity_precision")
@classmethod
def validate_quantity_precision(cls, value: int | None) -> int | None:
    if value is None:
        return None
    return _ensure_quantity_precision(value)
```

- [ ] **Step 4: Map the new validation errors to stable API details**

Extend `holding_validation_errors` in `backend/app/main.py`:

```python
"holding_lot_size_invalid": (
    "HOLDING_LOT_SIZE_INVALID",
    "Lot size must be positive.",
),
"holding_quantity_precision_invalid": (
    "HOLDING_QUANTITY_PRECISION_INVALID",
    "Quantity precision must be between 0 and 12.",
),
```

Keep the existing field extraction and 422 response shape unchanged.

- [ ] **Step 5: Run the focused backend suite and verify GREEN**

Re-run the Step 2 command.

Expected: all holding integration tests pass; each invalid request returns the exact code and field; valid precision 0 and 12 serialize successfully.

- [ ] **Step 6: Commit backend safety bounds**

```bash
git add backend/app/schemas/holding.py backend/app/main.py backend/tests/integration/test_holdings_api.py
git commit -m "fix: validate holding trade unit fields"
```

---

### Task 2: Add Editable Market Defaults and Frontend Validation

**Files:**
- Modify: `frontend/src/features/holdings/AddHoldingDrawer.tsx`
- Modify: `frontend/tests/HoldingsPage.test.tsx`

**Interfaces:**
- Consumes: existing `HoldingCreate` payload with `lot_size: string` and `quantity_precision: number`.
- Produces: market-change defaults and client-side `lot_size > 0`, integer `0..12` validation.

- [ ] **Step 1: Update existing payload expectations and add failing market-default contracts**

In `frontend/tests/HoldingsPage.test.tsx`:

- change the US create workflow expectation from `lot_size: "1"` to `lot_size: "0.01"` and add `quantity_precision: 2`;
- extend the Shanghai submission expectation with `lot_size: "100"` and `quantity_precision: 0`;
- add this market-switch and editable-override test:

```tsx
it("applies editable trade-unit defaults whenever the market changes", async () => {
  const user = userEvent.setup();
  let body: Record<string, unknown> | undefined;
  renderWithProviders(<HoldingsPage />, { handlers: [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => HttpResponse.json([])),
    http.post("/api/holdings", async ({ request }) => {
      body = await request.json() as Record<string, unknown>;
      return HttpResponse.json(holdingFixture, { status: 201 });
    }),
  ] });

  await user.click(await screen.findByRole("button", { name: "添加第一个持仓" }));
  await user.type(screen.getByRole("textbox", { name: "标的代码" }), "563020");
  await user.type(screen.getByRole("textbox", { name: "标的名称" }), "A 股 ETF");
  await user.type(screen.getByRole("textbox", { name: "账户名称" }), "证券账户");
  await user.click(screen.getByText("高级设置"));

  const market = screen.getByRole("combobox", { name: "上市市场" });
  const lotSize = screen.getByRole("textbox", { name: "最小交易单位" });
  const precision = screen.getByRole("textbox", { name: "份额小数位" });

  await user.selectOptions(market, "US");
  expect(lotSize).toHaveValue("0.01");
  expect(precision).toHaveValue("2");

  await user.selectOptions(market, "SH");
  expect(lotSize).toHaveValue("100");
  expect(precision).toHaveValue("0");

  await user.clear(lotSize);
  await user.type(lotSize, "50");
  await user.clear(precision);
  await user.type(precision, "1");
  await user.click(screen.getByRole("button", { name: "创建持仓" }));

  await waitFor(() => expect(body).toMatchObject({
    market: "SH",
    lot_size: "50",
    quantity_precision: 1,
  }));
});
```

Add a client validation test that makes two attempts and proves no request is sent:

```tsx
it("blocks unsafe lot size and quantity precision before submit", async () => {
  const user = userEvent.setup();
  let requestCount = 0;
  renderWithProviders(<HoldingsPage />, { handlers: [
    http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
    http.get("/api/holdings", () => HttpResponse.json([])),
    http.post("/api/holdings", () => {
      requestCount += 1;
      return HttpResponse.json(holdingFixture, { status: 201 });
    }),
  ] });

  await user.click(await screen.findByRole("button", { name: "添加第一个持仓" }));
  await user.type(screen.getByRole("textbox", { name: "标的代码" }), "SPY");
  await user.type(screen.getByRole("textbox", { name: "标的名称" }), "SPY ETF");
  await user.type(screen.getByRole("textbox", { name: "账户名称" }), "美股账户");
  await user.selectOptions(screen.getByRole("combobox", { name: "上市市场" }), "US");
  await user.click(screen.getByText("高级设置"));

  const lotSize = screen.getByRole("textbox", { name: "最小交易单位" });
  const precision = screen.getByRole("textbox", { name: "份额小数位" });
  await user.clear(lotSize);
  await user.type(lotSize, "0");
  await user.click(screen.getByRole("button", { name: "创建持仓" }));
  expect(screen.getByRole("alert")).toHaveTextContent("最小交易单位必须是大于 0 的十进制数");

  await user.clear(lotSize);
  await user.type(lotSize, "-1");
  await user.click(screen.getByRole("button", { name: "创建持仓" }));
  expect(screen.getByRole("alert")).toHaveTextContent("最小交易单位必须是大于 0 的十进制数");

  await user.clear(lotSize);
  await user.type(lotSize, "0.01");
  await user.clear(precision);
  await user.type(precision, "13");
  await user.click(screen.getByRole("button", { name: "创建持仓" }));
  expect(screen.getByRole("alert")).toHaveTextContent("份额小数位必须是 0 到 12 的整数");
  expect(requestCount).toBe(0);
});
```

- [ ] **Step 2: Run the focused frontend test and verify RED**

```powershell
Set-Location frontend
npm test -- HoldingsPage.test.tsx
```

Expected: old US payload still contains `lot_size: "1"`; SH does not default to `100`; market switching leaves the old advanced values; unsafe 0/13 inputs can submit.

- [ ] **Step 3: Implement market defaults and precise client validation**

Add near `decimalPattern` in `AddHoldingDrawer.tsx`:

```tsx
const marketTradeUnitDefaults = {
  US: { lotSize: "0.01", precision: "2" },
  SH: { lotSize: "100", precision: "0" },
  SZ: { lotSize: "100", precision: "0" },
} as const;

function isPositiveDecimal(value: string) {
  return decimalPattern.test(value) && /[1-9]/.test(value.replace(".", ""));
}

function isValidQuantityPrecision(value: string) {
  return /^\d+$/.test(value) && Number.parseInt(value, 10) <= 12;
}
```

Replace the market change handler with a named function inside the component:

```tsx
function changeMarket(next: string) {
  setMarket(next);
  if (next !== "US") {
    setCostFx("1");
    setBaselineFx("1");
  }
  const defaults = marketTradeUnitDefaults[next as keyof typeof marketTradeUnitDefaults];
  if (defaults) {
    setLotSize(defaults.lotSize);
    setPrecision(defaults.precision);
  }
}
```

Use `onChange={(event) => changeMarket(event.target.value)}` on the market selector.

Replace validation state with:

```tsx
const invalidDecimals = submitted && [quantity, averageCost, costFx, baselineFx]
  .some((value) => !decimalPattern.test(value));
const invalidLotSize = submitted && !isPositiveDecimal(lotSize);
const invalidPrecision = submitted && !isValidQuantityPrecision(precision);
const canSubmit = Boolean(
  assetClassId && symbol.trim() && name.trim() && market.trim() && accountName.trim()
  && [quantity, averageCost, costFx, baselineFx].every((value) => decimalPattern.test(value))
  && isPositiveDecimal(lotSize)
  && isValidQuantityPrecision(precision),
);
```

Render separate alerts after the existing identity alert:

```tsx
{invalidDecimals ? <div className={styles.alert} role="alert">成本与份额字段必须是非负十进制。</div> : null}
{invalidLotSize ? <div className={styles.alert} role="alert">最小交易单位必须是大于 0 的十进制数。</div> : null}
{invalidPrecision ? <div className={styles.alert} role="alert">份额小数位必须是 0 到 12 的整数。</div> : null}
```

Remove the previous combined `invalidDecimals || invalidPrecision` alert.

- [ ] **Step 4: Run the focused frontend test and verify GREEN**

```powershell
npm test -- HoldingsPage.test.tsx
```

Expected: all `HoldingsPage.test.tsx` tests pass, including market switching, editable overrides, and client-side rejection.

- [ ] **Step 5: Commit frontend defaults**

```bash
git add frontend/src/features/holdings/AddHoldingDrawer.tsx frontend/tests/HoldingsPage.test.tsx
git commit -m "feat: default holding trade units by market"
```

---

### Task 3: Full Branch Verification and Review

**Files:**
- Verify: `backend/app/schemas/holding.py`
- Verify: `backend/app/main.py`
- Verify: `backend/tests/integration/test_holdings_api.py`
- Verify: `frontend/src/features/holdings/AddHoldingDrawer.tsx`
- Verify: `frontend/tests/HoldingsPage.test.tsx`

**Interfaces:**
- Consumes: completed backend and frontend commits.
- Produces: a reviewed branch with fresh full-suite evidence, ready for local merge.

- [ ] **Step 1: Run the complete frontend suite and build**

```powershell
Set-Location frontend
npm test
npm run build
```

Expected: all Vitest files pass and Vite exits 0.

- [ ] **Step 2: Run the complete backend suite through the isolated target**

```powershell
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/market-holding-defaults `
  /usr/bin/make test-backend
```

Expected: 0 failures; the test project and disposable volumes are removed by the Make target. Do not replace this command with raw pytest.

- [ ] **Step 3: Check scope and working-tree integrity**

```powershell
git diff --check
git status --short
git diff --stat master...HEAD
git diff master...HEAD -- backend/app/schemas/holding.py backend/app/main.py backend/tests/integration/test_holdings_api.py frontend/src/features/holdings/AddHoldingDrawer.tsx frontend/tests/HoldingsPage.test.tsx
```

Confirm no Compose production defaults, migrations, database fixtures, unrelated pages, or Hong Kong support changed.

- [ ] **Step 4: Request whole-branch code review**

Use the `requesting-code-review` skill. Review against:

- `docs/superpowers/specs/2026-08-17-market-lot-size-precision-defaults-design.md`
- this implementation plan;
- the exact Global Constraints above.

Any Critical or Important finding receives a regression test, minimal fix, focused verification, and re-review before completion.

- [ ] **Step 5: Use the branch-finishing workflow**

Use `finishing-a-development-branch`. Select local merge before executing Task 4; do not deploy or mutate the production holding from an unmerged feature worktree.

---

### Task 4: Deploy Merged Code and Repair the Single Production Holding

**Files:**
- Modify data through API only: holding `9855dbdf-42fb-4dc9-853f-e08477809c93`
- Verify runtime: `compose.yaml`

**Interfaces:**
- Consumes: Tasks 1–3 merged into local `master`.
- Produces: healthy production holdings response, corrected `563020`, and restored asset configuration page.

- [ ] **Step 1: Verify the exact production target and capture the pre-repair row**

From the main repository root:

```powershell
git branch --show-current
git status --short --branch
docker compose config --format json | ConvertFrom-Json | Select-Object name
docker inspect portfolio-rebalancer-db-1 --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{end}}'
docker exec portfolio-rebalancer-db-1 psql -U portfolio -d portfolio -P pager=off -c `
  "SELECT id, asset_class_id, symbol, name, market, account_name, trade_currency, quantity, average_cost_price, cost_fx_to_cny, baseline_fx_to_cny, lot_size, quantity_precision, preferred_data_source, is_rebalance_preferred, is_active, version FROM holdings WHERE id = '9855dbdf-42fb-4dc9-853f-e08477809c93';"
```

Expected preconditions:

- branch is `master` and clean;
- Compose project is `portfolio-rebalancer`;
- DB mount is `portfolio-rebalancer_postgres_data -> /var/lib/postgresql/data`;
- exactly one row is returned with symbol `563020`, quantity `15000.000000000000`, lot size `1.000000000000`, precision `100`, and version `1`.

If any precondition differs, stop before mutation and report the changed state.

- [ ] **Step 2: Rebuild and restart only normal services without deleting volumes**

```powershell
docker compose up -d --build api frontend worker
docker compose ps
```

Expected: DB remains healthy on the same named volume; API becomes healthy; frontend binds `127.0.0.1:3000`; worker runs. Never use `down` or `-v` in this task.

- [ ] **Step 3: Repair the holding through PATCH**

```powershell
$body = @{ lot_size = "100"; quantity_precision = 0 } | ConvertTo-Json -Compress
Invoke-RestMethod `
  -Method Patch `
  -Uri 'http://localhost:3000/api/holdings/9855dbdf-42fb-4dc9-853f-e08477809c93' `
  -ContentType 'application/json' `
  -Body $body | ConvertTo-Json -Depth 6
```

Expected: HTTP 200 response for `563020` with `lot_size="100"`, `quantity_precision=0`, `quantity="15000"`, and `version=2`.

Do not retry automatically if this call fails or returns an unexpected version.

- [ ] **Step 4: Verify API recovery and field invariants**

```powershell
$holdings = Invoke-RestMethod -Uri 'http://localhost:3000/api/holdings?include_archived=true'
$holding = $holdings | Where-Object id -eq '9855dbdf-42fb-4dc9-853f-e08477809c93'
$holding | ConvertTo-Json -Depth 6
Invoke-RestMethod -Uri 'http://localhost:3000/api/asset-classes?include_inactive=true' | ConvertTo-Json -Depth 6
docker exec portfolio-rebalancer-db-1 psql -U portfolio -d portfolio -P pager=off -c `
  "SELECT id, asset_class_id, symbol, name, market, account_name, trade_currency, quantity, average_cost_price, cost_fx_to_cny, baseline_fx_to_cny, lot_size, quantity_precision, preferred_data_source, is_rebalance_preferred, is_active, version FROM holdings WHERE id = '9855dbdf-42fb-4dc9-853f-e08477809c93';"
docker inspect portfolio-rebalancer-db-1 --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{end}}'
```

Compare with Step 1: only lot size, precision, version, and `updated_at` may differ. Quantity, cost, FX, identity, preferences, and active state must match exactly.

- [ ] **Step 5: Verify the page in the browser**

Open `http://localhost:3000`, navigate to “资产配置”, and confirm the editor appears without the 500 error. Then open “持仓与成本” and confirm `563020` displays quantity `15000`.

- [ ] **Step 6: Report deployment evidence**

Report:

- frontend and backend test counts;
- production Compose project and volume name;
- PATCH response version;
- before/after values for `lot_size` and `quantity_precision`;
- confirmation that every protected business field remained unchanged;
- asset configuration and holdings endpoint status.
