# Async Rebalance Preview Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Move rebalance preview refresh and calculation to a persistent worker-backed job so the web API never times out or becomes unavailable during a preview.

**Architecture:** \`POST /api/rebalance/preview-jobs\` persists a validated request snapshot and returns \`202\`; \`GET\` exposes status and terminal payload. The existing worker claims queued rows, refreshes market data, computes the existing preview in its own transactions, and stores either its response or a safe business error. React Query polls until a terminal state and renders current preview components.

**Tech Stack:** FastAPI, SQLAlchemy async + PostgreSQL, Alembic, APScheduler worker, Pydantic, pytest/httpx, React, TypeScript, TanStack Query, MSW, Vitest.

## Global Constraints

- Do not alter holdings, asset classes, settings, historical snapshots, or rebalancing plans.
- The API endpoint must return without refreshing data or running the optimizer.
- Worker-only calculation retains certified optimization semantics and stops with a safe business error at a monotonic deadline.
- Errors use the existing safe \`{ code, message, ...detail }\` shape; never expose provider exceptions or credentials.
- Tests use the isolated test database only; they never access the Docker production data volume.
- Existing \`POST /api/rebalance/preview\` remains temporarily compatible for internal callers; the page uses only the job API.

---

## File Structure

- Create \`backend/alembic/versions/20260915_0009_rebalance_preview_jobs.py\`: persistent job table.
- Modify \`backend/app/db/models.py\`: \`RebalancePreviewJob\` ORM model.
- Modify \`backend/app/schemas/rebalance.py\`: job request/status/error schemas.
- Create \`backend/app/services/rebalance_preview_jobs.py\`: idempotent creation, claim, completion, failure, recovery.
- Modify \`backend/app/services/rebalancing.py\`: reusable calculation and deadline propagation.
- Modify \`backend/app/domain/rebalance_optimizer.py\`: monotonic deadline check.
- Modify \`backend/app/api/routes/rebalance.py\`: create/status resources.
- Modify \`backend/app/worker.py\`: polling executor and recovery.
- Modify \`frontend/src/api/types.ts\`, \`frontend/src/features/rebalance/api.ts\`, \`frontend/src/pages/RebalancePage.tsx\`: job polling UI.
- Test \`backend/tests/integration/test_rebalance_api.py\`, \`backend/tests/unit/test_worker.py\`, \`backend/tests/unit/test_rebalance_optimizer.py\`, \`frontend/tests/RebalancePage.test.tsx\`.

### Task 1: Persisted job contract

**Files:**
- Create: \`backend/alembic/versions/20260915_0009_rebalance_preview_jobs.py\`
- Modify: \`backend/app/db/models.py\`
- Modify: \`backend/app/schemas/rebalance.py\`
- Test: \`backend/tests/integration/test_rebalance_api.py\`

**Interfaces:**
- Consumes: \`RebalancePreviewRequest\`.
- Produces: \`RebalancePreviewJobCreateResponse\` and \`RebalancePreviewJobStatusResponse\`.

- [ ] **Step 1: Write the failing schema/API test**

\`\`\`python
created = await api_client.post("/api/rebalance/preview-jobs", json=_preview_payload())
assert created.status_code == 202
assert created.json()["status"] == "queued"
assert created.json()["result"] is None
assert created.json()["error"] is None
\`\`\`

- [ ] **Step 2: Run it red**

Run: \`cd backend && uv run pytest tests/integration/test_rebalance_api.py -k preview_job -v\`

Expected: FAIL with 404 because the job endpoint does not exist.

- [ ] **Step 3: Add the minimal persistent contract**

Create a \`rebalance_preview_jobs\` migration and model with UUID \`id\`, unique \`request_token\`, \`status\`, JSON \`payload\`, nullable JSON \`result\` and \`error\`, and UTC \`created_at\`, \`started_at\`, \`heartbeat_at\`, \`finished_at\`. Add a status check for exactly \`queued\`, \`refreshing\`, \`calculating\`, \`succeeded\`, \`failed\`, plus an index on \`(status, created_at)\`.

\`\`\`python
class RebalancePreviewJob(Base):
    __tablename__ = "rebalance_preview_jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    error: Mapped[dict[str, object] | None] = mapped_column(JSON)
\`\`\`

Define responses with \`id\`, \`status\`, nullable \`result: RebalancePreviewResponse | None\`, and nullable safe \`error: dict[str, object] | None\`.

- [ ] **Step 4: Run contract test**

Run: \`cd backend && uv run pytest tests/integration/test_rebalance_api.py -k preview_job -v\`

Expected: FAIL only because service/endpoints are absent.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add backend/alembic/versions/20260915_0009_rebalance_preview_jobs.py backend/app/db/models.py backend/app/schemas/rebalance.py backend/tests/integration/test_rebalance_api.py
git commit -m "feat: persist rebalance preview jobs"
\`\`\`

### Task 2: Job creation and status API

**Files:**
- Create: \`backend/app/services/rebalance_preview_jobs.py\`
- Modify: \`backend/app/api/routes/rebalance.py\`
- Test: \`backend/tests/integration/test_rebalance_api.py\`

**Interfaces:**
- Produces: \`create_preview_job(session, payload) -> tuple[RebalancePreviewJobStatusResponse, bool]\`, \`get_preview_job(session, job_id)\`, \`claim_next_preview_job(session)\`, \`complete_preview_job(...)\`, \`fail_preview_job(...)\`.

- [ ] **Step 1: Write the failing idempotency test**

\`\`\`python
first = await api_client.post("/api/rebalance/preview-jobs", json=_preview_payload())
second = await api_client.post("/api/rebalance/preview-jobs", json=_preview_payload())
status = await api_client.get("/api/rebalance/preview-jobs/" + first.json()["id"])
assert first.status_code == 202
assert second.status_code == 200
assert second.json()["id"] == first.json()["id"]
assert status.json()["status"] == "queued"
\`\`\`

- [ ] **Step 2: Run it red**

Run: \`cd backend && uv run pytest tests/integration/test_rebalance_api.py -k "preview_job and idempotent" -v\`

Expected: FAIL with 404.

- [ ] **Step 3: Implement creation, lookup, and claim**

Serialize \`payload.model_dump(mode="json")\`; lookup by \`request_token\`; return \`202\` only for creation and \`200\` for a duplicate. Unknown task IDs return \`404 REBALANCE_PREVIEW_JOB_NOT_FOUND\`. Claiming selects a queued row with \`FOR UPDATE SKIP LOCKED\`, sets \`refreshing\`, \`started_at\`, and \`heartbeat_at\`, then flushes.

- [ ] **Step 4: Run API tests green**

Run: \`cd backend && uv run pytest tests/integration/test_rebalance_api.py -k preview_job -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add backend/app/services/rebalance_preview_jobs.py backend/app/api/routes/rebalance.py backend/tests/integration/test_rebalance_api.py
git commit -m "feat: expose rebalance preview job API"
\`\`\`

### Task 3: Bounded certified optimizer

**Files:**
- Modify: \`backend/app/domain/rebalance_optimizer.py\`
- Modify: \`backend/app/domain/rebalance.py\`
- Modify: \`backend/app/services/rebalancing.py\`
- Test: \`backend/tests/unit/test_rebalance_optimizer.py\`

**Interfaces:**
- Consumes: optional \`deadline: float | None\`.
- Produces: \`OptimizationFailure("REBALANCE_OPTIMIZATION_TIMEOUT", explored_nodes, gap)\`.

- [ ] **Step 1: Write the failing deterministic deadline test**

\`\`\`python
with pytest.raises(OptimizationFailure) as raised:
    optimize_discrete(assets, cash, allow_sell=True, allow_fx=True, deadline=0)
assert raised.value.code == "REBALANCE_OPTIMIZATION_TIMEOUT"
\`\`\`

- [ ] **Step 2: Run it red**

Run: \`cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py -k deadline -v\`

Expected: FAIL because \`deadline\` is not accepted.

- [ ] **Step 3: Implement deadline propagation**

Import \`monotonic\`; accept a nullable deadline in optimizer/rebalance options; check it before each node pop. Keep the current node-budget behavior unchanged. The worker calculation creates \`monotonic() + PREVIEW_JOB_OPTIMIZATION_SECONDS\`; service code translates timeout into \`ServiceError(422, "REBALANCE_OPTIMIZATION_TIMEOUT", "再平衡计算超出时间预算。")\`.

- [ ] **Step 4: Run optimizer tests green**

Run: \`cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add backend/app/domain/rebalance_optimizer.py backend/app/domain/rebalance.py backend/app/services/rebalancing.py backend/tests/unit/test_rebalance_optimizer.py
git commit -m "fix: bound rebalance optimization runtime"
\`\`\`

### Task 4: Worker execution and crash recovery

**Files:**
- Modify: \`backend/app/worker.py\`
- Modify: \`backend/app/services/rebalance_preview_jobs.py\`
- Modify: \`backend/app/services/rebalancing.py\`
- Test: \`backend/tests/unit/test_worker.py\`
- Test: \`backend/tests/integration/test_rebalance_api.py\`

**Interfaces:**
- Produces: \`run_preview_job_once() -> bool\`, \`watch_preview_jobs()\`, and terminal persisted job results.

- [ ] **Step 1: Write failing worker tests**

\`\`\`python
processed = await worker_module.run_preview_job_once()
assert processed is True
assert refreshed.status == "succeeded"

requeued = await preview_jobs.requeue_abandoned_preview_jobs(session, now=NOW)
assert requeued == 1
assert abandoned.status == "queued"
\`\`\`

- [ ] **Step 2: Run them red**

Run: \`cd backend && uv run pytest tests/unit/test_worker.py -k preview_job -v\`

Expected: FAIL because the worker loop is absent.

- [ ] **Step 3: Implement job execution**

Add \`PREVIEW_JOB_POLL_SECONDS = 1\`, \`PREVIEW_JOB_RECOVERY_SECONDS = 120\`, and \`PREVIEW_JOB_OPTIMIZATION_SECONDS = 15\`. On startup and before polling, requeue stale \`refreshing\` and \`calculating\` rows. Claim one job transactionally; refresh data in a transaction; transition to \`calculating\`; compute with the deadline; complete with serialized existing \`RebalancePreviewResponse\`. Persist \`ServiceError.to_detail()\` as \`failed\`. Unexpected errors become safe \`REBALANCE_PREVIEW_JOB_FAILED\` and are logged server-side. Start and gracefully cancel this watcher alongside the schedule watcher.

- [ ] **Step 4: Run worker/API tests green**

Run: \`cd backend && uv run pytest tests/unit/test_worker.py -k preview_job -v; uv run pytest tests/integration/test_rebalance_api.py -k preview_job -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add backend/app/worker.py backend/app/services/rebalance_preview_jobs.py backend/app/services/rebalancing.py backend/tests/unit/test_worker.py backend/tests/integration/test_rebalance_api.py
git commit -m "feat: process rebalance preview jobs in worker"
\`\`\`

### Task 5: React creation, polling, and terminal rendering

**Files:**
- Modify: \`frontend/src/api/types.ts\`
- Modify: \`frontend/src/features/rebalance/api.ts\`
- Modify: \`frontend/src/pages/RebalancePage.tsx\`
- Test: \`frontend/tests/RebalancePage.test.tsx\`

**Interfaces:**
- Produces: \`useCreateRebalancePreviewJob()\`, \`useRebalancePreviewJob(jobId)\`, and terminal mapping to existing \`RebalancePreview\`.

- [ ] **Step 1: Write failing polling UI tests**

MSW returns \`queued\`, then \`refreshing\`, then \`succeeded\` with \`rebalancePreviewFixture\`.

\`\`\`tsx
expect(await screen.findByText("正在刷新行情")).toBeInTheDocument();
expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
expect(screen.queryByText("正在刷新行情")).not.toBeInTheDocument();
\`\`\`

Add a separate terminal \`failed\` response assertion for the returned Chinese message and no continued polling.

- [ ] **Step 2: Run it red**

Run: \`cd frontend && npm test -- RebalancePage.test.tsx\`

Expected: FAIL because the page posts to \`/api/rebalance/preview\`.

- [ ] **Step 3: Implement job hooks and view state**

Define \`RebalancePreviewJobStatus\` with exactly the five backend literals. The create mutation posts to \`/api/rebalance/preview-jobs\`. The status query GETs \`/api/rebalance/preview-jobs/{jobId}\` and uses a \`refetchInterval\` of 1000 until a terminal state. After defaults are saved, \`runPreview\` creates and stores the job ID, clears old output, and disables duplicate submit. On success use the existing preview-rendering state; on failure map \`error\` through existing \`ApiError\` display rules. Use exactly: \`正在排队测算\`, \`正在刷新行情\`, \`正在计算方案\`.

- [ ] **Step 4: Run UI tests green**

Run: \`cd frontend && npm test -- RebalancePage.test.tsx\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add frontend/src/api/types.ts frontend/src/features/rebalance/api.ts frontend/src/pages/RebalancePage.tsx frontend/tests/RebalancePage.test.tsx
git commit -m "feat: poll rebalance preview jobs in UI"
\`\`\`

### Task 6: Regression and delivery verification

**Files:**
- Modify only a file proven necessary by a failing regression test.
- Test: focused backend suite, frontend suite, migration suite.

- [ ] **Step 1: Run focused backend verification**

Run: \`cd backend && uv run pytest tests/integration/test_rebalance_api.py tests/unit/test_rebalance_optimizer.py tests/unit/test_worker.py -v\`

Expected: PASS with no production database access.

- [ ] **Step 2: Run frontend verification**

Run: \`cd frontend && npm test -- RebalancePage.test.tsx && npm run build\`

Expected: PASS.

- [ ] **Step 3: Run migration verification**

Run: \`cd backend && uv run pytest tests/integration/test_migrations.py -v\`

Expected: PASS.

- [ ] **Step 4: Inspect final changes**

Run: \`git diff --check HEAD~6..HEAD; git status --short\`

Expected: no whitespace errors and only intentional source/test changes.

- [ ] **Step 5: Commit a regression-only adjustment if and only if a failing test required it**

\`\`\`powershell
git add <only-files-proven-necessary-by-a-failing-regression-test>
git commit -m "test: cover async rebalance preview regression"
\`\`\`

