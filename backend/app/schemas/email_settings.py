from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

EmailSecurity = Literal["ssl", "starttls"]


def _validate_address(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    _display, address = parseaddr(stripped)
    if (
        address != stripped
        or "@" not in address
        or address.startswith("@")
        or address.endswith("@")
    ):
        raise PydanticCustomError(
            "settings_email_invalid",
            "{field} must be a valid email address.",
            {"field": field_name},
        )
    return stripped


class EmailSettingsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    enabled: bool
    recipient: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_security: EmailSecurity = "ssl"
    smtp_username: str | None = None
    from_address: str | None = None
    password: str | None = Field(default=None, max_length=512)

    @field_validator("recipient", "from_address")
    @classmethod
    def validate_email_fields(cls, value: str | None, info) -> str | None:
        return _validate_address(value, info.field_name)

    @model_validator(mode="after")
    def require_complete_config_when_enabled(self) -> "EmailSettingsUpdate":
        if self.enabled:
            for field_name in ("recipient", "smtp_host", "smtp_username"):
                if not getattr(self, field_name):
                    raise PydanticCustomError(
                        "settings_email_incomplete",
                        "Recipient, SMTP host and username are required when email is enabled.",
                        {"field": field_name},
                    )
        return self


class EmailSettingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    recipient: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_security: EmailSecurity
    smtp_username: str | None
    from_address: str | None
    password_masked: str | None
    updated_at: datetime


class EmailTestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "failed"]
    error_category: Literal[
        "not_configured",
        "smtp_connect_failed",
        "smtp_auth_failed",
        "smtp_recipient_rejected",
        "smtp_timeout",
        "smtp_send_failed",
    ] | None
