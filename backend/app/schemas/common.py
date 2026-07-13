from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

DecimalString = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]
