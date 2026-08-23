from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.backups.archive import ArchiveMetadata, write_archive
from app.backups.canonical import canonical_json_bytes, logical_checksum
from app.backups import migrations
from app.backups.constants import CURRENT_FORMAT_VERSION, DATA_MEMBERS
from app.services.backup_storage import BackupStorage
from app.services.backup_operations import BackupOperationManager
from app.services.backup_validation import (
    BackupValidationError,
    RestoreTokenRegistry,
    validate_backup,
)
from app.services.rebalance_version import rebalance_data_version


NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
IDS = {name: UUID(int=index) for index, name in enumerate(
    ("settings", "asset", "holding", "default", "market", "override", "cost",
     "before", "after", "before_item", "after_item", "plan", "credential"), start=1
)}


def _source() -> dict[str, list[dict[str, Any]]]:
    source = {member: [] for member in DATA_MEMBERS}
    dt = NOW
    source["data/asset_classes.json"] = [{
        "id": IDS["asset"], "name": "Synthetic", "target_weight": "1.000000000000",
        "display_order": 0, "is_active": True, "notes": None,
        "created_at": dt, "updated_at": dt,
    }]
    source["data/holdings.json"] = [{
        "id": IDS["holding"], "asset_class_id": IDS["asset"], "symbol": "SYNTH",
        "name": "Synthetic holding", "market": "US", "account_name": "test",
        "trade_currency": "USD", "quantity": "1.000000000000",
        "average_cost_price": "1.000000000000", "cost_fx_to_cny": "7.000000000000",
        "baseline_fx_to_cny": "7.000000000000", "lot_size": "1.000000000000",
        "quantity_precision": 0, "preferred_data_source": "yahoo",
        "is_rebalance_preferred": True, "is_active": True, "version": 1,
        "created_at": dt, "updated_at": dt,
    }]
    source["data/holding_defaults.json"] = [{
        "id": IDS["default"], "holding_id": IDS["holding"], "fee_currency": "USD",
        "commission_rate": "0.000000000000", "minimum_commission": "0.000000000000",
        "per_share_fee": "0.000000000000", "fixed_fee": "0.000000000000",
        "default_data_source": "yahoo", "created_at": dt, "updated_at": dt,
    }]
    source["data/market_data.json"] = [{
        "id": IDS["market"], "data_type": "price", "symbol": "SYNTH", "source": "yahoo",
        "value": "1.000000000000", "market_time": dt, "fetched_at": dt,
        "status": "valid", "error_summary": None, "created_at": dt,
    }]
    source["data/market_data_overrides.json"] = [{
        "id": IDS["override"], "data_type": "price", "symbol": "SYNTH",
        "value": "1.000000000000", "note": "synthetic", "effective_at": dt,
        "expires_at": None, "created_at": dt, "updated_at": dt,
    }]
    source["data/cost_adjustments.json"] = [{
        "id": IDS["cost"], "holding_id": IDS["holding"], "operation_type": "PURCHASE",
        "before_quantity": "0.000000000000", "before_average_cost_price": "0.000000000000",
        "before_cost_fx_to_cny": "7.000000000000", "after_quantity": "1.000000000000",
        "after_average_cost_price": "1.000000000000", "after_cost_fx_to_cny": "7.000000000000",
        "input_summary": {}, "note": None, "created_at": dt,
    }]
    for key, snapshot_type in (("before", "rebalance_before"), ("after", "rebalance_after")):
        source["data/snapshots.json"].append({
            "id": IDS[key], "snapshot_type": snapshot_type, "local_date": "2026-08-24",
            "captured_at": dt, "note": "synthetic", "data_complete": True,
            "has_stale_data": False, "has_manual_data": False, "created_at": dt,
        })
        source["data/snapshot_items.json"].append({
            "id": IDS[f"{key}_item"], "snapshot_id": IDS[key], "holding_id": IDS["holding"],
            "asset_class_name": "Synthetic", "holding_name": "Synthetic holding", "symbol": "SYNTH",
            "account_name": "test", "trade_currency": "USD", "quantity": "1.000000000000",
            "market_price": "1.000000000000", "current_fx_to_cny": "7.000000000000",
            "baseline_fx_to_cny": "7.000000000000", "average_cost_price": "1.000000000000",
            "cost_fx_to_cny": "7.000000000000", "target_weight": "1.000000000000",
            "market_value_cny": "7.000000000000", "fx_neutral_value_cny": "7.000000000000",
            "cost_value_cny": "7.000000000000", "unrealized_pnl_amount_cny": "0.000000000000",
            "unrealized_pnl_rate": "0.000000000000", "price_effect_cny": "0.000000000000",
            "fx_effect_cny": "0.000000000000", "actual_weight": "1.000000000000",
            "fx_neutral_weight": "1.000000000000", "price_status": "valid", "fx_status": "valid",
            "created_at": dt,
        })
    result = {
        "feasible": True, "max_drift_before": "0", "max_drift_after": "0",
        "fx_required_cny": "0", "remaining_cny": "0", "remaining_usd": "0",
        "projected_weights": [{"asset_class_id": str(IDS["asset"]), "before": "1", "after": "1", "target": "1"}],
        "trades": [],
    }
    market_ids = {"price:SYNTH": str(IDS["market"])}
    version_payload = {
        "market_data_record_ids": market_ids,
        "holding_versions": {str(IDS["holding"]): 1},
        "asset_class_targets": {str(IDS["asset"]): "1"},
    }
    data_version = rebalance_data_version(**version_payload)
    source["data/rebalance_plans.json"] = [{
        "id": IDS["plan"], "strategy_mode": "actual", "status": "completed",
        "data_version": data_version, "create_idempotency_key": "create",
        "input_summary": {
            "session_token": "synthetic-session", "request_token": "synthetic-request",
            "available_cny": "0", "available_usd": "0", "valuation_basis": "actual",
            "allow_sell": None, "allow_fx": None, "tolerance": None,
            "minimum_trade_cny": None, "acknowledge_stale_data": False,
            "holding_versions": version_payload["holding_versions"], "market_data_record_ids": market_ids,
            "asset_class_targets": version_payload["asset_class_targets"],
            "resolved_constraints": {"allow_sell": True, "allow_fx": True, "tolerance": "0.01", "minimum_trade_cny": "100"},
        },
        "suggested_actions": [],
        "projected_result": {"valuation_basis": "actual", "result": result,
                             "fx_comparison": {"valuation_basis": "fx_neutral", "result": result},
                             "data_status": "valid"},
        "before_snapshot_id": IDS["before"], "after_snapshot_id": IDS["after"],
        "started_at": dt, "cancelled_at": None, "created_at": dt, "updated_at": dt,
        "baseline_reset_at": dt, "start_market_data_record_ids": {"price:SYNTH": str(IDS["market"])},
        "completion_market_data_record_ids": {"price:SYNTH": str(IDS["market"])},
        "start_idempotency_key": "start", "cancel_idempotency_key": None,
        "complete_idempotency_key": "complete", "completed_at": dt,
    }]
    source["data/settings.json"] = [{
        "id": IDS["settings"], "refresh_hour": 7, "refresh_minute": 30,
        "provider_priority": ["yahoo", "sina", "akshare", "tushare", "alpha_vantage"], "default_tolerance": "0.010000000000",
        "minimum_trade_amount_cny": "100.000000000000", "allow_sell": True,
        "allow_fx": True, "rebalance_available_cny": "0.000000000000",
        "rebalance_available_usd": "0.000000000000", "rebalance_valuation_basis": "actual",
        "email_enabled": True, "email_recipient": "synthetic@example.test",
        "email_smtp_host": "smtp.example.test", "email_smtp_port": 465,
        "email_smtp_security": "ssl", "email_smtp_username": "synthetic@example.test",
        "email_from": "synthetic@example.test", "created_at": dt, "updated_at": dt,
    }]
    source["credentials.json"] = [{
        "id": IDS["credential"], "provider": "yahoo", "value": "synthetic-secret-never-leak",
        "masked_value": "****leak", "validation_status": "valid", "validation_message": None,
        "last_validated_at": dt, "created_at": dt, "updated_at": dt,
    }]
    return source


def _archive(tmp_path: Path, source: dict[str, list[dict[str, Any]]] | None = None) -> Path:
    path = tmp_path / "state.portfolio-backup"
    write_archive(path, source or _source(), ArchiveMetadata(
        source_application_version="1.2.3", exported_at=NOW, display_timezone="Asia/Shanghai"
    ))
    return path


def _validate(tmp_path: Path, source: dict[str, list[dict[str, Any]]]) -> None:
    validate_backup(
        _archive(tmp_path, source), path_id="upload:test",
        expires_at=NOW + timedelta(minutes=30), workspace_root=tmp_path,
    )


def test_valid_backup_returns_bounded_descriptor_and_closes_snapshot(tmp_path: Path, monkeypatch) -> None:
    from app.services import backup_validation as module
    real_inspect = module.open_verified_archive
    handles = []

    def tracked(path: Path):
        inspected = real_inspect(path)
        handles.append(inspected)
        return inspected

    monkeypatch.setattr(module, "open_verified_archive", tracked)
    validated = validate_backup(
        _archive(tmp_path), path_id="upload:test",
        expires_at=NOW + timedelta(minutes=30), workspace_root=tmp_path,
    )

    assert validated.source_format_version == 1
    assert validated.current_format_version == CURRENT_FORMAT_VERSION
    assert validated.credential_categories == ("yahoo",)
    assert "synthetic-secret" not in repr(validated)
    assert handles[0]._snapshot.closed


def test_older_rows_are_migrated_before_current_schema_and_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _archive(tmp_path)
    with ZipFile(current) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        members = {name: archive.read(name) for name in archive.namelist() if name != "manifest.json"}
    current_checksum = manifest["logical_checksum"]
    credentials = json.loads(members["credentials.json"])
    credentials[0]["secret"] = credentials[0].pop("value")
    members["credentials.json"] = canonical_json_bytes(credentials)
    old_document = {member: json.loads(payload) for member, payload in members.items()}
    old_checksum = logical_checksum(old_document)
    manifest["format_version"] = 0
    manifest["logical_checksum"] = old_checksum
    manifest["members"]["credentials.json"] = {
        "byte_length": len(members["credentials.json"]),
        "sha256": hashlib.sha256(members["credentials.json"]).hexdigest(),
    }
    old = tmp_path / "synthetic-v0.portfolio-backup"
    with ZipFile(old, "w", compression=ZIP_DEFLATED) as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)
        archive.writestr("manifest.json", canonical_json_bytes(manifest))

    def v0_to_v1(member: str, row: dict[str, Any]) -> dict[str, Any]:
        if member == "credentials.json":
            row = dict(row)
            row["value"] = row.pop("secret")
        return row

    monkeypatch.setitem(migrations.MIGRATIONS, 0, v0_to_v1)
    validated = validate_backup(old, path_id="upload:test", workspace_root=tmp_path)
    assert validated.source_format_version == 0
    assert validated.canonical_logical_checksum == current_checksum
    assert validated.canonical_logical_checksum != old_checksum


@pytest.mark.parametrize(
    ("member", "field", "invalid"),
    [
        ("data/holdings.json", "market", "MOON"),
        ("data/market_data.json", "status", "fresh"),
        ("data/snapshots.json", "snapshot_type", "unknown"),
        ("data/settings.json", "email_smtp_security", "plain"),
        ("credentials.json", "validation_status", "unknown"),
        ("credentials.json", "validation_status", "untested"),
        ("data/asset_classes.json", "target_weight", "10000000000000000.000000000000"),
        ("data/holdings.json", "quantity", "1.0000000000001"),
    ],
)
def test_strict_enum_and_numeric_contracts_are_rejected(
    tmp_path: Path, member: str, field: str, invalid: object
) -> None:
    source = _source()
    source[member][0][field] = invalid
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


@pytest.mark.parametrize(
    ("member", "field", "invalid"),
    [
        ("data/asset_classes.json", "target_weight", "-0.000000000001"),
        ("data/asset_classes.json", "target_weight", "1.000000000001"),
        ("data/holdings.json", "quantity_precision", -1),
        ("data/holdings.json", "quantity_precision", 13),
        ("data/holdings.json", "lot_size", "0.000000000000"),
        ("data/holdings.json", "quantity", "-0.000000000001"),
        ("data/holding_defaults.json", "commission_rate", "-0.000000000001"),
        ("data/market_data_overrides.json", "value", "0.000000000000"),
        ("data/market_data.json", "value", "0.000000000000"),
        ("data/cost_adjustments.json", "after_quantity", "-0.000000000001"),
        ("data/settings.json", "default_tolerance", "1.000000000001"),
        ("data/settings.json", "rebalance_available_cny", "-0.000000000001"),
        ("data/settings.json", "email_recipient", "not-an-email"),
    ],
)
def test_persisted_domain_constraint_families_are_rejected(
    tmp_path: Path, member: str, field: str, invalid: object,
) -> None:
    source = _source()
    source[member][0][field] = invalid
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


def test_persisted_holding_version_zero_is_rejected(tmp_path: Path) -> None:
    source = _source()
    source["data/holdings.json"][0]["version"] = 0

    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)

    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


@pytest.mark.parametrize("priority", [[], ["akshare", "yahoo", "tushare", "alpha_vantage"]])
def test_provider_priority_accepts_and_preserves_seed_and_known_legacy_subsets(
    tmp_path: Path, priority: list[str],
) -> None:
    source = _source()
    source["data/settings.json"][0]["provider_priority"] = priority
    archive = _archive(tmp_path, source)
    validate_backup(archive, path_id="upload:test", workspace_root=tmp_path)
    from app.backups.archive import inspect_archive, iter_current_rows
    with inspect_archive(archive) as inspected:
        [settings] = list(iter_current_rows(inspected, "data/settings.json"))
    assert settings["provider_priority"] == priority


@pytest.mark.parametrize("priority", [["yahoo", "yahoo"], ["unknown-provider"]])
def test_provider_priority_rejects_duplicates_and_unknowns(
    tmp_path: Path, priority: list[str],
) -> None:
    source = _source()
    source["data/settings.json"][0]["provider_priority"] = priority
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


def test_rebalance_response_shape_requires_every_plan_response_key(tmp_path: Path) -> None:
    source = _source()
    del source["data/rebalance_plans.json"][0]["input_summary"]["available_cny"]
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


@pytest.mark.parametrize("missing_asset_targets", [False, True])
def test_legacy_rebalance_fallback_and_optional_asset_targets_are_supported(
    tmp_path: Path, missing_asset_targets: bool,
) -> None:
    source = _source()
    plan = source["data/rebalance_plans.json"][0]
    plan["input_summary"].update(plan["input_summary"]["resolved_constraints"])
    plan["input_summary"].pop("resolved_constraints")
    if missing_asset_targets:
        plan["input_summary"].pop("asset_class_targets")
    plan["data_version"] = "legacy-opaque-version"

    _validate(tmp_path, source)


def test_legacy_rebalance_fallback_still_requires_renderer_constraint_keys(
    tmp_path: Path,
) -> None:
    source = _source()
    summary = source["data/rebalance_plans.json"][0]["input_summary"]
    summary.pop("resolved_constraints")
    summary.pop("minimum_trade_cny")
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


def test_modern_rebalance_data_version_must_match_exact_inputs(tmp_path: Path) -> None:
    source = _source()
    source["data/rebalance_plans.json"][0]["data_version"] = "0" * 64

    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)

    assert exc_info.value.code == "BACKUP_RELATIONSHIP_INVALID"


def test_modern_rebalance_exact_data_version_is_accepted(tmp_path: Path) -> None:
    source = _source()
    plan = source["data/rebalance_plans.json"][0]
    summary = plan["input_summary"]
    plan["data_version"] = rebalance_data_version(
        market_data_record_ids=summary["market_data_record_ids"],
        holding_versions=summary["holding_versions"],
        asset_class_targets=summary["asset_class_targets"],
    )

    _validate(tmp_path, source)


def test_holding_version_zero_is_rejected(tmp_path: Path) -> None:
    source = _source()
    source["data/rebalance_plans.json"][0]["input_summary"]["holding_versions"] = {
        str(IDS["holding"]): 0,
    }

    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)

    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


def test_holding_version_one_is_accepted(tmp_path: Path) -> None:
    source = _source()
    source["data/rebalance_plans.json"][0]["input_summary"]["holding_versions"] = {
        str(IDS["holding"]): 1,
    }

    _validate(tmp_path, source)


@pytest.mark.parametrize(
    "target",
    [
        "result", "projected_weight", "suggested_action", "result_trade",
        "fx_comparison", "fx_result", "fx_trade",
    ],
)
def test_rebalance_nested_unknown_fields_are_rejected(
    tmp_path: Path, target: str,
) -> None:
    source = _source()
    plan = source["data/rebalance_plans.json"][0]
    projected = plan["projected_result"]
    trade = {
        "symbol": "SYNTH", "action": "buy", "quantity": "1",
        "amount_cny": "1", "amount_trade_currency": "1",
        "reason_code": "UNDERWEIGHT_WITH_CASH", "reason": "Synthetic trade.",
    }
    plan["suggested_actions"] = [dict(trade)]
    projected["result"]["trades"] = [dict(trade)]
    projected["fx_comparison"]["result"]["trades"] = [dict(trade)]
    if target == "result":
        projected["result"]["unknown"] = "secret"
    elif target == "projected_weight":
        projected["result"]["projected_weights"][0]["unknown"] = "secret"
    elif target == "suggested_action":
        plan["suggested_actions"][0]["unknown"] = "secret"
    elif target == "result_trade":
        projected["result"]["trades"][0]["unknown"] = "secret"
    elif target == "fx_comparison":
        projected["fx_comparison"]["unknown"] = "secret"
    elif target == "fx_result":
        projected["fx_comparison"]["result"]["unknown"] = "secret"
    else:
        projected["fx_comparison"]["result"]["trades"][0]["unknown"] = "secret"
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


@pytest.mark.parametrize("map_field", ["input_summary", "start_market_data_record_ids", "completion_market_data_record_ids"])
def test_every_market_reference_key_must_match_target_semantics(tmp_path: Path, map_field: str) -> None:
    source = _source()
    plan = source["data/rebalance_plans.json"][0]
    if map_field == "input_summary":
        plan[map_field]["market_data_record_ids"] = {"price:WRONG": str(IDS["market"])}
    else:
        plan[map_field] = {"fx:USD/CNY": str(IDS["market"])}
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_RELATIONSHIP_INVALID"


def test_iso_trade_and_fee_currencies_are_not_restricted_to_cny_and_usd(
    tmp_path: Path,
) -> None:
    source = _source()
    source["data/holdings.json"][0]["trade_currency"] = "EUR"
    source["data/holding_defaults.json"][0]["fee_currency"] = "EUR"
    for row in source["data/snapshot_items.json"]:
        row["trade_currency"] = "EUR"

    _validate(tmp_path, source)


def test_rebalance_market_input_references_accept_manual_overrides(tmp_path: Path) -> None:
    source = _source()
    reference_map = {"price:SYNTH": str(IDS["override"])}
    plan = source["data/rebalance_plans.json"][0]
    plan["input_summary"]["market_data_record_ids"] = reference_map
    plan["start_market_data_record_ids"] = reference_map
    plan["completion_market_data_record_ids"] = reference_map
    version_payload = {
        "market_data_record_ids": reference_map,
        "holding_versions": plan["input_summary"]["holding_versions"],
        "asset_class_targets": plan["input_summary"]["asset_class_targets"],
    }
    plan["data_version"] = rebalance_data_version(**version_payload)

    _validate(tmp_path, source)


def test_postgresql_integer_range_is_enforced(tmp_path: Path) -> None:
    source = _source()
    source["data/asset_classes.json"][0]["display_order"] = 2**31

    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_INCOMPATIBLE"


@pytest.mark.parametrize(
    ("member", "field", "missing_member"),
    [
        ("data/holdings.json", "asset_class_id", "data/asset_classes.json"),
        ("data/holding_defaults.json", "holding_id", "data/holdings.json"),
        ("data/cost_adjustments.json", "holding_id", "data/holdings.json"),
        ("data/snapshot_items.json", "snapshot_id", "data/snapshots.json"),
        ("data/snapshot_items.json", "holding_id", "data/holdings.json"),
        ("data/rebalance_plans.json", "before_snapshot_id", "data/snapshots.json"),
        ("data/rebalance_plans.json", "after_snapshot_id", "data/snapshots.json"),
    ],
)
def test_every_foreign_key_is_checked_on_disk(
    tmp_path: Path, member: str, field: str, missing_member: str
) -> None:
    source = _source()
    source[member][0][field] = UUID(int=999)
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_RELATIONSHIP_INVALID"


def test_duplicate_logical_identity_is_rejected(tmp_path: Path) -> None:
    source = _source()
    duplicate = dict(source["credentials.json"][0], id=UUID(int=998), value="another-synthetic")
    source["credentials.json"].append(duplicate)
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_RELATIONSHIP_INVALID"


@pytest.mark.parametrize("status", ["draft", "in_progress", "cancelled", "completed"])
def test_rebalance_lifecycle_combinations_are_strict(tmp_path: Path, status: str) -> None:
    source = _source()
    plan = source["data/rebalance_plans.json"][0]
    plan["status"] = status
    plan["before_snapshot_id"] = None
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_RELATIONSHIP_INVALID"


def test_rebalance_snapshot_type_and_market_data_references_are_checked(tmp_path: Path) -> None:
    source = _source()
    source["data/rebalance_plans.json"][0]["before_snapshot_id"] = IDS["after"]
    source["data/rebalance_plans.json"][0]["start_market_data_record_ids"] = {
        "price:SYNTH": str(UUID(int=999))
    }
    with pytest.raises(BackupValidationError) as exc_info:
        _validate(tmp_path, source)
    assert exc_info.value.code == "BACKUP_RELATIONSHIP_INVALID"


def _rewrite_manifest(path: Path, **updates: object) -> Path:
    destination = path.with_name("rewritten.portfolio-backup")
    with ZipFile(path) as source:
        manifest = json.loads(source.read("manifest.json"))
        manifest.update(updates)
        with ZipFile(destination, "w", compression=ZIP_DEFLATED) as target:
            for info in source.infolist():
                payload = canonical_json_bytes(manifest) if info.filename == "manifest.json" else source.read(info)
                target.writestr(info.filename, payload)
    return destination


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"format_version": CURRENT_FORMAT_VERSION + 1}, "BACKUP_FUTURE_VERSION"),
        ({"format_version": 0}, "BACKUP_INCOMPATIBLE"),
        ({"logical_checksum": "0" * 64}, "BACKUP_INCOMPATIBLE"),
    ],
)
def test_version_and_checksum_failures_are_sanitized(
    tmp_path: Path, updates: dict[str, object], code: str
) -> None:
    hostile = _rewrite_manifest(_archive(tmp_path), **updates)
    with pytest.raises(BackupValidationError) as exc_info:
        validate_backup(hostile, path_id="upload:test", expires_at=NOW, workspace_root=tmp_path)
    assert exc_info.value.code == code
    assert "synthetic-secret-never-leak" not in str(exc_info.value)


def test_token_is_hashed_one_time_expiring_and_bound_to_archive(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained, path_id="upload:retained", expires_at=NOW + timedelta(minutes=30),
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)

    token = registry.issue(validated)
    journal_bytes = next(storage.uploads_dir.glob("*.token.json")).read_bytes()
    assert token.encode() not in journal_bytes
    assert b"synthetic-secret" not in journal_bytes
    assert registry.consume(token).archive_sha256 == hashlib.sha256(retained.read_bytes()).hexdigest()
    with pytest.raises(BackupValidationError) as consumed:
        registry.consume(token)
    assert consumed.value.code == "BACKUP_TOKEN_INVALID"

    expired_token = registry.issue(replace(validated, expires_at=NOW))
    with pytest.raises(BackupValidationError) as expired:
        registry.consume(expired_token)
    assert expired.value.code == "BACKUP_TOKEN_EXPIRED"

    bound_token = registry.issue(validated)
    retained.write_bytes(b"changed")
    with pytest.raises(BackupValidationError) as changed:
        registry.consume(bound_token)
    assert changed.value.code == "BACKUP_TOKEN_INVALID"


def test_token_can_be_consumed_by_only_one_concurrent_caller(
    tmp_path: Path,
) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained,
        path_id="upload:retained",
        expires_at=NOW + timedelta(minutes=30),
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    token = registry.issue(validated)
    barrier = threading.Barrier(2)

    def consume() -> str:
        barrier.wait(timeout=5)
        try:
            registry.consume(token)
        except BackupValidationError as exc:
            return exc.code
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume(), range(2)))

    assert sorted(results) == ["BACKUP_TOKEN_INVALID", "success"]


def test_consumed_token_keeps_expiry_tombstone_until_upload_cleanup(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    expires_at = NOW + timedelta(minutes=30)
    validated = validate_backup(
        retained,
        path_id="upload:retained",
        expires_at=expires_at,
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    token = registry.issue(validated)

    registry.consume(token)

    assert len(list(storage.uploads_dir.glob("*.consumed.json"))) == 1
    manager = BackupOperationManager(storage, clock=lambda: expires_at)
    assert manager.cleanup_expired(now=expires_at) is False
    assert not retained.exists()
    assert not list(storage.uploads_dir.glob("*.consumed.json"))


def test_stale_unlocked_claim_is_recovered_without_consuming_source_journal(
    tmp_path: Path,
) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained,
        path_id="upload:retained",
        expires_at=NOW + timedelta(minutes=30),
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    token = registry.issue(validated)
    [journal] = storage.uploads_dir.glob("*.token.json")
    claim = storage.uploads_dir / journal.name.replace(".token.json", ".token.claimed")
    claim.write_text("{}")
    stale = (NOW - timedelta(minutes=6)).timestamp()
    os.utime(claim, (stale, stale))

    assert registry.cleanup_expired() is False
    assert not claim.exists()
    assert journal.exists()
    assert not list(storage.uploads_dir.glob("*.consumed.json"))
    assert registry.consume(token).path_id == "upload:retained"


def test_cleanup_does_not_steal_an_active_atomic_token_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_validation as module
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained, path_id="upload:retained", expires_at=NOW + timedelta(minutes=30),
        workspace_root=storage.tmp_dir,
    )
    clock = [NOW]
    registry = RestoreTokenRegistry(storage, clock=lambda: clock[0])
    token = registry.issue(validated)
    claimed = threading.Event()
    release = threading.Event()

    def pause(_path: Path) -> None:
        claimed.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(module, "_after_claim_file_created", pause, raising=False)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(registry.consume, token)
        assert claimed.wait(timeout=5)
        clock[0] = NOW + timedelta(minutes=10)
        assert registry.cleanup_expired() is False
        assert list(storage.uploads_dir.glob("*.token.claimed"))
        assert list(storage.uploads_dir.glob("*.token.json"))
        release.set()
        assert future.result(timeout=5).path_id == "upload:retained"


def test_naive_token_expiry_is_sanitized_as_invalid(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained, path_id="upload:retained", expires_at=NOW + timedelta(minutes=30),
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    token = registry.issue(validated)
    [journal] = storage.uploads_dir.glob("*.token.json")
    document = json.loads(journal.read_text())
    document["expires_at"] = "2026-08-24T04:30:00"
    journal.write_bytes(canonical_json_bytes(document))
    with pytest.raises(BackupValidationError) as exc_info:
        registry.consume(token)
    assert exc_info.value.code == "BACKUP_TOKEN_INVALID"


@pytest.mark.parametrize("failure", ["unlink", "fsync"])
def test_expired_consume_storage_failures_are_typed_sanitized_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained, path_id="upload:retained", expires_at=NOW,
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    token = registry.issue(validated)
    secret = f"private-{failure}-path SELECT credential-secret"
    real_unlink = Path.unlink
    real_fsync = storage._fsync_directory

    if failure == "unlink":
        def fail_unlink(path: Path, *args: object, **kwargs: object) -> None:
            if path == retained:
                raise OSError(secret)
            real_unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail_unlink)
    else:
        def fail_fsync(directory: Path) -> None:
            if directory == storage.uploads_dir and not retained.exists():
                raise OSError(secret)
            real_fsync(directory)
        monkeypatch.setattr(storage, "_fsync_directory", fail_fsync)

    with pytest.raises(BackupValidationError) as exc_info:
        registry.consume(token)
    error = exc_info.value
    assert error.code == "BACKUP_RESOURCE_LIMIT"
    assert error.status_code == 507
    assert secret not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in caplog.text
    assert list(storage.uploads_dir.glob("*.token.json"))
    assert not list(storage.uploads_dir.glob("*.consumed.json"))

    monkeypatch.setattr(Path, "unlink", real_unlink)
    monkeypatch.setattr(storage, "_fsync_directory", real_fsync)
    with pytest.raises(BackupValidationError) as retried:
        registry.consume(token)
    assert retried.value.code == "BACKUP_TOKEN_EXPIRED"
    assert list(storage.uploads_dir.glob("*.consumed.json"))


def test_open_index_closes_connection_when_schema_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_validation as module

    class FailingConnection:
        closed = False

        def execute(self, _statement: str) -> None:
            raise sqlite3.OperationalError("synthetic-private-sql")

        def close(self) -> None:
            self.closed = True

    connection = FailingConnection()
    monkeypatch.setattr(module.sqlite3, "connect", lambda _path: connection)
    with pytest.raises(sqlite3.OperationalError):
        module._open_index(tmp_path / "semantic.sqlite3")
    assert connection.closed is True


def test_semantic_index_resource_failures_are_typed_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_validation as module
    secret = "synthetic-private-sqlite-path"

    def fail_index(_path: Path):
        raise sqlite3.OperationalError(f"database full at /private/{secret}")

    monkeypatch.setattr(module, "_open_index", fail_index)

    with pytest.raises(BackupValidationError) as exc_info:
        validate_backup(
            _archive(tmp_path),
            path_id="upload:test",
            expires_at=NOW + timedelta(minutes=30),
            workspace_root=tmp_path,
        )
    assert exc_info.value.code == "BACKUP_RESOURCE_LIMIT"
    assert secret not in str(exc_info.value)


def test_expiry_cleanup_removes_upload_archive_and_token_journal(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained,
        path_id="upload:retained",
        expires_at=NOW,
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    registry.issue(validated)

    assert registry.cleanup_expired() is False
    assert not retained.exists()
    assert not list(storage.uploads_dir.glob("*.token.json"))


def test_expiry_cleanup_preserves_journal_for_retry_after_archive_delete_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained,
        path_id="upload:retained",
        expires_at=NOW,
        workspace_root=storage.tmp_dir,
    )
    registry = RestoreTokenRegistry(storage, clock=lambda: NOW)
    registry.issue(validated)
    real_unlink = Path.unlink
    failures = 0

    def fail_archive_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failures
        if path == retained and failures == 0:
            failures += 1
            raise OSError("synthetic private archive deletion failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_archive_once)

    assert registry.cleanup_expired() is True
    assert retained.exists()
    assert len(list(storage.uploads_dir.glob("*.token.json"))) == 1
    assert registry.cleanup_expired() is False
    assert not retained.exists()
    assert not list(storage.uploads_dir.glob("*.token.json"))


def test_periodic_backup_maintenance_cleans_expired_uploads(tmp_path: Path) -> None:
    storage = BackupStorage(tmp_path / "backups")
    storage.initialize()
    archive = _archive(tmp_path)
    retained = storage.uploads_dir / "retained.portfolio-backup"
    retained.write_bytes(archive.read_bytes())
    validated = validate_backup(
        retained,
        path_id="upload:retained",
        expires_at=NOW,
        workspace_root=storage.tmp_dir,
    )
    RestoreTokenRegistry(storage, clock=lambda: NOW).issue(validated)

    assert BackupOperationManager(storage, clock=lambda: NOW).cleanup_expired(now=NOW) is False
    assert not retained.exists()
