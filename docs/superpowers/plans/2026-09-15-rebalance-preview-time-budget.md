# Rebalance Preview Time Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the asynchronous rebalance preview worker up to five minutes of optimizer time without weakening its bounded-search safeguards.

**Architecture:** The worker remains the only caller that supplies an optimization deadline. Change its single time-budget constant from 15 to 300 seconds, preserving the node cap, persistent job lifecycle, and frontend polling.

**Tech Stack:** Python 3.13, pytest, Docker Compose, FastAPI worker.

## Global Constraints

- Set the preview optimizer budget to exactly 300 seconds.
- Keep the node budget and typed timeout behaviour unchanged.
- Run tests only through the isolated `portfolio-rebalancer-test` Compose environment.
- Do not modify production portfolio, holding, market-data, or settings records.

---

### Task 1: Increase and protect the worker calculation budget

**Files:**
- Modify: `backend/app/worker.py:32-35`
- Modify: `backend/tests/unit/test_worker.py`

**Interfaces:**
- Consumes: `PREVIEW_JOB_OPTIMIZATION_SECONDS` passed by `run_preview_job_once()` to `preview_rebalance_from_current_data()`.
- Produces: a five-minute calculation allowance while retaining `REBALANCE_OPTIMIZATION_TIMEOUT`.

- [x] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_worker.py`:

```python
def test_preview_job_uses_a_five_minute_optimization_budget() -> None:
    assert worker.PREVIEW_JOB_OPTIMIZATION_SECONDS == 300
```

- [x] **Step 2: Run the focused test to verify it fails**

Run with the existing isolated test Compose environment:

```powershell
docker compose run --rm -e DATABASE_URL -e PYTEST_DATABASE_RESET_TOKEN -e COMPOSE_PROJECT_NAME -e PYTEST_POSTGRES_VOLUME -e PYTEST_SECRET_VOLUME -e PYTEST_BACKUP_VOLUME api uv run pytest tests/unit/test_worker.py -q
```

Expected: FAIL because the current constant is `15`.

- [x] **Step 3: Make the minimal implementation change**

Update `backend/app/worker.py`:

```python
PREVIEW_JOB_OPTIMIZATION_SECONDS = 300
```

- [x] **Step 4: Run focused verification**

Repeat the Step 2 command. Expected: all worker tests PASS.

- [x] **Step 5: Run the complete backend suite in the isolated environment**

```powershell
docker compose run --rm -e DATABASE_URL -e PYTEST_DATABASE_RESET_TOKEN -e COMPOSE_PROJECT_NAME -e PYTEST_POSTGRES_VOLUME -e PYTEST_SECRET_VOLUME -e PYTEST_BACKUP_VOLUME api uv run pytest -q
```

Expected: zero failures.

- [x] **Step 6: Commit**

```powershell
git add backend/app/worker.py backend/tests/unit/test_worker.py
git commit -m "fix: extend rebalance preview time budget"
```
