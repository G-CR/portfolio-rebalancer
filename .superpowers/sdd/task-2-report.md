# Task 2 report: Progressive holding creation

## Scope delivered

- Replaced the free-text market entry with exactly three market choices:
  - `美股` (`US`)
  - `上海 A 股` (`SH`)
  - `深圳 A 股` (`SZ`)
- The drawer derives trade currency from the selected market: `US` uses `USD`; `SH` and `SZ` use `CNY`.
- Cost and baseline FX inputs render only for US holdings. Selecting either A-share market resets both submitted FX values to `"1"`.
- Moved preferred data source, minimum trade unit, quantity precision, and rebalance preference into the native labelled `高级设置` `<details>` section.
- Preserved all existing defaults and create-payload field names/types. No backend files were changed.

## TDD evidence

1. Added tests for Shanghai A-share submission, US FX visibility/editability, and advanced-settings payload handling before production changes.
2. Ran `npm test -- HoldingsPage.test.tsx` before implementation: 3 failures, all because `上市市场` was still a text field rather than the required selector.
3. Implemented the minimal drawer and CSS changes, then updated existing drawer tests from text entry to the required market selector.
4. Added an exact-market-options assertion. Its focused test run failed because an extra placeholder option was present; removed that option and defaulted the selector to `US`.
5. Re-ran focused tests successfully.

## Verification

- Focused: `npm test -- HoldingsPage.test.tsx` — 1 file, 10 tests passed.
- Full frontend: `npm test` — 25 files, 145 tests passed.
- `git diff --check` — no whitespace errors.

## Files changed

- `frontend/src/features/holdings/AddHoldingDrawer.tsx`
- `frontend/src/features/holdings/Holdings.module.css`
- `frontend/tests/HoldingsPage.test.tsx`

## Concerns

None.

## Reviewer follow-up: required market selection

- Restored the prior empty market default and added a disabled `请选择市场` prompt option. The three valid market options remain `美股` (`US`), `上海 A 股` (`SH`), and `深圳 A 股` (`SZ`).
- Added a regression test that fills every other required identity field, leaves market unselected, and verifies that creation is blocked without making a request.
- TDD evidence: the new test failed with the previous `US` default, reporting received value `US` where an empty value was required.
- Verification after the fix:
  - Focused: `npm test -- HoldingsPage.test.tsx` — 1 file, 11 tests passed.
  - Full frontend: `npm test` — 25 files, 146 tests passed.
