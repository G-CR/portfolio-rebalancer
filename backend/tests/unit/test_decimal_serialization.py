from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import DecimalString


class Payload(BaseModel):
    value: DecimalString


def test_decimal_is_serialized_as_string() -> None:
    payload = Payload(value=Decimal("7.075000"))

    assert payload.model_dump(mode="json") == {"value": "7.075000"}
