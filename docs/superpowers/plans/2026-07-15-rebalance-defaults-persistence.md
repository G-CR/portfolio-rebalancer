# Rebalance Defaults Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use subagents for this project. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the last explicitly calculated rebalance funds and constraints in the database and restore them on every future page load.

**Architecture:** Extend the singleton settings row with funds and valuation basis, while reusing its existing tolerance, minimum trade, allow-sell, and allow-FX fields. Expose a dedicated rebalance-defaults API and initialize the frontend form from it. Explicit calculation saves defaults first, then runs preview even if persistence fails.

**Tech Stack:** PostgreSQL 17, Alembic, SQLAlchemy 2, FastAPI, Pydantic 2, React 19, TanStack Query, Vitest, MSW, Playwright, Docker Compose.

---

### Task 1: Database And API Contract

**Files:**
- Create: `backend/alembic/versions/20260715_0007_rebalance_defaults.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/services/settings.py`
- Modify: `backend/app/api/routes/settings.py`
- Test: `backend/tests/integration/test_settings_api.py`
- Test: `backend/tests/integration/test_migrations.py`

- [ ] Add failing settings API tests for default values, round-trip persistence, validation, and preservation when `/api/settings/general` is updated.
- [ ] Add a migration test that upgrades to head, verifies the three columns and defaults, downgrades to `20260714_0006`, and upgrades again.
- [ ] Run the focused backend tests and verify failure because the route and columns do not exist.
- [ ] Add `rebalance_available_cny NUMERIC(28,12) NOT NULL DEFAULT 0`, `rebalance_available_usd NUMERIC(28,12) NOT NULL DEFAULT 0`, and `rebalance_valuation_basis VARCHAR(16) NOT NULL DEFAULT 'actual'` with an `actual/fx_neutral` check constraint.
- [ ] Add matching `Setting` model fields.
- [ ] Add `RebalanceDefaultsUpdate` and `RebalanceDefaultsResponse` schemas with Decimal string serialization and validation.
- [ ] Add `get_rebalance_defaults` and `update_rebalance_defaults` services. Updating rebalance defaults must update all seven values and `updated_at`; updating general settings must preserve the new fields.
- [ ] Add `GET` and `PUT /api/settings/rebalance-defaults` routes using the existing transactional write helper.
- [ ] Run focused API and migration tests until they pass.

### Task 2: Frontend API And Form Initialization

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/settings/api.ts`
- Modify: `frontend/src/pages/RebalancePage.tsx`
- Modify: `frontend/src/features/rebalance/RebalanceInputs.tsx`
- Test: `frontend/tests/RebalancePage.test.tsx`
- Test: `frontend/tests/RebalanceLifecycle.test.tsx`

- [ ] Add failing component tests proving database defaults populate all inputs without calling preview.
- [ ] Add `RebalanceDefaults` and update payload TypeScript types.
- [ ] Add query key, `useRebalanceDefaults`, and `useSaveRebalanceDefaults`; successful save updates both rebalance-default and overlapping general-settings cache fields.
- [ ] Initialize the form only after defaults resolve, converting tolerance ratio to UI percentage.
- [ ] If loading fails, use built-in defaults and display a non-blocking warning without triggering preview.
- [ ] Ensure stale acknowledgement remains false after hydration.
- [ ] Add default API handlers to all rebalance component tests.
- [ ] Run focused frontend tests until they pass.

### Task 3: Save Defaults On Explicit Calculation

**Files:**
- Modify: `frontend/src/pages/RebalancePage.tsx`
- Modify: `frontend/src/features/rebalance/Rebalance.module.css`
- Test: `frontend/tests/RebalancePage.test.tsx`
- Modify: `frontend/e2e/rebalance.spec.ts`
- Modify: `frontend/e2e/fixtures/portfolio.ts`

- [ ] Add a failing test proving `开始测算` sends the same current configuration to defaults and preview endpoints.
- [ ] Add a failing test proving preview still runs and results remain usable when defaults saving fails.
- [ ] Convert UI percentage tolerance back to a ratio for both defaults saving and preview.
- [ ] In `runPreview`, attempt defaults persistence first, record a dedicated warning on failure, then always execute preview.
- [ ] Clear the persistence warning after a later successful save.
- [ ] Update Playwright mocks and verify restored defaults can be edited before calculation.
- [ ] Run focused component and Playwright tests until they pass.

### Task 4: Verification And Deployment

**Files:**
- No source files expected.

- [ ] Run isolated full backend verification with `make test-backend`.
- [ ] Run `npm test -- --run`, `npm run build`, and `npx playwright test` in `frontend`.
- [ ] Run `git diff --check` and inspect the final diff.
- [ ] Commit implementation and push `master`.
- [ ] Back up `portfolio-v1-db-1` before deployment.
- [ ] Rebuild with `COMPOSE_PROJECT_NAME=portfolio-v1 PORTFOLIO_PORT=55113 docker compose up -d --build`.
- [ ] Verify migration head, API health, defaults round trip, and the real `/rebalance` page at 1440x900.
