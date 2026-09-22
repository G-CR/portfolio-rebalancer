# Domestic ETF Sina Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep domestic ETF market data usable when AKShare's Eastmoney snapshot fails on the deployed server.

**Architecture:** Keep AKShare as the first domestic source. Add a domestic quote operation to the existing Sina provider and route only SH/SZ domestic attempts through it. Provider failures continue through the current registry and last-valid-value logic.

**Tech Stack:** Python 3.13, FastAPI, pytest, Docker Compose, PostgreSQL.

## Global Constraints

- Keep the current international quote and FX paths unchanged.
- Require a six-digit domestic symbol, matching exchange quote key, positive price, and a parseable Shanghai-local market timestamp.
- Do not add AKShare retries; its installed library already retries three times.
- Do not alter production database volumes or stored credentials during deployment.

---

### Task 1: Parse domestic Sina ETF quotes

**Files:**
- Modify: `backend/app/providers/sina.py`
- Test: `backend/tests/unit/test_provider_normalization.py`

**Interfaces:**
- Produce: `SinaProvider.fetch_domestic_price(symbol: str, market: str) -> MarketQuote`
- Produce: `SinaProvider.normalize_domestic_price(symbol: str, market: str, payload: str, *, fetched_at: datetime | None = None) -> MarketQuote`

- [ ] **Step 1: Write a failing test** using a realistic `var hq_str_sh510300` payload; assert current price, `CNY`, source, original symbol, and `Asia/Shanghai` market timestamp. Add a rejection case for a mismatched quote identifier and missing price.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_provider_normalization.py -k sina_domestic -q` from `backend` and confirm failure because the domestic operation is absent.
- [ ] **Step 3: Implement** exchange normalization (`SH`/`SSE`, `SZ`/`SZSE`), the exchange-qualified HTTP request, strict identifier and field validation, and `MarketQuote` construction. Reuse `_blocking_get_text`, `_parse_shanghai_timestamp`, and `decimal_from_value`.
- [ ] **Step 4: Re-run the focused tests** and confirm all pass.

### Task 2: Route domestic fallback through the provider registry

**Files:**
- Modify: `backend/app/services/market_data.py`
- Test: `backend/tests/unit/test_provider_normalization.py`

**Interfaces:**
- Consume: `SinaProvider.fetch_domestic_price(symbol, market)` from Task 1.
- Produce: domestic order `akshare`, `sina`, `tushare`, while international and FX orders remain unchanged.

- [ ] **Step 1: Write a failing registry test** in which AKShare raises `ProviderRequestError`, the Sina domestic operation returns a `MarketQuote`, and the registry returns that quote for `market="SH"`. Assert the preferred source and failure aggregation still work.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_provider_normalization.py -k domestic_fallback -q` and confirm failure under the old domestic order.
- [ ] **Step 3: Implement** the domestic order and a Sina-specific domestic call in `ProviderRegistry.fetch_price`; keep the existing `fetch_price` path for international symbols.
- [ ] **Step 4: Run** the focused provider tests, then the backend test target `make test-backend` if Docker is available. Inspect any existing expectations for provider order and update only those made obsolete by the approved behavior.

### Task 3: Deploy and verify

**Files:**
- Deploy only: `backend/app/providers/sina.py`, `backend/app/services/market_data.py` in a versioned API image.

- [ ] **Step 1: Record** the current image tag, container health, and domestic `stale` statuses. Build and transfer the new API image without changing the PostgreSQL or secret volumes.
- [ ] **Step 2: Recreate** API and worker with the new image. Ensure database migrations and both containers start cleanly.
- [ ] **Step 3: Trigger** one market-data refresh and verify each required SH/SZ ETF has `status="valid"`, `source="sina"` when AKShare is unavailable, with price and market timestamp present. Verify US ETF and FX inputs remain valid and the analytics stale warning clears.
- [ ] **Step 4: Inspect** logs and container health; report any source availability limitation. Do not send a test email unless requested.
