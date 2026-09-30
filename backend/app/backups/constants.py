from __future__ import annotations

CURRENT_FORMAT_VERSION = 2

MANIFEST_MEMBER = "manifest.json"
CREDENTIALS_MEMBER = "credentials.json"
V1_TABLE_MEMBERS = (
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
V1_DATA_MEMBERS = (CREDENTIALS_MEMBER, *V1_TABLE_MEMBERS)
NEW_TABLE_MEMBERS = (
    "data/reference_fx_days.json",
    "data/reference_fx_revisions.json",
    "data/ledger_periods.json",
    "data/ledger_openings.json",
    "data/ledger_entries.json",
    "data/decision_policy.json",
    "data/decision_observations.json",
    "data/notification_outbox.json",
)
TABLE_MEMBERS = (*V1_TABLE_MEMBERS, *NEW_TABLE_MEMBERS)
DATA_MEMBERS = (CREDENTIALS_MEMBER, *TABLE_MEMBERS)

def data_members_for_version(version: int) -> tuple[str, ...]:
    # Unknown older versions still receive byte checks before migration rejection.
    return V1_DATA_MEMBERS if version == 1 else DATA_MEMBERS

ALLOWED_MEMBERS = (MANIFEST_MEMBER, *DATA_MEMBERS)

MAX_COMPRESSED_BYTES = 500 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_AGGREGATE_COMPRESSION_RATIO = 100
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
# A single logical row is bounded independently of the 2 GiB archive limit so
# JSON parsing can never turn one hostile scalar/container into unbounded RAM.
MAX_LOGICAL_ROW_BYTES = 16 * 1024 * 1024
ROW_SCAN_CHUNK_BYTES = 64 * 1024
