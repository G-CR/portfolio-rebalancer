# Portfolio Rebalancer V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the confirmed V1.1 local portfolio calibration web app, including cost basis maintenance, automated end-of-day market data, P&L decomposition, snapshots, and explainable rebalancing suggestions.

**Architecture:** A React 19 single-page application is served by Nginx and calls a FastAPI API through `/api`. FastAPI owns every financial formula and persists PostgreSQL data through SQLAlchemy; a separate worker process uses the same service layer for scheduled market refreshes and daily snapshots. Docker Compose exposes only `127.0.0.1:8080`, while API, worker, and database remain on the internal Docker network.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL 17, APScheduler, httpx, yfinance, AKShare, Tushare, cryptography, pytest, Hypothesis, React 19, TypeScript, Vite, React Router, TanStack Query, React Hook Form, Zod, Recharts, Lucide React, CSS Modules, Vitest, Testing Library, axe-core, Playwright, Nginx, Docker Compose.

---

## Delivery Phases

1. **Foundation:** Docker, API health, database migrations, and default strategy seed.
2. **Manual Core:** Asset classes, holdings, financial analytics, cost adjustments, and the confirmed front-end shell.
3. **Market & History:** Data providers, overrides, scheduled refresh, dashboard, P&L analysis, and snapshots.
4. **Rebalancing:** Explainable buy/sell/FX suggestions, formal rebalance lifecycle, and baseline FX reset.
5. **Operations & Acceptance:** Encrypted provider keys, backup/restore, visual regression, accessibility, and Docker verification.

Each phase ends with working software and a Git commit. Do not begin the next phase while the current phase's full test command is failing.

## Locked Technical Decisions

- Use `uv` for Python dependency and lockfile management.
- Use `npm` and commit `frontend/package-lock.json`.
- Use `Decimal` in Python and PostgreSQL `NUMERIC`; API decimal values are serialized as strings.
- Store quantities, prices, FX values, and weights at 12 decimal places. Do not quantize intermediate calculations; compare CNY accounting identities after quantizing both sides to `Decimal("0.01")`.
- Use UTC timestamps in PostgreSQL and convert to `Asia/Shanghai` at API/UI boundaries.
- Keep all business calculations in `backend/app/domain`; React only formats API results.
- Use CSS custom properties plus CSS Modules. Do not introduce Tailwind or a component framework.
- Bundle `Noto Sans SC` and `IBM Plex Mono` as local WOFF2 files before final acceptance.
- Use Lucide icons in production UI. Character icons shown in design mockups are not implementation assets.
- Use a deterministic heuristic rebalancing engine for five asset classes; keep the optimizer behind a pure function so it can later be replaced without changing API/UI contracts.

## Target File Map

```text
portfolio-rebalancer/
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── compose.yaml
├── scripts/
│   ├── backup.sh
│   └── restore.sh
├── backend/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── api/
│   │   │   ├── router.py
│   │   │   └── routes/
│   │   │       ├── analytics.py
│   │   │       ├── asset_classes.py
│   │   │       ├── cost_adjustments.py
│   │   │       ├── health.py
│   │   │       ├── holdings.py
│   │   │       ├── market_data.py
│   │   │       ├── rebalance.py
│   │   │       ├── settings.py
│   │   │       └── snapshots.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── decimal.py
│   │   │   ├── errors.py
│   │   │   └── secrets.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   ├── domain/
│   │   │   ├── analytics.py
│   │   │   ├── cost_basis.py
│   │   │   └── rebalance.py
│   │   ├── providers/
│   │   │   ├── alpha_vantage.py
│   │   │   ├── akshare.py
│   │   │   ├── base.py
│   │   │   ├── tushare.py
│   │   │   └── yahoo.py
│   │   ├── schemas/
│   │   │   ├── analytics.py
│   │   │   ├── asset_class.py
│   │   │   ├── common.py
│   │   │   ├── cost_adjustment.py
│   │   │   ├── holding.py
│   │   │   ├── market_data.py
│   │   │   ├── rebalance.py
│   │   │   ├── settings.py
│   │   │   └── snapshot.py
│   │   ├── services/
│   │   │   ├── analytics.py
│   │   │   ├── asset_classes.py
│   │   │   ├── baseline.py
│   │   │   ├── cost_adjustments.py
│   │   │   ├── holdings.py
│   │   │   ├── market_data.py
│   │   │   ├── rebalancing.py
│   │   │   ├── settings.py
│   │   │   └── snapshots.py
│   │   ├── main.py
│   │   └── worker.py
│   └── tests/
│       ├── conftest.py
│       ├── integration/
│       └── unit/
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── package-lock.json
│   ├── playwright.config.ts
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── public/fonts/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── types.ts
│   │   ├── app/
│   │   │   ├── App.tsx
│   │   │   ├── providers.tsx
│   │   │   └── router.tsx
│   │   ├── components/
│   │   │   ├── AppShell/
│   │   │   ├── CalibrationRail/
│   │   │   ├── DataStatus/
│   │   │   ├── FormField/
│   │   │   └── WorkDrawer/
│   │   ├── features/
│   │   │   ├── analytics/
│   │   │   ├── assetClasses/
│   │   │   ├── holdings/
│   │   │   ├── marketData/
│   │   │   ├── rebalance/
│   │   │   ├── settings/
│   │   │   └── snapshots/
│   │   ├── pages/
│   │   │   ├── AssetClassesPage.tsx
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── HoldingsPage.tsx
│   │   │   ├── MarketDataPage.tsx
│   │   │   ├── PnlPage.tsx
│   │   │   ├── RebalancePage.tsx
│   │   │   └── SnapshotsPage.tsx
│   │   ├── styles/
│   │   │   ├── global.css
│   │   │   └── tokens.css
│   │   └── main.tsx
│   ├── tests/
│   └── e2e/
└── docs/superpowers/
    ├── plans/
    └── specs/
```

## Phase 1: Foundation

### Task 1: Repository and Docker skeleton

**Files:**
- Create: `.env.example`
- Create: `Makefile`
- Create: `compose.yaml`
- Create: `backend/Dockerfile`
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/app/api/router.py`
- Create: `backend/app/api/routes/health.py`
- Create: `backend/tests/unit/test_health.py`
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `frontend/package.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Modify: `.gitignore`

- [ ] **Step 1: Add the failing API health test**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}
```

- [ ] **Step 2: Run the health test and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_health.py -v`

Expected: FAIL because `app.main` and the health route do not exist.

- [ ] **Step 3: Create the minimal FastAPI application**

```python
# backend/app/api/routes/health.py
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}
```

```python
# backend/app/api/router.py
from fastapi import APIRouter

from app.api.routes.health import router as health_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
```

```python
# backend/app/main.py
from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(title="Portfolio Rebalancer", version="1.0.0")
app.include_router(api_router)
```

- [ ] **Step 4: Add container and local commands**

`compose.yaml` must define `frontend`, `api`, `worker`, and `db`; bind only `127.0.0.1:8080:80`; keep API and PostgreSQL unexposed; use named volumes `postgres_data` and `secret_data`. `Makefile` must provide `up`, `down`, `logs`, `test-backend`, and `test-frontend` targets.

Run: `docker compose config`

Expected: exit code 0 and four services in the rendered configuration.

- [ ] **Step 5: Run the API test and container smoke test**

Run: `cd backend && uv run pytest tests/unit/test_health.py -v`

Expected: PASS.

Run: `docker compose up -d db api frontend && curl -fsS http://localhost:8080/api/health`

Expected: `{"status":"ok","service":"api"}`.

- [ ] **Step 6: Commit the skeleton**

```bash
git add .env.example .gitignore Makefile compose.yaml backend frontend
git commit -m "chore: scaffold portfolio application"
```

### Task 2: Configuration, async database session, and migrations

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/20260713_0001_initial_schema.py`
- Create: `backend/tests/integration/test_migrations.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Write the migration smoke test**

```python
from sqlalchemy import text


async def test_initial_migration_creates_core_tables(db_session) -> None:
    rows = await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    names = {row[0] for row in rows}

    assert {
        "asset_classes",
        "holdings",
        "holding_defaults",
        "market_data",
        "market_data_overrides",
        "cost_adjustments",
        "snapshots",
        "snapshot_items",
        "rebalance_plans",
        "settings",
        "encrypted_secrets",
    } <= names
```

- [ ] **Step 2: Run the migration test and verify failure**

Run: `docker compose run --rm api uv run pytest tests/integration/test_migrations.py -v`

Expected: FAIL because the migration and tables do not exist.

- [ ] **Step 3: Implement typed configuration and session factory**

```python
# backend/app/core/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio"
    timezone: str = "Asia/Shanghai"
    refresh_hour: int = 8
    refresh_minute: int = 0
    secret_key_path: str = "/run/portfolio-secrets/fernet.key"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# backend/app/db/session.py
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
```

- [ ] **Step 4: Define the initial schema and Alembic migration**

Use SQLAlchemy `Mapped` models with UUID primary keys, `DateTime(timezone=True)`, and `Numeric(28, 12)` for quantity, prices, rates, amounts, and weights. Add unique constraints for active asset-class names, symbol/account pairs, market-data source keys, and one daily snapshot per local date.

Add an integer `version` column to `holdings`, defaulting to 1 and incremented by every cost or direct holding update. `backend/tests/conftest.py` must provide isolated async `db_session` and `api_client` fixtures against the Compose PostgreSQL test database, rolling back or truncating business tables between tests.

The API container command must run `uv run alembic upgrade head` before starting Uvicorn. The worker waits for the API health check so only one service performs migrations.

Run: `docker compose run --rm api uv run alembic upgrade head`

Expected: migration completes without warnings.

- [ ] **Step 5: Run integration tests**

Run: `docker compose run --rm api uv run pytest tests/integration/test_migrations.py -v`

Expected: PASS and all required table names are present.

- [ ] **Step 6: Commit database foundation**

```bash
git add backend/app/core backend/app/db backend/alembic.ini backend/alembic backend/tests/conftest.py backend/tests/integration backend/pyproject.toml backend/uv.lock
git commit -m "feat: add database schema and migrations"
```

### Task 3: Default strategy seed and decimal API contract

**Files:**
- Create: `backend/app/core/decimal.py`
- Create: `backend/app/schemas/common.py`
- Create: `backend/app/services/asset_classes.py`
- Create: `backend/tests/unit/test_decimal_serialization.py`
- Create: `backend/tests/integration/test_default_strategy.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write decimal serialization and seed tests**

```python
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import DecimalString


class Payload(BaseModel):
    value: DecimalString


def test_decimal_is_serialized_as_string() -> None:
    payload = Payload(value=Decimal("7.075000"))
    assert payload.model_dump(mode="json") == {"value": "7.075000"}
```

```python
from app.services.asset_classes import list_asset_classes, seed_default_strategy


async def test_default_strategy_is_seeded_once(db_session) -> None:
    await seed_default_strategy(db_session)
    await seed_default_strategy(db_session)
    items = await list_asset_classes(db_session)

    assert [(item.name, format(item.target_weight, "f")) for item in items] == [
        ("红利低波", "0.20000000"),
        ("红利质量", "0.20000000"),
        ("标普 500", "0.30000000"),
        ("纳斯达克 100", "0.20000000"),
        ("黄金", "0.10000000"),
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker compose run --rm api uv run pytest tests/unit/test_decimal_serialization.py tests/integration/test_default_strategy.py -v`

Expected: FAIL because the decimal alias and seed service are absent.

- [ ] **Step 3: Implement the decimal type**

```python
# backend/app/core/decimal.py
from decimal import Decimal

CNY_CENT = Decimal("0.01")
DB_QUANTUM = Decimal("0.000000000001")


def quantize_cny(value: Decimal) -> Decimal:
    return value.quantize(CNY_CENT)
```

```python
# backend/app/schemas/common.py
from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

DecimalString = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]
```

- [ ] **Step 4: Implement idempotent default seeding**

`seed_default_strategy(session)` must insert the five confirmed asset classes only when no rows exist, preserve the confirmed order, and commit in one transaction. It must also seed default settings: tolerance `0.02`, minimum trade CNY `500`, allow sell `true`, allow FX `true`, and refresh time `08:00`. Call it from the API startup lifespan after migrations have run.

- [ ] **Step 5: Run tests**

Run: `docker compose run --rm api uv run pytest tests/unit/test_decimal_serialization.py tests/integration/test_default_strategy.py -v`

Expected: PASS; invoking the seed twice still returns five rows.

- [ ] **Step 6: Commit default strategy support**

```bash
git add backend/app/core/decimal.py backend/app/schemas backend/app/services/asset_classes.py backend/app/main.py backend/tests
git commit -m "feat: seed default allocation strategy"
```

## Phase 2: Manual Core

### Task 4: Pure portfolio analytics domain

**Files:**
- Create: `backend/app/domain/analytics.py`
- Create: `backend/app/schemas/analytics.py`
- Create: `backend/tests/unit/test_analytics.py`
- Create: `backend/tests/unit/test_analytics_properties.py`

- [ ] **Step 1: Write exact formula tests**

```python
from decimal import Decimal

from app.domain.analytics import PositionInput, analyze_position


def test_usd_position_decomposes_pnl_exactly() -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal("150"),
            cost_price=Decimal("106.666666666667"),
            current_price=Decimal("120"),
            cost_fx=Decimal("7.075"),
            current_fx=Decimal("7.20"),
            baseline_fx=Decimal("7.00"),
        )
    )

    assert result.cost_cny == Decimal("113200.000000000354")
    assert result.market_value_cny == Decimal("129600.00")
    assert result.fx_neutral_value_cny == Decimal("126000.00")
    assert result.price_effect + result.fx_effect == result.unrealized_pnl
```

- [ ] **Step 2: Write the property test**

```python
from decimal import Decimal

from hypothesis import given, strategies as st

from app.domain.analytics import PositionInput, analyze_position


positive = st.decimals(min_value="0.0001", max_value="100000", places=4)


@given(positive, positive, positive, positive, positive, positive)
def test_pnl_decomposition_identity(qty, cost, current, cost_fx, current_fx, baseline_fx) -> None:
    result = analyze_position(
        PositionInput(
            quantity=Decimal(qty),
            cost_price=Decimal(cost),
            current_price=Decimal(current),
            cost_fx=Decimal(cost_fx),
            current_fx=Decimal(current_fx),
            baseline_fx=Decimal(baseline_fx),
        )
    )
    assert result.price_effect + result.fx_effect == result.unrealized_pnl
```

- [ ] **Step 3: Run analytics tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_analytics.py tests/unit/test_analytics_properties.py -v`

Expected: FAIL because `PositionInput` and `analyze_position` do not exist.

- [ ] **Step 4: Implement immutable analytics values**

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionInput:
    quantity: Decimal
    cost_price: Decimal
    current_price: Decimal
    cost_fx: Decimal
    current_fx: Decimal
    baseline_fx: Decimal


@dataclass(frozen=True)
class PositionAnalysis:
    cost_cny: Decimal
    market_value_cny: Decimal
    fx_neutral_value_cny: Decimal
    unrealized_pnl: Decimal
    unrealized_return: Decimal
    price_effect: Decimal
    fx_effect: Decimal


def analyze_position(value: PositionInput) -> PositionAnalysis:
    cost_cny = value.quantity * value.cost_price * value.cost_fx
    market_value_cny = value.quantity * value.current_price * value.current_fx
    neutral_value = value.quantity * value.current_price * value.baseline_fx
    price_effect = value.quantity * value.current_price * value.cost_fx - cost_cny
    fx_effect = market_value_cny - value.quantity * value.current_price * value.cost_fx
    pnl = market_value_cny - cost_cny
    return PositionAnalysis(
        cost_cny=cost_cny,
        market_value_cny=market_value_cny,
        fx_neutral_value_cny=neutral_value,
        unrealized_pnl=pnl,
        unrealized_return=pnl / cost_cny if cost_cny else Decimal("0"),
        price_effect=price_effect,
        fx_effect=fx_effect,
    )
```

- [ ] **Step 5: Run unit and property tests**

Run: `cd backend && uv run pytest tests/unit/test_analytics.py tests/unit/test_analytics_properties.py -v`

Expected: PASS.

- [ ] **Step 6: Commit analytics domain**

```bash
git add backend/app/domain/analytics.py backend/app/schemas/analytics.py backend/tests/unit/test_analytics.py backend/tests/unit/test_analytics_properties.py
git commit -m "feat: add portfolio analytics formulas"
```

### Task 5: Asset-class and holding CRUD API

**Files:**
- Create: `backend/app/schemas/asset_class.py`
- Create: `backend/app/schemas/holding.py`
- Create: `backend/app/services/holdings.py`
- Create: `backend/app/api/routes/asset_classes.py`
- Create: `backend/app/api/routes/holdings.py`
- Create: `backend/tests/integration/test_asset_classes_api.py`
- Create: `backend/tests/integration/test_holdings_api.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: Write target-weight validation tests**

```python
async def test_asset_class_update_rejects_total_other_than_one(api_client) -> None:
    classes = (await api_client.get("/api/asset-classes")).json()
    payload = [
        {**item, "target_weight": "0.10000000"}
        for item in classes
    ]

    response = await api_client.put("/api/asset-classes", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TARGET_WEIGHT_TOTAL_INVALID"
    assert response.json()["detail"]["actual_total"] == "0.50000000"
```

- [ ] **Step 2: Write holding validation tests**

```python
async def test_create_usd_holding_requires_positive_fx_values(api_client, asset_class_id) -> None:
    response = await api_client.post(
        "/api/holdings",
        json={
            "asset_class_id": asset_class_id,
            "symbol": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "market": "US",
            "account_name": "港资券商",
            "trade_currency": "USD",
            "quantity": "10",
            "average_cost_price": "500",
            "cost_fx_to_cny": "0",
            "baseline_fx_to_cny": "7.20",
            "lot_size": "1",
            "quantity_precision": 0,
            "is_rebalance_preferred": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "FX_MUST_BE_POSITIVE"
```

- [ ] **Step 3: Run API tests and verify failure**

Run: `docker compose run --rm api uv run pytest tests/integration/test_asset_classes_api.py tests/integration/test_holdings_api.py -v`

Expected: FAIL because the routes and services do not exist.

- [ ] **Step 4: Implement explicit schemas and services**

Use `AssetClassUpdate`, `HoldingCreate`, `HoldingUpdate`, and response schemas with `DecimalString` fields. `replace_asset_classes()` must lock active rows, validate the total equals `Decimal("1")`, and update all rows in one transaction. `create_holding()` must set CNY FX fields to `1`, reject negative values, and enforce one preferred holding per asset class.

- [ ] **Step 5: Add CRUD routes and error contract**

Expose:

```text
GET    /api/asset-classes
PUT    /api/asset-classes
GET    /api/holdings
POST   /api/holdings
PATCH  /api/holdings/{holding_id}
POST   /api/holdings/{holding_id}/archive
```

All domain validation errors must return `{ "detail": { "code": str, "message": str, ... } }`. Archiving a holding with non-zero quantity returns `409 HOLDING_NOT_EMPTY`.

- [ ] **Step 6: Run integration tests**

Run: `docker compose run --rm api uv run pytest tests/integration/test_asset_classes_api.py tests/integration/test_holdings_api.py -v`

Expected: PASS.

- [ ] **Step 7: Commit CRUD APIs**

```bash
git add backend/app/api backend/app/schemas backend/app/services backend/tests/integration
git commit -m "feat: add asset class and holding APIs"
```

### Task 6: Cost-basis engine and adjustment audit trail

**Files:**
- Create: `backend/app/domain/cost_basis.py`
- Create: `backend/app/schemas/cost_adjustment.py`
- Create: `backend/app/services/cost_adjustments.py`
- Create: `backend/app/api/routes/cost_adjustments.py`
- Create: `backend/tests/unit/test_cost_basis.py`
- Create: `backend/tests/unit/test_cost_basis_properties.py`
- Create: `backend/tests/integration/test_cost_adjustments_api.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: Write purchase and fee tests**

```python
from decimal import Decimal

from app.domain.cost_basis import CostBasis, Purchase, add_purchase


def test_add_purchase_with_trade_currency_fee() -> None:
    result = add_purchase(
        CostBasis(quantity=Decimal("100"), average_price=Decimal("100"), cost_fx=Decimal("7.00")),
        Purchase(
            quantity=Decimal("50"),
            price=Decimal("120"),
            fx=Decimal("7.20"),
            fee_trade_currency=Decimal("2"),
            fee_cny=Decimal("0"),
        ),
    )

    assert result.quantity == Decimal("150")
    assert result.average_price == Decimal("106.68")
    assert result.total_cost_cny == Decimal("113214.40")
    assert (result.quantity * result.average_price * result.cost_fx).quantize(Decimal("0.01")) == result.total_cost_cny.quantize(Decimal("0.01"))


def test_actual_fee_overrides_estimated_fee() -> None:
    from app.domain.cost_basis import FeeRule, resolve_fee

    fee = resolve_fee(
        trade_value=Decimal("3251"),
        quantity=Decimal("5"),
        rule=FeeRule(
            commission_rate=Decimal("0"),
            minimum_commission=Decimal("0"),
            per_share_fee=Decimal("0.01"),
            fixed_fee=Decimal("2"),
        ),
        actual_fee=Decimal("2.30"),
    )

    assert fee == Decimal("2.30")
```

- [ ] **Step 2: Write partial-sale and identity property tests**

```python
def test_partial_sale_preserves_average_cost() -> None:
    from app.domain.cost_basis import CostBasis, sell_quantity

    result = sell_quantity(
        CostBasis(quantity=Decimal("100"), average_price=Decimal("50"), cost_fx=Decimal("7.10")),
        Decimal("25"),
    )

    assert result == CostBasis(
        quantity=Decimal("75"),
        average_price=Decimal("50"),
        cost_fx=Decimal("7.10"),
    )
```

The Hypothesis test must generate positive current bases, purchases, FX values, and either fee currency, then assert both sides of `new.quantity × new.average_price × new.cost_fx = new.total_cost_cny` are equal after CNY-cent quantization.

- [ ] **Step 3: Run unit tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_cost_basis.py tests/unit/test_cost_basis_properties.py -v`

Expected: FAIL because cost-basis functions are absent.

- [ ] **Step 4: Implement the pure cost-basis API**

```python
@dataclass(frozen=True)
class CostBasis:
    quantity: Decimal
    average_price: Decimal
    cost_fx: Decimal

    @property
    def total_cost_cny(self) -> Decimal:
        return self.quantity * self.average_price * self.cost_fx


@dataclass(frozen=True)
class Purchase:
    quantity: Decimal
    price: Decimal
    fx: Decimal
    fee_trade_currency: Decimal
    fee_cny: Decimal
```

`add_purchase()` must use the exact V1.1 formulas. `sell_quantity()` must reject values above current quantity and return zero cost fields only when the resulting quantity is zero. `resolve_fee()` must calculate `max(value × rate, minimum) + quantity × per_share + fixed` unless an actual fee is supplied.

- [ ] **Step 5: Write preview and confirmation API tests**

```python
async def test_stale_cost_preview_is_rejected(api_client, spy_holding) -> None:
    preview = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/preview-purchase",
        json={
            "quantity": "5",
            "price": "650.20",
            "fx": "7.1850",
            "actual_fee": "2.30",
            "fee_currency": "USD",
            "save_fee_defaults": True,
        },
    )
    await api_client.patch(f"/api/holdings/{spy_holding['id']}", json={"quantity": "87"})
    response = await api_client.post(
        f"/api/cost-adjustments/{spy_holding['id']}/confirm",
        json={
            "expected_version": preview.json()["holding_version"],
            "operation": "purchase",
            "payload": {
                "quantity": "5",
                "price": "650.20",
                "fx": "7.1850",
                "actual_fee": "2.30",
                "fee_currency": "USD",
                "save_fee_defaults": True,
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_COST_PREVIEW"
```

- [ ] **Step 6: Implement preview, confirm, sell, correction, and restore services**

Confirmation must lock the holding row, compare `expected_version`, recompute from the submitted operation payload, increment the holding version, update the holding, optionally persist fee defaults, and insert one `cost_adjustments` record in the same transaction. The backend never accepts derived totals from the client. Restore must create a new `MANUAL_CORRECTION` record; it must never delete prior audit rows.

- [ ] **Step 7: Run cost tests**

Run: `docker compose run --rm api uv run pytest tests/unit/test_cost_basis.py tests/unit/test_cost_basis_properties.py tests/integration/test_cost_adjustments_api.py -v`

Expected: PASS.

- [ ] **Step 8: Commit cost maintenance**

```bash
git add backend/app/domain/cost_basis.py backend/app/schemas/cost_adjustment.py backend/app/services/cost_adjustments.py backend/app/api/routes/cost_adjustments.py backend/tests
git commit -m "feat: add cost basis adjustment workflow"
```

### Task 7: Front-end toolchain and confirmed design system

**Files:**
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`
- Create: `frontend/src/app/providers.tsx`
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/components/AppShell/AppShell.tsx`
- Create: `frontend/src/components/AppShell/AppShell.module.css`
- Create: `frontend/src/components/FormField/FormField.tsx`
- Create: `frontend/src/components/WorkDrawer/WorkDrawer.tsx`
- Create: `frontend/src/components/CalibrationRail/CalibrationRail.tsx`
- Create: `frontend/src/components/CalibrationRail/CalibrationRail.module.css`
- Create: `frontend/tests/CalibrationRail.test.tsx`
- Create: `frontend/tests/AppShell.test.tsx`
- Create: `frontend/tests/testProviders.tsx`
- Create: `frontend/tests/fixtures.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Install the locked front-end dependencies**

Run:

```bash
cd frontend
npm install react@^19 react-dom@^19 react-router-dom@^7 @tanstack/react-query@^5 react-hook-form@^7 zod@^4 @hookform/resolvers@^5 recharts@^3 lucide-react@^0.5
npm install -D typescript@^5 vite@^7 @vitejs/plugin-react@^4 vitest@^3 jsdom@^26 @testing-library/react@^16 @testing-library/jest-dom@^6 @testing-library/user-event@^14 axe-core@^4 msw@^2
```

Expected: `package-lock.json` is created and `npm audit` reports no high or critical vulnerabilities.

- [ ] **Step 2: Write calibration-rail tests**

```tsx
import { render, screen } from "@testing-library/react";

import { CalibrationRail } from "../src/components/CalibrationRail/CalibrationRail";

it("renders textual values for every marker", () => {
  render(
    <CalibrationRail
      assetName="标普 500"
      target={30}
      actual={31.8}
      fxNeutral={30.7}
      tolerance={2}
    />,
  );

  expect(screen.getByText("目标 30.0%")).toBeInTheDocument();
  expect(screen.getByText("实际 31.8%")).toBeInTheDocument();
  expect(screen.getByText("剔汇率 30.7%")).toBeInTheDocument();
  expect(screen.getByText("+1.8pp")).toBeInTheDocument();
});

it("shows an overflow indicator without compressing the scale", () => {
  render(
    <CalibrationRail assetName="标普 500" target={30} actual={36} tolerance={2} />,
  );
  expect(screen.getByLabelText("实际占比超出右侧刻度，真实值 36.0%")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run component tests and verify failure**

Run: `cd frontend && npm test -- CalibrationRail.test.tsx AppShell.test.tsx`

Expected: FAIL because the design-system components do not exist.

- [ ] **Step 4: Implement design tokens**

```css
/* frontend/src/styles/tokens.css */
:root {
  --color-ground: #eef2ee;
  --color-surface: #fbfcfa;
  --color-ink: #18221d;
  --color-actual: #2f5da8;
  --color-fx: #c94a3a;
  --color-target: #b58b2a;
  --color-planned: #2e7458;
  --color-rule: #cbd4ce;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --sidebar-width: 188px;
  --topbar-height: 66px;
  --focus-ring: 0 0 0 3px rgb(47 93 168 / 24%);
}
```

- [ ] **Step 5: Implement the shell and calibration rail**

`AppShell` must render the seven confirmed routes with Lucide icons and text labels. `CalibrationRail` must use a target-centered ±4pp scale, clamp marker positions at the edges, render overflow arrows, expose all values as text, and accept optional `planned` and `fxNeutral` markers.

`testProviders.tsx` must wrap tests with `QueryClientProvider` and `MemoryRouter`, create a fresh retry-disabled query client for every render, and allow fixtures to be injected through Mock Service Worker handlers. `fixtures.ts` owns the shared portfolio, holding, market-data, snapshot, and rebalance response objects referenced by later component tests.

- [ ] **Step 6: Run tests and production build**

Run: `cd frontend && npm test && npm run build`

Expected: all tests PASS and Vite creates `dist/` without TypeScript errors.

- [ ] **Step 7: Commit the front-end foundation**

```bash
git add frontend
git commit -m "feat: add calibration desk design system"
```

### Task 8: Asset configuration, holdings table, and cost drawer UI

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/features/assetClasses/api.ts`
- Create: `frontend/src/features/assetClasses/AssetClassEditor.tsx`
- Create: `frontend/src/features/holdings/api.ts`
- Create: `frontend/src/features/holdings/HoldingsTable.tsx`
- Create: `frontend/src/features/holdings/PurchaseDrawer.tsx`
- Create: `frontend/src/features/holdings/SaleDrawer.tsx`
- Create: `frontend/src/features/holdings/CorrectionDrawer.tsx`
- Create: `frontend/src/features/holdings/AdjustmentHistoryDrawer.tsx`
- Create: `frontend/src/pages/AssetClassesPage.tsx`
- Create: `frontend/src/pages/HoldingsPage.tsx`
- Create: `frontend/tests/AssetClassEditor.test.tsx`
- Create: `frontend/tests/PurchaseDrawer.test.tsx`
- Modify: `frontend/src/app/router.tsx`

- [ ] **Step 1: Define API types using decimal strings**

```ts
export type DecimalString = string;

export interface Holding {
  id: string;
  asset_class_id: string;
  symbol: string;
  name: string;
  market: string;
  account_name: string;
  trade_currency: "CNY" | "USD";
  quantity: DecimalString;
  average_cost_price: DecimalString;
  cost_fx_to_cny: DecimalString;
  baseline_fx_to_cny: DecimalString;
  lot_size: DecimalString;
  quantity_precision: number;
  is_rebalance_preferred: boolean;
}
```

- [ ] **Step 2: Write the asset-total and purchase-preview tests**

```tsx
it("blocks saving when enabled target weights do not total 100%", async () => {
  const user = userEvent.setup();
  render(<AssetClassEditor initialItems={defaultAssetClasses} onSave={vi.fn()} />);
  await user.clear(screen.getByLabelText("红利低波目标比例"));
  await user.type(screen.getByLabelText("红利低波目标比例"), "10");
  expect(screen.getByText("还差 10.0% 才达到 100%"));
  expect(screen.getByRole("button", { name: "保存资产配置" })).toBeDisabled();
});

it("uses actual fee and shows the confirmed cost preview", async () => {
  render(<PurchaseDrawer holding={spyHolding} open onClose={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("新增份额"), "5");
  await userEvent.type(screen.getByLabelText("成交价"), "650.20");
  await userEvent.type(screen.getByLabelText("本次汇率"), "7.1850");
  await userEvent.click(screen.getByRole("tab", { name: "录入实际费用" }));
  await userEvent.type(screen.getByLabelText("实际费用"), "2.30");
  expect(await screen.findByText("成本预览")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "更新 SPY 持仓" })).toBeEnabled();
});
```

- [ ] **Step 3: Run UI tests and verify failure**

Run: `cd frontend && npm test -- AssetClassEditor.test.tsx PurchaseDrawer.test.tsx`

Expected: FAIL because the feature components do not exist.

- [ ] **Step 4: Implement query and mutation hooks**

Use TanStack Query keys `['asset-classes']`, `['holdings']`, and `['cost-adjustments', holdingId]`. The API client must parse the server error contract and preserve decimal strings; it must not coerce financial values through JavaScript `number` before submission.

- [ ] **Step 5: Implement the confirmed page layouts**

The holdings page must use a single table, icon actions, archived-holding filter, and a right-side `WorkDrawer`. The purchase drawer must preserve this order: transaction inputs, fee mode, per-holding defaults, before/after preview, identity check, confirm button. Sale and correction drawers must use distinct command text and never display realized P&L. `AdjustmentHistoryDrawer` must show before/after values, time, operation, note, and a “恢复到此状态” action that creates a new correction preview rather than deleting history.

- [ ] **Step 6: Run component tests and build**

Run: `cd frontend && npm test && npm run build`

Expected: PASS and no TypeScript errors.

- [ ] **Step 7: Run manual-core integration tests**

Run: `docker compose up -d db api frontend && docker compose run --rm api uv run pytest tests/integration/test_asset_classes_api.py tests/integration/test_holdings_api.py tests/integration/test_cost_adjustments_api.py -v`

Expected: PASS; asset and cost APIs work through the container network.

- [ ] **Step 8: Commit the manual core UI**

```bash
git add frontend/src frontend/tests
git commit -m "feat: add holdings and cost maintenance UI"
```

## Phase 3: Market Data, Analytics, and History

### Task 9: Market-data providers, effective values, overrides, and worker

**Files:**
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/yahoo.py`
- Create: `backend/app/providers/akshare.py`
- Create: `backend/app/providers/tushare.py`
- Create: `backend/app/providers/alpha_vantage.py`
- Create: `backend/app/schemas/market_data.py`
- Create: `backend/app/services/market_data.py`
- Create: `backend/app/api/routes/market_data.py`
- Create: `backend/app/worker.py`
- Create: `backend/tests/unit/test_market_data_resolution.py`
- Create: `backend/tests/unit/test_provider_normalization.py`
- Create: `backend/tests/integration/test_market_data_api.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/pyproject.toml`
- Modify: `compose.yaml`

- [ ] **Step 1: Write effective-value precedence tests**

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.market_data import AutomatedValue, ManualOverride, resolve_effective_value


def test_active_manual_override_wins_over_newer_automated_value() -> None:
    now = datetime(2026, 7, 13, 1, 0, tzinfo=UTC)
    result = resolve_effective_value(
        automated=AutomatedValue(
            value=Decimal("7.20"), source="yahoo", as_of=now, fetched_at=now
        ),
        override=ManualOverride(
            value=Decimal("7.18"), note="券商结算参考", starts_at=now - timedelta(hours=1), expires_at=None
        ),
        now=now,
    )

    assert result.value == Decimal("7.18")
    assert result.status == "manual"
    assert result.source == "manual"
```

- [ ] **Step 2: Write provider normalization tests**

```python
def test_yahoo_normalizes_spy_close(yahoo_payload) -> None:
    quote = YahooProvider().normalize_price("SPY", yahoo_payload)

    assert quote.symbol == "SPY"
    assert quote.value == Decimal("651.28")
    assert quote.currency == "USD"
    assert quote.source == "yahoo"


def test_akshare_normalizes_cn_etf_code(akshare_frame) -> None:
    quote = AkshareProvider().normalize_price("510880", akshare_frame)

    assert quote.symbol == "510880"
    assert quote.value == Decimal("3.025")
    assert quote.currency == "CNY"
```

- [ ] **Step 3: Run provider tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_market_data_resolution.py tests/unit/test_provider_normalization.py -v`

Expected: FAIL because providers and effective-value resolution do not exist.

- [ ] **Step 4: Implement the provider contract**

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class MarketQuote:
    key: str
    value: Decimal
    currency: str
    source: str
    as_of: datetime
    fetched_at: datetime


class MarketDataProvider(Protocol):
    async def fetch_price(self, symbol: str) -> MarketQuote: ...
    async def fetch_fx(self, base: str, quote: str) -> MarketQuote: ...


class ProviderCredentialReader(Protocol):
    def get_api_key(self, provider: str) -> str | None: ...
```

Yahoo and AKShare must work without API keys. Tushare and Alpha Vantage adapters receive a `ProviderCredentialReader` and must raise `ProviderNotConfigured` when it returns no key. Task 9 uses a reader that returns `None`; Task 15 connects the encrypted secret store without changing provider interfaces. Blocking library calls must run through `asyncio.to_thread`.

- [ ] **Step 5: Implement refresh, stale preservation, and manual overrides**

`refresh_market_data()` must write a new valid record only after parsing and validation succeeds. A provider failure writes an error summary but never overwrites the last valid value. `resolve_effective_value()` must implement manual override, newest automated value, then stale fallback order.

Expose:

```text
GET    /api/market-data
POST   /api/market-data/refresh
POST   /api/market-data/{key}/override
DELETE /api/market-data/{key}/override
```

- [ ] **Step 6: Implement the scheduled worker**

```python
async def scheduled_refresh() -> None:
    async with SessionFactory() as session:
        await refresh_all_required_data(session)


def main() -> None:
    scheduler = AsyncIOScheduler(timezone=get_settings().timezone)
    scheduler.add_job(
        scheduled_refresh,
        trigger="cron",
        hour=get_settings().refresh_hour,
        minute=get_settings().refresh_minute,
        id="daily-market-refresh",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    asyncio.get_event_loop().run_forever()
```

The worker service in `compose.yaml` must use the backend image and command `uv run python -m app.worker`.

Task 11 adds daily snapshot creation to `scheduled_refresh()` after the snapshot service exists. Until then, the worker performs refresh only.

- [ ] **Step 7: Run market-data tests**

Run: `docker compose run --rm api uv run pytest tests/unit/test_market_data_resolution.py tests/unit/test_provider_normalization.py tests/integration/test_market_data_api.py -v`

Expected: PASS, including provider failure and stale fallback cases.

- [ ] **Step 8: Commit market data support**

```bash
git add backend/app/providers backend/app/services/market_data.py backend/app/schemas/market_data.py backend/app/api/routes/market_data.py backend/app/worker.py backend/tests compose.yaml backend/pyproject.toml backend/uv.lock
git commit -m "feat: add automated market data refresh"
```

### Task 10: Portfolio analytics API, dashboard, and P&L page

**Files:**
- Create: `backend/app/services/analytics.py`
- Create: `backend/app/api/routes/analytics.py`
- Create: `backend/tests/integration/test_analytics_api.py`
- Create: `frontend/src/features/analytics/api.ts`
- Create: `frontend/src/features/analytics/DecisionBanner.tsx`
- Create: `frontend/src/features/analytics/PortfolioMetrics.tsx`
- Create: `frontend/src/features/analytics/PnlBreakdown.tsx`
- Create: `frontend/src/pages/DashboardPage.tsx`
- Create: `frontend/src/pages/PnlPage.tsx`
- Create: `frontend/tests/DashboardPage.test.tsx`
- Create: `frontend/tests/PnlPage.test.tsx`
- Modify: `backend/app/api/router.py`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/pages/HoldingsPage.tsx`
- Modify: `frontend/src/features/holdings/HoldingsTable.tsx`

- [ ] **Step 1: Write portfolio aggregation tests**

```python
async def test_portfolio_response_contains_actual_and_fx_neutral_weights(api_client, seeded_portfolio) -> None:
    response = await api_client.get("/api/analytics/portfolio")
    payload = response.json()

    assert response.status_code == 200
    assert sum(Decimal(item["actual_weight"]) for item in payload["asset_classes"]) == Decimal("1")
    assert sum(Decimal(item["fx_neutral_weight"]) for item in payload["asset_classes"]) == Decimal("1")
    assert Decimal(payload["unrealized_pnl"]) == (
        Decimal(payload["price_effect"]) + Decimal(payload["fx_effect"])
    )
    assert payload["decision"]["status"] in {"hold", "contribute", "rebalance"}


async def test_empty_portfolio_returns_setup_state(api_client) -> None:
    response = await api_client.get("/api/analytics/portfolio")

    assert response.status_code == 200
    assert response.json()["decision"]["status"] == "setup"
    assert response.json()["market_value_cny"] == "0"
    assert response.json()["asset_classes"] == []
```

- [ ] **Step 2: Run analytics integration test and verify failure**

Run: `docker compose run --rm api uv run pytest tests/integration/test_analytics_api.py -v`

Expected: FAIL because the aggregation service and route do not exist.

- [ ] **Step 3: Implement the aggregation service**

Load active holdings with effective prices and FX values, call the pure analytics domain for each holding, aggregate by asset class, then compute actual and FX-neutral denominators independently. Return explicit data-status metadata for every required input. If any required value is missing, return `409 PORTFOLIO_DATA_INCOMPLETE`; stale values remain usable and set `has_stale_data=true`.

Serialize weights at 12 decimal places. Calculate the final active asset-class weight as `1 - sum(previous weights)` so each actual-weight set and FX-neutral-weight set sums exactly to `1.000000000000` in the API response.

- [ ] **Step 4: Implement the decision banner contract**

The backend must return:

```json
{
  "status": "hold",
  "title": "保持现状",
  "reason": "全部资产仍在 ±2.0 个百分点策略区间内。",
  "max_drift": "0.01800000",
  "fx_contribution": "0.01100000",
  "primary_action": "simulate_contribution"
}
```

The decision status uses the configured threshold and does not modify holdings.

- [ ] **Step 5: Write dashboard component tests**

```tsx
it("shows the action decision before portfolio metrics", async () => {
  render(<DashboardPage />, { wrapper: testProviders(portfolioFixture) });
  const decision = await screen.findByRole("heading", { name: "保持现状" });
  const value = screen.getByText("1,268,420");
  expect(decision.compareDocumentPosition(value) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("labels stale data without clearing values", async () => {
  render(<DashboardPage />, { wrapper: testProviders(stalePortfolioFixture) });
  expect(await screen.findByText("数据已过期")).toBeInTheDocument();
  expect(screen.getByText("1,268,420")).toBeInTheDocument();
});
```

- [ ] **Step 6: Implement dashboard and P&L pages**

Follow the confirmed order: decision banner, metrics strip, five calibration rails, P&L decomposition, data-status strip. The P&L page must state “当前持仓，不含已实现盈亏”, support CNY/trading-currency segmented views, and use Recharts only for time-series/decomposition visuals. Update the holdings table to join raw holding rows with the analytics response so current price, current FX, CNY market value, and unrealized P&L replace the manual-core placeholders.

- [ ] **Step 7: Run backend and frontend tests**

Run: `docker compose run --rm api uv run pytest tests/integration/test_analytics_api.py -v`

Run: `cd frontend && npm test -- DashboardPage.test.tsx PnlPage.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 8: Commit analytics experience**

```bash
git add backend/app/services/analytics.py backend/app/api/routes/analytics.py backend/tests/integration/test_analytics_api.py frontend/src/features/analytics frontend/src/features/holdings/HoldingsTable.tsx frontend/src/pages/DashboardPage.tsx frontend/src/pages/HoldingsPage.tsx frontend/src/pages/PnlPage.tsx frontend/tests
git commit -m "feat: add portfolio dashboard and pnl analysis"
```

### Task 11: Snapshots, daily idempotency, and history UI

**Files:**
- Create: `backend/app/schemas/snapshot.py`
- Create: `backend/app/services/snapshots.py`
- Create: `backend/app/api/routes/snapshots.py`
- Create: `backend/tests/integration/test_snapshots.py`
- Create: `frontend/src/features/snapshots/api.ts`
- Create: `frontend/src/features/snapshots/SnapshotChart.tsx`
- Create: `frontend/src/features/snapshots/SnapshotTable.tsx`
- Create: `frontend/src/pages/SnapshotsPage.tsx`
- Create: `frontend/tests/SnapshotsPage.test.tsx`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/worker.py`
- Modify: `frontend/src/app/router.tsx`

- [ ] **Step 1: Write daily-snapshot idempotency tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.snapshots import create_daily_snapshot_if_complete


async def test_daily_snapshot_is_upserted_for_same_local_date(db_session, complete_portfolio) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    first = await create_daily_snapshot_if_complete(
        db_session, now=datetime(2026, 7, 13, 8, 5, tzinfo=timezone)
    )
    first_id = first.id
    first_captured_at = first.captured_at
    second = await create_daily_snapshot_if_complete(
        db_session, now=datetime(2026, 7, 13, 9, 10, tzinfo=timezone)
    )

    assert first_id == second.id
    assert second.captured_at > first_captured_at


async def test_incomplete_market_data_skips_automatic_snapshot(db_session, portfolio_missing_fx) -> None:
    result = await create_daily_snapshot_if_complete(
        db_session,
        now=datetime(2026, 7, 13, 8, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert result is None
```

- [ ] **Step 2: Run snapshot tests and verify failure**

Run: `docker compose run --rm api uv run pytest tests/integration/test_snapshots.py -v`

Expected: FAIL because snapshot services do not exist.

- [ ] **Step 3: Implement immutable snapshot payloads**

Each snapshot item must copy holding identity, quantity, cost values, effective market values, current and baseline FX, asset-class target, both weights, P&L decomposition, and data status. Manual and rebalance snapshots are append-only. Daily snapshots use a unique `(type, local_date)` constraint and update the existing row in one transaction.

After this service exists, update `scheduled_refresh()` in `backend/app/worker.py` to call `create_daily_snapshot_if_complete(session)` immediately after a successful full refresh.

- [ ] **Step 4: Add snapshot routes**

Expose:

```text
GET  /api/snapshots
GET  /api/snapshots/{snapshot_id}
POST /api/snapshots/manual
```

Manual snapshot requests require a non-empty note only when stale or manually overridden values are present.

- [ ] **Step 5: Write history-page tests**

```tsx
it("does not label snapshot history as portfolio return", async () => {
  render(<SnapshotsPage />, { wrapper: testProviders(snapshotFixtures) });
  expect(await screen.findByText("核心池市值")).toBeInTheDocument();
  expect(screen.queryByText("组合收益率")).not.toBeInTheDocument();
});

it("pairs before and after rebalance events", async () => {
  render(<SnapshotsPage />, { wrapper: testProviders(rebalanceSnapshotFixtures) });
  expect(await screen.findByText("再平衡前")).toBeInTheDocument();
  expect(screen.getByText("再平衡后")).toBeInTheDocument();
});
```

- [ ] **Step 6: Implement the history page**

Provide time-range, snapshot-type, and asset-class filters. Render one selected metric at a time, place event markers on the chart, and show an event table with time, type, note, completeness, and detail action.

- [ ] **Step 7: Run snapshot and UI tests**

Run: `docker compose run --rm api uv run pytest tests/integration/test_snapshots.py -v`

Run: `cd frontend && npm test -- SnapshotsPage.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 8: Commit snapshot history**

```bash
git add backend/app/schemas/snapshot.py backend/app/services/snapshots.py backend/app/api/routes/snapshots.py backend/app/worker.py backend/tests/integration/test_snapshots.py frontend/src/features/snapshots frontend/src/pages/SnapshotsPage.tsx frontend/tests/SnapshotsPage.test.tsx
git commit -m "feat: add portfolio snapshot history"
```

## Phase 4: Rebalancing

### Task 12: Pure deterministic rebalancing engine

**Files:**
- Create: `backend/app/domain/rebalance.py`
- Create: `backend/app/schemas/rebalance.py`
- Create: `backend/tests/unit/test_rebalance.py`
- Create: `backend/tests/unit/test_rebalance_properties.py`

- [ ] **Step 1: Write cash-first behavior tests**

```python
from decimal import Decimal

from app.domain.rebalance import AssetInput, CashInput, RebalanceOptions, rebalance


def test_cash_is_used_before_any_sell() -> None:
    assets = [
        AssetInput("low-vol", "510880", "CNY", Decimal("180000"), Decimal("0.20"), Decimal("3"), Decimal("100")),
        AssetInput("quality", "159758", "CNY", Decimal("210000"), Decimal("0.20"), Decimal("1.2"), Decimal("100")),
        AssetInput("sp500", "SPY", "USD", Decimal("310000"), Decimal("0.30"), Decimal("4687.20"), Decimal("1")),
        AssetInput("nasdaq", "QQQ", "USD", Decimal("200000"), Decimal("0.20"), Decimal("3950.64"), Decimal("1")),
        AssetInput("gold", "518880", "CNY", Decimal("100000"), Decimal("0.10"), Decimal("5.8"), Decimal("100")),
    ]
    result = rebalance(
        assets,
        CashInput(cny=Decimal("20000"), usd=Decimal("0"), usd_cny=Decimal("7.20")),
        RebalanceOptions(
            tolerance=Decimal("0.02"),
            minimum_trade_cny=Decimal("500"),
            allow_sell=True,
            allow_fx=True,
        ),
    )

    assert all(item.action == "buy" for item in result.trades)
    assert sum(item.amount_cny for item in result.trades) <= Decimal("20000")
```

- [ ] **Step 2: Write sell, FX, lot, and determinism tests**

```python
def test_sell_is_suggested_only_when_cash_cannot_restore_tolerance(overweight_assets) -> None:
    result = rebalance(
        overweight_assets,
        CashInput(cny=Decimal("20000"), usd=Decimal("0"), usd_cny=Decimal("7.20")),
        RebalanceOptions(Decimal("0.02"), Decimal("500"), True, True),
    )
    spy_sell = next(item for item in result.trades if item.symbol == "SPY" and item.action == "sell")
    assert spy_sell.reason_code == "OVERWEIGHT_AFTER_CASH"


def test_same_input_produces_same_ordered_plan(overweight_assets) -> None:
    options = RebalanceOptions(Decimal("0.02"), Decimal("500"), True, True)
    cash = CashInput(Decimal("20000"), Decimal("0"), Decimal("7.20"))
    assert rebalance(overweight_assets, cash, options) == rebalance(overweight_assets, cash, options)
```

The property suite must assert no sell trades when `allow_sell=False`, no FX conversion when `allow_fx=False`, buy spending does not exceed available cash plus sale proceeds, quantities are multiples of lot size, and all returned amounts are non-negative.

- [ ] **Step 3: Run rebalancing tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_rebalance.py tests/unit/test_rebalance_properties.py -v`

Expected: FAIL because the rebalancing domain does not exist.

- [ ] **Step 4: Implement immutable input and result types**

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class AssetInput:
    asset_class_id: str
    symbol: str
    currency: str
    current_value_cny: Decimal
    target_weight: Decimal
    unit_price_cny: Decimal
    lot_size: Decimal


@dataclass(frozen=True)
class CashInput:
    cny: Decimal
    usd: Decimal
    usd_cny: Decimal


@dataclass(frozen=True)
class RebalanceOptions:
    tolerance: Decimal
    minimum_trade_cny: Decimal
    allow_sell: bool
    allow_fx: bool


@dataclass(frozen=True)
class TradeSuggestion:
    symbol: str
    action: Literal["buy", "sell"]
    quantity: Decimal
    amount_cny: Decimal
    amount_trade_currency: Decimal
    reason_code: str


@dataclass(frozen=True)
class ProjectedWeight:
    asset_class_id: str
    before: Decimal
    after: Decimal
    target: Decimal


@dataclass(frozen=True)
class RebalanceResult:
    feasible: bool
    max_drift_before: Decimal
    max_drift_after: Decimal
    fx_required_cny: Decimal
    remaining_cny: Decimal
    remaining_usd: Decimal
    projected_weights: tuple[ProjectedWeight, ...]
    trades: tuple[TradeSuggestion, ...]
```

- [ ] **Step 5: Implement the deterministic four-pass algorithm**

Use these ordered passes:

1. Calculate projected total and target values using all temporary cash.
2. Spend same-currency cash on deficits sorted by largest absolute deficit, then by symbol.
3. If enabled, convert only the CNY amount required for remaining USD deficits; reuse USD sale proceeds before conversion.
4. If enabled and a class remains above the upper tolerance boundary, sell enough preferred-holding lots to approach target without crossing below it, then repeat the buy pass.

After each pass, remove trades below the minimum CNY amount, round quantities to lot size, recompute projected weights, and merge same-symbol/same-action rows. Return unspent CNY and USD explicitly.

- [ ] **Step 6: Add reason and feasibility output**

The result must include `feasible`, `max_drift_before`, `max_drift_after`, `fx_required_cny`, `remaining_cny`, `remaining_usd`, projected weights, ordered trades, and human-readable reason inputs. Human-readable Chinese sentences are assembled in the service layer from stable reason codes.

- [ ] **Step 7: Run unit and property tests**

Run: `cd backend && uv run pytest tests/unit/test_rebalance.py tests/unit/test_rebalance_properties.py -v`

Expected: PASS.

- [ ] **Step 8: Commit the optimizer**

```bash
git add backend/app/domain/rebalance.py backend/app/schemas/rebalance.py backend/tests/unit/test_rebalance.py backend/tests/unit/test_rebalance_properties.py
git commit -m "feat: add deterministic rebalancing engine"
```

### Task 13: Rebalance API, plan lifecycle, event snapshots, and baseline reset

**Files:**
- Create: `backend/app/services/rebalancing.py`
- Create: `backend/app/services/baseline.py`
- Create: `backend/app/api/routes/rebalance.py`
- Create: `backend/tests/integration/test_rebalance_api.py`
- Create: `backend/tests/integration/test_rebalance_lifecycle.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/services/snapshots.py`

- [ ] **Step 1: Write preview API tests for both valuation bases**

```python
async def test_preview_defaults_to_actual_weights(api_client, seeded_portfolio) -> None:
    response = await api_client.post(
        "/api/rebalance/preview",
        json={
            "available_cny": "20000",
            "available_usd": "0",
            "valuation_basis": "actual",
            "allow_sell": True,
            "allow_fx": True,
            "tolerance": "0.02",
            "minimum_trade_cny": "500",
        },
    )

    assert response.status_code == 200
    assert response.json()["valuation_basis"] == "actual"
    assert "fx_comparison" in response.json()
```

- [ ] **Step 2: Write lifecycle and baseline tests**

```python
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Holding


async def test_complete_rebalance_creates_after_snapshot_and_resets_baseline(
    api_client, db_session, started_plan, updated_holdings
) -> None:
    before_rows = (await db_session.scalars(select(Holding).where(Holding.is_active))).all()
    before_cost_fx = {row.id: row.cost_fx_to_cny for row in before_rows}
    response = await api_client.post(f"/api/rebalance/plans/{started_plan['id']}/complete")
    db_session.expire_all()
    after = (await db_session.scalars(select(Holding).where(Holding.is_active))).all()

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["after_snapshot_id"]
    for holding in after:
        if holding.trade_currency == "CNY":
            assert holding.baseline_fx_to_cny == Decimal("1")
        else:
            assert holding.baseline_fx_to_cny == Decimal("7.20")
        assert holding.cost_fx_to_cny == before_cost_fx[holding.id]
```

- [ ] **Step 3: Run lifecycle tests and verify failure**

Run: `docker compose run --rm api uv run pytest tests/integration/test_rebalance_api.py tests/integration/test_rebalance_lifecycle.py -v`

Expected: FAIL because the service and routes do not exist.

- [ ] **Step 4: Implement preview assembly**

The service must request a best-effort refresh before the first preview in a browser session, then load preferred holdings, current effective prices/FX, target weights, and configured trade constraints; map them to pure domain inputs; run the requested valuation basis; then run the alternate basis for comparison. A refresh failure falls back to the last valid values. Stale data is allowed only when the request includes `acknowledge_stale_data=true`.

- [ ] **Step 5: Implement persisted plan lifecycle**

Expose:

```text
POST /api/rebalance/preview
POST /api/rebalance/plans
GET  /api/rebalance/plans
GET  /api/rebalance/plans/{plan_id}
POST /api/rebalance/plans/{plan_id}/start
POST /api/rebalance/plans/{plan_id}/cancel
POST /api/rebalance/plans/{plan_id}/complete
```

`start` creates a `rebalance_before` snapshot and records the exact market-data IDs used. `complete` requires `in_progress` state, creates `rebalance_after`, updates all active baseline FX values in one transaction, and records the new baseline timestamp. `cancel` never changes holdings or baselines.

- [ ] **Step 6: Implement baseline reset service**

```python
async def reset_baseline_fx(session: AsyncSession, effective_fx: dict[str, Decimal]) -> None:
    holdings = await list_active_holdings_for_update(session)
    for holding in holdings:
        holding.baseline_fx_to_cny = (
            Decimal("1")
            if holding.trade_currency == "CNY"
            else effective_fx[holding.trade_currency]
        )
```

Do not modify `average_cost_price` or `cost_fx_to_cny` in this service.

- [ ] **Step 7: Run API and lifecycle tests**

Run: `docker compose run --rm api uv run pytest tests/integration/test_rebalance_api.py tests/integration/test_rebalance_lifecycle.py -v`

Expected: PASS.

- [ ] **Step 8: Commit rebalance workflow**

```bash
git add backend/app/services/rebalancing.py backend/app/services/baseline.py backend/app/services/snapshots.py backend/app/api/routes/rebalance.py backend/app/api/router.py backend/tests/integration/test_rebalance_api.py backend/tests/integration/test_rebalance_lifecycle.py
git commit -m "feat: add formal rebalance workflow"
```

### Task 14: Rebalance workbench UI

**Files:**
- Create: `frontend/src/features/rebalance/api.ts`
- Create: `frontend/src/features/rebalance/RebalanceInputs.tsx`
- Create: `frontend/src/features/rebalance/RebalanceSummary.tsx`
- Create: `frontend/src/features/rebalance/ProjectedAllocation.tsx`
- Create: `frontend/src/features/rebalance/TradeSuggestions.tsx`
- Create: `frontend/src/features/rebalance/RebalanceLifecycle.tsx`
- Create: `frontend/src/pages/RebalancePage.tsx`
- Create: `frontend/tests/RebalancePage.test.tsx`
- Create: `frontend/tests/RebalanceLifecycle.test.tsx`
- Modify: `frontend/src/app/router.tsx`

- [ ] **Step 1: Write input persistence and result tests**

```tsx
it("keeps inputs visible after recalculation", async () => {
  render(<RebalancePage />, { wrapper: testProviders(rebalancePreviewFixture) });
  await userEvent.clear(screen.getByLabelText("人民币"));
  await userEvent.type(screen.getByLabelText("人民币"), "20000");
  await userEvent.click(screen.getByRole("button", { name: "重新测算" }));

  expect(await screen.findByText("建议执行 4 笔交易")).toBeInTheDocument();
  expect(screen.getByLabelText("人民币")).toHaveValue("20000");
});

it("distinguishes current and projected allocation markers", async () => {
  render(<RebalancePage />, { wrapper: testProviders(rebalancePreviewFixture) });
  expect(await screen.findAllByLabelText(/当前占比/)).toHaveLength(5);
  expect(screen.getAllByLabelText(/预计占比/)).toHaveLength(5);
});
```

- [ ] **Step 2: Write sell explanation and stale-data tests**

```tsx
it("shows a reason for every sell suggestion", async () => {
  render(<RebalancePage />, { wrapper: testProviders(rebalancePreviewFixture) });
  const sellRow = await screen.findByRole("row", { name: /SPY 卖出/ });
  expect(within(sellRow).getByText("新增资金不足以消除高配")).toBeInTheDocument();
});

it("requires stale-data acknowledgement before saving", async () => {
  render(<RebalancePage />, { wrapper: testProviders(staleRebalanceFixture) });
  expect(await screen.findByText("部分行情数据已过期")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存方案" })).toBeDisabled();
});
```

- [ ] **Step 3: Run UI tests and verify failure**

Run: `cd frontend && npm test -- RebalancePage.test.tsx RebalanceLifecycle.test.tsx`

Expected: FAIL because the workbench components do not exist.

- [ ] **Step 4: Implement the confirmed two-column workbench**

Keep available CNY/USD and strategy controls in the left column. Keep feasibility, metrics, current/projected calibration rails, trade table, FX comparison, and commands in the right column. At widths below 1100px, place inputs before results in one column.

- [ ] **Step 5: Implement valuation-basis comparison and lifecycle commands**

The segmented control must request fresh previews for `actual` and `fx_neutral`. “开始本次再平衡” creates the before snapshot and changes the plan to `in_progress`; it must never claim an order was submitted. “完成再平衡并建立新基准” is only visible for in-progress plans.

- [ ] **Step 6: Run component tests, accessibility scan, and build**

Run: `cd frontend && npm test -- RebalancePage.test.tsx RebalanceLifecycle.test.tsx && npm run build`

Expected: PASS with no TypeScript errors. Task 17 adds full axe and keyboard coverage after all critical pages exist.

- [ ] **Step 7: Commit rebalance UI**

```bash
git add frontend/src/features/rebalance frontend/src/pages/RebalancePage.tsx frontend/tests frontend/src/app/router.tsx
git commit -m "feat: add explainable rebalance workbench"
```

## Phase 5: Settings, Operations, and Acceptance

### Task 15: Encrypted provider settings and data-source UI

**Files:**
- Create: `backend/app/core/secrets.py`
- Create: `backend/app/schemas/settings.py`
- Create: `backend/app/services/settings.py`
- Create: `backend/app/api/routes/settings.py`
- Create: `backend/tests/unit/test_secret_store.py`
- Create: `backend/tests/integration/test_settings_api.py`
- Create: `frontend/src/features/settings/api.ts`
- Create: `frontend/src/features/settings/ProviderSettings.tsx`
- Create: `frontend/src/features/marketData/api.ts`
- Create: `frontend/src/features/marketData/MarketDataTable.tsx`
- Create: `frontend/src/features/marketData/OverrideDrawer.tsx`
- Create: `frontend/src/pages/MarketDataPage.tsx`
- Create: `frontend/tests/MarketDataPage.test.tsx`
- Modify: `backend/app/api/router.py`
- Modify: `frontend/src/app/router.tsx`

- [ ] **Step 1: Write encryption-at-rest tests**

```python
from app.core.secrets import SecretStore


def test_secret_store_round_trips_without_plaintext(tmp_path) -> None:
    store = SecretStore(tmp_path / "fernet.key")
    ciphertext = store.encrypt("alpha-secret-value")

    assert b"alpha-secret-value" not in ciphertext
    assert store.decrypt(ciphertext) == "alpha-secret-value"
    assert (tmp_path / "fernet.key").read_bytes() != b"alpha-secret-value"
```

- [ ] **Step 2: Write masked-settings API tests**

```python
async def test_provider_key_is_never_returned(api_client) -> None:
    await api_client.put(
        "/api/settings/providers/alpha-vantage",
        json={"api_key": "alpha-secret-value", "priority": 1, "enabled": True},
    )
    response = await api_client.get("/api/settings/providers")
    item = next(value for value in response.json() if value["provider"] == "alpha-vantage")

    assert item["key_status"] == "configured"
    assert item["masked_key"].endswith("alue")
    assert "alpha-secret-value" not in response.text
```

- [ ] **Step 3: Run settings tests and verify failure**

Run: `docker compose run --rm api uv run pytest tests/unit/test_secret_store.py tests/integration/test_settings_api.py -v`

Expected: FAIL because encrypted settings support does not exist.

- [ ] **Step 4: Implement key generation and authenticated encryption**

```python
from pathlib import Path

from cryptography.fernet import Fernet


class SecretStore:
    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            self.key_path.chmod(0o600)
        self.fernet = Fernet(self.key_path.read_bytes())

    def encrypt(self, value: str) -> bytes:
        return self.fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        return self.fernet.decrypt(value).decode("utf-8")
```

Provider API keys must be encrypted before insertion into `encrypted_secrets`. Application logs must use provider name and validation status only.

Implement `EncryptedProviderCredentialReader` with the `ProviderCredentialReader` interface from Task 9 and inject it into Tushare and Alpha Vantage provider factories.

- [ ] **Step 5: Implement settings and provider validation routes**

Expose provider list/update/test endpoints and general settings for refresh time, priority, default tolerance, minimum trade amount, allow-sell default, and allow-FX default. Provider tests must perform one lightweight request and store the last validation time and result.

- [ ] **Step 6: Write data-source UI tests**

```tsx
it("keeps the last value visible when a source failed", async () => {
  render(<MarketDataPage />, { wrapper: testProviders(failedMarketDataFixture) });
  expect(await screen.findByText("651.28")).toBeInTheDocument();
  expect(screen.getByText("数据已过期")).toBeInTheDocument();
  expect(screen.getByText("Yahoo 请求超时，当前使用 07/10 收盘值")).toBeInTheDocument();
});

it("requires a note for a manual override", async () => {
  render(<OverrideDrawer marketKey="USD/CNY" open onClose={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("手动值"), "7.18");
  expect(screen.getByRole("button", { name: "启用手动汇率" })).toBeDisabled();
});
```

- [ ] **Step 7: Implement the settings and data-source page**

Use a single status table with effective value, source, market time, fetched time, state, refresh action, and override action. Provider keys use password fields and show masked values after save. Override drawers require a note and optional expiry. Each holding edit row must expose its preferred provider, with “follow global priority” as the default.

- [ ] **Step 8: Run backend and frontend tests**

Run: `docker compose run --rm api uv run pytest tests/unit/test_secret_store.py tests/integration/test_settings_api.py -v`

Run: `cd frontend && npm test -- MarketDataPage.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 9: Commit settings and source management**

```bash
git add backend/app/core/secrets.py backend/app/schemas/settings.py backend/app/services/settings.py backend/app/api/routes/settings.py backend/tests frontend/src/features/settings frontend/src/features/marketData frontend/src/pages/MarketDataPage.tsx frontend/tests frontend/src/app/router.tsx
git commit -m "feat: add secure data source settings"
```

### Task 16: Backup, restore, and local-only deployment hardening

**Files:**
- Create: `scripts/backup.sh`
- Create: `scripts/restore.sh`
- Create: `backend/tests/integration/test_backup_restore.py`
- Modify: `Makefile`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write backup/restore verification test**

```python
def test_backup_restore_round_trip(tmp_path, docker_compose, seeded_database) -> None:
    backup = tmp_path / "portfolio-20260713T080000Z.dump"
    docker_compose.run("./scripts/backup.sh", str(backup))
    seeded_database.delete_all_holdings()
    docker_compose.run("./scripts/restore.sh", "--yes", str(backup))

    assert seeded_database.count_holdings() == 5
    assert seeded_database.count_snapshots() >= 1
```

- [ ] **Step 2: Implement backup script**

`scripts/backup.sh` must enable `set -euo pipefail`, create the destination directory, and run `pg_dump --format=custom --no-owner --no-acl` through `docker compose exec -T db`. Default output is `backups/portfolio-<UTC timestamp>.dump`.

- [ ] **Step 3: Implement restore script**

`scripts/restore.sh` must require an existing dump file and either interactive confirmation or `--yes`. Before restore, create a safety backup; then run `pg_restore --clean --if-exists --no-owner --no-acl` inside the database container. It must not overwrite or export the separate Fernet key volume.

- [ ] **Step 4: Add Makefile commands**

Provide:

```make
backup:
	./scripts/backup.sh

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/file.dump" && exit 1)
	./scripts/restore.sh "$(FILE)"
```

- [ ] **Step 5: Verify local-only networking**

Run: `docker compose config | rg '127.0.0.1:8080'`

Expected: one frontend binding.

Run: `docker compose config | rg '5432:5432'`

Expected: no output and exit code 1.

- [ ] **Step 6: Run backup/restore test**

Run: `docker compose run --rm api uv run pytest tests/integration/test_backup_restore.py -v`

Expected: PASS.

- [ ] **Step 7: Commit operations support**

```bash
git add scripts Makefile compose.yaml .env.example README.md backend/tests/integration/test_backup_restore.py
git commit -m "feat: add backup and restore operations"
```

### Task 17: Fonts, responsive behavior, accessibility, and visual regression

**Files:**
- Create: `frontend/public/fonts/NotoSansSC-Regular.woff2`
- Create: `frontend/public/fonts/NotoSansSC-SemiBold.woff2`
- Create: `frontend/public/fonts/IBMPlexMono-Regular.woff2`
- Create: `frontend/public/fonts/IBMPlexMono-SemiBold.woff2`
- Create: `frontend/e2e/dashboard.spec.ts`
- Create: `frontend/e2e/holdings-cost.spec.ts`
- Create: `frontend/e2e/rebalance.spec.ts`
- Create: `frontend/e2e/accessibility.spec.ts`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/fixtures/portfolio.ts`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add licensed local fonts and declarations**

Record source URLs and licenses in `README.md`. Define `@font-face` with `font-display: swap`; Chinese UI uses `Noto Sans SC`, and numeric/code roles use `IBM Plex Mono`. Tests must run with network disabled to prove fonts are local.

Run: `cd frontend && npm install -D @playwright/test@^1 @axe-core/playwright@^4`

Expected: Playwright and axe packages are recorded in `package.json` and `package-lock.json`.

- [ ] **Step 2: Write desktop and compact screenshot tests**

```ts
test("dashboard matches calibration desk at supported widths", async ({ page }) => {
  await seedPortfolio(page, "balanced");
  for (const viewport of [
    { width: 1440, height: 900, name: "desktop" },
    { width: 1024, height: 768, name: "compact" },
    { width: 390, height: 844, name: "mobile" },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/");
    await expect(page).toHaveScreenshot(`dashboard-${viewport.name}.png`, {
      animations: "disabled",
      maxDiffPixelRatio: 0.01,
    });
  }
});
```

- [ ] **Step 3: Write overlap and workflow tests**

```ts
test("cost drawer remains reachable at compact width", async ({ page }) => {
  await seedPortfolio(page, "balanced");
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/holdings");
  await page.getByRole("button", { name: "追加买入 SPY" }).click();
  await expect(page.getByRole("heading", { name: "追加买入 · SPY" })).toBeVisible();
  await expect(page.getByRole("button", { name: "更新 SPY 持仓" })).toBeInViewport();
});
```

The rebalance E2E test must cover actual/FX-neutral switching, one sell reason, save plan, start plan, update holdings, and complete baseline reset.

Add an empty-state E2E case that starts with only the five seeded asset classes, verifies the dashboard offers “添加第一个持仓”, and confirms the asset-class editor remains available.

- [ ] **Step 4: Add accessibility checks**

```ts
import AxeBuilder from "@axe-core/playwright";


test("critical pages have no serious accessibility violations", async ({ page }) => {
  for (const path of ["/", "/holdings", "/rebalance"]) {
    await page.goto(path);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
  }
});
```

- [ ] **Step 5: Test reduced motion and keyboard-only operation**

Use Playwright `page.emulateMedia({ reducedMotion: 'reduce' })` and assert calibration markers have zero transition duration. Complete asset creation, purchase preview, and saved rebalance plan without mouse input.

- [ ] **Step 6: Run Playwright suite**

Run: `docker compose up -d && cd frontend && npx playwright test`

Expected: PASS with screenshots for 1440×900, 1024×768, and 390×844; no incoherent overlap or serious accessibility violations.

- [ ] **Step 7: Commit visual acceptance assets**

```bash
git add frontend/public/fonts frontend/e2e frontend/playwright.config.ts frontend/src/styles/global.css frontend/package.json frontend/package-lock.json README.md
git commit -m "test: add visual and accessibility coverage"
```

### Task 18: Full-system acceptance and operator documentation

**Files:**
- Create: `docs/operations.md`
- Create: `docs/user-guide.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-13-portfolio-rebalancer-design.md`

- [ ] **Step 1: Document first-run workflow**

`README.md` must contain exact Docker Desktop prerequisites, `.env` creation, `docker compose up -d`, `http://localhost:8080`, health checks, logs, shutdown, and upgrade commands.

- [ ] **Step 2: Document user workflows**

`docs/user-guide.md` must cover initial holdings, cost FX meaning, purchase fee defaults, actual-fee override, partial sale limitation, market-data override, dashboard interpretation, rebalancing, completion/baseline reset, snapshot history, backup, and restore.

- [ ] **Step 3: Document operations and recovery**

`docs/operations.md` must describe service responsibilities, volumes, provider keys, scheduled refresh, stale-data behavior, database backup/restore, Fernet key handling, and how to verify that no service except Nginx is exposed.

- [ ] **Step 4: Run the complete backend suite**

Run: `docker compose run --rm api uv run pytest -v`

Expected: PASS with unit, property, and integration tests.

- [ ] **Step 5: Run the complete frontend suite**

Run: `cd frontend && npm test -- --run && npm run build && npx playwright test`

Expected: PASS; Vite builds successfully and all E2E tests pass.

- [ ] **Step 6: Rebuild from an empty Docker state**

Run:

```bash
docker compose down -v
docker compose build --no-cache
docker compose up -d
docker compose ps
curl -fsS http://localhost:8080/api/health
```

Expected: all four services are healthy, the API returns `{"status":"ok","service":"api"}`, default strategy rows are seeded once, and the application loads at `http://localhost:8080`.

- [ ] **Step 7: Execute the acceptance checklist**

Verify every item in design specification section 20, including decimal identities, stale-data fallback, cost preview, sell-enabled rebalancing, daily/manual/event snapshots, baseline reset, local-only networking, calibration-rail semantics, responsive screenshots, and keyboard-only critical flows. Mark design status `Implemented` only after every item has evidence.

- [ ] **Step 8: Commit documentation and acceptance evidence**

```bash
git add README.md docs
git commit -m "docs: add portfolio operator and user guides"
```

## Specification Coverage Matrix

| Design requirement | Implementation tasks |
| --- | --- |
| Docker Desktop, localhost-only frontend, internal API/DB | 1, 2, 16, 18 |
| Default five-class strategy and editable 100% target | 3, 5, 8 |
| Holdings, accounts, currencies, cost and baseline FX | 2, 5, 8 |
| Actual and FX-neutral allocation formulas | 4, 10 |
| P&L, price effect, and FX effect | 4, 10 |
| Purchase fee rules, actual fee override, per-symbol defaults | 6, 8 |
| Partial sale, correction, audit history, restore-as-new-change | 6, 8 |
| Yahoo, AKShare, optional Tushare/Alpha Vantage | 9, 15 |
| Manual market override, expiry, stale fallback | 9, 15 |
| Scheduled refresh and daily snapshot | 9, 11 |
| Manual and rebalance event snapshots | 11, 13 |
| Cash-first buy/sell/FX rebalancing | 12, 13, 14 |
| Actual versus FX-neutral rebalance comparison | 13, 14 |
| Rebalance completion and baseline reset | 13, 14 |
| “组合校准台” design system and calibration rail | 7, 10, 14, 17 |
| Dashboard, asset configuration, holdings, P&L, history, data source pages | 8, 10, 11, 15 |
| Encrypted provider keys | 15 |
| Backup and restore | 16, 18 |
| Responsive, keyboard, reduced-motion, visual regression | 17 |
| User and operator documentation | 18 |

## Final Execution Order

Execute Tasks 1 through 18 in order. After Tasks 8, 11, 14, and 18, stop for a manual checkpoint:

- **After Task 8:** confirm manual asset, holding, and cost workflows.
- **After Task 11:** confirm automated data, dashboard, P&L, and history.
- **After Task 14:** confirm rebalancing suggestions and baseline lifecycle.
- **After Task 18:** confirm Docker rebuild, visual acceptance, backup, and restore.

Do not combine checkpoint commits. A failure found at a checkpoint must be fixed in the phase that introduced it before later tasks begin.
