# AKShare Refresh Snapshot Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every market-data refresh download the complete AKShare ETF snapshot at most once while preserving per-symbol normalization, fallback diagnostics, and fresh data on the next refresh.

**Architecture:** Keep the optimization inside the request-scoped `AkshareProvider` instance owned by `ProviderRegistry`. Lazily cache one `asyncio.Task` and one snapshot timestamp so sequential and concurrent symbol requests share the same success or failure; a new registry on the next refresh creates a fresh provider and a fresh request.

**Tech Stack:** Python 3.13, asyncio, FastAPI service layer, pytest, pytest-asyncio, Docker Compose, PostgreSQL 17

## Global Constraints

- Optimize only AKShare price retrieval for supported domestic markets.
- Keep provider order unchanged: domestic prices use AKShare then Tushare; international prices and FX retain their current providers and fallbacks.
- Do not require or configure a Tushare token.
- Do not change the frontend, API contracts, database schema, Compose configuration, or scheduled-refresh behavior.
- Do not introduce a process-wide or time-based cache.
- Cache both success and failure only for the lifetime of one `AkshareProvider` instance.
- A successful shared snapshot must still normalize and persist each symbol independently.
- Backend tests must run only through the isolated `make test-backend` target using `portfolio_test`; never run raw pytest against the production Compose project.
- Production must remain attached to `portfolio-rebalancer_postgres_data`; never use `down -v` or truncate business tables.

---

### Task 1: Reuse One AKShare Snapshot Per Provider Instance

**Files:**
- Modify: `backend/app/providers/akshare.py`
- Modify: `backend/tests/unit/test_provider_normalization.py`

**Interfaces:**
- Consumes: existing `AkshareProvider.fetch_price(symbol: str) -> MarketQuote` and `normalize_price` behavior.
- Produces: instance fields `_price_rows_task: asyncio.Task[list[dict[str, Any]]] | None` and `_price_snapshot_fetched_at: datetime | None`; private `_blocking_fetch_price_rows() -> list[dict[str, Any]]` with no unused symbol argument.

- [ ] **Step 1: Add deterministic failing tests for sequential reuse and refresh isolation**

Add `import asyncio` at the top of `backend/tests/unit/test_provider_normalization.py`, then add after the existing AKShare normalization tests:

```python
@pytest.mark.asyncio
async def test_akshare_reuses_one_snapshot_for_sequential_symbols_and_new_instance_refreshes(
    monkeypatch,
) -> None:
    rows = [
        {"代码": "159209", "最新价": "1.142", "时间": "2026-08-20 15:00:00"},
        {"代码": "518850", "最新价": "9.324", "时间": "2026-08-20 15:00:00"},
    ]
    calls = 0

    def load_rows(self) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return rows

    monkeypatch.setattr(AkshareProvider, "_blocking_fetch_price_rows", load_rows)

    provider = AkshareProvider()
    first = await provider.fetch_price("159209")
    second = await provider.fetch_price("518850")

    assert calls == 1
    assert first.value == Decimal("1.142")
    assert second.value == Decimal("9.324")
    assert first.fetched_at == second.fetched_at

    await AkshareProvider().fetch_price("159209")
    assert calls == 2
```

- [ ] **Step 2: Add deterministic failing tests for concurrent reuse and failure reuse**

Add:

```python
@pytest.mark.asyncio
async def test_akshare_separate_instances_do_not_share_snapshot(monkeypatch) -> None:
    calls = 0

    def load_rows(self) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [
            {"代码": "159209", "最新价": "1.142", "时间": "2026-08-20 15:00:00"},
            {"代码": "518850", "最新价": "9.324", "时间": "2026-08-20 15:00:00"},
        ]

    monkeypatch.setattr(AkshareProvider, "_blocking_fetch_price_rows", load_rows)
    quotes = await asyncio.gather(
        AkshareProvider().fetch_price("159209"),
        AkshareProvider().fetch_price("518850"),
    )

    assert calls == 2
    assert [quote.symbol for quote in quotes] == ["159209", "518850"]
```

The test above deliberately proves separate provider instances do not share a global cache. Add the actual same-instance concurrency contract separately:

```python
@pytest.mark.asyncio
async def test_akshare_same_instance_concurrent_symbols_share_snapshot(monkeypatch) -> None:
    calls = 0

    def load_rows(self) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [
            {"代码": "159209", "最新价": "1.142", "时间": "2026-08-20 15:00:00"},
            {"代码": "518850", "最新价": "9.324", "时间": "2026-08-20 15:00:00"},
        ]

    monkeypatch.setattr(AkshareProvider, "_blocking_fetch_price_rows", load_rows)
    provider = AkshareProvider()
    quotes = await asyncio.gather(
        provider.fetch_price("159209"),
        provider.fetch_price("518850"),
    )

    assert calls == 1
    assert [quote.symbol for quote in quotes] == ["159209", "518850"]
```

Add the cached-failure contract:

```python
@pytest.mark.asyncio
async def test_akshare_same_instance_reuses_snapshot_failure(monkeypatch) -> None:
    calls = 0

    def fail_rows(self) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        raise ProviderRequestError("AKShare request failed.")

    monkeypatch.setattr(AkshareProvider, "_blocking_fetch_price_rows", fail_rows)
    provider = AkshareProvider()
    results = await asyncio.gather(
        provider.fetch_price("159209"),
        provider.fetch_price("518850"),
        return_exceptions=True,
    )

    assert calls == 1
    assert all(isinstance(result, ProviderRequestError) for result in results)
```

- [ ] **Step 3: Run the focused provider suite and verify RED**

From PowerShell in the isolated worktree, run:

```powershell
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/akshare-snapshot-reuse `
  /usr/bin/make test-backend "PYTEST_ARGS=-q tests/unit/test_provider_normalization.py"
```

Expected: the same-instance sequential, concurrent, and failure contracts fail because `_blocking_fetch_price_rows` is called once per symbol. Existing provider tests remain green.

- [ ] **Step 4: Add the minimal provider-instance single-flight cache**

Change `backend/app/providers/akshare.py` as follows:

```python
class AkshareProvider:
    source = "akshare"

    def __init__(self) -> None:
        self._price_rows_task: asyncio.Task[list[dict[str, Any]]] | None = None
        self._price_snapshot_fetched_at: datetime | None = None

    async def fetch_price(self, symbol: str) -> MarketQuote:
        if self._price_rows_task is None:
            self._price_snapshot_fetched_at = datetime.now(UTC)
            self._price_rows_task = asyncio.create_task(
                asyncio.to_thread(self._blocking_fetch_price_rows)
            )

        payload = await self._price_rows_task
        if self._price_snapshot_fetched_at is None:  # pragma: no cover - invariant
            raise RuntimeError("AKShare snapshot timestamp was not initialized.")
        return self.normalize_price(
            symbol,
            payload,
            fetched_at=self._price_snapshot_fetched_at,
        )
```

Change the private blocking method signature and leave its import/request error translation unchanged:

```python
def _blocking_fetch_price_rows(self) -> list[dict[str, Any]]:
```

Do not clear `_price_rows_task` after success or failure. Do not add TTLs, module globals, locks, retries, or service-layer AKShare branches.

- [ ] **Step 5: Run the focused provider suite and verify GREEN**

Re-run the Step 3 command.

Expected: all provider normalization tests pass; same-instance success/failure calls use one blocking request, while a new provider instance performs a new request.

- [ ] **Step 6: Run the focused market-data integration suite**

```powershell
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/akshare-snapshot-reuse `
  /usr/bin/make test-backend "PYTEST_ARGS=-q tests/integration/test_market_data_api.py"
```

Expected: all market-data integration tests pass, proving API response, fallback summaries, persistence, and failure handling remain unchanged.

- [ ] **Step 7: Commit the provider optimization**

```bash
git add backend/app/providers/akshare.py backend/tests/unit/test_provider_normalization.py
git commit -m "perf: reuse AKShare snapshot per refresh"
```

---

### Task 2: Full Verification and Review

**Files:**
- Verify: `backend/app/providers/akshare.py`
- Verify: `backend/tests/unit/test_provider_normalization.py`

**Interfaces:**
- Consumes: the Task 1 provider-instance cache.
- Produces: fresh whole-branch test evidence and an approved branch ready for integration.

- [ ] **Step 1: Run the complete backend suite through the isolated target**

```powershell
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/akshare-snapshot-reuse `
  /usr/bin/make test-backend
```

Expected: zero failures; the isolated test Compose project and disposable volumes are removed automatically.

- [ ] **Step 2: Check scope and working-tree integrity**

```powershell
git diff --check
git status --short
git diff --stat master...HEAD
git diff master...HEAD -- backend/app/providers/akshare.py backend/tests/unit/test_provider_normalization.py
```

Confirm no frontend, database, Compose, provider-order, credential, or scheduled-refresh files changed.

- [ ] **Step 3: Request task and whole-branch code review**

Review against:

- `docs/superpowers/specs/2026-08-20-akshare-refresh-snapshot-reuse-design.md`;
- this implementation plan; and
- the exact Global Constraints above.

The reviewer must specifically inspect task lifetime, failure reuse, concurrent callers, timestamp semantics, absence of global caching, unchanged provider fallback order, and test determinism. Resolve every Critical or Important finding and re-run the covering tests before requesting re-review.

- [ ] **Step 4: Complete the development branch**

Use the `finishing-a-development-branch` skill. Present the standard four choices. Do not deploy or refresh production until the user selects local merge or otherwise authorizes integration.

---

### Task 3: Deploy and Verify Live Refresh After Merge

**Files:**
- Deploy only after merge: `backend/app/providers/akshare.py`
- Verify only: production Compose services and market-data API

**Interfaces:**
- Consumes: merged, reviewed backend image.
- Produces: one successful live refresh with all required quotes usable and the official data volume unchanged.

- [ ] **Step 1: Record production safety invariants**

```powershell
docker inspect portfolio-rebalancer-db-1 --format '{{.Id}}'
docker inspect portfolio-rebalancer-db-1 --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}'
docker exec portfolio-rebalancer-db-1 psql -U portfolio -d portfolio -X -P pager=off -c `
  "SELECT count(*) AS holdings_count FROM holdings;"
```

Expected: the volume is exactly `portfolio-rebalancer_postgres_data`; record the DB container ID and holdings count before deployment.

- [ ] **Step 2: Rebuild only backend runtime services**

```powershell
docker compose up -d --build api worker
docker compose ps
```

Expected: API is healthy, worker is running, DB remains healthy, the DB container ID and volume name from Step 1 are unchanged.

- [ ] **Step 3: Trigger one timed live refresh through the normal API**

```powershell
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$result = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:3000/api/market-data/refresh' `
  -TimeoutSec 120
$timer.Stop()
Write-Output "elapsed_seconds=$([math]::Round($timer.Elapsed.TotalSeconds, 2))"
$result | ConvertTo-Json -Depth 12
```

Expected: HTTP 200. `price:159209`, `price:518850`, `price:563020`, `price:VOO`, `price:QQQ`, and `fx:USD/CNY` all have non-null `effective_value`; newly refreshed items have `status="valid"`. Domestic prices normally use `akshare`; international prices and USD/CNY may use `yahoo` or `sina` according to the existing fallback order.

- [ ] **Step 4: Verify persisted results and production isolation**

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/market-data' -TimeoutSec 15 |
  ConvertTo-Json -Depth 12
docker inspect portfolio-rebalancer-db-1 --format '{{.Id}}'
docker inspect portfolio-rebalancer-db-1 --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}'
docker exec portfolio-rebalancer-db-1 psql -U portfolio -d portfolio -X -P pager=off -c `
  "SELECT count(*) AS holdings_count FROM holdings;"
docker compose logs --since 10m api worker |
  Select-String -Pattern 'Traceback|ERROR| 500 | 504 ' -CaseSensitive:$false
```

Expected: all required data stays usable, holdings count is unchanged, DB container ID is unchanged, volume remains `portfolio-rebalancer_postgres_data`, and no new application traceback or 5xx is present.
