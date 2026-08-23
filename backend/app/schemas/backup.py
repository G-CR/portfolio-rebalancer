from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


OperationKind = Literal["export", "restore"]
OperationStatus = Literal["pending", "running", "succeeded", "failed", "interrupted"]


class BackupStage(StrEnum):
    VALIDATED = "validated"
    LOCKING_DATA = "locking_data"
    CREATING_SAFETY_BACKUP = "creating_safety_backup"
    WRITING_DATA = "writing_data"
    VERIFYING_INTEGRITY = "verifying_integrity"
    COMPLETED = "completed"


class BackupError(BaseModel):
    code: str
    message: str


class BackupOperationResponse(BaseModel):
    id: UUID
    kind: OperationKind
    status: OperationStatus
    stage: BackupStage
    error: BackupError | None = None
    download_ready: bool = False


class BackupOperation(BackupOperationResponse):
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    @classmethod
    def new(
        cls,
        kind: OperationKind,
        *,
        now: datetime | None = None,
        operation_id: UUID | None = None,
    ) -> BackupOperation:
        timestamp = now or datetime.now(timezone.utc)
        return cls(
            id=operation_id or uuid4(),
            kind=kind,
            status="pending",
            stage=BackupStage.VALIDATED,
            created_at=timestamp,
            updated_at=timestamp,
        )


class SafetyBackupResponse(BaseModel):
    id: UUID
    exported_at: datetime
    source_application_version: str
    format_version: int
    size_bytes: int = Field(ge=0)
    record_counts: dict[str, int]


class BackupCountComparison(BaseModel):
    backup: int = Field(ge=0)
    current: int = Field(ge=0)
    delta: int


class BackupPreviewResponse(BaseModel):
    exported_at: datetime
    source_application_version: str
    source_format_version: int = Field(ge=0)
    current_format_version: int = Field(ge=0)
    record_counts: dict[str, int]
    current_record_counts: dict[str, int]
    count_comparison: dict[str, BackupCountComparison]
    warnings: list[str]
    credential_categories: list[str]
    restore_token: str
    expires_at: datetime
