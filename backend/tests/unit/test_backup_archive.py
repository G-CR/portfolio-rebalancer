from __future__ import annotations

import hashlib
import json
import stat
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from app.backups import archive as archive_module
from app.backups.archive import (
    ArchiveLimitExceeded,
    ArchiveMetadata,
    InvalidBackupArchive,
    InvalidBackupDocument,
    UnsupportedBackupVersion,
    inspect_archive,
    iter_current_rows,
    write_archive,
)
from app.backups.canonical import canonical_json_bytes, encode_json_value, logical_checksum
from app.backups.constants import (
    ALLOWED_MEMBERS,
    CURRENT_FORMAT_VERSION,
    DATA_MEMBERS,
    MAX_AGGREGATE_COMPRESSION_RATIO,
    MAX_COMPRESSED_BYTES,
    MAX_UNCOMPRESSED_BYTES,
)
from app.backups.contracts import CREDENTIAL_CONTRACT, TABLE_CONTRACTS
from app.backups.migrations import MissingMigrationPath, migrate_to_current


FIXTURE = Path(__file__).parents[1] / "fixtures" / "backups" / "v1-minimal.portfolio-backup"
FIXED_UUID = UUID("00000000-0000-0000-0000-000000000123")
FIXED_TIME = datetime(2026, 8, 23, 12, 34, 56, 123456, tzinfo=timezone.utc)


def empty_source() -> dict[str, list[dict[str, Any]]]:
    return {member: [] for member in DATA_MEMBERS}


def metadata(**overrides: Any) -> ArchiveMetadata:
    values: dict[str, Any] = {
        "source_application_version": "0.1.0-test",
        "exported_at": FIXED_TIME,
        "display_timezone": "Asia/Shanghai",
    }
    values.update(overrides)
    return ArchiveMetadata(**values)


def write_valid_archive(tmp_path: Path, source: dict[str, list[dict[str, Any]]] | None = None) -> Path:
    path = tmp_path / "valid.portfolio-backup"
    write_archive(path, source or empty_source(), metadata())
    return path


def rewrite_archive(
    source: Path,
    destination: Path,
    *,
    replace: dict[str, bytes] | None = None,
    omit: set[str] | None = None,
    additions: list[tuple[ZipInfo | str, bytes]] | None = None,
) -> Path:
    replace = replace or {}
    omit = omit or set()
    additions = additions or []
    with ZipFile(source) as old, ZipFile(destination, "w", compression=ZIP_DEFLATED) as new:
        for info in old.infolist():
            if info.filename not in omit:
                new.writestr(info.filename, replace.get(info.filename, old.read(info)))
        for info, payload in additions:
            new.writestr(info, payload)
    return destination


def rewrite_manifest_and_member(
    source: Path,
    destination: Path,
    member: str,
    payload: bytes,
    **manifest_updates: Any,
) -> Path:
    with ZipFile(source) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["members"][member] = {
        "byte_length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest.update(manifest_updates)
    manifest_payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return rewrite_archive(
        source,
        destination,
        replace={member: payload, "manifest.json": manifest_payload},
    )


def test_v1_constants_freeze_exact_archive_limits_and_members() -> None:
    assert CURRENT_FORMAT_VERSION == 1
    assert MAX_COMPRESSED_BYTES == 500 * 1024 * 1024
    assert MAX_UNCOMPRESSED_BYTES == 2 * 1024 * 1024 * 1024
    assert MAX_AGGREGATE_COMPRESSION_RATIO == 100
    assert ALLOWED_MEMBERS == (
        "manifest.json",
        "credentials.json",
        "data/asset_classes.json",
        "data/holdings.json",
        "data/holding_defaults.json",
        "data/market_data.json",
        "data/market_data_overrides.json",
        "data/cost_adjustments.json",
        "data/snapshots.json",
        "data/snapshot_items.json",
        "data/rebalance_plans.json",
        "data/settings.json",
    )


def test_v1_contract_covers_every_persisted_column() -> None:
    assert len(TABLE_CONTRACTS) == 10
    for contract in TABLE_CONTRACTS:
        assert tuple(column.name for column in contract.model.__table__.columns) == contract.columns
        assert len(contract.codecs) == len(contract.columns)


def test_credential_contract_replaces_only_encrypted_value_with_plaintext_value() -> None:
    model_columns = tuple(
        column.name for column in CREDENTIAL_CONTRACT.model.__table__.columns
    )
    expected = tuple(
        "value" if column == "encrypted_value" else column for column in model_columns
    )
    assert CREDENTIAL_CONTRACT.member == "credentials.json"
    assert CREDENTIAL_CONTRACT.columns == expected
    assert "encrypted_value" not in CREDENTIAL_CONTRACT.columns


def test_exact_scalar_encoding_preserves_precision_offsets_unicode_and_null() -> None:
    value = {
        "decimal": Decimal("123.4500"),
        "date": date(2026, 8, 23),
        "datetime": datetime.fromisoformat("2026-08-23T20:34:56.123456+08:00"),
        "uuid": FIXED_UUID,
        "text": "资产配置",
        "null": None,
    }
    encoded = encode_json_value(value)
    assert encoded == {
        "decimal": "123.4500",
        "date": "2026-08-23",
        "datetime": "2026-08-23T20:34:56.123456+08:00",
        "uuid": str(FIXED_UUID),
        "text": "资产配置",
        "null": None,
    }
    assert "资产配置".encode() in canonical_json_bytes(value)
    assert b"\\u8d44" not in canonical_json_bytes(value)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        encode_json_value(datetime(2026, 8, 23, 12, 34, 56))


def test_canonical_checksum_ignores_input_row_and_object_order() -> None:
    canonical_document = {
        "data/holdings.json": [
            {"id": "1", "payload": {"a": 1, "b": 2}},
            {"id": "2", "payload": {"a": 3, "b": 4}},
        ],
        "credentials.json": [],
    }
    shuffled_document = {
        "credentials.json": [],
        "data/holdings.json": [
            {"payload": {"b": 4, "a": 3}, "id": "2"},
            {"payload": {"b": 2, "a": 1}, "id": "1"},
        ],
    }
    assert logical_checksum(shuffled_document) == logical_checksum(canonical_document)


def test_logical_checksum_excludes_manifest() -> None:
    document = {"credentials.json": [], "manifest.json": {"exported_at": "one"}}
    changed = {"manifest.json": {"exported_at": "two"}, "credentials.json": []}
    assert logical_checksum(document) == logical_checksum(changed)


def test_writer_is_deterministic_and_round_trips_rows(tmp_path: Path) -> None:
    row = {
        "id": FIXED_UUID,
        "name": "中国资产",
        "target_weight": Decimal("0.250000000000"),
        "display_order": 1,
        "is_active": True,
        "notes": None,
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
    }
    source = empty_source()
    source["data/asset_classes.json"] = [row]
    first = tmp_path / "first.portfolio-backup"
    second = tmp_path / "second.portfolio-backup"
    first_summary = write_archive(first, source, metadata())
    second_summary = write_archive(second, source, metadata())

    assert first.read_bytes() == second.read_bytes()
    assert first_summary == second_summary
    inspected = inspect_archive(first)
    assert list(iter_current_rows(inspected, "data/asset_classes.json")) == [
        {
            "id": str(FIXED_UUID),
            "name": "中国资产",
            "target_weight": "0.250000000000",
            "display_order": 1,
            "is_active": True,
            "notes": None,
            "created_at": FIXED_TIME.isoformat(),
            "updated_at": FIXED_TIME.isoformat(),
        }
    ]


def test_writer_requires_exact_source_members(tmp_path: Path) -> None:
    source = empty_source()
    source.pop("credentials.json")
    with pytest.raises(InvalidBackupDocument):
        write_archive(tmp_path / "missing.portfolio-backup", source, metadata())


def test_archive_requires_exact_allowlisted_members(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    missing = rewrite_archive(
        valid,
        tmp_path / "missing.portfolio-backup",
        omit={"data/settings.json"},
    )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(missing)


def test_missing_archive_path_raises_typed_sanitized_error(tmp_path: Path) -> None:
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(tmp_path / "missing.portfolio-backup")


@pytest.mark.parametrize(
    "name",
    ["unknown.json", "../manifest.json", "/manifest.json", "C:/manifest.json", "data\\holdings.json"],
)
def test_unknown_traversal_and_absolute_members_are_rejected(tmp_path: Path, name: str) -> None:
    valid = write_valid_archive(tmp_path)
    hostile = rewrite_archive(
        valid,
        tmp_path / f"hostile-{hashlib.sha256(name.encode()).hexdigest()}.portfolio-backup",
        additions=[(name, b"[]")],
    )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(hostile)


def test_duplicate_member_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = rewrite_archive(
            valid,
            tmp_path / "duplicate.portfolio-backup",
            additions=[("credentials.json", b"[]")],
        )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(duplicate)


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    link = ZipInfo("credentials.json")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    hostile = rewrite_archive(
        valid,
        tmp_path / "symlink.portfolio-backup",
        omit={"credentials.json"},
        additions=[(link, b"target")],
    )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(hostile)


def test_compressed_size_limit_is_enforced_from_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    valid = write_valid_archive(tmp_path)
    monkeypatch.setattr(archive_module, "MAX_COMPRESSED_BYTES", valid.stat().st_size - 1)
    with pytest.raises(ArchiveLimitExceeded):
        inspect_archive(valid)


def test_uncompressed_size_limit_is_enforced_from_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    valid = write_valid_archive(tmp_path)
    with ZipFile(valid) as archive:
        declared = sum(info.file_size for info in archive.infolist())
    monkeypatch.setattr(archive_module, "MAX_UNCOMPRESSED_BYTES", declared - 1)
    with pytest.raises(ArchiveLimitExceeded):
        inspect_archive(valid)


def test_aggregate_compression_ratio_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = empty_source()
    source["credentials.json"] = []
    valid = write_valid_archive(tmp_path, source)
    monkeypatch.setattr(archive_module, "MAX_AGGREGATE_COMPRESSION_RATIO", 1)
    with pytest.raises(ArchiveLimitExceeded):
        inspect_archive(valid)


def test_member_sha256_mismatch_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    tampered = rewrite_archive(
        valid,
        tmp_path / "bad-hash.portfolio-backup",
        replace={"credentials.json": b"[ ]"},
    )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(tampered)


def test_member_length_mismatch_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    with ZipFile(valid) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["members"]["credentials.json"]["byte_length"] += 1
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    tampered = rewrite_archive(
        valid,
        tmp_path / "bad-length.portfolio-backup",
        replace={"manifest.json": payload},
    )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(tampered)


def test_malformed_manifest_json_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    malformed = rewrite_archive(
        valid,
        tmp_path / "bad-manifest.portfolio-backup",
        replace={"manifest.json": b"{"},
    )
    with pytest.raises(InvalidBackupArchive):
        inspect_archive(malformed)


def test_malformed_collection_json_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    malformed = rewrite_manifest_and_member(
        valid,
        tmp_path / "bad-data.portfolio-backup",
        "credentials.json",
        b"[",
    )
    with pytest.raises(InvalidBackupDocument):
        inspect_archive(malformed)


def test_future_archive_is_rejected_before_document_validation(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    invalid_row = b'[{"unknown":"field"}]'
    future = rewrite_manifest_and_member(
        valid,
        tmp_path / "future.portfolio-backup",
        "credentials.json",
        invalid_row,
        format_version=CURRENT_FORMAT_VERSION + 1,
    )
    with pytest.raises(UnsupportedBackupVersion):
        inspect_archive(future)


def test_missing_migration_path_is_typed(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    with ZipFile(valid) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["format_version"] = 0
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    old = rewrite_archive(
        valid,
        tmp_path / "old.portfolio-backup",
        replace={"manifest.json": payload},
    )
    with pytest.raises(MissingMigrationPath):
        inspect_archive(old)


def test_unknown_manifest_field_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    with ZipFile(valid) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["surprise"] = True
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    unknown = rewrite_archive(
        valid,
        tmp_path / "unknown-manifest.portfolio-backup",
        replace={"manifest.json": payload},
    )
    with pytest.raises(InvalidBackupDocument):
        inspect_archive(unknown)


def test_unknown_row_field_is_rejected_after_migration(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    payload = b'[{"unknown":"field"}]'
    unknown = rewrite_manifest_and_member(
        valid,
        tmp_path / "unknown-row.portfolio-backup",
        "credentials.json",
        payload,
    )
    with pytest.raises(InvalidBackupDocument):
        inspect_archive(unknown)


def test_record_count_mismatch_is_rejected(tmp_path: Path) -> None:
    valid = write_valid_archive(tmp_path)
    with ZipFile(valid) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["record_counts"]["credentials.json"] = 1
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    bad_count = rewrite_archive(
        valid,
        tmp_path / "bad-count.portfolio-backup",
        replace={"manifest.json": payload},
    )
    with pytest.raises(InvalidBackupDocument):
        inspect_archive(bad_count)


def test_identity_migration_returns_current_archive(tmp_path: Path) -> None:
    inspected = inspect_archive(write_valid_archive(tmp_path))
    migrated = migrate_to_current(inspected)
    assert migrated.format_version == CURRENT_FORMAT_VERSION
    assert migrated.path == inspected.path


def test_iter_current_rows_rejects_non_collection_member(tmp_path: Path) -> None:
    inspected = inspect_archive(write_valid_archive(tmp_path))
    with pytest.raises(InvalidBackupDocument):
        list(iter_current_rows(inspected, "manifest.json"))


def test_committed_v1_golden_fixture_opens_through_production_reader() -> None:
    inspected = inspect_archive(FIXTURE)
    assert inspected.manifest.format_version == 1
    assert inspected.manifest.contains_plaintext_credentials is True
    assert list(iter_current_rows(inspected, "credentials.json")) == []
    rows = list(iter_current_rows(inspected, "data/asset_classes.json"))
    assert rows[0]["name"] == "黄金夹具"
    assert rows[0]["notes"] is None
