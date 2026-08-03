# Email Daily Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a daily email digest that, on trading days, sends per-holding PnL analysis and rebalancing suggestions after the scheduled market refresh, plus a data-anomaly email when market data is incomplete.

**Architecture:** Extend the worker's existing daily pipeline (refresh -> snapshot -> email). A new `email_sender.py` handles SMTP delivery with stdlib `smtplib` in `asyncio.to_thread`; `email_digest.py` renders HTML and orchestrates the digest; `email_settings.py` persists SMTP config with the password encrypted via the existing Fernet `SecretStore`. Settings are stored on the singleton `settings` row plus one `encrypted_secrets` row with `provider='smtp'`, exposed through `GET/PUT /api/settings/email` and `POST /api/settings/email/test`. Frontend adds an "邮件通知" section to the existing data-source settings block.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, Alembic, APScheduler worker, stdlib `smtplib`/`email`; React 19, TanStack Query, Vitest + msw.

## Global Constraints

- No new Python runtime dependencies: SMTP must use stdlib `smtplib` and `email`.
- Decimals stay serialized as strings (existing `DecimalString` pattern).
- Credentials are never logged, returned in API responses, or stored in plaintext; reuse `SecretStore` Fernet encryption and the masked-value pattern from provider keys.
- UI strings are Chinese; backend user-facing messages follow existing `ServiceError` codes.
- Worker timezone is `Asia/Shanghai`; trading days are Monday-Friday by local date.
- Every production change is written test-first (RED -> GREEN) and committed per task.
- Tests run with `make test-backend` (Docker Compose test project) and `make test-frontend` (vitest run).

---

### Task 1: Settings Model Columns And Migration

**Files:**
- Modify: `backend/app/db/models.py` (add email columns to `Setting`)
- Create: `backend/alembic/versions/20260803_0008_email_settings.py`
- Test: `backend/tests/integration/test_email_migration.py`

**Interfaces:**
- Produces: `Setting.email_enabled: bool`, `Setting.email_recipient: str | None`, `Setting.email_smtp_host: str | None`, `Setting.email_smtp_port: int` (default 465), `Setting.email_smtp_security: str` (default "ssl"), `Setting.email_smtp_username: str | None`, `Setting.email_from: str | None`; DB check constraint `ck_settings_email_smtp_security`.

- [ ] **Step 1: Write the failing model and migration tests**

Create `backend/tests/integration/test_email_migration.py`:

```python
import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import Setting


MIGRATION_TEST_ENGINE = create_async_engine(
    "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio",
    pool_pre_ping=True,
    poolclass=NullPool,
)
MigrationSessionFactory = async_sessionmaker(MIGRATION_TEST_ENGINE, expire_on_commit=False)


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


async def _run_alembic_upgrade(revision: str) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_config(), revision)


async def _run_alembic_downgrade(revision: str) -> None:
    await asyncio.to_thread(command.downgrade, _alembic_config(), revision)


async def _email_settings_migration_state() -> dict[str, object]:
    async with MigrationSessionFactory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        columns = {
            row["column_name"]
            for row in (
                await session.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'settings'
                          AND column_name IN (
                              'email_enabled',
                              'email_recipient',
                              'email_smtp_host',
                              'email_smtp_port',
                              'email_smtp_security',
                              'email_smtp_username',
                              'email_from'
                          )
                        """
                    )
                )
            ).mappings()
        }
        constraints = set(
            await session.scalars(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'settings'::regclass
                    """
                )
            )
        )
    return {"revision": revision, "columns": columns, "constraints": constraints}


EXPECTED_EMAIL_COLUMNS = {
    "email_enabled",
    "email_recipient",
    "email_smtp_host",
    "email_smtp_port",
    "email_smtp_security",
    "email_smtp_username",
    "email_from",
}


@pytest.mark.asyncio
async def test_settings_email_migration_round_trip(_reset_database) -> None:
    try:
        await _run_alembic_downgrade("20260715_0007")
        before = await _email_settings_migration_state()
        assert EXPECTED_EMAIL_COLUMNS.isdisjoint(before["columns"])

        await _run_alembic_upgrade("head")
        after_upgrade = await _email_settings_migration_state()
        assert after_upgrade["revision"] == "20260803_0008"
        assert EXPECTED_EMAIL_COLUMNS <= after_upgrade["columns"]
        assert "ck_settings_email_smtp_security" in after_upgrade["constraints"]

        await _run_alembic_downgrade("20260715_0007")
        after_downgrade = await _email_settings_migration_state()
        assert EXPECTED_EMAIL_COLUMNS.isdisjoint(after_downgrade["columns"])
        assert "ck_settings_email_smtp_security" not in after_downgrade["constraints"]

        await _run_alembic_upgrade("head")
    finally:
        await _run_alembic_upgrade("head")


@pytest.mark.asyncio
async def test_settings_email_columns_default_and_round_trip(db_session) -> None:
    setting = await db_session.scalar(select(Setting).limit(1))
    assert setting is not None
    assert setting.email_enabled is False
    assert setting.email_smtp_port == 465
    assert setting.email_smtp_security == "ssl"

    setting.email_enabled = True
    setting.email_recipient = "owner@example.com"
    setting.email_smtp_host = "smtp.example.com"
    setting.email_smtp_port = 587
    setting.email_smtp_security = "starttls"
    setting.email_smtp_username = "owner@example.com"
    setting.email_from = None
    await db_session.commit()
    db_session.expire_all()

    stored = await db_session.scalar(select(Setting).limit(1))
    assert stored.email_enabled is True
    assert stored.email_recipient == "owner@example.com"
    assert stored.email_smtp_host == "smtp.example.com"
    assert stored.email_smtp_port == 587
    assert stored.email_smtp_security == "starttls"
    assert stored.email_smtp_username == "owner@example.com"
    assert stored.email_from is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_email_migration.py -v` (via the Docker test project: `make test-backend` runs the whole suite; for the fast loop use `docker compose -p portfolio-rebalancer-test run --rm api uv run pytest tests/integration/test_email_migration.py -v` after starting the test DB).

Expected: FAIL - `Setting` has no attribute `email_enabled`; migration state is missing the email columns.

- [ ] **Step 3: Add the model columns**

In `backend/app/db/models.py`, inside the `Setting` class after the `rebalance_valuation_basis` column, add:

```python
    email_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    email_recipient: Mapped[str | None] = mapped_column(String(320))
    email_smtp_host: Mapped[str | None] = mapped_column(String(255))
    email_smtp_port: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=465,
        server_default="465",
    )
    email_smtp_security: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ssl",
        server_default="ssl",
    )
    email_smtp_username: Mapped[str | None] = mapped_column(String(320))
    email_from: Mapped[str | None] = mapped_column(String(320))
```

And add to the `__table_args__` tuple, after the existing `CheckConstraint`:

```python
        CheckConstraint(
            "email_smtp_security IN ('ssl', 'starttls')",
            name="ck_settings_email_smtp_security",
        ),
```

- [ ] **Step 4: Add the migration**

Create `backend/alembic/versions/20260803_0008_email_settings.py`:

```python
"""add email notification settings

Revision ID: 20260803_0008
Revises: 20260715_0007
Create Date: 2026-08-03 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0008"
down_revision: str | None = "20260715_0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("settings", sa.Column("email_recipient", sa.String(length=320), nullable=True))
    op.add_column("settings", sa.Column("email_smtp_host", sa.String(length=255), nullable=True))
    op.add_column(
        "settings",
        sa.Column("email_smtp_port", sa.Integer(), nullable=False, server_default="465"),
    )
    op.add_column(
        "settings",
        sa.Column(
            "email_smtp_security",
            sa.String(length=16),
            nullable=False,
            server_default="ssl",
        ),
    )
    op.add_column("settings", sa.Column("email_smtp_username", sa.String(length=320), nullable=True))
    op.add_column("settings", sa.Column("email_from", sa.String(length=320), nullable=True))
    op.create_check_constraint(
        "ck_settings_email_smtp_security",
        "settings",
        "email_smtp_security IN ('ssl', 'starttls')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_settings_email_smtp_security", "settings", type_="check")
    op.drop_column("settings", "email_from")
    op.drop_column("settings", "email_smtp_username")
    op.drop_column("settings", "email_smtp_security")
    op.drop_column("settings", "email_smtp_port")
    op.drop_column("settings", "email_smtp_host")
    op.drop_column("settings", "email_recipient")
    op.drop_column("settings", "email_enabled")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/integration/test_email_migration.py -v`

Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260803_0008_email_settings.py backend/tests/integration/test_email_migration.py
git commit -m "feat: add email settings columns and migration"
```

---

### Task 2: Email Settings Schema, Service, And GET/PUT API

**Files:**
- Create: `backend/app/schemas/email_settings.py`
- Create: `backend/app/services/email_settings.py`
- Modify: `backend/app/api/routes/settings.py`
- Test: `backend/tests/unit/test_email_settings_schema.py`
- Test: `backend/tests/integration/test_email_settings_api.py`

**Interfaces:**
- Consumes: `Setting.email_*` columns (Task 1), `EncryptedSecret` model, `SecretStore`, `ServiceError`, `_run_write` helper in `settings.py` routes.
- Produces: `EmailSettingsUpdate` (enabled, recipient, smtp_host, smtp_port, smtp_security, smtp_username, from_address, password), `EmailSettingsResponse` (same fields minus password, plus `password_masked` and `updated_at`), `get_email_settings(session)`, `update_email_settings(session, payload)`; routes `GET /api/settings/email`, `PUT /api/settings/email`.

- [ ] **Step 1: Write the failing schema tests**

Create `backend/tests/unit/test_email_settings_schema.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.email_settings import EmailSettingsUpdate


def test_email_settings_update_accepts_valid_payload() -> None:
    payload = EmailSettingsUpdate(
        enabled=True,
        recipient="owner@example.com",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_security="ssl",
        smtp_username="owner@example.com",
        from_address=None,
        password="auth-code",
    )

    assert payload.recipient == "owner@example.com"
    assert payload.smtp_port == 465


def test_email_settings_update_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        EmailSettingsUpdate(
            enabled=False,
            recipient="not-an-email",
            smtp_host="",
            smtp_port=465,
            smtp_security="ssl",
            smtp_username="",
        )


def test_email_settings_update_requires_complete_config_when_enabled() -> None:
    with pytest.raises(ValidationError, match="recipient"):
        EmailSettingsUpdate(
            enabled=True,
            recipient="",
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_security="ssl",
            smtp_username="owner@example.com",
        )


def test_email_settings_update_rejects_bad_port_and_security() -> None:
    with pytest.raises(ValidationError):
        EmailSettingsUpdate(
            enabled=False,
            recipient="owner@example.com",
            smtp_host="smtp.qq.com",
            smtp_port=0,
            smtp_security="ssl",
            smtp_username="owner@example.com",
        )
    with pytest.raises(ValidationError):
        EmailSettingsUpdate(
            enabled=False,
            recipient="owner@example.com",
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_security="plain",
            smtp_username="owner@example.com",
        )
```

- [ ] **Step 2: Run the schema tests to verify they fail**

Run: `pytest tests/unit/test_email_settings_schema.py -v`

Expected: FAIL - `ModuleNotFoundError: app.schemas.email_settings`.

- [ ] **Step 3: Create the schema module**

Create `backend/app/schemas/email_settings.py`:

```python
from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

EmailSecurity = Literal["ssl", "starttls"]


def _validate_address(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    _display, address = parseaddr(stripped)
    if (
        address != stripped
        or "@" not in address
        or address.startswith("@")
        or address.endswith("@")
    ):
        raise PydanticCustomError(
            "settings_email_invalid",
            "{field} must be a valid email address.",
            {"field": field_name},
        )
    return stripped


class EmailSettingsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    enabled: bool
    recipient: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_security: EmailSecurity = "ssl"
    smtp_username: str | None = None
    from_address: str | None = None
    password: str | None = Field(default=None, max_length=512)

    @field_validator("recipient", "from_address")
    @classmethod
    def validate_email_fields(cls, value: str | None, info) -> str | None:
        return _validate_address(value, info.field_name)

    @model_validator(mode="after")
    def require_complete_config_when_enabled(self) -> "EmailSettingsUpdate":
        if self.enabled:
            for field_name in ("recipient", "smtp_host", "smtp_username"):
                if not getattr(self, field_name):
                    raise PydanticCustomError(
                        "settings_email_incomplete",
                        "Recipient, SMTP host and username are required when email is enabled.",
                        {"field": field_name},
                    )
        return self


class EmailSettingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    recipient: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_security: EmailSecurity
    smtp_username: str | None
    from_address: str | None
    password_masked: str | None
    updated_at: datetime
```

- [ ] **Step 4: Run the schema tests to verify they pass**

Run: `pytest tests/unit/test_email_settings_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Write the failing settings service and API tests**

Create `backend/tests/integration/test_email_settings_api.py`:

```python
from sqlalchemy import select

from app.db.models import EncryptedSecret, Setting


def _email_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": True,
        "recipient": "owner@example.com",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "smtp_username": "owner@qq.com",
        "from_address": None,
        "password": "smtp-auth-code",
    }
    payload.update(overrides)
    return payload


async def test_email_settings_round_trip_and_encrypted_password(api_client, db_session) -> None:
    initial = await api_client.get("/api/settings/email")
    assert initial.status_code == 200, initial.text
    assert initial.json()["enabled"] is False
    assert initial.json()["smtp_port"] == 465
    assert initial.json()["smtp_security"] == "ssl"
    assert initial.json()["password_masked"] is None

    saved = await api_client.put("/api/settings/email", json=_email_payload())
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is True
    assert saved.json()["recipient"] == "owner@example.com"
    assert saved.json()["password_masked"] == "****ode"
    assert "smtp-auth-code" not in saved.text

    fetched = await api_client.get("/api/settings/email")
    db_session.expire_all()
    stored = await db_session.scalar(select(Setting).limit(1))
    secret = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["password_masked"] == "****ode"
    assert stored.email_enabled is True
    assert stored.email_recipient == "owner@example.com"
    assert stored.email_smtp_host == "smtp.qq.com"
    assert stored.email_smtp_port == 465
    assert stored.email_smtp_security == "ssl"
    assert stored.email_smtp_username == "owner@qq.com"
    assert secret is not None
    assert secret.masked_value == "****ode"
    assert "smtp-auth-code" not in secret.encrypted_value

    kept = await api_client.put(
        "/api/settings/email",
        json=_email_payload(password="", recipient="other@example.com"),
    )
    db_session.expire_all()
    secret_after = await db_session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )

    assert kept.status_code == 200, kept.text
    assert kept.json()["recipient"] == "other@example.com"
    assert kept.json()["password_masked"] == "****ode"
    assert secret_after is not None
    assert secret_after.masked_value == "****ode"


async def test_email_settings_validation_errors(api_client) -> None:
    bad_email = await api_client.put(
        "/api/settings/email",
        json=_email_payload(recipient="not-an-email"),
    )
    incomplete = await api_client.put(
        "/api/settings/email",
        json=_email_payload(enabled=True, recipient="", smtp_host="", smtp_username=""),
    )
    bad_port = await api_client.put(
        "/api/settings/email",
        json=_email_payload(smtp_port=0),
    )

    assert bad_email.status_code == 422
    assert incomplete.status_code == 422
    assert bad_port.status_code == 422
```

- [ ] **Step 6: Run the API tests to verify they fail**

Run: `pytest tests/integration/test_email_settings_api.py -v`

Expected: FAIL - routes `/api/settings/email` do not exist (404).

- [ ] **Step 7: Create the email settings service**

Create `backend/app/services/email_settings.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.db.models import EncryptedSecret, Setting
from app.schemas.email_settings import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
)
from app.services.errors import ServiceError


def _secret_store() -> SecretStore:
    return SecretStore(Path(get_settings().secret_key_path))


def _mask_secret(value: str) -> str:
    suffix = value[-4:] if len(value) >= 4 else value
    return f"****{suffix}"


async def _get_setting(session: AsyncSession, *, lock: bool = False) -> Setting:
    statement = select(Setting).limit(1)
    if lock:
        statement = statement.with_for_update()
    setting = await session.scalar(statement)
    if setting is None:
        raise RuntimeError("Default settings row is missing.")
    return setting


async def _smtp_secret(session: AsyncSession) -> EncryptedSecret | None:
    return await session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )


async def get_email_settings(session: AsyncSession) -> EmailSettingsResponse:
    setting = await _get_setting(session)
    secret = await _smtp_secret(session)
    return EmailSettingsResponse(
        enabled=setting.email_enabled,
        recipient=setting.email_recipient,
        smtp_host=setting.email_smtp_host,
        smtp_port=setting.email_smtp_port,
        smtp_security=setting.email_smtp_security,  # type: ignore[arg-type]
        smtp_username=setting.email_smtp_username,
        from_address=setting.email_from,
        password_masked=secret.masked_value if secret is not None else None,
        updated_at=setting.updated_at,
    )


async def update_email_settings(
    session: AsyncSession,
    payload: EmailSettingsUpdate,
) -> EmailSettingsResponse:
    setting = await _get_setting(session, lock=True)
    setting.email_enabled = payload.enabled
    setting.email_recipient = payload.recipient
    setting.email_smtp_host = payload.smtp_host
    setting.email_smtp_port = payload.smtp_port
    setting.email_smtp_security = payload.smtp_security
    setting.email_smtp_username = payload.smtp_username
    setting.email_from = payload.from_address
    setting.updated_at = datetime.now(UTC)

    secret = await _smtp_secret(session)
    if payload.password:
        encrypted = _secret_store().encrypt(payload.password).decode("ascii")
        if secret is None:
            session.add(
                EncryptedSecret(
                    provider="smtp",
                    encrypted_value=encrypted,
                    masked_value=_mask_secret(payload.password),
                )
            )
        else:
            secret.encrypted_value = encrypted
            secret.masked_value = _mask_secret(payload.password)
            secret.validation_status = None
            secret.validation_message = None
            secret.last_validated_at = None
    await session.flush()
    return await get_email_settings(session)


async def require_email_configured(session: AsyncSession) -> EncryptedSecret:
    secret = await _smtp_secret(session)
    if secret is None:
        raise ServiceError(409, "EMAIL_NOT_CONFIGURED", "SMTP authorization code is not configured.")
    return secret
```

- [ ] **Step 8: Add the GET/PUT routes**

In `backend/app/api/routes/settings.py`, extend the imports:

```python
from app.schemas.email_settings import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
)
from app.services.email_settings import (
    get_email_settings,
    update_email_settings,
)
```

And add after the `put_rebalance_default_setting` route:

```python
@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_setting(
    session: AsyncSession = Depends(get_session),
) -> EmailSettingsResponse:
    return await get_email_settings(session)


@router.put("/email", response_model=EmailSettingsResponse)
async def put_email_setting(
    payload: EmailSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> EmailSettingsResponse:
    return await _run_write(session, lambda: update_email_settings(session, payload))
```

- [ ] **Step 9: Run the API tests to verify they pass**

Run: `pytest tests/integration/test_email_settings_api.py -v`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/schemas/email_settings.py backend/app/services/email_settings.py backend/app/api/routes/settings.py backend/tests/unit/test_email_settings_schema.py backend/tests/integration/test_email_settings_api.py
git commit -m "feat: email settings API with encrypted SMTP password"
```

---

### Task 3: Rebalance Preview With Default Settings

**Files:**
- Modify: `backend/app/services/rebalancing.py`
- Test: `backend/tests/integration/test_rebalance_defaults_preview.py`

**Interfaces:**
- Consumes: `_prepare_rebalance`, `_preview_response`, `RebalancePreviewRequest`, `Setting` (Task 1), `uuid4` (already imported in `rebalancing.py`).
- Produces: `preview_rebalance_with_defaults(session: AsyncSession) -> RebalancePreviewResponse` - a preview that uses the persisted default funds/constraints and `acknowledge_stale_data=True`.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_rebalance_defaults_preview.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update

from app.db.models import MarketData, Setting
from app.services.rebalancing import preview_rebalance_with_defaults


def _holding_payload(asset_class_id: str, *, symbol: str, quantity: str) -> dict[str, object]:
    return {
        "asset_class_id": asset_class_id,
        "symbol": symbol,
        "name": symbol,
        "market": "SH",
        "account_name": symbol,
        "trade_currency": "CNY",
        "quantity": quantity,
        "average_cost_price": "1",
        "cost_fx_to_cny": "1",
        "baseline_fx_to_cny": "1",
        "lot_size": "1",
        "quantity_precision": 12,
        "is_rebalance_preferred": True,
    }


async def test_preview_with_defaults_uses_persisted_constraints(api_client, db_session) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    quantities = ("20", "20", "30", "20", "10")
    for index, (asset_class, quantity) in enumerate(zip(asset_classes, quantities, strict=True)):
        await api_client.post(
            "/api/holdings",
            json=_holding_payload(
                asset_class["id"],
                symbol=f"51010{index}",
                quantity=quantity,
            ),
        )
    now = datetime.now(UTC)
    for index in range(5):
        db_session.add(
            MarketData(
                data_type="price",
                symbol=f"51010{index}",
                source="test-provider",
                value=Decimal("1"),
                market_time=now,
                fetched_at=now,
                status="valid",
            )
        )
    await db_session.execute(
        update(Setting).values(
            rebalance_available_cny=Decimal("10000"),
            default_tolerance=Decimal("0.01"),
            allow_sell=True,
            allow_fx=False,
        )
    )
    await db_session.commit()

    preview = await preview_rebalance_with_defaults(db_session)

    assert preview.status == "ok"
    assert preview.valuation_basis == "actual"
    assert len(preview.result.projected_weights) == 5
    assert preview.result.feasible is True
    assert any(trade.action == "buy" for trade in preview.result.trades)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_rebalance_defaults_preview.py -v`

Expected: FAIL - `ImportError: cannot import name 'preview_rebalance_with_defaults'`.

- [ ] **Step 3: Implement the service function**

In `backend/app/services/rebalancing.py`, add at the end of the module:

```python
async def preview_rebalance_with_defaults(session: AsyncSession) -> RebalancePreviewResponse:
    setting = await session.scalar(select(Setting).limit(1))
    if setting is None:
        raise RuntimeError("Default settings row is missing.")
    payload = RebalancePreviewRequest(
        session_token="daily-email-digest",
        request_token=uuid4().hex,
        available_cny=setting.rebalance_available_cny,
        available_usd=setting.rebalance_available_usd,
        valuation_basis=setting.rebalance_valuation_basis,
        allow_sell=setting.allow_sell,
        allow_fx=setting.allow_fx,
        tolerance=setting.default_tolerance,
        minimum_trade_cny=setting.minimum_trade_amount_cny,
        acknowledge_stale_data=True,
    )
    prepared = await _prepare_rebalance(session, payload=payload, allow_stale=True)
    return _preview_response(payload=payload, prepared=prepared, refresh_attempted=False)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_rebalance_defaults_preview.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rebalancing.py backend/tests/integration/test_rebalance_defaults_preview.py
git commit -m "feat: rebalance preview with persisted default constraints"
```

---

### Task 4: Digest HTML Rendering

**Files:**
- Create: `backend/app/services/email_digest.py` (render functions only)
- Test: `backend/tests/unit/test_email_digest_render.py`

**Interfaces:**
- Consumes: `PortfolioAnalyticsResponse`, `RebalancePreviewResponse` (from `app.schemas.analytics` / `app.schemas.rebalance`).
- Produces: `build_digest_html(*, analytics: PortfolioAnalyticsResponse, rebalance: RebalancePreviewResponse | None, local_date: date) -> str`, `build_anomaly_html(*, items: list[dict[str, object]], local_date: date) -> str`.

- [ ] **Step 1: Write the failing render tests**

Create `backend/tests/unit/test_email_digest_render.py`:

```python
from datetime import date
from decimal import Decimal

from app.schemas.analytics import (
    AssetClassAnalyticsResponse,
    HoldingAnalyticsResponse,
    PortfolioAnalyticsResponse,
    PortfolioDecisionResponse,
)
from app.schemas.rebalance import (
    RebalanceComparisonResponse,
    ProjectedWeightResponse,
    RebalancePreviewResponse,
    RebalanceResultResponse,
    TradeSuggestionResponse,
)
from app.services.email_digest import build_anomaly_html, build_digest_html


def _holding() -> HoldingAnalyticsResponse:
    return HoldingAnalyticsResponse(
        holding_id="00000000-0000-0000-0000-000000000001",
        asset_class_id="00000000-0000-0000-0000-0000000000aa",
        symbol="SPY",
        name="标普 500",
        trade_currency="USD",
        current_price="100",
        current_fx_to_cny="7.2",
        price_status="valid",
        fx_status="valid",
        cost_trade_currency="270",
        market_value_trade_currency="300",
        unrealized_pnl_trade_currency="30",
        cost_cny="1944",
        market_value_cny="2160",
        fx_neutral_value_cny="2040",
        unrealized_pnl="216",
        unrealized_return="0.111111111111",
        price_effect="189",
        fx_effect="27",
    )


def _asset_class() -> AssetClassAnalyticsResponse:
    return AssetClassAnalyticsResponse(
        id="00000000-0000-0000-0000-0000000000aa",
        name="美股",
        target_weight="0.5",
        display_order=1,
        actual_weight="0.5",
        fx_neutral_weight="0.48",
        drift="0",
        fx_weight_contribution="0.02",
        cost_cny="1944",
        market_value_cny="2160",
        fx_neutral_value_cny="2040",
        unrealized_pnl="216",
        price_effect="189",
        fx_effect="27",
    )


def _analytics() -> PortfolioAnalyticsResponse:
    return PortfolioAnalyticsResponse(
        as_of=None,
        data_status="valid",
        has_stale_data=False,
        has_manual_data=False,
        tolerance="0.02",
        cost_cny="1944",
        market_value_cny="2160",
        fx_neutral_value_cny="2040",
        unrealized_pnl="216",
        unrealized_return="0.111111111111",
        price_effect="189",
        fx_effect="27",
        overseas_weight="1",
        decision=PortfolioDecisionResponse(
            status="rebalance",
            title="建议再平衡",
            reason="至少一个资产类别超出策略区间。",
            max_drift="0.05",
            fx_contribution="0.02",
            primary_action="view_rebalance",
        ),
        asset_classes=[_asset_class()],
        holdings=[_holding()],
        data_inputs=[],
    )


def _result() -> RebalanceResultResponse:
    return RebalanceResultResponse(
        feasible=True,
        max_drift_before="0.05",
        max_drift_after="0.01",
        fx_required_cny="0",
        remaining_cny="0",
        remaining_usd="0",
        projected_weights=(
            ProjectedWeightResponse(
                asset_class_id="00000000-0000-0000-0000-0000000000aa",
                before="0.5",
                after="0.5",
                target="0.5",
            ),
        ),
        trades=(
            TradeSuggestionResponse(
                symbol="SPY",
                action="buy",
                quantity="0.1",
                amount_cny="72",
                amount_trade_currency="10",
                reason_code="UNDERWEIGHT_WITH_CASH",
                reason="当前低配，可直接使用同币种现金补足目标仓位。",
            ),
        ),
    )


def _rebalance() -> RebalancePreviewResponse:
    result = _result()
    return RebalancePreviewResponse(
        session_token="t",
        request_token="r",
        status="ok",
        data_status="valid",
        acknowledge_stale_data=True,
        refresh_attempted=False,
        valuation_basis="actual",
        result=result,
        fx_comparison=RebalanceComparisonResponse(
            valuation_basis="fx_neutral",
            result=result,
        ),
    )


def test_digest_html_contains_summary_holdings_and_trades() -> None:
    html = build_digest_html(
        analytics=_analytics(),
        rebalance=_rebalance(),
        local_date=date(2026, 8, 3),
    )

    assert "投资组合日报" in html
    assert "2026-08-03" in html
    assert "总市值" in html
    assert "标普 500" in html
    assert "SPY" in html
    assert "建议再平衡" in html
    assert "买入" in html
    assert "72.00" in html
    assert "当前配置在容差内" not in html


def test_digest_html_no_trades_shows_hold_copy() -> None:
    rebalance = _rebalance()
    empty = _result().model_copy(update={"trades": ()})
    html = build_digest_html(
        analytics=_analytics(),
        rebalance=RebalancePreviewResponse(
            session_token="t",
            request_token="r",
            status="ok",
            data_status="valid",
            acknowledge_stale_data=True,
            refresh_attempted=False,
            valuation_basis="actual",
            result=empty,
            fx_comparison=RebalanceComparisonResponse(
                valuation_basis="fx_neutral",
                result=empty,
            ),
        ),
        local_date=date(2026, 8, 3),
    )

    assert "当前配置在容差内，无需调整" in html


def test_digest_html_escapes_holding_names() -> None:
    holding = _holding().model_copy(update={"name": "A&B <ETF>"})
    analytics = _analytics().model_copy(update={"holdings": [holding]})

    html = build_digest_html(
        analytics=analytics,
        rebalance=None,
        local_date=date(2026, 8, 3),
    )

    assert "A&amp;B &lt;ETF&gt;" in html
    assert "A&B <ETF>" not in html
    assert "再平衡建议暂不可用" in html


def test_digest_html_stale_banner() -> None:
    analytics = _analytics().model_copy(update={"has_stale_data": True})

    html = build_digest_html(
        analytics=analytics,
        rebalance=None,
        local_date=date(2026, 8, 3),
    )

    assert "部分行情数据可能过期" in html


def test_anomaly_html_lists_items_without_analysis() -> None:
    html = build_anomaly_html(
        items=[
            {
                "holding_id": "00000000-0000-0000-0000-000000000001",
                "symbol": "SPY",
                "input": "price",
                "key": "price:SPY",
                "status": "failed",
                "value": None,
                "market_time": None,
                "source": "yahoo",
                "error_summary": "provider_request_failed: hidden",
            }
        ],
        local_date=date(2026, 8, 3),
    )

    assert "数据异常" in html
    assert "SPY" in html
    assert "price" in html
    assert "总市值" not in html
```

- [ ] **Step 2: Run the render tests to verify they fail**

Run: `pytest tests/unit/test_email_digest_render.py -v`

Expected: FAIL - `ModuleNotFoundError: app.services.email_digest`.

- [ ] **Step 3: Implement the render functions**

Create `backend/app/services/email_digest.py`:

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from html import escape

from app.schemas.analytics import PortfolioAnalyticsResponse
from app.schemas.rebalance import RebalancePreviewResponse


def _esc(value: object) -> str:
    return escape(str(value))


def _money(value: object) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _signed_money(value: object) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):+,.2f}"


def _percent(value: object) -> str:
    return f"{Decimal(str(value)) * 100:.2f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th style=\"padding:6px 10px;border-bottom:1px solid #ddd;text-align:left;font-size:12px;\">{_esc(header)}</th>" for header in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td style=\"padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;\">{cell}</td>"
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return f"<table style=\"border-collapse:collapse;width:100%;\"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build_digest_html(
    *,
    analytics: PortfolioAnalyticsResponse,
    rebalance: RebalancePreviewResponse | None,
    local_date: date,
) -> str:
    stale_banner = ""
    if analytics.has_stale_data:
        stale_banner = (
            "<p style=\"background:#fff7e0;border:1px solid #e0b94d;color:#7a5a00;"
            "padding:10px;font-size:13px;\">部分行情数据可能过期，以下内容基于最近有效数据。</p>"
        )

    decision = analytics.decision
    summary_rows = [
        ["总市值 (CNY)", _money(analytics.market_value_cny)],
        ["总浮动盈亏 (CNY)", _signed_money(analytics.unrealized_pnl)],
        ["总盈亏率", _percent(analytics.unrealized_return)],
        ["决策", f"{_esc(decision.title)}（{_esc(decision.reason)}）"],
        ["数据时间", _esc(analytics.as_of.strftime("%Y-%m-%d %H:%M:%S %Z") if analytics.as_of else "-")],
    ]

    class_rows = [
        [
            _esc(item.name),
            _percent(item.target_weight),
            _percent(item.actual_weight),
            f"{Decimal(item.drift) * 100:+.2f}%",
            _signed_money(item.unrealized_pnl),
        ]
        for item in analytics.asset_classes
    ]

    class_names = {item.id: item.name for item in analytics.asset_classes}
    holdings_by_class: list[tuple[str, list]] = []
    for holding in analytics.holdings:
        name = class_names.get(holding.asset_class_id, "未分类")
        if holdings_by_class and holdings_by_class[-1][0] == name:
            holdings_by_class[-1][1].append(holding)
        else:
            holdings_by_class.append((name, [holding]))

    holding_sections = []
    for class_name, holdings in holdings_by_class:
        rows = [
            [
                _esc(holding.name),
                _esc(holding.symbol),
                _esc(holding.account_name),
                _esc(holding.quantity),
                _esc(holding.current_price),
                _esc(holding.current_fx_to_cny),
                _money(holding.market_value_cny),
                _signed_money(holding.unrealized_pnl),
                _percent(holding.unrealized_return),
                _signed_money(holding.price_effect),
                _signed_money(holding.fx_effect),
            ]
            for holding in holdings
        ]
        holding_sections.append(
            f"<h3 style=\"margin:18px 0 6px;font-size:14px;\">{_esc(class_name)}</h3>"
            + _table(
                ["名称", "代码", "账户", "份额", "现价", "汇率", "市值 (CNY)", "浮动盈亏 (CNY)", "盈亏率", "价格影响", "汇率影响"],
                rows,
            )
        )

    if rebalance is not None and rebalance.result.trades:
        trade_rows = [
            [
                _esc(trade.symbol),
                "买入" if trade.action == "buy" else "卖出",
                _esc(trade.quantity),
                _money(trade.amount_cny),
                _esc(trade.reason),
            ]
            for trade in rebalance.result.trades
        ]
        rebalance_html = _table(
            ["标的", "方向", "数量", "金额 (CNY)", "原因"],
            trade_rows,
        )
    elif rebalance is not None:
        rebalance_html = "<p style=\"font-size:13px;\">当前配置在容差内，无需调整。</p>"
    else:
        rebalance_html = "<p style=\"font-size:13px;\">再平衡建议暂不可用。</p>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Microsoft YaHei',sans-serif;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;padding:24px;border:1px solid #e5e5e5;">
    <h1 style="margin:0 0 4px;font-size:20px;">投资组合日报</h1>
    <p style="margin:0 0 16px;color:#666;font-size:12px;">{_esc(local_date.isoformat())}</p>
    {stale_banner}
    <h2 style="font-size:14px;">组合摘要</h2>
    {_table(["指标", "数值"], summary_rows)}
    <h2 style="font-size:14px;margin-top:18px;">资产类别</h2>
    {_table(["名称", "目标占比", "实际占比", "偏移", "浮动盈亏 (CNY)"], class_rows)}
    <h2 style="font-size:14px;margin-top:18px;">持仓盈亏明细</h2>
    {''.join(holding_sections) or '<p style="font-size:13px;">暂无持仓。</p>'}
    <h2 style="font-size:14px;margin-top:18px;">再平衡建议</h2>
    {rebalance_html}
    <p style="margin-top:20px;color:#999;font-size:11px;">再平衡建议基于当前默认约束计算，仅供参考。</p>
  </div>
</body>
</html>"""


def build_anomaly_html(*, items: list[dict[str, object]], local_date: date) -> str:
    rows = [
        [
            _esc(item.get("symbol", "-")),
            _esc(item.get("input", "-")),
            _esc(item.get("key", "-")),
            _esc(item.get("status", "-")),
            _esc(item.get("source", "-") or "-"),
            _esc(item.get("error_summary", "-") or "-"),
        ]
        for item in items
    ]
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Microsoft YaHei',sans-serif;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;padding:24px;border:1px solid #e5e5e5;">
    <h1 style="margin:0 0 4px;font-size:20px;">投资组合日报（数据异常）</h1>
    <p style="margin:0 0 16px;color:#666;font-size:12px;">{_esc(local_date.isoformat())}</p>
    <p style="font-size:13px;">部分必要行情或汇率数据不完整，本次未生成盈亏分析与再平衡建议。请到「数据源」页面检查以下异常项：</p>
    {_table(["标的", "类型", "数据项", "状态", "来源", "错误摘要"], rows)}
  </div>
</body>
</html>"""
```

- [ ] **Step 4: Run the render tests to verify they pass**

Run: `pytest tests/unit/test_email_digest_render.py -v`

Expected: PASS. Fix any assertion mismatches by adjusting the test data, not the production behavior.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/email_digest.py backend/tests/unit/test_email_digest_render.py
git commit -m "feat: render daily digest and anomaly email HTML"
```

---

### Task 5: SMTP Sender, Digest Orchestration, And Test Endpoint

**Files:**
- Create: `backend/app/services/email_sender.py`
- Modify: `backend/app/services/email_settings.py` (add `EmailConfig`, `load_email_config`, `test_email_settings`)
- Modify: `backend/app/services/email_digest.py` (add `_is_trading_day`, `send_daily_digest_if_configured`)
- Modify: `backend/app/schemas/email_settings.py` (add `EmailTestResult`)
- Modify: `backend/app/api/routes/settings.py` (add `POST /email/test`)
- Test: `backend/tests/unit/test_email_sender.py`
- Test: `backend/tests/integration/test_email_digest.py`
- Test: extend `backend/tests/integration/test_email_settings_api.py` (test endpoint)

**Interfaces:**
- Consumes: `build_digest_html`, `build_anomaly_html` (Task 4), `get_portfolio_analytics`, `preview_rebalance_with_defaults` (Task 3), `SecretStore`, `ServiceError`, `Setting.email_*`, `EncryptedSecret(provider='smtp')`.
- Produces: `EmailConfig` dataclass (`host`, `port`, `security`, `username`, `password`, `from_address`, `recipient`); `load_email_config(session) -> EmailConfig | None`; `send_email(config, subject, html)`; `classify_smtp_error(exc) -> str`; `test_email_settings(session) -> EmailTestResult`; `send_daily_digest_if_configured(session, *, now: datetime | None = None)`; route `POST /api/settings/email/test`.

- [ ] **Step 1: Write the failing sender unit tests**

Create `backend/tests/unit/test_email_sender.py`:

```python
import smtplib
from unittest.mock import Mock

import pytest

from app.services.email_sender import (
    EmailConfig,
    classify_smtp_error,
    send_email,
)


def _config(**overrides: object) -> EmailConfig:
    values: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 465,
        "security": "ssl",
        "username": "owner@example.com",
        "password": "secret-auth-code",
        "from_address": "owner@example.com",
        "recipient": "receiver@example.com",
    }
    values.update(overrides)
    return EmailConfig(**values)  # type: ignore[arg-type]


def test_send_email_ssl_branch(monkeypatch) -> None:
    server = Mock()
    smtp_ssl = Mock(return_value=server)
    monkeypatch.setattr("app.services.email_sender.smtplib.SMTP_SSL", smtp_ssl)

    send_email(_config(), subject="投资组合日报 2026-08-03", html="<p>内容</p>")

    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)
    server.login.assert_called_once_with("owner@example.com", "secret-auth-code")
    sent = server.send_message.call_args.args[0]
    assert "投资组合日报" in str(sent["Subject"])
    assert sent["To"] == "receiver@example.com"
    assert "<p>内容</p>" in sent.get_payload()[1].get_payload()
    server.__enter__.assert_called_once()


def test_send_email_starttls_branch(monkeypatch) -> None:
    server = Mock()
    monkeypatch.setattr("app.services.email_sender.smtplib.SMTP", Mock(return_value=server))

    send_email(
        _config(port=587, security="starttls"),
        subject="test",
        html="<p>内容</p>",
    )

    server.starttls.assert_called_once()
    server.login.assert_called_once()


def test_classify_smtp_errors() -> None:
    assert classify_smtp_error(smtplib.SMTPAuthenticationError(535, b"auth")) == "smtp_auth_failed"
    assert classify_smtp_error(smtplib.SMTPRecipientsRefused({})) == "smtp_recipient_rejected"
    assert classify_smtp_error(ConnectionError("boom")) == "smtp_connect_failed"
    assert classify_smtp_error(TimeoutError("slow")) == "smtp_timeout"
    assert classify_smtp_error(smtplib.SMTPException("other")) == "smtp_send_failed"
```

- [ ] **Step 2: Run the sender tests to verify they fail**

Run: `pytest tests/unit/test_email_sender.py -v`

Expected: FAIL - `ModuleNotFoundError: app.services.email_sender`.

- [ ] **Step 3: Implement the sender**

Create `backend/app/services/email_sender.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage
import logging
import smtplib
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmailConfig:
    host: str
    port: int
    security: Literal["ssl", "starttls"]
    username: str
    password: str
    from_address: str
    recipient: str


def _send_smtp_sync(config: EmailConfig, message: EmailMessage) -> None:
    if config.security == "ssl":
        with smtplib.SMTP_SSL(config.host, config.port, timeout=30) as server:
            server.login(config.username, config.password)
            server.send_message(message, from_addr=config.from_address, to_addrs=[config.recipient])
        return
    with smtplib.SMTP(config.host, config.port, timeout=30) as server:
        server.starttls()
        server.login(config.username, config.password)
        server.send_message(message, from_addr=config.from_address, to_addrs=[config.recipient])


async def send_email(config: EmailConfig, *, subject: str, html: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = config.recipient
    message.set_content("请使用支持 HTML 的邮件客户端查看本邮件。")
    message.add_alternative(html, subtype="html")
    await asyncio.to_thread(_send_smtp_sync, config, message)


def classify_smtp_error(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "smtp_auth_failed"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "smtp_recipient_rejected"
    if isinstance(exc, TimeoutError):
        return "smtp_timeout"
    if isinstance(exc, (ConnectionError, OSError)):
        return "smtp_connect_failed"
    if isinstance(exc, smtplib.SMTPException):
        return "smtp_send_failed"
    return "smtp_send_failed"
```

- [ ] **Step 4: Run the sender tests to verify they pass**

Run: `pytest tests/unit/test_email_sender.py -v`

Expected: PASS.

- [ ] **Step 5: Add config loading and the test service**

In `backend/app/services/email_settings.py`, replace the module with:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.secrets import SecretStore
from app.db.models import EncryptedSecret, Setting
from app.schemas.email_settings import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailTestResult,
)
from app.services.email_sender import EmailConfig, classify_smtp_error, send_email
from app.services.errors import ServiceError


def _secret_store() -> SecretStore:
    return SecretStore(Path(get_settings().secret_key_path))


def _mask_secret(value: str) -> str:
    suffix = value[-4:] if len(value) >= 4 else value
    return f"****{suffix}"


async def _get_setting(session: AsyncSession, *, lock: bool = False) -> Setting:
    statement = select(Setting).limit(1)
    if lock:
        statement = statement.with_for_update()
    setting = await session.scalar(statement)
    if setting is None:
        raise RuntimeError("Default settings row is missing.")
    return setting


async def _smtp_secret(session: AsyncSession) -> EncryptedSecret | None:
    return await session.scalar(
        select(EncryptedSecret).where(EncryptedSecret.provider == "smtp")
    )


async def get_email_settings(session: AsyncSession) -> EmailSettingsResponse:
    setting = await _get_setting(session)
    secret = await _smtp_secret(session)
    return EmailSettingsResponse(
        enabled=setting.email_enabled,
        recipient=setting.email_recipient,
        smtp_host=setting.email_smtp_host,
        smtp_port=setting.email_smtp_port,
        smtp_security=setting.email_smtp_security,  # type: ignore[arg-type]
        smtp_username=setting.email_smtp_username,
        from_address=setting.email_from,
        password_masked=secret.masked_value if secret is not None else None,
        updated_at=setting.updated_at,
    )


async def update_email_settings(
    session: AsyncSession,
    payload: EmailSettingsUpdate,
) -> EmailSettingsResponse:
    setting = await _get_setting(session, lock=True)
    setting.email_enabled = payload.enabled
    setting.email_recipient = payload.recipient
    setting.email_smtp_host = payload.smtp_host
    setting.email_smtp_port = payload.smtp_port
    setting.email_smtp_security = payload.smtp_security
    setting.email_smtp_username = payload.smtp_username
    setting.email_from = payload.from_address
    setting.updated_at = datetime.now(UTC)

    secret = await _smtp_secret(session)
    if payload.password:
        encrypted = _secret_store().encrypt(payload.password).decode("ascii")
        if secret is None:
            session.add(
                EncryptedSecret(
                    provider="smtp",
                    encrypted_value=encrypted,
                    masked_value=_mask_secret(payload.password),
                )
            )
        else:
            secret.encrypted_value = encrypted
            secret.masked_value = _mask_secret(payload.password)
            secret.validation_status = None
            secret.validation_message = None
            secret.last_validated_at = None
    await session.flush()
    return await get_email_settings(session)


async def load_email_config(session: AsyncSession) -> EmailConfig | None:
    setting = await _get_setting(session)
    secret = await _smtp_secret(session)
    if (
        not setting.email_enabled
        or not setting.email_recipient
        or not setting.email_smtp_host
        or not setting.email_smtp_username
        or secret is None
    ):
        return None
    try:
        password = _secret_store().decrypt(secret.encrypted_value.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("Stored SMTP authorization code cannot be decrypted.") from exc
    return EmailConfig(
        host=setting.email_smtp_host,
        port=setting.email_smtp_port,
        security=setting.email_smtp_security,  # type: ignore[arg-type]
        username=setting.email_smtp_username,
        password=password,
        from_address=setting.email_from or setting.email_smtp_username,
        recipient=setting.email_recipient,
    )


async def test_email_settings(session: AsyncSession) -> EmailTestResult:
    config = await load_email_config(session)
    if config is None:
        return EmailTestResult(status="failed", error_category="not_configured")
    try:
        await send_email(config, subject="[测试] 投资组合日报邮件通知", html="<p>这是一封测试邮件。</p>")
    except Exception as exc:
        return EmailTestResult(status="failed", error_category=classify_smtp_error(exc))
    return EmailTestResult(status="ok", error_category=None)
```

- [ ] **Step 6: Add the test-result schema**

In `backend/app/schemas/email_settings.py`, add:

```python
class EmailTestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "failed"]
    error_category: Literal[
        "not_configured",
        "smtp_connect_failed",
        "smtp_auth_failed",
        "smtp_recipient_rejected",
        "smtp_timeout",
        "smtp_send_failed",
    ] | None
```

- [ ] **Step 7: Add the test route**

In `backend/app/api/routes/settings.py`, extend imports with `EmailTestResult` and `test_email_settings`, then add:

```python
@router.post("/email/test", response_model=EmailTestResult)
async def post_email_test(
    session: AsyncSession = Depends(get_session),
) -> EmailTestResult:
    return await _run_write(session, lambda: test_email_settings(session))
```

- [ ] **Step 8: Write the failing orchestration integration test**

Create `backend/tests/integration/test_email_digest.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

from sqlalchemy import update

from app.db.models import MarketData
from app.services.email_digest import send_daily_digest_if_configured


async def _enable_email(api_client, db_session) -> None:
    response = await api_client.put(
        "/api/settings/email",
        json={
            "enabled": True,
            "recipient": "owner@example.com",
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
            "smtp_security": "ssl",
            "smtp_username": "owner@qq.com",
            "from_address": None,
            "password": "smtp-auth-code",
        },
    )
    assert response.status_code == 200, response.text


async def _seed_portfolio(api_client, db_session) -> None:
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    for index, asset_class in enumerate(asset_classes):
        response = await api_client.post(
            "/api/holdings",
            json={
                "asset_class_id": asset_class["id"],
                "symbol": f"51010{index}",
                "name": f"标的{index}",
                "market": "SH",
                "account_name": f"账户{index}",
                "trade_currency": "CNY",
                "quantity": "20",
                "average_cost_price": "1",
                "cost_fx_to_cny": "1",
                "baseline_fx_to_cny": "1",
                "lot_size": "1",
                "quantity_precision": 12,
                "is_rebalance_preferred": True,
            },
        )
        assert response.status_code == 201, response.text
        now = datetime.now(UTC)
        db_session.add(
            MarketData(
                data_type="price",
                symbol=f"51010{index}",
                source="test-provider",
                value=Decimal("1"),
                market_time=now,
                fetched_at=now,
                status="valid",
            )
        )
    await db_session.commit()


async def test_digest_skipped_when_email_disabled(api_client, db_session, monkeypatch) -> None:
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_not_awaited()


async def test_digest_skipped_on_weekend(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(
        db_session,
        now=datetime(2026, 8, 2, 8, 0, tzinfo=UTC),  # Sunday
    )

    send.assert_not_awaited()


async def test_digest_sends_anomaly_email_when_data_incomplete(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await _enable_email(api_client, db_session)
    asset_classes = (await api_client.get("/api/asset-classes")).json()
    await api_client.post(
        "/api/holdings",
        json={
            "asset_class_id": asset_classes[0]["id"],
            "symbol": "MISSING",
            "name": "缺失标的",
            "market": "SH",
            "account_name": "账户",
            "trade_currency": "CNY",
            "quantity": "10",
            "average_cost_price": "1",
            "cost_fx_to_cny": "1",
            "baseline_fx_to_cny": "1",
            "lot_size": "1",
            "quantity_precision": 12,
            "is_rebalance_preferred": True,
        },
    )
    await db_session.commit()
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_awaited_once()
    subject = send.await_args.kwargs["subject"]
    html = send.await_args.kwargs["html"]
    assert "数据异常" in subject
    assert "MISSING" in html
    assert "总市值" not in html


async def test_digest_sends_full_analysis_email(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    await _seed_portfolio(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_awaited_once()
    subject = send.await_args.kwargs["subject"]
    html = send.await_args.kwargs["html"]
    assert subject.startswith("投资组合日报")
    assert "总市值" in html
    assert "标的0" in html
    assert "再平衡建议" in html


async def test_digest_skipped_for_empty_portfolio(api_client, db_session, monkeypatch) -> None:
    await _enable_email(api_client, db_session)
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_digest.send_email", send)

    await send_daily_digest_if_configured(db_session)

    send.assert_not_awaited()
```

- [ ] **Step 9: Run the orchestration test to verify it fails**

Run: `pytest tests/integration/test_email_digest.py -v`

Expected: FAIL - `ImportError: cannot import name 'send_daily_digest_if_configured'`.

- [ ] **Step 10: Implement the orchestration**

In `backend/app/services/email_digest.py`, replace the module with the full implementation:

```python
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.analytics import PortfolioAnalyticsResponse
from app.schemas.rebalance import RebalancePreviewResponse
from app.services.analytics import get_portfolio_analytics
from app.services.email_sender import EmailConfig, send_email
from app.services.email_settings import load_email_config
from app.services.errors import ServiceError
from app.services.rebalancing import preview_rebalance_with_defaults


def _esc(value: object) -> str:
    return escape(str(value))


def _money(value: object) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _signed_money(value: object) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):+,.2f}"


def _percent(value: object) -> str:
    return f"{Decimal(str(value)) * 100:.2f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f"<th style=\"padding:6px 10px;border-bottom:1px solid #ddd;text-align:left;font-size:12px;\">{_esc(header)}</th>"
        for header in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td style=\"padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;\">{cell}</td>"
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return f"<table style=\"border-collapse:collapse;width:100%;\"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build_digest_html(
    *,
    analytics: PortfolioAnalyticsResponse,
    rebalance: RebalancePreviewResponse | None,
    local_date: date,
) -> str:
    stale_banner = ""
    if analytics.has_stale_data:
        stale_banner = (
            "<p style=\"background:#fff7e0;border:1px solid #e0b94d;color:#7a5a00;"
            "padding:10px;font-size:13px;\">部分行情数据可能过期，以下内容基于最近有效数据。</p>"
        )

    decision = analytics.decision
    summary_rows = [
        ["总市值 (CNY)", _money(analytics.market_value_cny)],
        ["总浮动盈亏 (CNY)", _signed_money(analytics.unrealized_pnl)],
        ["总盈亏率", _percent(analytics.unrealized_return)],
        ["决策", f"{_esc(decision.title)}（{_esc(decision.reason)}）"],
        [
            "数据时间",
            _esc(analytics.as_of.strftime("%Y-%m-%d %H:%M:%S %Z") if analytics.as_of else "-"),
        ],
    ]

    class_rows = [
        [
            _esc(item.name),
            _percent(item.target_weight),
            _percent(item.actual_weight),
            f"{Decimal(item.drift) * 100:+.2f}%",
            _signed_money(item.unrealized_pnl),
        ]
        for item in analytics.asset_classes
    ]

    class_names = {item.id: item.name for item in analytics.asset_classes}
    holdings_by_class: list[tuple[str, list]] = []
    for holding in analytics.holdings:
        name = class_names.get(holding.asset_class_id, "未分类")
        if holdings_by_class and holdings_by_class[-1][0] == name:
            holdings_by_class[-1][1].append(holding)
        else:
            holdings_by_class.append((name, [holding]))

    holding_sections = []
    for class_name, holdings in holdings_by_class:
        rows = [
            [
                _esc(holding.name),
                _esc(holding.symbol),
                _esc(holding.account_name),
                _esc(holding.quantity),
                _esc(holding.current_price),
                _esc(holding.current_fx_to_cny),
                _money(holding.market_value_cny),
                _signed_money(holding.unrealized_pnl),
                _percent(holding.unrealized_return),
                _signed_money(holding.price_effect),
                _signed_money(holding.fx_effect),
            ]
            for holding in holdings
        ]
        holding_sections.append(
            f"<h3 style=\"margin:18px 0 6px;font-size:14px;\">{_esc(class_name)}</h3>"
            + _table(
                [
                    "名称",
                    "代码",
                    "账户",
                    "份额",
                    "现价",
                    "汇率",
                    "市值 (CNY)",
                    "浮动盈亏 (CNY)",
                    "盈亏率",
                    "价格影响",
                    "汇率影响",
                ],
                rows,
            )
        )

    if rebalance is not None and rebalance.result.trades:
        trade_rows = [
            [
                _esc(trade.symbol),
                "买入" if trade.action == "buy" else "卖出",
                _esc(trade.quantity),
                _money(trade.amount_cny),
                _esc(trade.reason),
            ]
            for trade in rebalance.result.trades
        ]
        rebalance_html = _table(
            ["标的", "方向", "数量", "金额 (CNY)", "原因"],
            trade_rows,
        )
    elif rebalance is not None:
        rebalance_html = "<p style=\"font-size:13px;\">当前配置在容差内，无需调整。</p>"
    else:
        rebalance_html = "<p style=\"font-size:13px;\">再平衡建议暂不可用。</p>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Microsoft YaHei',sans-serif;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;padding:24px;border:1px solid #e5e5e5;">
    <h1 style="margin:0 0 4px;font-size:20px;">投资组合日报</h1>
    <p style="margin:0 0 16px;color:#666;font-size:12px;">{_esc(local_date.isoformat())}</p>
    {stale_banner}
    <h2 style="font-size:14px;">组合摘要</h2>
    {_table(["指标", "数值"], summary_rows)}
    <h2 style="font-size:14px;margin-top:18px;">资产类别</h2>
    {_table(["名称", "目标占比", "实际占比", "偏移", "浮动盈亏 (CNY)"], class_rows)}
    <h2 style="font-size:14px;margin-top:18px;">持仓盈亏明细</h2>
    {''.join(holding_sections) or '<p style="font-size:13px;">暂无持仓。</p>'}
    <h2 style="font-size:14px;margin-top:18px;">再平衡建议</h2>
    {rebalance_html}
    <p style="margin-top:20px;color:#999;font-size:11px;">再平衡建议基于当前默认约束计算，仅供参考。</p>
  </div>
</body>
</html>"""


def build_anomaly_html(*, items: list[dict[str, object]], local_date: date) -> str:
    rows = [
        [
            _esc(item.get("symbol", "-")),
            _esc(item.get("input", "-")),
            _esc(item.get("key", "-")),
            _esc(item.get("status", "-")),
            _esc(item.get("source", "-") or "-"),
            _esc(item.get("error_summary", "-") or "-"),
        ]
        for item in items
    ]
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Microsoft YaHei',sans-serif;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;padding:24px;border:1px solid #e5e5e5;">
    <h1 style="margin:0 0 4px;font-size:20px;">投资组合日报（数据异常）</h1>
    <p style="margin:0 0 16px;color:#666;font-size:12px;">{_esc(local_date.isoformat())}</p>
    <p style="font-size:13px;">部分必要行情或汇率数据不完整，本次未生成盈亏分析与再平衡建议。请到「数据源」页面检查以下异常项：</p>
    {_table(["标的", "类型", "数据项", "状态", "来源", "错误摘要"], rows)}
  </div>
</body>
</html>"""


def _is_trading_day(local_date: date) -> bool:
    return local_date.weekday() < 5


async def send_daily_digest_if_configured(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> None:
    config = await load_email_config(session)
    if config is None:
        return
    local_now = now or datetime.now(UTC)
    local_date = local_now.astimezone(ZoneInfo(get_settings().timezone)).date()
    if not _is_trading_day(local_date):
        return

    try:
        analytics = await get_portfolio_analytics(session)
    except ServiceError as exc:
        if exc.code == "PORTFOLIO_DATA_INCOMPLETE":
            await send_email(
                config,
                subject=f"投资组合日报 {local_date.isoformat()}（数据异常）",
                html=build_anomaly_html(items=exc.extra["items"], local_date=local_date),
            )
            return
        raise
    if analytics.data_status == "setup" or not analytics.holdings:
        return

    rebalance: RebalancePreviewResponse | None = None
    try:
        rebalance = await preview_rebalance_with_defaults(session)
    except ServiceError:
        rebalance = None
    await send_email(
        config,
        subject=f"投资组合日报 {local_date.isoformat()}",
        html=build_digest_html(
            analytics=analytics,
            rebalance=rebalance,
            local_date=local_date,
        ),
    )
```

- [ ] **Step 11: Run the orchestration tests to verify they pass**

Run: `pytest tests/integration/test_email_digest.py -v`

Expected: PASS. If `send.await_args` is None, fix the assertion helper (assert awaited once first).

- [ ] **Step 12: Add the test-endpoint integration test**

Append to `backend/tests/integration/test_email_settings_api.py`:

```python
from unittest.mock import AsyncMock


async def test_email_test_endpoint_returns_ok(api_client, db_session, monkeypatch) -> None:
    await api_client.put("/api/settings/email", json=_email_payload())
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_settings.send_email", send)

    response = await api_client.post("/api/settings/email/test")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "error_category": None}
    send.assert_awaited_once()


async def test_email_test_endpoint_reports_failure_category(
    api_client,
    db_session,
    monkeypatch,
) -> None:
    await api_client.put("/api/settings/email", json=_email_payload())
    from smtplib import SMTPAuthenticationError

    async def _fail(*args, **kwargs):
        raise SMTPAuthenticationError(535, b"auth")

    monkeypatch.setattr("app.services.email_settings.send_email", _fail)

    response = await api_client.post("/api/settings/email/test")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "failed", "error_category": "smtp_auth_failed"}


async def test_email_test_endpoint_not_configured(api_client) -> None:
    response = await api_client.post("/api/settings/email/test")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "failed", "error_category": "not_configured"}
```

Note: move the `from unittest.mock import AsyncMock` import to the top of the file with the other imports.

- [ ] **Step 13: Run the settings API tests to verify they pass**

Run: `pytest tests/integration/test_email_settings_api.py tests/unit/test_email_sender.py -v`

Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add backend/app/services/email_sender.py backend/app/services/email_settings.py backend/app/services/email_digest.py backend/app/schemas/email_settings.py backend/app/api/routes/settings.py backend/tests/unit/test_email_sender.py backend/tests/integration/test_email_digest.py backend/tests/integration/test_email_settings_api.py
git commit -m "feat: SMTP sender and daily digest orchestration"
```

---

### Task 6: Worker Pipeline Integration

**Files:**
- Modify: `backend/app/worker.py`
- Test: `backend/tests/unit/test_worker.py`

**Interfaces:**
- Consumes: `send_daily_digest_if_configured(session, *, now=None)` (Task 5).
- Produces: `scheduled_refresh()` now runs refresh -> snapshot -> digest, each in its own transaction, with the digest step failure-isolated.

- [ ] **Step 1: Update the failing worker tests**

In `backend/tests/unit/test_worker.py`, update `test_scheduled_refresh_uses_distinct_transactions` to three sessions and a digest mock:

```python
@pytest.mark.asyncio
async def test_scheduled_refresh_uses_distinct_transactions(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    refresh_session = _FakeSession()
    snapshot_session = _FakeSession()
    digest_session = _FakeSession()
    sessions = iter([refresh_session, snapshot_session, digest_session])
    refresh_all_required_data = AsyncMock()
    create_daily_snapshot_if_complete = AsyncMock()
    send_daily_digest_if_configured = AsyncMock()

    class _SessionScope:
        def __init__(self, session) -> None:
            self.session = session

        async def __aenter__(self) -> _FakeSession:
            return self.session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope(next(sessions)))
    monkeypatch.setattr(worker_module, "refresh_all_required_data", refresh_all_required_data)
    monkeypatch.setattr(
        worker_module,
        "create_daily_snapshot_if_complete",
        create_daily_snapshot_if_complete,
    )
    monkeypatch.setattr(worker_module, "send_daily_digest_if_configured", send_daily_digest_if_configured)

    await worker_module.scheduled_refresh()

    refresh_all_required_data.assert_awaited_once_with(refresh_session)
    create_daily_snapshot_if_complete.assert_awaited_once_with(snapshot_session)
    send_daily_digest_if_configured.assert_awaited_once_with(digest_session)
```

Add a new test for digest failure isolation:

```python
@pytest.mark.asyncio
async def test_scheduled_refresh_contains_digest_failure(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    class _SessionScope:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    refresh = AsyncMock()
    snapshot = AsyncMock()
    digest = AsyncMock(side_effect=RuntimeError("smtp failed"))
    log_exception = Mock()
    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope())
    monkeypatch.setattr(worker_module, "refresh_all_required_data", refresh)
    monkeypatch.setattr(worker_module, "create_daily_snapshot_if_complete", snapshot)
    monkeypatch.setattr(worker_module, "send_daily_digest_if_configured", digest)
    monkeypatch.setattr(worker_module.logger, "exception", log_exception)

    await worker_module.scheduled_refresh()

    refresh.assert_awaited_once()
    snapshot.assert_awaited_once()
    digest.assert_awaited_once()
    log_exception.assert_called_once_with(
        "Daily email digest failed after successful market refresh"
    )
```

Also update the existing `test_scheduled_refresh_contains_snapshot_failure` test so the digest step still runs after a snapshot failure:

```python
@pytest.mark.asyncio
async def test_scheduled_refresh_contains_snapshot_failure(monkeypatch) -> None:
    class _TransactionScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def begin(self) -> _TransactionScope:
            return _TransactionScope()

    class _SessionScope:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    refresh = AsyncMock()
    snapshot = AsyncMock(side_effect=RuntimeError("snapshot write failed"))
    digest = AsyncMock()
    log_exception = Mock()
    monkeypatch.setattr(worker_module, "SessionFactory", lambda: _SessionScope())
    monkeypatch.setattr(worker_module, "refresh_all_required_data", refresh)
    monkeypatch.setattr(worker_module, "create_daily_snapshot_if_complete", snapshot)
    monkeypatch.setattr(worker_module, "send_daily_digest_if_configured", digest)
    monkeypatch.setattr(worker_module.logger, "exception", log_exception)

    await worker_module.scheduled_refresh()

    refresh.assert_awaited_once()
    snapshot.assert_awaited_once()
    digest.assert_awaited_once()
    log_exception.assert_called_once_with(
        "Daily snapshot creation failed after successful market refresh"
    )
```

- [ ] **Step 2: Run the worker tests to verify they fail**

Run: `pytest tests/unit/test_worker.py -v`

Expected: FAIL - `AttributeError: module 'app.worker' has no attribute 'send_daily_digest_if_configured'`.

- [ ] **Step 3: Wire the digest step into the worker**

In `backend/app/worker.py`, add the import and extend `scheduled_refresh`:

```python
from app.services.email_digest import send_daily_digest_if_configured
```

```python
async def scheduled_refresh() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await refresh_all_required_data(session)

    try:
        async with SessionFactory() as session:
            async with session.begin():
                await create_daily_snapshot_if_complete(session)
    except Exception:
        logger.exception("Daily snapshot creation failed after successful market refresh")

    try:
        async with SessionFactory() as session:
            async with session.begin():
                await send_daily_digest_if_configured(session)
    except Exception:
        logger.exception("Daily email digest failed after successful market refresh")
```

- [ ] **Step 4: Run the worker tests to verify they pass**

Run: `pytest tests/unit/test_worker.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker.py backend/tests/unit/test_worker.py
git commit -m "feat: send daily digest in the worker pipeline"
```

---

### Task 7: Frontend Email Settings Form

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/settings/api.ts`
- Create: `frontend/src/features/settings/EmailSettingsForm.tsx`
- Modify: `frontend/src/features/settings/ProviderSettings.tsx`
- Modify: `frontend/tests/fixtures.ts`
- Modify: `frontend/tests/MarketDataPage.test.tsx`
- Test: `frontend/tests/EmailSettingsForm.test.tsx`

**Interfaces:**
- Consumes: `GET/PUT /api/settings/email`, `POST /api/settings/email/test` (Tasks 2, 5).
- Produces: `EmailSettings` / `EmailTestResult` types, `emailSettingsQueryKey`, `useEmailSettings`, `useSaveEmailSettings`, `useTestEmailSettings`, `EmailSettingsForm` component.

- [ ] **Step 1: Write the failing frontend tests**

Add to `frontend/tests/fixtures.ts`:

```ts
export const emailSettingsFixture: EmailSettings = {
  enabled: false,
  recipient: null,
  smtp_host: null,
  smtp_port: 465,
  smtp_security: "ssl",
  smtp_username: null,
  from_address: null,
  password_masked: null,
  updated_at: "2026-07-15T08:00:00Z",
};
```

(Add the `EmailSettings` import to the fixture file's type imports.)

Create `frontend/tests/EmailSettingsForm.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { EmailSettingsForm } from "../src/features/settings/EmailSettingsForm";
import { emailSettingsFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function handlers() {
  return [
    http.get("/api/settings/email", () => HttpResponse.json(emailSettingsFixture)),
  ];
}

it("renders the email notification form and saves the payload", async () => {
  let received: Record<string, unknown> | null = null;
  renderWithProviders(<EmailSettingsForm />, {
    handlers: [
      ...handlers(),
      http.put("/api/settings/email", async ({ request }) => {
        received = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          ...emailSettingsFixture,
          enabled: true,
          recipient: "owner@example.com",
          smtp_host: "smtp.qq.com",
          smtp_username: "owner@qq.com",
          password_masked: "****ode",
        });
      }),
    ],
  });
  const user = userEvent.setup();

  await screen.findByLabelText("收件人");
  await user.click(screen.getByRole("checkbox", { name: "启用每日邮件" }));
  await user.type(screen.getByLabelText("收件人"), "owner@example.com");
  await user.type(screen.getByLabelText("SMTP 服务器"), "smtp.qq.com");
  await user.type(screen.getByLabelText("账号"), "owner@qq.com");
  await user.type(screen.getByLabelText("授权码"), "smtp-auth-code");
  await user.click(screen.getByRole("button", { name: "保存邮件设置" }));

  expect(received).toMatchObject({
    enabled: true,
    recipient: "owner@example.com",
    smtp_host: "smtp.qq.com",
    smtp_username: "owner@qq.com",
    password: "smtp-auth-code",
  });
});

it("sends a test email and shows the result", async () => {
  renderWithProviders(<EmailSettingsForm />, {
    handlers: [
      ...handlers(),
      http.post("/api/settings/email/test", () => HttpResponse.json({ status: "ok", error_category: null })),
    ],
  });
  const user = userEvent.setup();

  await screen.findByRole("heading", { name: "邮件通知" });
  await user.click(screen.getByRole("button", { name: "发送测试邮件" }));

  expect(await screen.findByText("测试邮件已发送")).toBeInTheDocument();
});
```

In `frontend/tests/MarketDataPage.test.tsx`, add the email handler to `pageHandlers()`:

```ts
http.get("/api/settings/email", () => HttpResponse.json(emailSettingsFixture)),
```

and add `emailSettingsFixture` to the existing fixture imports.

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `cd frontend && npm test -- EmailSettingsForm MarketDataPage`

Expected: FAIL - `EmailSettingsForm` module does not exist / `EmailSettings` type missing.

- [ ] **Step 3: Add the types**

In `frontend/src/api/types.ts`, add after the `RebalanceDefaults` interface:

```ts
export type EmailSecurity = "ssl" | "starttls";

export interface EmailSettings {
  enabled: boolean;
  recipient: string | null;
  smtp_host: string | null;
  smtp_port: number;
  smtp_security: EmailSecurity;
  smtp_username: string | null;
  from_address: string | null;
  password_masked: string | null;
  updated_at: string;
}

export interface EmailTestResult {
  status: "ok" | "failed";
  error_category:
    | "not_configured"
    | "smtp_connect_failed"
    | "smtp_auth_failed"
    | "smtp_recipient_rejected"
    | "smtp_timeout"
    | "smtp_send_failed"
    | null;
}
```

- [ ] **Step 4: Add the query hooks**

In `frontend/src/features/settings/api.ts`, extend the imports and add:

```ts
import type { EmailSettings, EmailTestResult } from "../../api/types";

export const emailSettingsQueryKey = ["settings", "email"] as const;

export function useEmailSettings() {
  return useQuery({
    queryKey: emailSettingsQueryKey,
    queryFn: () => apiRequest<EmailSettings>("/api/settings/email"),
  });
}

export function useSaveEmailSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Omit<EmailSettings, "password_masked" | "updated_at"> & { password: string | null }) =>
      apiRequest<EmailSettings>("/api/settings/email", { method: "PUT", body: jsonBody(payload) }),
    onSuccess: (saved) => queryClient.setQueryData(emailSettingsQueryKey, saved),
  });
}

export function useTestEmailSettings() {
  return useMutation({
    mutationFn: () => apiRequest<EmailTestResult>("/api/settings/email/test", { method: "POST" }),
  });
}
```

- [ ] **Step 5: Create the EmailSettingsForm component**

Create `frontend/src/features/settings/EmailSettingsForm.tsx`:

```tsx
import { Mail, Save, Send } from "lucide-react";
import { useEffect, useState } from "react";

import type { EmailSecurity, EmailTestResult } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { useEmailSettings, useSaveEmailSettings, useTestEmailSettings } from "./api";
import styles from "../marketData/MarketData.module.css";

const TEST_ERROR_LABELS: Record<string, string> = {
  not_configured: "邮件尚未配置完整",
  smtp_connect_failed: "无法连接 SMTP 服务器",
  smtp_auth_failed: "SMTP 认证失败，请检查账号和授权码",
  smtp_recipient_rejected: "收件人被邮件服务器拒绝",
  smtp_timeout: "SMTP 连接超时",
  smtp_send_failed: "邮件发送失败",
};

export function EmailSettingsForm() {
  const settings = useEmailSettings();
  const save = useSaveEmailSettings();
  const test = useTestEmailSettings();
  const [enabled, setEnabled] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("465");
  const [security, setSecurity] = useState<EmailSecurity>("ssl");
  const [username, setUsername] = useState("");
  const [fromAddress, setFromAddress] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (!settings.data) return;
    setEnabled(settings.data.enabled);
    setRecipient(settings.data.recipient ?? "");
    setHost(settings.data.smtp_host ?? "");
    setPort(String(settings.data.smtp_port));
    setSecurity(settings.data.smtp_security);
    setUsername(settings.data.smtp_username ?? "");
    setFromAddress(settings.data.from_address ?? "");
  }, [settings.data?.updated_at]);

  async function submit() {
    await save.mutateAsync({
      enabled,
      recipient,
      smtp_host: host,
      smtp_port: Number(port),
      smtp_security: security,
      smtp_username: username,
      from_address: fromAddress || null,
      password: password || null,
    });
    setPassword("");
  }

  function testLabel(result: EmailTestResult) {
    return TEST_ERROR_LABELS[result.error_category ?? ""] ?? "测试邮件发送失败";
  }

  return (
    <section className={styles.generalSettings} aria-labelledby="email-settings-title">
      <header className={styles.sectionHeading}>
        <div><p>EMAIL NOTIFICATION</p><h2 id="email-settings-title">邮件通知</h2></div>
        <label className={styles.enabled}><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />启用每日邮件</label>
      </header>
      {settings.isPending ? <p className={styles.muted}>正在载入邮件设置...</p> : null}
      {settings.isError ? <p className={styles.error} role="alert">邮件设置加载失败。</p> : null}
      {settings.data ? <div className={styles.generalGrid}>
        <FormField label="收件人"><input type="email" value={recipient} onChange={(event) => setRecipient(event.target.value)} /></FormField>
        <FormField label="SMTP 服务器"><input value={host} onChange={(event) => setHost(event.target.value)} /></FormField>
        <FormField label="端口"><input inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value)} /></FormField>
        <FormField label="安全方式"><select value={security} onChange={(event) => setSecurity(event.target.value as EmailSecurity)}><option value="ssl">SSL</option><option value="starttls">STARTTLS</option></select></FormField>
        <FormField label="账号"><input value={username} onChange={(event) => setUsername(event.target.value)} /></FormField>
        <FormField label="授权码"><input type="password" autoComplete="new-password" value={password} placeholder={settings.data.password_masked ?? "输入授权码"} onChange={(event) => setPassword(event.target.value)} /></FormField>
        <FormField label="发件人（可选）"><input type="email" value={fromAddress} onChange={(event) => setFromAddress(event.target.value)} /></FormField>
      </div> : null}
      <div className={styles.providerActions}>
        <button type="button" className={styles.secondary} onClick={() => void test.mutateAsync()} disabled={test.isPending || save.isPending}><Send size={15} aria-hidden="true" />{test.isPending ? "正在发送" : "发送测试邮件"}</button>
        <button type="button" className={styles.primary} onClick={() => void submit()} disabled={save.isPending}><Save size={16} aria-hidden="true" />保存邮件设置</button>
      </div>
      {test.data ? <small className={test.data.status === "ok" ? styles.validationGood : styles.validationBad}>{test.data.status === "ok" ? "测试邮件已发送" : testLabel(test.data)}</small> : null}
      {save.isError ? <small className={styles.validationBad}>{save.error instanceof Error ? save.error.message : "邮件设置保存失败。"}</small> : null}
      <small className={styles.muted}><Mail size={12} aria-hidden="true" /> 每日刷新完成后，在工作日自动发送盈亏分析与再平衡建议邮件。</small>
    </section>
  );
}
```

- [ ] **Step 6: Wire the form into ProviderSettings**

In `frontend/src/features/settings/ProviderSettings.tsx`, add the import:

```tsx
import { EmailSettingsForm } from "./EmailSettingsForm";
```

and render it after `GeneralSettingsForm`:

```tsx
      {general.data ? <GeneralSettingsForm value={general.data} key={general.data.updated_at} /> : null}
      <EmailSettingsForm />
```

- [ ] **Step 7: Run the frontend tests to verify they pass**

Run: `cd frontend && npm test -- --run`

Expected: PASS (new tests plus existing suites).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/features/settings/api.ts frontend/src/features/settings/EmailSettingsForm.tsx frontend/src/features/settings/ProviderSettings.tsx frontend/tests/fixtures.ts frontend/tests/MarketDataPage.test.tsx frontend/tests/EmailSettingsForm.test.tsx
git commit -m "feat: email notification settings form"
```

---

## Final Verification

- [ ] Run `make test-backend` (full backend suite in the isolated Compose project).
- [ ] Run `make test-frontend` (full vitest suite).
- [ ] Run `docker compose build` to confirm both images build.
- [ ] Run `docker compose up -d` and check `docker compose logs worker` shows no errors after the scheduled run (or verify via a manually triggered digest test).
- [ ] Confirm `git status` is clean and all commits are pushed when the user asks.
