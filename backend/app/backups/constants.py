from __future__ import annotations

CURRENT_FORMAT_VERSION = 1

MANIFEST_MEMBER = "manifest.json"
CREDENTIALS_MEMBER = "credentials.json"
TABLE_MEMBERS = (
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
DATA_MEMBERS = (CREDENTIALS_MEMBER, *TABLE_MEMBERS)
ALLOWED_MEMBERS = (MANIFEST_MEMBER, *DATA_MEMBERS)

MAX_COMPRESSED_BYTES = 500 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_AGGREGATE_COMPRESSION_RATIO = 100
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
