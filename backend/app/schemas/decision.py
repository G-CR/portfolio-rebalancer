from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class DecisionSettingsUpdate(BaseModel):
    review_day: int = Field(ge=1, le=31)
    notification_mode: Literal['daily', 'attention']
    monthly_email: bool

class DecisionSettingsResponse(DecisionSettingsUpdate):
    model_config = ConfigDict(from_attributes=True)
    last_checked_at: datetime | None
    last_reviewed_at: datetime | None

class DecisionClass(BaseModel):
    id: str
    name: str
    target_weight: str
    actual_weight: str
    drift: str
    direction: int
    observations: int

class DecisionResponse(BaseModel):
    status: Literal['setup', 'data_issue', 'in_progress', 'sustained', 'observing', 'normal']
    title: str
    reason: str
    classes: list[DecisionClass]
    issues: list[dict]
    has_manual_data: bool
    latest_valid_date: date | None
    last_checked_at: datetime | None
    active_plan_id: str | None
    review_date: date
    review_due: bool
    last_reviewed_at: datetime | None
