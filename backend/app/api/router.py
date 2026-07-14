from fastapi import APIRouter

from app.api.routes.analytics import router as analytics_router
from app.api.routes.asset_classes import router as asset_classes_router
from app.api.routes.cost_adjustments import router as cost_adjustments_router
from app.api.routes.health import router as health_router
from app.api.routes.holdings import router as holdings_router
from app.api.routes.market_data import router as market_data_router
from app.api.routes.rebalance import router as rebalance_router
from app.api.routes.settings import router as settings_router
from app.api.routes.snapshots import router as snapshots_router

api_router = APIRouter(prefix="/api")
api_router.include_router(analytics_router)
api_router.include_router(asset_classes_router)
api_router.include_router(cost_adjustments_router)
api_router.include_router(health_router)
api_router.include_router(holdings_router)
api_router.include_router(market_data_router)
api_router.include_router(rebalance_router)
api_router.include_router(settings_router)
api_router.include_router(snapshots_router)
