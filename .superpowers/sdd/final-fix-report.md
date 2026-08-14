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
