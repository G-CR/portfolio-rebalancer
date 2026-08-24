import os
from pathlib import Path
import shutil
import tempfile
from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.database_safety import require_safe_test_database, require_safe_test_environment

BUSINESS_TABLES = (
    "snapshot_items",
    "cost_adjustments",
    "holding_defaults",
    "market_data_overrides",
    "market_data",
    "rebalance_plans",
    "encrypted_secrets",
    "settings",
    "snapshots",
    "holdings",
    "asset_classes",
)

require_safe_test_environment(os.environ)
DATABASE_URL = require_safe_test_database(
    os.getenv("DATABASE_URL"),
    os.getenv("PYTEST_DATABASE_RESET_TOKEN"),
)
TEST_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix="portfolio-test-backups-"))
os.environ["BACKUP_ROOT"] = str(TEST_BACKUP_ROOT)

from app.main import app  # noqa: E402
from app.db.session import engine as app_engine  # noqa: E402

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_test_engine() -> AsyncIterator[None]:
    yield
    await engine.dispose()
    shutil.rmtree(TEST_BACKUP_ROOT, ignore_errors=True)


async def _truncate_business_tables(session: AsyncSession) -> None:
    rows = await session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    existing_tables = {row[0] for row in rows}
    tables_to_truncate = [table for table in BUSINESS_TABLES if table in existing_tables]

    if not tables_to_truncate:
        return

    await session.execute(text(f"TRUNCATE TABLE {', '.join(tables_to_truncate)} CASCADE"))
    await session.commit()


@pytest_asyncio.fixture
async def _reset_database() -> AsyncIterator[None]:
    async with SessionFactory() as session:
        await _truncate_business_tables(session)

    yield

    async with SessionFactory() as session:
        await _truncate_business_tables(session)


@pytest_asyncio.fixture
async def db_session(_reset_database: None) -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


@pytest_asyncio.fixture
async def api_client(_reset_database: None) -> AsyncIterator[AsyncClient]:
    shutil.rmtree(TEST_BACKUP_ROOT, ignore_errors=True)
    TEST_BACKUP_ROOT.mkdir(mode=0o700)
    await app_engine.dispose()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=os.getenv("API_BASE_URL", "http://testserver"),
        ) as client:
            yield client
