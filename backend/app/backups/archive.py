from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

import ijson

from app.backups.canonical import (
    JsonValue,
    canonical_json_bytes,
    canonical_parsed_json_bytes,
    encode_json_value,
)
from app.backups.constants import (
    ALLOWED_MEMBERS,
    CURRENT_FORMAT_VERSION,
    DATA_MEMBERS,
    MANIFEST_MEMBER,
    MAX_AGGREGATE_COMPRESSION_RATIO,
    MAX_COMPRESSED_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_LOGICAL_ROW_BYTES,
    MAX_UNCOMPRESSED_BYTES,
    STREAM_CHUNK_BYTES,
    ROW_SCAN_CHUNK_BYTES,
)
from app.backups.contracts import CONTRACTS_BY_MEMBER, Codec, TableContract
from app.backups.migrations import (
    BackupMigrationError,
    MigratedArchive,
    migrate_to_current,
    require_migration_path,
)


class BackupArchiveError(Exception):
    """Base class for sanitized logical-backup errors."""


class InvalidBackupArchive(BackupArchiveError):
    pass


class ArchiveLimitExceeded(InvalidBackupArchive):
    pass


class InvalidBackupDocument(BackupArchiveError):
    pass


class UnsupportedBackupVersion(BackupArchiveError):
    pass


_VERIFIED_ARCHIVE_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ArchiveMetadata:
    source_application_version: str
    exported_at: datetime
    display_timezone: str

    def __post_init__(self) -> None:
        if not self.source_application_version:
            raise ValueError("source application version is required")
        if not self.display_timezone:
            raise ValueError("display timezone is required")
        if self.exported_at.tzinfo is None or self.exported_at.utcoffset() is None:
            raise ValueError("exported_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MemberDigest:
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BackupManifest:
    format_version: int
    source_application_version: str
    exported_at: str
    display_timezone: str
    contains_plaintext_credentials: bool
    record_counts: dict[str, int]
    members: dict[str, MemberDigest]
    logical_checksum: str


@dataclass(frozen=True, slots=True)
class ArchiveSummary:
    format_version: int
    record_counts: dict[str, int]
    logical_checksum: str
    compressed_size: int


@dataclass(frozen=True, slots=True)
class InspectedArchive:
    path: Path
    manifest: BackupManifest
    archive_sha256: str
    compressed_size: int
    _snapshot: BinaryIO
    _zip: ZipFile
    _verification_token: object

    @property
    def format_version(self) -> int:
        return self.manifest.format_version

    def close(self) -> None:
        try:
            self._zip.close()
        finally:
            self._snapshot.close()

    def __enter__(self) -> InspectedArchive:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def iter_source_rows(self, member: str) -> Iterator[dict[str, Any]]:
        if member not in DATA_MEMBERS or self._verification_token is not _VERIFIED_ARCHIVE_TOKEN:
            raise InvalidBackupDocument("archive verification handle is invalid")
        info = self._zip.getinfo(member)
        try:
            with self._zip.open(info) as raw:
                bounded = _BoundedRows(raw)
                for item in ijson.items(bounded, "item"):
                    if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
                        raise InvalidBackupDocument("backup collection item must be an object")
                    _validate_json_tree(item)
                    yield item
        except (ArchiveLimitExceeded, InvalidBackupDocument):
            raise
        except (ijson.JSONError, UnicodeDecodeError, BadZipFile, OSError, RuntimeError):
            raise InvalidBackupDocument("backup collection JSON is malformed") from None


class _BoundedRows:
    """Incrementally reject oversized top-level array items before JSON materialization."""

    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.started = False
        self.in_row = False
        self.in_string = False
        self.escaped = False
        self.depth = 0
        self.row_bytes = 0

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        requested = ROW_SCAN_CHUNK_BYTES if size < 0 else min(size, ROW_SCAN_CHUNK_BYTES)
        chunk = self.source.read(requested)
        self._scan(chunk)
        return chunk

    def _scan(self, chunk: bytes) -> None:
        for byte in chunk:
            if not self.started:
                if chr(byte).isspace():
                    continue
                if byte != ord("["):
                    raise InvalidBackupDocument("backup collection must be a JSON array")
                self.started = True
                continue
            if not self.in_row:
                if chr(byte).isspace() or byte in (ord(","), ord("]")):
                    continue
                if byte != ord("{"):
                    raise InvalidBackupDocument("backup collection item must be an object")
                self.in_row = True
                self.depth = 1
                self.row_bytes = 1
                continue
            self.row_bytes += 1
            if self.row_bytes > MAX_LOGICAL_ROW_BYTES:
                raise ArchiveLimitExceeded("backup row exceeds the resource limit")
            if self.in_string:
                if self.escaped:
                    self.escaped = False
                elif byte == ord("\\"):
                    self.escaped = True
                elif byte == ord('"'):
                    self.in_string = False
                continue
            if byte == ord('"'):
                self.in_string = True
            elif byte in (ord("{"), ord("[")):
                self.depth += 1
            elif byte in (ord("}"), ord("]")):
                self.depth -= 1
                if self.depth == 0:
                    self.in_row = False


def _zip_info(member: str) -> ZipInfo:
    info = ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _open_row_store(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
        """
        CREATE TABLE rows (
            member TEXT NOT NULL,
            order_key TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (member, order_key)
        ) WITHOUT ROWID
        """
        )
        return connection
    except Exception:
        connection.close()
        raise


def _validate_json_tree(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise InvalidBackupDocument("invalid JSON value")
        return
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidBackupDocument("invalid JSON value")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_tree(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json_tree(item)
        return
    raise InvalidBackupDocument("invalid JSON value")


def _validate_field(value: object, codec: Codec) -> None:
    if codec is Codec.STRING:
        if not isinstance(value, str):
            raise InvalidBackupDocument("backup field has invalid type")
    elif codec is Codec.UUID:
        if not isinstance(value, str):
            raise InvalidBackupDocument("backup UUID has invalid type")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise InvalidBackupDocument("backup UUID is invalid") from exc
        if str(parsed) != value:
            raise InvalidBackupDocument("backup UUID is not canonical")
    elif codec is Codec.DECIMAL:
        if not isinstance(value, str):
            raise InvalidBackupDocument("backup decimal must be a string")
        try:
            parsed_decimal = Decimal(value)
        except InvalidOperation as exc:
            raise InvalidBackupDocument("backup decimal is invalid") from exc
        if not parsed_decimal.is_finite() or format(parsed_decimal, "f") != value:
            raise InvalidBackupDocument("backup decimal is not canonical")
    elif codec is Codec.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidBackupDocument("backup integer is invalid")
    elif codec is Codec.BOOLEAN:
        if not isinstance(value, bool):
            raise InvalidBackupDocument("backup boolean is invalid")
    elif codec is Codec.DATE:
        if not isinstance(value, str):
            raise InvalidBackupDocument("backup date is invalid")
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise InvalidBackupDocument("backup date is invalid") from exc
        if parsed_date.isoformat() != value:
            raise InvalidBackupDocument("backup date is not canonical")
    elif codec is Codec.DATETIME:
        if not isinstance(value, str):
            raise InvalidBackupDocument("backup datetime is invalid")
        try:
            parsed_datetime = datetime.fromisoformat(value)
        except ValueError as exc:
            raise InvalidBackupDocument("backup datetime is invalid") from exc
        if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
            raise InvalidBackupDocument("backup datetime must be timezone-aware")
        if parsed_datetime.isoformat() != value:
            raise InvalidBackupDocument("backup datetime is not canonical")
        if parsed_datetime.utcoffset() != timedelta(0):
            raise InvalidBackupDocument("backup datetime must use canonical UTC")
    elif codec is Codec.JSON:
        _validate_json_tree(value)


def _validate_row(member: str, row: object) -> dict[str, JsonValue]:
    if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
        raise InvalidBackupDocument("backup collection item must be an object")
    contract = CONTRACTS_BY_MEMBER[member]
    if set(row) != set(contract.columns):
        raise InvalidBackupDocument("backup row fields do not match the versioned contract")
    for column, field_codec in zip(contract.columns, contract.codecs, strict=True):
        value = row[column]
        if value is None:
            if not field_codec.nullable:
                raise InvalidBackupDocument("required backup field is null")
            continue
        _validate_field(value, field_codec.codec)
    return row


def _encoded_source_row(contract: TableContract, row: Mapping[str, object]) -> dict[str, JsonValue]:
    try:
        encoded = encode_json_value(dict(row))
    except (TypeError, ValueError) as exc:
        raise InvalidBackupDocument("source row contains an unsupported value") from exc
    return _validate_row(contract.member, encoded)


def _insert_row(
    connection: sqlite3.Connection,
    contract: TableContract,
    row: dict[str, JsonValue],
) -> None:
    order_key = row[contract.order_key]
    if order_key is None:
        raise InvalidBackupDocument("backup order key is null")
    try:
        connection.execute(
            "INSERT INTO rows(member, order_key, payload) VALUES (?, ?, ?)",
            (contract.member, str(order_key), canonical_parsed_json_bytes(row)),
        )
    except sqlite3.IntegrityError as exc:
        raise InvalidBackupDocument("duplicate backup row identity") from exc


def _iter_payloads(connection: sqlite3.Connection, member: str) -> Iterator[bytes]:
    cursor = connection.execute(
        "SELECT payload FROM rows WHERE member = ? ORDER BY order_key",
        (member,),
    )
    for (payload,) in cursor:
        yield bytes(payload)


def _logical_checksum_from_store(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    digest.update(b"{")
    for member_index, member in enumerate(sorted(DATA_MEMBERS)):
        if member_index:
            digest.update(b",")
        digest.update(canonical_json_bytes(member))
        digest.update(b":[")
        for row_index, payload in enumerate(_iter_payloads(connection, member)):
            if row_index:
                digest.update(b",")
            digest.update(payload)
        digest.update(b"]")
    digest.update(b"}")
    return digest.hexdigest()


def _write_member(
    archive: ZipFile,
    connection: sqlite3.Connection,
    member: str,
) -> MemberDigest:
    digest = hashlib.sha256()
    length = 0
    with archive.open(_zip_info(member), "w", force_zip64=True) as destination:
        for chunk in (b"[",):
            destination.write(chunk)
            digest.update(chunk)
            length += len(chunk)
        for index, payload in enumerate(_iter_payloads(connection, member)):
            if index:
                destination.write(b",")
                digest.update(b",")
                length += 1
            destination.write(payload)
            digest.update(payload)
            length += len(payload)
        destination.write(b"]")
        digest.update(b"]")
        length += 1
    return MemberDigest(byte_length=length, sha256=digest.hexdigest())


def _manifest_payload(manifest: BackupManifest) -> bytes:
    document = {
        "format_version": manifest.format_version,
        "source_application_version": manifest.source_application_version,
        "exported_at": manifest.exported_at,
        "display_timezone": manifest.display_timezone,
        "contains_plaintext_credentials": manifest.contains_plaintext_credentials,
        "record_counts": manifest.record_counts,
        "members": {
            member: {
                "byte_length": details.byte_length,
                "sha256": details.sha256,
            }
            for member, details in manifest.members.items()
        },
        "logical_checksum": manifest.logical_checksum,
    }
    return canonical_json_bytes(document)


def write_archive(
    destination: Path,
    source: Mapping[str, Iterable[Mapping[str, object]]],
    metadata: ArchiveMetadata,
) -> ArchiveSummary:
    destination = Path(destination)
    if set(source) != set(DATA_MEMBERS):
        raise InvalidBackupDocument("backup source members do not match the versioned contract")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_archive: Path | None = None
    with tempfile.TemporaryDirectory(dir=destination.parent) as workspace_name:
        workspace = Path(workspace_name)
        connection = _open_row_store(workspace / "rows.sqlite3")
        try:
            record_counts: dict[str, int] = {}
            for member in DATA_MEMBERS:
                contract = CONTRACTS_BY_MEMBER[member]
                count = 0
                for source_row in source[member]:
                    if not isinstance(source_row, Mapping):
                        raise InvalidBackupDocument("source collection item must be a mapping")
                    _insert_row(connection, contract, _encoded_source_row(contract, source_row))
                    count += 1
                record_counts[member] = count
            connection.commit()
            logical_checksum = _logical_checksum_from_store(connection)
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".partial",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_archive = Path(temporary.name)
            with ZipFile(temporary_archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
                member_digests = {
                    member: _write_member(archive, connection, member) for member in DATA_MEMBERS
                }
                manifest = BackupManifest(
                    format_version=CURRENT_FORMAT_VERSION,
                    source_application_version=metadata.source_application_version,
                    exported_at=metadata.exported_at.astimezone(timezone.utc).isoformat(),
                    display_timezone=metadata.display_timezone,
                    contains_plaintext_credentials=True,
                    record_counts=record_counts,
                    members=member_digests,
                    logical_checksum=logical_checksum,
                )
                archive.writestr(_zip_info(MANIFEST_MEMBER), _manifest_payload(manifest))
            os.replace(temporary_archive, destination)
            temporary_archive = None
        finally:
            connection.close()
            if temporary_archive is not None:
                temporary_archive.unlink(missing_ok=True)
    return ArchiveSummary(
        format_version=CURRENT_FORMAT_VERSION,
        record_counts=record_counts,
        logical_checksum=logical_checksum,
        compressed_size=destination.stat().st_size,
    )


def _is_symlink(info: ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def _read_manifest(archive: ZipFile, info: ZipInfo) -> dict[str, Any]:
    if info.file_size > MAX_MANIFEST_BYTES:
        raise ArchiveLimitExceeded("backup manifest exceeds the resource limit")
    try:
        payload = archive.read(info)
        document = json.loads(payload)
    except (BadZipFile, OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidBackupArchive("backup manifest is malformed") from exc
    if not isinstance(document, dict):
        raise InvalidBackupArchive("backup manifest must be an object")
    return document


def _format_version(document: dict[str, Any]) -> int:
    value = document.get("format_version")
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidBackupDocument("backup format version is invalid")
    if value > CURRENT_FORMAT_VERSION:
        raise UnsupportedBackupVersion("backup format is newer than this application")
    return value


def _parse_manifest(document: dict[str, Any], version: int) -> BackupManifest:
    expected_fields = {
        "format_version",
        "source_application_version",
        "exported_at",
        "display_timezone",
        "contains_plaintext_credentials",
        "record_counts",
        "members",
        "logical_checksum",
    }
    if set(document) != expected_fields:
        raise InvalidBackupDocument("backup manifest fields do not match the versioned contract")
    source_version = document["source_application_version"]
    exported_at = document["exported_at"]
    display_timezone = document["display_timezone"]
    plaintext_marker = document["contains_plaintext_credentials"]
    checksum = document["logical_checksum"]
    if not isinstance(source_version, str) or not source_version:
        raise InvalidBackupDocument("source application version is invalid")
    if not isinstance(display_timezone, str) or not display_timezone:
        raise InvalidBackupDocument("display timezone is invalid")
    if plaintext_marker is not True:
        raise InvalidBackupDocument("plaintext credential marker is invalid")
    if not isinstance(exported_at, str):
        raise InvalidBackupDocument("export timestamp is invalid")
    try:
        parsed_exported_at = datetime.fromisoformat(exported_at)
    except ValueError as exc:
        raise InvalidBackupDocument("export timestamp is invalid") from exc
    if parsed_exported_at.tzinfo is None or parsed_exported_at.utcoffset() is None:
        raise InvalidBackupDocument("export timestamp must be timezone-aware")
    if parsed_exported_at.isoformat() != exported_at:
        raise InvalidBackupDocument("export timestamp is not canonical")
    if parsed_exported_at.utcoffset() != timedelta(0):
        raise InvalidBackupDocument("export timestamp must use canonical UTC")
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise InvalidBackupDocument("logical checksum is invalid")
    try:
        bytes.fromhex(checksum)
    except ValueError as exc:
        raise InvalidBackupDocument("logical checksum is invalid") from exc

    counts = document["record_counts"]
    if not isinstance(counts, dict) or set(counts) != set(DATA_MEMBERS):
        raise InvalidBackupDocument("record counts do not match archive members")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
        raise InvalidBackupDocument("record count is invalid")

    raw_members = document["members"]
    if not isinstance(raw_members, dict) or set(raw_members) != set(DATA_MEMBERS):
        raise InvalidBackupDocument("member metadata does not match archive members")
    members: dict[str, MemberDigest] = {}
    for member in DATA_MEMBERS:
        details = raw_members[member]
        if not isinstance(details, dict) or set(details) != {"byte_length", "sha256"}:
            raise InvalidBackupDocument("member metadata is invalid")
        byte_length = details["byte_length"]
        sha256 = details["sha256"]
        if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length < 0:
            raise InvalidBackupDocument("member byte length is invalid")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise InvalidBackupDocument("member checksum is invalid")
        try:
            bytes.fromhex(sha256)
        except ValueError as exc:
            raise InvalidBackupDocument("member checksum is invalid") from exc
        members[member] = MemberDigest(byte_length=byte_length, sha256=sha256)
    return BackupManifest(
        format_version=version,
        source_application_version=source_version,
        exported_at=exported_at,
        display_timezone=display_timezone,
        contains_plaintext_credentials=True,
        record_counts=dict(counts),
        members=members,
        logical_checksum=checksum,
    )


def _verify_member_bytes(archive: ZipFile, info: ZipInfo, expected: MemberDigest) -> None:
    digest = hashlib.sha256()
    observed = 0
    try:
        with archive.open(info) as source:
            while chunk := source.read(STREAM_CHUNK_BYTES):
                observed += len(chunk)
                if observed > MAX_UNCOMPRESSED_BYTES:
                    raise ArchiveLimitExceeded("backup exceeds the uncompressed resource limit")
                digest.update(chunk)
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise InvalidBackupArchive("backup member is unreadable") from exc
    if observed != info.file_size or observed != expected.byte_length:
        raise InvalidBackupArchive("backup member length does not match its manifest")
    if digest.hexdigest() != expected.sha256:
        raise InvalidBackupArchive("backup member checksum does not match its manifest")


def _check_archive_metadata(compressed_size: int, infos: list[ZipInfo]) -> dict[str, ZipInfo]:
    if compressed_size > MAX_COMPRESSED_BYTES:
        raise ArchiveLimitExceeded("backup exceeds the compressed resource limit")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise InvalidBackupArchive("backup contains duplicate members")
    if tuple(sorted(names)) != tuple(sorted(ALLOWED_MEMBERS)):
        raise InvalidBackupArchive("backup members do not match the allowlist")
    if any(_is_symlink(info) for info in infos):
        raise InvalidBackupArchive("backup contains a symbolic link")
    if any(info.flag_bits & 0x1 for info in infos):
        raise InvalidBackupArchive("encrypted ZIP members are not supported")
    total_uncompressed = sum(info.file_size for info in infos)
    total_compressed = sum(info.compress_size for info in infos)
    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
        raise ArchiveLimitExceeded("backup exceeds the uncompressed resource limit")
    ratio = total_uncompressed / max(total_compressed, 1)
    if ratio > MAX_AGGREGATE_COMPRESSION_RATIO:
        raise ArchiveLimitExceeded("backup exceeds the compression ratio limit")
    return {info.filename: info for info in infos}


def _snapshot_archive(path: Path) -> tuple[BinaryIO, int, str]:
    snapshot = tempfile.TemporaryFile()
    digest = hashlib.sha256()
    observed = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(STREAM_CHUNK_BYTES):
                observed += len(chunk)
                if observed > MAX_COMPRESSED_BYTES:
                    raise ArchiveLimitExceeded("backup exceeds the compressed resource limit")
                snapshot.write(chunk)
                digest.update(chunk)
        snapshot.seek(0)
        return snapshot, observed, digest.hexdigest()
    except Exception:
        snapshot.close()
        raise


def open_verified_archive(path: Path) -> InspectedArchive:
    path = Path(path)
    snapshot: BinaryIO | None = None
    archive: ZipFile | None = None
    owns_resources = True
    try:
        snapshot, compressed_size, archive_sha256 = _snapshot_archive(path)
        archive = ZipFile(snapshot)
        infos = archive.infolist()
        by_name = _check_archive_metadata(compressed_size, infos)
        raw_manifest = _read_manifest(archive, by_name[MANIFEST_MEMBER])
        version = _format_version(raw_manifest)
        manifest = _parse_manifest(raw_manifest, version)
        for member in DATA_MEMBERS:
            _verify_member_bytes(archive, by_name[member], manifest.members[member])
        require_migration_path(version)
        inspected = InspectedArchive(
            path=path,
            manifest=manifest,
            archive_sha256=archive_sha256,
            compressed_size=compressed_size,
            _snapshot=snapshot,
            _zip=archive,
            _verification_token=_VERIFIED_ARCHIVE_TOKEN,
        )
        owns_resources = False
        return inspected
    except (
        ArchiveLimitExceeded,
        BackupMigrationError,
        InvalidBackupArchive,
        InvalidBackupDocument,
        UnsupportedBackupVersion,
    ):
        raise
    except BadZipFile:
        raise InvalidBackupArchive("backup is not a valid ZIP archive") from None
    except OSError:
        raise InvalidBackupArchive("backup archive is unavailable") from None
    finally:
        if owns_resources:
            try:
                if archive is not None:
                    archive.close()
            finally:
                if snapshot is not None:
                    snapshot.close()


def inspect_archive(path: Path) -> InspectedArchive:
    inspected = open_verified_archive(path)
    try:
        migrated = migrate_to_current(inspected)
        with tempfile.TemporaryDirectory(dir=Path(path).parent) as workspace_name:
            connection = _open_row_store(Path(workspace_name) / "rows.sqlite3")
            try:
                for member in DATA_MEMBERS:
                    count = 0
                    for row in iter_current_rows(migrated, member):
                        _insert_row(connection, CONTRACTS_BY_MEMBER[member], row)
                        count += 1
                    if count != inspected.manifest.record_counts[member]:
                        raise InvalidBackupDocument("backup record count does not match manifest")
                connection.commit()
                checksum = _logical_checksum_from_store(connection)
                if inspected.format_version == CURRENT_FORMAT_VERSION and checksum != inspected.manifest.logical_checksum:
                    raise InvalidBackupDocument("backup logical checksum does not match manifest")
            finally:
                connection.close()
        return inspected
    except Exception:
        inspected.close()
        raise


def _verified_inspected_archive(
    archive: InspectedArchive | MigratedArchive,
) -> InspectedArchive:
    if isinstance(archive, InspectedArchive):
        inspected = archive
        migrate_to_current(inspected)
    elif isinstance(archive, MigratedArchive) and isinstance(archive.source, InspectedArchive):
        inspected = archive.source
        if archive.format_version != CURRENT_FORMAT_VERSION:
            raise InvalidBackupDocument("archive migration handle is invalid")
    else:
        raise InvalidBackupDocument("archive has not been verified")
    if (
        inspected._verification_token is not _VERIFIED_ARCHIVE_TOKEN
        or inspected._zip.fp is None
        or inspected._snapshot.closed
    ):
        raise InvalidBackupDocument("archive verification handle is invalid")
    return inspected


def iter_current_rows(
    archive: InspectedArchive | MigratedArchive,
    member: str,
) -> Iterator[dict[str, JsonValue]]:
    if member not in DATA_MEMBERS:
        raise InvalidBackupDocument("requested member is not a backup collection")
    inspected = _verified_inspected_archive(archive)
    migrated = archive if isinstance(archive, MigratedArchive) else migrate_to_current(inspected)
    for item in migrated.iter_rows(member):
        yield _validate_row(member, item)
