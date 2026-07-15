# Rebalance And Market Data Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use multi-agent execution for this project. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show holding names in rebalance trades, format FX drift, align provider controls, and level market-data row rules.

**Architecture:** Reuse existing holdings queries and formatters. Keep table semantics native and make alignment changes inside focused component wrappers and CSS classes.

**Tech Stack:** React 19, TypeScript, CSS Modules, TanStack Query, Vitest, Testing Library, Playwright.

---

### Task 1: Trade Names And FX Formatting

**Files:**
- Modify: `frontend/src/pages/RebalancePage.tsx`
- Modify: `frontend/src/features/rebalance/TradeSuggestions.tsx`
- Modify: `frontend/src/features/rebalance/Rebalance.module.css`
- Test: `frontend/tests/RebalancePage.test.tsx`

- [ ] Add failing assertions for the holding name and formatted comparison percentage.
- [ ] Load active holdings, create the symbol/name lookup, and render the secondary name.
- [ ] Format comparison drift with `formatPercent(..., 2)`.
- [ ] Run `frontend/tests/RebalancePage.test.tsx`.

### Task 2: Provider And Effective-Value Alignment

**Files:**
- Modify: `frontend/src/features/settings/ProviderSettings.tsx`
- Modify: `frontend/src/features/marketData/MarketDataTable.tsx`
- Modify: `frontend/src/features/marketData/MarketData.module.css`
- Test: `frontend/tests/MarketDataPage.test.tsx`
- Test: `frontend/e2e/market-data-layout.spec.ts`

- [ ] Add component assertions for provider field labels and status wrappers.
- [ ] Add uniform provider field wrappers and action spacing.
- [ ] Move multi-line table content into inner wrappers and keep cells as table cells.
- [ ] Add browser geometry checks for provider columns and row borders.
- [ ] Run focused Vitest and Playwright tests.

### Task 3: Verification And Deployment

- [ ] Run all frontend tests, production build, and Playwright.
- [ ] Run `git diff --check` and commit changes.
- [ ] Push `master` to `origin`.
- [ ] Rebuild `portfolio-v1` on port `55113` without deleting volumes.
- [ ] Inspect desktop screenshots and verify all four requested changes.
