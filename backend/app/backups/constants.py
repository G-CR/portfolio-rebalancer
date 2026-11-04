from __future__ import annotations

CURRENT_FORMAT_VERSION = 3

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

# Format 2 was shipped by the (since reverted) long-term ledger build.  Those
# archives carry extra members that the current application does not persist.
# They are accepted, verified byte-for-byte, and then intentionally ignored.
LEGACY_V2_TABLE_MEMBERS = (
    "data/reference_fx_days.json",
    "data/reference_fx_revisions.json",
    "data/ledger_periods.json",
    "data/ledger_openings.json",
    "data/ledger_entries.json",
    "data/decision_policy.json",
    "data/decision_observations.json",
    "data/notification_outbox.json",
)
LEGACY_V2_DATA_MEMBERS = (*V1_DATA_MEMBERS, *LEGACY_V2_TABLE_MEMBERS)

# Current archives keep exactly the original business tables.
TABLE_MEMBERS = V1_TABLE_MEMBERS
DATA_MEMBERS = V1_DATA_MEMBERS
ALLOWED_MEMBERS = (MANIFEST_MEMBER, *LEGACY_V2_DATA_MEMBERS)


def data_members_for_version(version: int) -> tuple[str, ...]:
    if version == 2:
        return LEGACY_V2_DATA_MEMBERS
    return V1_DATA_MEMBERS

MAX_COMPRESSED_BYTES = 500 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_AGGREGATE_COMPRESSION_RATIO = 100
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
# A single logical row is bounded independently of the 2 GiB archive limit so
# JSON parsing can never turn one hostile scalar/container into unbounded RAM.
MAX_LOGICAL_ROW_BYTES = 16 * 1024 * 1024
ROW_SCAN_CHUNK_BYTES = 64 * 1024
