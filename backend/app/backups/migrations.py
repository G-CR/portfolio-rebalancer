from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from app.backups.constants import CURRENT_FORMAT_VERSION, NEW_TABLE_MEMBERS


class BackupMigrationError(Exception):
    """A sanitized backup-version migration failure."""


class MissingMigrationPath(BackupMigrationError):
    pass


class ArchiveLike(Protocol):
    path: Path

    @property
    def format_version(self) -> int: ...

    def iter_source_rows(self, member: str) -> Iterator[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class MigratedArchive:
    source: ArchiveLike
    format_version: int
    transforms: tuple[Callable[[str, dict[str, Any]], dict[str, Any]], ...] = ()

    @property
    def path(self) -> Path:
        return self.source.path

    def iter_rows(self, member: str) -> Iterator[dict[str, Any]]:
        if self.source.format_version == 1 and member in NEW_TABLE_MEMBERS:
            return
        for source_row in self.source.iter_source_rows(member):
            row = source_row
            for transform in self.transforms:
                row = transform(member, row)
            yield row


Migration = Callable[[str, dict[str, Any]], dict[str, Any]]


# Each entry upgrades exactly one version.  Current-version archives need no
# transform; older versions are streamed through these ordered row transforms.
MIGRATIONS: dict[int, Migration] = {1: lambda member, row: row}


def require_migration_path(source_version: int) -> None:
    version = source_version
    while version < CURRENT_FORMAT_VERSION:
        if version not in MIGRATIONS:
            raise MissingMigrationPath("no supported migration path for backup format")
        version += 1
    if version != CURRENT_FORMAT_VERSION:
        raise MissingMigrationPath("no supported migration path for backup format")


def migrate_to_current(archive: ArchiveLike) -> MigratedArchive:
    require_migration_path(archive.format_version)
    transforms = tuple(MIGRATIONS[version] for version in range(archive.format_version, CURRENT_FORMAT_VERSION))
    return MigratedArchive(source=archive, format_version=CURRENT_FORMAT_VERSION, transforms=transforms)
