# International Market Data Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use multi-agent execution for this project. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably refresh SPY, QQQ, and USD/CNY without requiring an API key when Yahoo is rate-limited.

**Architecture:** Keep provider selection in `ProviderRegistry`. Harden Yahoo requests and numeric normalization, add a separate Sina provider, then include Sina in provider schemas, settings normalization, frontend source types, and default fallback order.

**Tech Stack:** Python 3.13, FastAPI, urllib, Decimal, pytest, React, TypeScript, Docker Compose.

---

### Task 1: Harden Yahoo Requests And Values

**Files:**
- Modify: `backend/app/providers/yahoo.py`
- Test: `backend/tests/unit/test_provider_normalization.py`

- [ ] Add a test proving Yahoo sends User-Agent and JSON Accept headers.
- [ ] Run the focused test and verify it fails because `urlopen` receives a string.
- [ ] Send an explicit `Request` with the accepted headers.
- [ ] Add a test using `751.8300170898438` and assert the stored value fits 12 decimal places.
- [ ] Quantize Yahoo values to `Decimal("0.000000000001")` with `ROUND_HALF_EVEN`.
- [ ] Run all provider normalization tests.

### Task 2: Add Sina Price And FX Provider

**Files:**
- Create: `backend/app/providers/sina.py`
- Test: `backend/tests/unit/test_provider_normalization.py`

- [ ] Add failing tests for SPY payload parsing, USD/CNY payload parsing, required request headers, and unsupported FX pairs.
- [ ] Implement `SinaProvider.fetch_price`, `fetch_fx`, payload decoding, value parsing, and Asia/Shanghai timestamps.
- [ ] Run provider normalization tests and verify they pass.

### Task 3: Register Sina And Preserve Existing Settings

**Files:**
- Modify: `backend/app/services/market_data.py`
- Modify: `backend/app/services/settings.py`
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/schemas/holding.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/holdings/AddHoldingDrawer.tsx`
- Modify: `frontend/src/features/holdings/HoldingsMarketDataNotice.tsx`
- Test: `backend/tests/unit/test_provider_normalization.py`
- Test: `backend/tests/integration/test_settings_api.py`

- [ ] Add failing tests proving international and FX order is Yahoo, Sina, Alpha Vantage and legacy four-provider settings normalize with Sina inserted.
- [ ] Register Sina and extend safe provider names.
- [ ] Extend backend and frontend provider name unions and labels.
- [ ] Run focused backend and frontend tests.

### Task 4: Full Verification And Deployment

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/user-guide.md`

- [ ] Document the automatic Sina fallback and actual-source display.
- [ ] Run `make test-backend`.
- [ ] Run `npm test -- --run`, `npm run build`, and `npx playwright test` in `frontend/`.
- [ ] Commit implementation and documentation.
- [ ] Push `master` to `origin`.
- [ ] Back up the production database.
- [ ] Rebuild `portfolio-v1` on port `55113` without deleting volumes.
- [ ] Trigger a live refresh and assert positive SPY, QQQ, and USD/CNY values.
- [ ] Confirm holdings and analytics return HTTP 200.
