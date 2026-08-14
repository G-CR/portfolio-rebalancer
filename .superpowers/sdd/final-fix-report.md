# Final review fix report

## Findings resolved

- A successful topbar market refresh now advances a query-backed refresh version. A mounted `RebalancePage` observes that version and resets its local preview, unsaved/draft plan state, dirty state, and related messages. An active in-progress formal plan is retained so its checklist and completion command remain available.
- `RebalancePage` now restores the newest in-progress formal plan from the existing `GET /api/rebalance/plans` API. Returning after updating holdings therefore preserves access to the completion checklist and completion command. Draft plans are intentionally not restored.
- The third execution-checklist item is exactly `核对调整结果`.
- The shell no longer reports an empty market-data collection as valid; it displays `尚无市场数据`.
- Replaced the undefined `--color-negative`, `--color-warning`, and `--space-12` references with existing design tokens.

## TDD evidence

The regression tests were added before production changes. The initial focused run failed in four expected ways: the old checklist wording remained, no active plan was restored, a topbar refresh left the saved plan and preview visible, and an empty market-data collection was labelled valid. After the minimal implementation, the focused suite passed with 17 tests.

## Verification

- Focused: `npm test -- AppShell.test.tsx RebalanceLifecycle.test.tsx` — 2 files, 17 tests passed.
- Full frontend: `npm test` — 25 files, 152 tests passed.
- Production build: `npm run build` — succeeded; Vite emitted its existing large-chunk advisory.
- CSS token scan — every `var(--token)` reference resolves to a token declared in `frontend/src/styles/tokens.css`.
- `git diff --check` — no whitespace errors.

## Follow-up: preserve active plans during refresh

- The refresh reset now retains a plan only when its status is `in_progress`; unsaved and draft calculations continue to clear.
- Added a topbar integration regression that starts a formal rebalance, refreshes market data, and verifies that the in-progress heading, execution checklist, and enabled completion command remain.
- TDD red evidence: the new test failed because the refresh effect unconditionally replaced the active plan with `null`.
- Focused: `npm test -- AppShell.test.tsx -t "topbar market refresh"` — both draft-clearing and in-progress-preservation tests passed.
- Full frontend: `npm test` — 25 files, 153 tests passed.
- Production build: `npm run build` — succeeded; Vite emitted its existing large-chunk advisory.

## Final review fix wave (base `acd6504`, 2026-08-15)

### Implementation commit

- `fee929884cae7ccacaa94743b44b8a65fffcc4bc` — `fix: preserve active rebalance workflows`

### Per-finding implementation

1. **Preserve and lock an active rebalance plan.** `RebalancePage` now treats an `in_progress` plan as immutable page state until cancel/complete: the calibration inputs and recalculation command are disabled, event handlers guard against programmatic edits, and market refresh continues to retain the active plan while clearing only unsaved/draft calculations. `RebalanceInputs` received an explicit `disabled` contract so pending-copy semantics remain separate from lifecycle locking. Regressions cover both a newly started plan and a restored plan.

2. **Remove the initial restoration/refresh race.** The one-shot restoration marker is now React state set only after a successful plan-list response is inspected. The refresh effect no longer marks restoration complete. Calculation and new-plan controls remain disabled while the initial plan lookup is unresolved, but a settled lookup error does not permanently deadlock the controls. A delayed `GET /api/rebalance/plans` regression refreshes market data first, then resolves an active plan and verifies that the completion workflow is restored.

3. **Render restored plans with their saved basis and tolerance.** `RebalancePlanResponse` now exposes the resolved `tolerance` already stored in `RebalancePlan.input_summary`; no migration or persistence change was added. Frontend plan types and fixtures include the field. While a plan is active, the header, disabled basis/tolerance inputs, and projected-allocation tolerance band all derive from the saved plan rather than current defaults. Backend create/list/detail and frontend restoration regressions cover the contract.

4. **Constrain replacement markets.** `ReplacementDrawer` replaces the arbitrary market textbox with an accessibly labelled selector containing only `US`/美股, `SH`/上海 A 股, and `SZ`/深圳 A 股. Submission validation also checks membership in this fixed set. Component coverage verifies the accessible combobox, exact choices, and constrained submitted value.

5. **Restore replacement fixture fidelity.** Shared replacement request/response helpers now produce an archived zero-quantity, non-preferred source with an incremented version while preserving sell-side cost semantics. Component mocks use the helper and all archived component rows are zero-quantity/non-preferred. The Playwright fixture rejects missing/archived sources, enforces `source_version`, demotes another preferred holding in the source asset class, increments affected versions, persists the in-memory plan across create/start/complete, and returns `{ items: [...] }` for plan listing. A browser-level fixture contract checks stale-version rejection, archived-source rejection, source version/quantity/cost state, preferred demotion, and plan-list shape.

### RED evidence captured before production changes

- Backend contract: `docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py::test_create_plan_persists_exact_preview_contract_and_supports_list_detail` — **1 failed** with `KeyError: 'tolerance'` on the created plan response.
- Frontend behavior: `npm test -- --run tests/RebalanceLifecycle.test.tsx tests/AppShell.test.tsx tests/HoldingsPage.test.tsx` — **5 failed / 40 passed**. Failures showed active controls were enabled, restored basis remained `actual`, delayed lookup controls were enabled, and replacement market remained a textbox in both the inherited-default and submission paths.
- Playwright fixture: `npm run test:e2e -- e2e/holdings-cost.spec.ts --grep "replacement fixture enforces production replacement invariants"` — **1 failed** because `GET /api/rebalance/plans` returned a 204 empty body, producing `Unexpected end of JSON input`.

### GREEN and covering verification

- Backend focused contract: the same single-test command — **1 passed**.
- Backend covering integration: `docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py tests/integration/test_rebalance_lifecycle.py tests/integration/test_holdings_api.py` — **52 passed**. This covers formal-plan contracts/lifecycle and the unchanged atomic holding-replacement invariants.
- Frontend focused: `npm test -- --run tests/RebalanceLifecycle.test.tsx tests/AppShell.test.tsx tests/HoldingsPage.test.tsx` — **45 passed**.
- Frontend full: `npm test -- --run` — **25 files, 172 tests passed** after the final fixture-fidelity edit.
- Frontend production build: `npm run build` — **succeeded**; Vite emitted only the pre-existing large-chunk advisory.
- Playwright focused: `npm run test:e2e -- e2e/holdings-cost.spec.ts e2e/rebalance.spec.ts` — **9 passed**.
- Playwright broad functional run: `npm run test:e2e -- --grep-invert "dashboard matches calibration desk"` — **13 passed**.
- `git diff --check` — **clean** (only the repository's Windows LF-to-CRLF notices).

### Changed files

- Backend plan contract: `backend/app/schemas/rebalance.py`, `backend/app/services/rebalancing.py`, `backend/tests/integration/test_rebalance_api.py`.
- Rebalance lifecycle/restoration/rendering: `frontend/src/api/types.ts`, `frontend/src/features/rebalance/RebalanceInputs.tsx`, `frontend/src/pages/RebalancePage.tsx`, `frontend/tests/AppShell.test.tsx`, `frontend/tests/RebalanceLifecycle.test.tsx`, `frontend/tests/fixtures.ts`.
- Replacement selector and fixture fidelity: `frontend/src/features/holdings/ReplacementDrawer.tsx`, `frontend/tests/HoldingsPage.test.tsx`, `frontend/tests/fixtures.ts`, `frontend/e2e/fixtures/portfolio.ts`, `frontend/e2e/holdings-cost.spec.ts`.

### Self-review of `acd6504..fee9298`

- Re-read all five verified findings against the complete diff; each has direct production/fixture coverage and a focused regression.
- Confirmed the backend replacement service, transaction boundaries, version check, unique-preferred invariant, and cost-adjustment logic were not changed.
- Confirmed market-refresh API/cache invalidation behavior was not changed; only `RebalancePage`'s local reaction and restoration gate changed.
- Confirmed saved tolerance is read from existing `input_summary.resolved_constraints`; no migration or data rewrite was introduced.
- Confirmed active-plan locking is limited to `in_progress`; draft, completed, and cancelled lifecycle behavior remains available as before.
- Confirmed the replacement selector exposes exactly the three supported markets and retains separate currency editing required by the design.
- No additional in-scope defects were found.

### Remaining concerns outside this fix wave

- A full backend run completed **286 passed / 3 skipped / 2 failed**. The two failures are `test_digest_sends_anomaly_email_when_data_incomplete` and `test_digest_sends_full_analysis_email`; both call `send_daily_digest_if_configured()` without a fixed `now`. On 2026-08-15 in configured `Asia/Shanghai` (Saturday), production correctly takes its weekend skip branch, so each mock observed zero sends. No email code or tests were modified in this wave.
- The complete Playwright run has one reproducible unrelated visual failure: `dashboard matches calibration desk at supported widths` differs from `dashboard-desktop.png` by 28,377 pixels (3%, threshold 1%). The dashboard and its styles were untouched. The failure reproduced in isolation; the remaining 13 Playwright tests pass.

## Re-review follow-up (2026-08-15)

### Implementation commit

- `029f142c763bdd3d01f34c7213896015ac06de52` — `fix: restore saved rebalance constraints`

### Per-finding implementation

6. **Hydrate every locked field from the restored active plan.** `RebalancePlanResponse` now exposes saved available CNY/USD and stale acknowledgement from the existing `input_summary`, plus saved minimum trade and sell/FX permissions from `resolved_constraints`. The frontend plan type and shared fixture include the full contract. `RebalancePage` maps all of those values, as well as the already-supported basis and tolerance, into the disabled active-plan form. The restoration regression deliberately gives the active plan cash, minimum-trade, permission, stale-acknowledgement, basis, and tolerance values that differ from the current defaults and verifies the saved values are displayed. No migration or persistence rewrite was added.

7. **Match production replacement storage and FX normalization.** The shared replacement response fixture now zeros archived `average_cost_price` and `cost_fx_to_cny` when the source quantity reaches zero, matching production `_storage_basis`. It also normalizes both target FX values to `1` for CNY replacements, matching `_normalized_fx_values`. The browser fixture contract now performs a CNY replacement with deliberately non-unit requested FX and asserts both the archived zero basis and normalized target FX.

### RED evidence captured before production behavior changes

- Backend response contract: `docker compose build api; docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py::test_create_plan_persists_exact_preview_contract_and_supports_list_detail` — **1 failed** with `KeyError: 'available_cny'` on the created response. (A preliminary host-side `uv run` could not resolve Docker hostname `db`; rebuilding the container ensured the edited test and pre-fix application were both exercised.)
- Frontend restoration: `npm test -- --run tests/RebalanceLifecycle.test.tsx -t "restores an in-progress plan"` — **1 failed**. The accessible DOM showed restored basis/tolerance but current-default values `0`, `0`, and `500`, with both permission checkboxes checked and no stale acknowledgement. The initial assertion used the longer descriptive label; it was corrected to the component's actual accessible names (`人民币`, `美元`, `最小交易金额`) before the green run.
- Playwright fixture fidelity: `npm run test:e2e -- e2e/holdings-cost.spec.ts --grep "replacement fixture enforces production replacement invariants"` — **1 failed** because the archived response still returned `average_cost_price: "510.25"` and `cost_fx_to_cny: "7.18"` instead of zero. The same regression also covers CNY target normalization after the archived-source assertion passes.

### GREEN and covering verification

- Backend focused: `docker compose build api; docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py::test_create_plan_persists_exact_preview_contract_and_supports_list_detail` — **1 passed**.
- Backend covering integration: `docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py tests/integration/test_rebalance_lifecycle.py tests/integration/test_holdings_api.py` — **52 passed**.
- Frontend focused: `npm test -- --run tests/RebalanceLifecycle.test.tsx -t "restores an in-progress plan"` — **1 passed / 3 skipped**.
- Frontend full: `npm test -- --run` — **25 files, 172 tests passed**.
- Frontend production build: `npm run build` — **succeeded**; only the existing large-chunk advisory was emitted.
- Playwright focused contract: `npm run test:e2e -- e2e/holdings-cost.spec.ts --grep "replacement fixture enforces production replacement invariants"` — **1 passed**.
- Playwright covering workflows: `npm run test:e2e -- e2e/holdings-cost.spec.ts e2e/rebalance.spec.ts` — **9 passed**.
- Playwright broad functional run: `npm run test:e2e -- --grep-invert "dashboard matches calibration desk"` — **13 passed**.
- `git diff --check` — **clean** (only Windows LF-to-CRLF notices).

### Changed files

- Backend response contract and regression: `backend/app/schemas/rebalance.py`, `backend/app/services/rebalancing.py`, `backend/tests/integration/test_rebalance_api.py`.
- Frontend active-plan hydration and regression: `frontend/src/api/types.ts`, `frontend/src/pages/RebalancePage.tsx`, `frontend/tests/RebalanceLifecycle.test.tsx`, `frontend/tests/fixtures.ts`.
- Replacement fixture fidelity and browser assertion: `frontend/tests/fixtures.ts`, `frontend/e2e/fixtures/portfolio.ts`, `frontend/e2e/holdings-cost.spec.ts`.

### Self-review

- Re-read both appended re-review findings against `acd6504..029f142`; every saved field named by the reviewer is present in the backend response, frontend type/fixture, and active-plan display mapping.
- Confirmed nullable request constraints are not surfaced directly: sell/FX permissions, tolerance, and minimum trade come from the persisted resolved constraint values, while cash and stale acknowledgement come from the persisted request summary.
- Confirmed no migration, model, transaction-boundary, replacement-service, or market-refresh changes were introduced. Atomic replacement and active-plan refresh semantics remain unchanged.
- Compared the shared fixture with production `_storage_basis` and `_normalized_fx_values`: archived quantity/basis and CNY target FX now match the service behavior.
- Reviewed all nine implementation/test files and found no additional in-scope defect. `git diff --check` was clean.

### Remaining concerns

- No new concern was introduced by this follow-up. The previously documented Saturday-dependent email-test failures and unrelated dashboard screenshot drift remain outside this fix wave.

## Final compatibility follow-up (2026-08-15)

### Implementation commit

- `cb1533707f61352b0fd02b223c9c9a23ccb348f4` — `fix: preserve legacy rebalance plan compatibility`

### Per-finding implementation

8. **Read legacy rebalance plan summaries.** `_plan_response` now uses the nested `resolved_constraints` object when present and falls back to the plan's top-level `input_summary` for rows written before commit `4d9fde9`. The regression creates a current plan, rewrites its persisted summary to the historical top-level-only shape, and verifies both list and detail responses expose sell/FX permissions, tolerance, and minimum trade without breaking restoration.

9. **Scale replacement target quantity.** The shared replacement response helper formats the target quantity with `quantity_precision`, matching `HoldingResponse`'s scaled serialization for the fixture contract. The browser regression sends quantity `"8"` at precision `4` and requires target quantity `"8.0000"`.

### RED evidence captured before production/fixture changes

- Legacy plan contract: `docker compose build api; docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py::test_create_plan_persists_exact_preview_contract_and_supports_list_detail` — **1 failed** while listing the historical row with `KeyError: 'resolved_constraints'` in `_plan_response`.
- Replacement quantity contract: `npm run test:e2e -- e2e/holdings-cost.spec.ts --grep "replacement fixture enforces production replacement invariants"` — **1 failed** because the target response returned `quantity: "8"` instead of `"8.0000"`.

### GREEN and covering verification

- Backend focused: `docker compose build api; docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py::test_create_plan_persists_exact_preview_contract_and_supports_list_detail` — **1 passed**.
- Backend covering integration: `docker compose run --rm api uv run pytest -q tests/integration/test_rebalance_api.py tests/integration/test_rebalance_lifecycle.py tests/integration/test_holdings_api.py` — **52 passed**.
- Frontend full: `npm test -- --run` — **25 files, 172 tests passed**.
- Frontend production build: `npm run build` — **succeeded**; only the existing large-chunk advisory was emitted.
- Playwright focused: `npm run test:e2e -- e2e/holdings-cost.spec.ts --grep "replacement fixture enforces production replacement invariants"` — **1 passed**.
- Playwright broad functional run: `npm run test:e2e -- --grep-invert "dashboard matches calibration desk"` — **13 passed**.
- `git diff --check` — **clean** (only Windows LF-to-CRLF notices).

### Changed files

- Legacy backend compatibility and regression: `backend/app/services/rebalancing.py`, `backend/tests/integration/test_rebalance_api.py`.
- Quantity serialization fixture and browser assertion: `frontend/tests/fixtures.ts`, `frontend/e2e/holdings-cost.spec.ts`.

### Self-review

- Compared the fallback against both historical shapes: nested resolved constraints remain authoritative for current rows, while only absent nested data falls back to the four legacy top-level values.
- Confirmed available cash and stale acknowledgement continue to come from their unchanged top-level saved fields in both shapes.
- Confirmed the regression exercises both collection and detail endpoints after persisting the legacy shape, covering active-plan restoration's collection dependency.
- Confirmed quantity scaling affects only the synthetic target response; archived-source zero quantity/basis, CNY FX normalization, preferred-holding demotion, versioning, and backend atomic replacement code are unchanged.
- Reviewed `acd6504..cb15337` and found no new in-scope defect. `git diff --check` was clean.

### Remaining concerns

- No new concern was introduced. The previously documented Saturday-dependent email-test failures and unrelated dashboard screenshot drift remain outside this compatibility follow-up.

## Exact replacement quantity follow-up (2026-08-15)

### Implementation commit

- `77dc478b0e0822bac019834907c62eede073d405` — `test: preserve exact replacement quantities`

### Finding implementation

10. **Scale fixture quantities without binary floating point.** The shared replacement fixture no longer converts quantity through JavaScript `Number`/`toFixed`. Its local decimal-string scaler parses sign, integral, and fractional digits into `BigInt` units, scales with exact powers of ten, and applies ties-to-even rounding to mirror the backend `Decimal.quantize` serializer. It accepts the same ordinary decimal forms as the replacement UI, including leading-dot fractions. Focused fixture tests cover a valid integer above JavaScript's safe range and the `1.015` midpoint at precision 2.

### RED evidence

- `npm test -- --run tests/ReplacementFixture.test.ts` — **2 failed** before the formatter change: `"9007199254740993"` was returned as `"9007199254740992"`, and `"1.015"` at precision 2 was returned as `"1.01"` instead of the backend-compatible `"1.02"`.

### GREEN and covering verification

- Focused unit: `npm test -- --run tests/ReplacementFixture.test.ts` — **2 passed**.
- Frontend full: `npm test -- --run` — **26 files, 174 tests passed**.
- Frontend production build: `npm run build` — **succeeded**; only the existing large-chunk advisory was emitted.
- Playwright focused fixture contract: `npm run test:e2e -- e2e/holdings-cost.spec.ts --grep "replacement fixture enforces production replacement invariants"` — **1 passed**.
- Playwright broad functional run: `npm run test:e2e -- --grep-invert "dashboard matches calibration desk"` — **13 passed**.
- `git diff --check` — **clean** (only Windows LF-to-CRLF notices).

### Changed files

- Exact formatter: `frontend/tests/fixtures.ts`.
- Precision regressions: `frontend/tests/ReplacementFixture.test.ts`.

### Self-review

- Compared the scaler with backend `_scale_decimal`: precision padding is exact, discarded digits are compared exactly with half a unit, and midpoint increments only an odd retained unit (ties to even).
- Confirmed no `Number` conversion remains in the replacement quantity response path, so integers beyond `Number.MAX_SAFE_INTEGER` retain identity.
- Confirmed the parser accepts the replacement UI's signed ordinary-decimal grammar, including `1.`, `.5`, and leading zeros; invalid synthetic payloads fail explicitly.
- Confirmed archived-source zeroing, target CNY FX normalization, preferred/version behavior, backend replacement transactions, and rebalance compatibility are untouched.
- Reviewed `acd6504..77dc478` and found no additional in-scope defect. `git diff --check` was clean.

### Remaining concerns

- No new concern was introduced. The previously documented Saturday-dependent email-test failures and unrelated dashboard screenshot drift remain outside this minor fixture fix.
