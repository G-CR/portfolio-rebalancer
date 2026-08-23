from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import (
    request_validation_exception_handler as fastapi_request_validation_exception_handler,
)
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import engine
from app.db.session import SessionFactory
from app.services.asset_classes import seed_default_strategy
from app.services.backup_operations import BackupOperationManager
from app.services.backup_storage import BackupStorage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    storage = BackupStorage(
        settings.backup_root,
        export_ttl=timedelta(seconds=settings.backup_export_ttl_seconds),
        upload_ttl=timedelta(seconds=settings.backup_upload_ttl_seconds),
        safety_retention=settings.backup_safety_retention,
    )
    manager = BackupOperationManager(storage)
    try:
        storage.initialize()
        manager.recover()
        manager.start_cleanup()
        app.state.backup_storage = storage
        app.state.backup_operation_manager = manager
        async with SessionFactory() as session:
            async with session.begin():
                await seed_default_strategy(session)
        yield
    finally:
        await manager.stop()
        await engine.dispose()


app = FastAPI(title="Portfolio Rebalancer", version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0]
    holding_validation_errors = {
        "holding_market_invalid": (
            "HOLDING_MARKET_INVALID",
            "Market must be one of US, SH, or SZ.",
        ),
        "holding_trade_currency_invalid": (
            "HOLDING_TRADE_CURRENCY_INVALID",
            "Trade currency must be exactly three ASCII letters.",
        ),
        "holding_lot_size_invalid": (
            "HOLDING_LOT_SIZE_INVALID",
            "Lot size must be positive.",
        ),
        "holding_quantity_precision_invalid": (
            "HOLDING_QUANTITY_PRECISION_INVALID",
            "Quantity precision must be between 0 and 12.",
        ),
    }
    if first_error["type"] in holding_validation_errors:
        code, message = holding_validation_errors[first_error["type"]]
        field = str(first_error.get("ctx", {}).get("field") or first_error["loc"][-1])
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": code, "message": message, "field": field}},
        )

    market_data_validation_errors = {
        "market_data_value_invalid": (
            "MARKET_DATA_OVERRIDE_VALUE_INVALID",
            "Market-data values must be positive and finite.",
        ),
        "market_data_numeric_out_of_range": (
            "MARKET_DATA_NUMERIC_OUT_OF_RANGE",
            "Market-data values must fit NUMERIC(28,12).",
        ),
    }
    if first_error["type"] in market_data_validation_errors:
        code, message = market_data_validation_errors[first_error["type"]]
        field = str(first_error.get("ctx", {}).get("field") or first_error["loc"][-1])
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": code, "message": message, "field": field}},
        )

    if first_error["type"] == "cost_adjustment_numeric_out_of_range":
        field = str(first_error.get("ctx", {}).get("field") or first_error["loc"][-1])
        detail = {
            "code": "COST_ADJUSTMENT_NUMERIC_OUT_OF_RANGE",
            "message": "Cost adjustment numeric fields must fit NUMERIC(28,12).",
            "field": field,
        }
        return JSONResponse(status_code=422, content={"detail": detail})

    if first_error["type"] != "negative_numeric_field":
        return await fastapi_request_validation_exception_handler(_, exc)

    field = str(first_error.get("ctx", {}).get("field") or first_error["loc"][-1])
    detail = {
        "code": "NEGATIVE_NUMERIC_FIELD",
        "message": "Numeric request fields must be non-negative.",
        "field": field,
    }

    return JSONResponse(status_code=422, content={"detail": detail})


app.include_router(api_router)
