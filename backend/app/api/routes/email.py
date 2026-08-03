from fastapi import APIRouter

from app.schemas.email_settings import EmailDigestTriggerResult
from app.services.email_digest import run_manual_digest

router = APIRouter(prefix="/email", tags=["email"])


@router.post("/digest", response_model=EmailDigestTriggerResult)
async def post_email_digest() -> EmailDigestTriggerResult:
    return await run_manual_digest()
