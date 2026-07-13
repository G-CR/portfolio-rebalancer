from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ServiceError(Exception):
    status_code: int
    code: str
    message: str
    extra: dict[str, object] = field(default_factory=dict)

    def to_detail(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, **self.extra}
