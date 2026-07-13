from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.schemas.common import DecimalString


class AssetClassResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    name: str
    target_weight: DecimalString
    display_order: int
    notes: str | None
    is_active: bool

    @field_serializer("target_weight")
    def serialize_target_weight(self, value) -> str:
        return format(value.quantize(type(value)("0.00000001")), "f")


class AssetClassUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: UUID
    name: str
    target_weight: DecimalString
    display_order: int
    notes: str | None = None
    is_active: bool = True
