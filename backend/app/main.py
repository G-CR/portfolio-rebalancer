from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0]
    field = str(first_error.get("ctx", {}).get("field") or first_error["loc"][-1])

    if first_error["type"] == "negative_numeric_field":
        detail = {
            "code": "NEGATIVE_NUMERIC_FIELD",
            "message": "Numeric request fields must be non-negative.",
            "field": field,
        }
    else:
        detail = {
            "code": "INVALID_REQUEST",
            "message": first_error["msg"],
            "field": field,
        }

    return JSONResponse(status_code=422, content={"detail": detail})


app.include_router(api_router)
