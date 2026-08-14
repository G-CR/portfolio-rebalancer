# Task 3 report: Action-first dashboard decision

## Scope delivered

- Decision facts (maximum drift and FX contribution) now appear only for `contribute` and `rebalance` decisions.
- `hold` decisions retain their title, reason, icon, and primary action while omitting the two supporting facts.
- Existing action routing remains unchanged; the contribution action continues to route to `/rebalance`.

## TDD evidence

1. Added contracts for hiding facts on a `hold` decision and displaying both facts plus the contribution action on a `contribute` decision.
2. Ran `npm test -- AnalyticsContracts.test.tsx` before the implementation. The new hold contract failed as expected because `最大偏离` was rendered.
3. Added the minimal status guard in `DecisionBanner` and re-ran the focused suite successfully.

## Verification

- Focused: `npm test -- AnalyticsContracts.test.tsx` — 1 file, 5 tests passed.
- Full frontend: `npm test` — 25 files, 148 tests passed.
- `git diff --check` — no whitespace errors.

## Files changed

- `frontend/src/features/analytics/DecisionBanner.tsx`
- `frontend/tests/AnalyticsContracts.test.tsx`

## Concerns

None.
