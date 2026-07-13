from pydantic import BaseModel, ConfigDict

from app.schemas.common import DecimalString


class PositionAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    cost_cny: DecimalString
    market_value_cny: DecimalString
    fx_neutral_value_cny: DecimalString
    unrealized_pnl: DecimalString
    unrealized_return: DecimalString
    price_effect: DecimalString
    fx_effect: DecimalString
