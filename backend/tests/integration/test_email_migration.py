import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import Setting


MIGRATION_TEST_ENGINE = create_async_engine(
    os.environ["DATABASE_URL"],
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
        assert "ck_settings_ck_settings_email_smtp_security" in after_upgrade["constraints"]

        await _run_alembic_downgrade("20260715_0007")
        after_downgrade = await _email_settings_migration_state()
        assert EXPECTED_EMAIL_COLUMNS.isdisjoint(after_downgrade["columns"])
        assert "ck_settings_ck_settings_email_smtp_security" not in after_downgrade["constraints"]

        await _run_alembic_upgrade("head")
    finally:
        await _run_alembic_upgrade("head")


@pytest.mark.asyncio
async def test_settings_email_columns_default_and_round_trip(api_client, db_session) -> None:
    await api_client.get("/api/health")
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
