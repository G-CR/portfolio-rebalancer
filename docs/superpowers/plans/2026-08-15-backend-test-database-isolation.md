# Backend Test Database Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every backend database test fail closed unless it is explicitly targeting the isolated `portfolio_test` database, while preserving the real Compose project, its PostgreSQL volume, and all portfolio data.

**Architecture:** Add a pure URL/token guard in the pytest package and invoke it before SQLAlchemy creates the test engine. Make the supported Make target create a separate Compose project whose PostgreSQL instance is initialized as `portfolio_test`, and explicitly inject both the guarded URL and reset token into migration/test containers. Verify the safety boundary by fingerprinting the real database before and after both the supported path and the formerly dangerous raw pytest path.

**Tech Stack:** Python 3.13, pytest, SQLAlchemy URL parsing, Docker Compose v2, GNU Make, PostgreSQL 17, Markdown

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-15-backend-test-database-isolation-design.md` exactly.
- Use test-driven development: capture each intended failure before adding its implementation.
- Never run a database-backed pytest command against the main Compose project before the fail-closed guard is installed and proven.
- Never run `docker compose down -v` without the isolated `COMPOSE_PROJECT_NAME=portfolio-rebalancer-test` value in the same shell scope.
- Do not change production database schemas, application APIs, Docker production defaults, or user data.
- Do not add a force bypass or accept database-name patterns; only the exact database/token pair `portfolio_test` is valid.
- Preserve unrelated user changes and the existing production Compose containers and volumes.

---

## Task 1: Add a pure fail-closed database identity guard

**Files:**

- Create: `backend/tests/__init__.py`
- Create: `backend/tests/database_safety.py`
- Create: `backend/tests/unit/test_database_safety.py`

- [ ] **Step 1: Write the guard contract tests**

Create `backend/tests/__init__.py` as an empty package marker, then add `backend/tests/unit/test_database_safety.py`:

```python
import pytest

from tests.database_safety import require_safe_test_database


SAFE_URL = "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test"


@pytest.mark.parametrize(
    ("database_url", "reset_token", "rejected_database"),
    [
        (None, "portfolio_test", "unset"),
        (
            "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio",
            "portfolio_test",
            "portfolio",
        ),
        (SAFE_URL, None, "portfolio_test"),
        (SAFE_URL, "wrong-token", "portfolio_test"),
    ],
)
def test_rejects_unsafe_database_identity(
    database_url: str | None,
    reset_token: str | None,
    rejected_database: str,
) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        require_safe_test_database(database_url, reset_token)

    message = str(exc_info.value)
    assert rejected_database in message
    assert "Business databases must never be reset by pytest" in message
    assert "make test-backend" in message


@pytest.mark.parametrize(
    "database_url",
    [
        SAFE_URL,
        f"{SAFE_URL}?ssl=disable",
    ],
)
def test_accepts_only_explicit_test_database_and_token(database_url: str) -> None:
    assert require_safe_test_database(database_url, "portfolio_test") == database_url
```

- [ ] **Step 2: Run the focused tests in a disposable, database-free Compose project and confirm RED**

Run from the repository root in a POSIX-compatible shell used by `make`:

```bash
COMPOSE_PROJECT_NAME=portfolio-rebalancer-guard-red \
docker compose run --rm --no-deps \
  -e DATABASE_URL=postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test \
  -e PYTEST_DATABASE_RESET_TOKEN=portfolio_test \
  api uv run pytest -q tests/unit/test_database_safety.py
```

Expected: collection fails because `tests.database_safety` does not exist. This command uses a distinct Compose project and `--no-deps`, so it cannot start or attach to the main PostgreSQL service.

- [ ] **Step 3: Implement the pure guard**

Create `backend/tests/database_safety.py`:

```python
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


EXPECTED_TEST_DATABASE = "portfolio_test"


def require_safe_test_database(
    database_url: str | None,
    reset_token: str | None,
) -> str:
    database_name = "unset"
    if database_url is not None:
        try:
            database_name = make_url(database_url).database or "unset"
        except ArgumentError:
            database_name = "invalid"

    if (
        database_url is None
        or database_name != EXPECTED_TEST_DATABASE
        or reset_token != EXPECTED_TEST_DATABASE
    ):
        raise RuntimeError(
            "Refusing pytest database reset: "
            f"database={database_name!r}. "
            "Business databases must never be reset by pytest. "
            "Run `make test-backend`."
        )

    return database_url
```

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Re-run the Step 2 command.

Expected: 6 tests pass without starting a PostgreSQL container.

- [ ] **Step 5: Commit the guard contract**

```bash
git add backend/tests/__init__.py backend/tests/database_safety.py backend/tests/unit/test_database_safety.py
git commit -m "test: define safe database reset identity"
```

---

## Task 2: Enforce the guard before creating the pytest engine

**Files:**

- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/unit/test_database_safety.py`

- [ ] **Step 1: Add an import-time subprocess regression test**

Extend `backend/tests/unit/test_database_safety.py` with a subprocess test that imports `tests.conftest` in a clean environment and proves the rejected production URL fails before an engine can be used:

```python
import os
from pathlib import Path
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_conftest_rejects_business_database_before_test_collection() -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio"
    )
    environment["PYTEST_DATABASE_RESET_TOKEN"] = "portfolio_test"

    result = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "database='portfolio'" in result.stderr
    assert "make test-backend" in result.stderr
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run the disposable command from Task 1, Step 2.

Expected: the new subprocess assertion fails because current `conftest.py` accepts the production database URL.

- [ ] **Step 3: Remove the production fallback and validate before engine creation**

Change the database setup in `backend/tests/conftest.py` to:

```python
from tests.database_safety import require_safe_test_database


DATABASE_URL = require_safe_test_database(
    os.getenv("DATABASE_URL"),
    os.getenv("PYTEST_DATABASE_RESET_TOKEN"),
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
```

Delete the existing `os.getenv(..., ".../portfolio")` fallback. Keep this guard call above `create_async_engine`, `SessionFactory`, every fixture, and every call that can open a database connection.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Re-run the disposable command from Task 1, Step 2.

Expected: 7 tests pass; the child process rejects `portfolio` while the parent test process is explicitly authorized for `portfolio_test`.

- [ ] **Step 5: Prove the formerly dangerous raw command now fails closed**

First record the real database fingerprint using the already-running main `db` container:

```bash
docker compose exec -T db psql -U portfolio -d portfolio -Atc \
  "SELECT json_build_object('asset_classes',(SELECT count(*) FROM asset_classes),'holdings',(SELECT count(*) FROM holdings),'snapshots',(SELECT count(*) FROM snapshots),'settings',(SELECT count(*) FROM settings))::text" \
  > .superpowers/main-db-before.txt
```

Then run the old command without either safety variable:

```bash
docker compose run --rm api uv run pytest -q tests/integration/test_holdings_api.py
```

Expected: non-zero exit during `conftest.py` import with `database='unset'` and `make test-backend` in the error. It must not report a test body as started.

Capture the fingerprint again and compare:

```bash
docker compose exec -T db psql -U portfolio -d portfolio -Atc \
  "SELECT json_build_object('asset_classes',(SELECT count(*) FROM asset_classes),'holdings',(SELECT count(*) FROM holdings),'snapshots',(SELECT count(*) FROM snapshots),'settings',(SELECT count(*) FROM settings))::text" \
  > .superpowers/main-db-after-raw-command.txt
cmp .superpowers/main-db-before.txt .superpowers/main-db-after-raw-command.txt
```

Expected: `cmp` exits 0.

- [ ] **Step 6: Commit the enforced pytest boundary**

```bash
git add backend/tests/conftest.py backend/tests/unit/test_database_safety.py
git commit -m "fix: block pytest resets outside test database"
```

---

## Task 3: Make the supported test target provision `portfolio_test`

**Files:**

- Modify: `Makefile`

- [ ] **Step 1: Add explicit isolated database variables and container injection**

Replace the `test-backend` recipe with:

```make
PYTEST_ARGS ?= -v

test-backend:
	@set -eu; \
		export COMPOSE_PROJECT_NAME=portfolio-rebalancer-test; \
		export POSTGRES_DB=portfolio_test; \
		export DATABASE_URL=postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test; \
		export PYTEST_DATABASE_RESET_TOKEN=portfolio_test; \
		export PORTFOLIO_PORT=0; \
		cleanup() { docker compose down -v --remove-orphans >/dev/null 2>&1 || true; }; \
		trap cleanup EXIT; \
		cleanup; \
		docker compose up -d db; \
		docker compose build api; \
		docker compose run --rm -e DATABASE_URL api uv run alembic upgrade head; \
		docker compose run --rm -e DATABASE_URL -e PYTEST_DATABASE_RESET_TOKEN api uv run pytest $(PYTEST_ARGS)
```

The `PYTEST_ARGS` override permits focused verification while the no-argument command still runs the complete suite verbosely. Do not pass either safety variable to the normal `up` target.

- [ ] **Step 2: Inspect the resolved isolated Compose configuration**

```bash
COMPOSE_PROJECT_NAME=portfolio-rebalancer-test \
POSTGRES_DB=portfolio_test \
DATABASE_URL=postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test \
PYTEST_DATABASE_RESET_TOKEN=portfolio_test \
PORTFOLIO_PORT=0 \
docker compose config
```

Expected: the database service initializes `POSTGRES_DB: portfolio_test`; no main-project volume name appears; no public PostgreSQL port is published.

- [ ] **Step 3: Run the supported target against the isolated database**

```bash
make test-backend PYTEST_ARGS="-q tests/unit/test_database_safety.py tests/integration/test_holdings_api.py"
```

Expected: focused guard and holdings integration tests pass, migrations target `portfolio_test`, and the cleanup trap removes only `portfolio-rebalancer-test` containers and volumes.

- [ ] **Step 4: Verify real services, volume identity, and database fingerprint are unchanged**

```bash
docker compose ps
docker compose exec -T db psql -U portfolio -d portfolio -Atc \
  "SELECT json_build_object('asset_classes',(SELECT count(*) FROM asset_classes),'holdings',(SELECT count(*) FROM holdings),'snapshots',(SELECT count(*) FROM snapshots),'settings',(SELECT count(*) FROM settings))::text" \
  > .superpowers/main-db-after-supported-tests.txt
cmp .superpowers/main-db-before.txt .superpowers/main-db-after-supported-tests.txt
docker volume inspect portfolio-rebalancer_postgres_data
```

Expected: main services remain running, `cmp` exits 0, and the production volume still exists with the same name and mount identity recorded before testing. If the actual Compose project/volume prefix differs locally, resolve it read-only with `docker compose ps -q db` plus `docker inspect` and compare that exact volume before/after instead of guessing.

- [ ] **Step 5: Commit the safe test entry point**

```bash
git add Makefile
git commit -m "build: isolate backend test database"
```

---

## Task 4: Document the one supported backend test workflow

**Files:**

- Modify: `README.md`
- Modify: `docs/operations.md`

- [ ] **Step 1: Add a README testing section**

Insert before `## Fonts` in `README.md`:

```markdown
## Backend Tests

Run backend tests only through the isolated target:

```bash
make test-backend
```

The target uses a separate Compose project, a disposable PostgreSQL volume, and the dedicated `portfolio_test` database. Do not run `docker compose run api pytest`, `docker compose run --rm api uv run pytest`, or database integration tests directly in the normal Compose project: pytest intentionally refuses those commands before any business table can be cleared.
```

- [ ] **Step 2: Strengthen the operations warning**

Replace the `docs/operations.md` “后端测试” paragraph with:

```markdown
## 后端测试

唯一支持的后端测试入口是：

```bash
make test-backend
```

该目标固定使用独立 Compose 项目 `portfolio-rebalancer-test`、一次性 PostgreSQL 卷和专用数据库 `portfolio_test`，并在结束后只清理测试项目。pytest 还会在创建测试引擎前校验数据库名和重置标记。

不要在日常 Compose 项目中运行 `docker compose run api pytest`、`docker compose run --rm api uv run pytest`，也不要直接执行数据库集成测试。此类命令会在任何清表操作前被拒绝，并提示改用 `make test-backend`。日常项目仍然只能用不带 `-v` 的 `docker compose down` 停机。
```

- [ ] **Step 3: Check that documentation exposes no unsafe backend test command as runnable guidance**

```bash
rg -n "pytest|test-backend|down -v" README.md docs Makefile
```

Expected: `make test-backend` is the only supported command; raw pytest forms appear only inside explicit prohibition text; `down -v` remains scoped to the test recipe or warning text.

- [ ] **Step 4: Commit the documentation**

```bash
git add README.md docs/operations.md
git commit -m "docs: require isolated backend test target"
```

---

## Task 5: Full safety verification and review

**Files:**

- Verify: `backend/tests/database_safety.py`
- Verify: `backend/tests/conftest.py`
- Verify: `backend/tests/unit/test_database_safety.py`
- Verify: `Makefile`
- Verify: `README.md`
- Verify: `docs/operations.md`

- [ ] **Step 1: Run the complete backend suite through the isolated entry point**

```bash
make test-backend
```

Expected: all non-environment-dependent backend tests pass. If an existing date-dependent email test fails, record its exact test name and output, then re-run every other backend test through the same isolated Make target; do not weaken the safety guard or run the suite against the main database to obtain a green result.

- [ ] **Step 2: Repeat the formerly dangerous raw-command regression after the full suite**

```bash
docker compose run --rm api uv run pytest -q tests/integration/test_holdings_api.py
```

Expected: immediate non-zero exit with the safety message, before any test or table reset.

- [ ] **Step 3: Perform the final production-data invariants check**

Re-capture the same database fingerprint, main `db` container ID, and attached PostgreSQL volume name used earlier. Compare all three to the pre-test values.

Expected: fingerprint, container identity, and production volume identity are unchanged; `docker compose ps` still reports the normal services running.

- [ ] **Step 4: Inspect the final diff for scope and secrets**

```bash
git diff --check
git status --short
git diff -- backend/tests/database_safety.py backend/tests/conftest.py backend/tests/unit/test_database_safety.py Makefile README.md docs/operations.md
```

Confirm there is no force bypass, no production database fallback, no broad database-name matching, no credential leakage, no production Compose change, and no unrelated user-file modification.

- [ ] **Step 5: Request code review and address only verified findings**

Use the `requesting-code-review` skill against the design spec and implementation plan. Reproduce any reported issue, add a regression test where applicable, make the smallest fix, and rerun the focused plus safety verification commands.

- [ ] **Step 6: Commit any verified review fixes**

```bash
git add backend/tests/database_safety.py backend/tests/conftest.py backend/tests/unit/test_database_safety.py Makefile README.md docs/operations.md
git commit -m "fix: harden backend test isolation"
```

Skip this commit if review requires no code changes.

- [ ] **Step 7: Hand off with evidence**

Report the exact passing test counts, any known unrelated failures, the raw-command rejection output, and the before/after production database/container/volume comparison. Do not claim completion until the verification evidence is fresh. Use `finishing-a-development-branch` to let the user choose merge, push, PR, or retention/cleanup.
