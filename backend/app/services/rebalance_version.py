from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def rebalance_preview_input_signature(
    *,
    effective_inputs: Mapping[str, tuple[str | None, str, str | None, str]],
    holding_versions: Mapping[str, int],
    asset_class_targets: Mapping[str, str],
) -> str:
    """Hash the values and versions that produced a preview result."""
    payload = {
        "effective_inputs": dict(effective_inputs),
        "holding_versions": dict(holding_versions),
        "asset_class_targets": dict(asset_class_targets),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def rebalance_data_version(
    *,
    market_data_record_ids: Mapping[str, str],
    holding_versions: Mapping[str, int],
    asset_class_targets: Mapping[str, str],
    **_ignored: object,
) -> str:
    """Hash the exact persisted inputs that define a modern rebalance plan."""
    payload = {
        "market_data_record_ids": dict(market_data_record_ids),
        "holding_versions": dict(holding_versions),
        "asset_class_targets": dict(asset_class_targets),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
