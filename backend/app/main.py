from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.db.session import engine
from app.db.session import SessionFactory
from app.services.asset_classes import seed_default_strategy


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        async with SessionFactory() as session:
            async with session.begin():
                await seed_default_strategy(session)
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Portfolio Rebalancer", version="1.0.0", lifespan=lifespan)
app.include_router(api_router)
