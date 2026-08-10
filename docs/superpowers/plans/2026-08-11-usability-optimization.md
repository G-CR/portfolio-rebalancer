# 易用性优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve refresh trust, holding entry, dashboard focus, and rebalance execution without changing backend APIs.

**Architecture:** Reuse existing market-data mutation and React Query cache invalidation. Keep form, dashboard, and lifecycle changes in their existing React components and derive behavior from existing fields and plan statuses.

**Tech Stack:** React 19, TypeScript, TanStack Query 5, Vitest, React Testing Library, MSW, CSS Modules.

## Global Constraints

- Use the existing `POST /api/market-data/refresh`; no backend or database changes.
- Do not add onboarding, imports, broker execution, providers, or financial-model changes.
- Markets remain `US`, `SH`, `SZ`; currencies remain `CNY`, `USD`.
- Preserve cached market values when refresh fails.

---

### Task 1: Refresh cache and shell status

**Files:**
- Modify: `frontend/src/features/marketData/api.ts`
- Modify: `frontend/src/components/AppShell/AppShell.tsx`
- Modify: `frontend/src/components/AppShell/AppShell.module.css`
- Test: `frontend/tests/MarketDataPage.test.tsx`, `frontend/tests/AppShell.test.tsx`

**Interfaces:** `useRefreshMarketData()` keeps `marketDataQueryKey` updated and invalidates `portfolioAnalyticsKey`, `holdingsQueryRoot`, and `snapshotsQueryRoot`. `AppShell` consumes `useMarketData()` and this mutation.

- [ ] Write a failing mutation test asserting successful refresh invalidates analytics, holdings, and snapshots.
- [ ] Run `cd frontend && npm test -- --run tests/MarketDataPage.test.tsx`; expect failure because only analytics is invalidated.
- [ ] Import the two query roots and invalidate all three dependent roots in `onSuccess` after `setQueryData`.
- [ ] Add failing shell tests with MSW: latest non-null `market_time` displays, pending refresh says `正在刷新`, and failed refresh renders a `role="alert"` link to `/data-sources`.
- [ ] Implement shell state priority: missing/failed → `数据需处理`; stale → `数据已过期`; manual → `包含手动值`; otherwise `数据有效`. Call `mutateAsync`, preserve cached status after rejection, disable the button while pending.
- [ ] Re-run both focused suites; expect pass.

### Task 2: Progressive holding creation

**Files:**
- Modify: `frontend/src/features/holdings/AddHoldingDrawer.tsx`
- Modify: `frontend/src/features/holdings/Holdings.module.css`
- Test: `frontend/tests/HoldingsPage.test.tsx`

**Interfaces:** The drawer produces unchanged `HoldingCreate`, with market preset pairs: `US`/`USD`, `SH`/`CNY`, `SZ`/`CNY`.

- [ ] Write a failing A-share test: selecting `上海 A 股` hides FX controls and POSTs `SH`, `CNY`, and both FX values as `1`.
- [ ] Write a failing US test: selecting `美股` exposes both FX controls; opening `高级设置` exposes source, lot size, precision, and preferred fields.
- [ ] Run `cd frontend && npm test -- --run tests/HoldingsPage.test.tsx`; expect failure because market is free text.
- [ ] Replace market input with presets; derive currency/FX defaults from selection; only render editable FX controls for `US`; move the four optional controls into labelled native `<details>`.
- [ ] Re-run the focused suite; expect pass.

### Task 3: Action-first dashboard decision

**Files:**
- Modify: `frontend/src/features/analytics/DecisionBanner.tsx`
- Test: `frontend/tests/AnalyticsContracts.test.tsx`

**Interfaces:** `DecisionBanner` consumes `PortfolioDecision.status`; title, reason, icon, and action mapping are unchanged.

- [ ] Add failing tests showing `hold` has no maximum-drift/FX facts while `contribute` shows both facts and its action.
- [ ] Run `cd frontend && npm test -- --run tests/AnalyticsContracts.test.tsx`; expect failure.
- [ ] Render `decisionFacts` only when status is `contribute` or `rebalance`.
- [ ] Re-run the focused suite; expect pass.

### Task 4: Rebalance execution checklist

**Files:**
- Modify: `frontend/src/features/rebalance/RebalanceLifecycle.tsx`
- Modify: `frontend/src/features/rebalance/Rebalance.module.css`
- Test: `frontend/tests/RebalanceLifecycle.test.tsx`

**Interfaces:** Checklist is derived solely from `RebalancePlan.status === "in_progress"`.

- [ ] Add failing tests for the four ordered steps and completion impact copy; assert draft has no checklist.
- [ ] Run `cd frontend && npm test -- --run tests/RebalanceLifecycle.test.tsx`; expect failure.
- [ ] Render the four steps: execute broker trades, record them in holdings, review result, then establish the new baseline. State that completion creates an after snapshot, resets the current FX baseline, and does not alter cost price or cost FX.
- [ ] Re-run the focused suite; expect pass.

### Task 5: Complete verification

**Files:**
- Modify: test files above as required by Tasks 1–4.

- [ ] Run `cd frontend && npm test -- --run --passWithNoTests`; expect zero failures.
- [ ] Run `cd frontend && npm run build`; expect a successful Vite build.
- [ ] Commit with `git add frontend/src frontend/tests docs/superpowers/plans/2026-08-11-usability-optimization.md` then `git commit -m "feat: improve daily portfolio workflows"`.
