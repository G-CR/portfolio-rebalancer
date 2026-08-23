from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app.backups.constants import CURRENT_FORMAT_VERSION


class BackupMigrationError(Exception):
    """A sanitized backup-version migration failure."""


class MissingMigrationPath(BackupMigrationError):
    pass


class ArchiveLike(Protocol):
    path: Path

    @property
    def format_version(self) -> int: ...


@dataclass(frozen=True, slots=True)
class MigratedArchive:
    source: ArchiveLike
    format_version: int

    @property
    def path(self) -> Path:
        return self.source.path


Migration = Callable[[ArchiveLike], MigratedArchive]


def _identity_v1(archive: ArchiveLike) -> MigratedArchive:
    return MigratedArchive(source=archive, format_version=CURRENT_FORMAT_VERSION)


MIGRATIONS: dict[int, Migration] = {1: _identity_v1}


def require_migration_path(source_version: int) -> None:
    if source_version not in MIGRATIONS:
        raise MissingMigrationPath("no supported migration path for backup format")


def migrate_to_current(archive: ArchiveLike) -> MigratedArchive:
    require_migration_path(archive.format_version)
    return MIGRATIONS[archive.format_version](archive)
