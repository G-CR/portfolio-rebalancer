import os
from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.main import app

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

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio",
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


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
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=os.getenv("API_BASE_URL", "http://testserver"),
    ) as client:
        yield client
