from fastapi import APIRouter

from app.api.routes.asset_classes import router as asset_classes_router
from app.api.routes.health import router as health_router
from app.api.routes.holdings import router as holdings_router

api_router = APIRouter(prefix="/api")
api_router.include_router(asset_classes_router)
api_router.include_router(health_router)
api_router.include_router(holdings_router)
