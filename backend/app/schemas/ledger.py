from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.decimal import fits_numeric_28_12


class OpeningRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=128)
    preview_token: str | None = None


class EntryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    holding_id: UUID
    kind: Literal['purchase', 'sale', 'dividend', 'split', 'manual_correction']
    occurred_on: date
    quantity: Decimal = Decimal(0)
    price: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)
    fee: Decimal = Decimal(0)
    fee_currency: str | None = Field(default=None, max_length=8)
    currency: str | None = Field(default=None, max_length=8)
    ratio: Decimal = Decimal(1)
    gross_amount: Decimal | None = None
    tax: Decimal | None = None
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    preview_token: str | None = None
    replaces_id: UUID | None = None
    linked_entry_id: UUID | None = None

    @field_validator('currency', 'fee_currency')
    @classmethod
    def currency_code(cls, value):
        if value is None:
            return None
        value = value.upper()
        if not re.fullmatch('[A-Z]{3}', value):
            raise ValueError('币种必须为三位大写字母代码。')
        return value

    @field_validator('quantity', 'price', 'amount', 'fee', 'ratio', 'gross_amount', 'tax')
    @classmethod
    def numeric(cls, value):
        if value is not None and (not fits_numeric_28_12(value) or value < 0):
            raise ValueError('数值必须非负且符合 NUMERIC(28,12)。')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.kind in {'purchase', 'sale'} and (self.quantity <= 0 or self.price <= 0):
            raise ValueError('交易份额和价格必须为正。')
        if self.kind == 'split' and self.ratio <= 0:
            raise ValueError('折算比例必须为正。')
        if self.kind == 'manual_correction' and not self.note:
            raise ValueError('人工修正需要原因。')
        if self.kind == 'dividend' and (self.gross_amount is not None or self.tax is not None):
            if self.gross_amount is None or self.tax is None or self.gross_amount - self.tax != self.amount:
                raise ValueError('税前金额减扣税必须等于净到账金额。')
        if self.replaces_id and not self.note:
            raise ValueError('更正流水需要原因。')
        return self
