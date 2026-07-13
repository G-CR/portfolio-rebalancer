from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.analytics import PortfolioAnalyticsResponse
from app.services.analytics import get_portfolio_analytics
from app.services.errors import ServiceError

router = APIRouter(tags=["analytics"])


@router.get("/analytics/portfolio", response_model=PortfolioAnalyticsResponse)
async def get_portfolio(
    session: AsyncSession = Depends(get_session),
) -> PortfolioAnalyticsResponse:
    try:
        return await get_portfolio_analytics(session)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
