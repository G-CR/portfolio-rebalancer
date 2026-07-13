from sqlalchemy import text


async def test_initial_migration_creates_core_tables(db_session) -> None:
    rows = await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    names = {row[0] for row in rows}

    assert {
        "asset_classes",
        "holdings",
        "holding_defaults",
        "market_data",
        "market_data_overrides",
        "cost_adjustments",
        "snapshots",
        "snapshot_items",
        "rebalance_plans",
        "settings",
        "encrypted_secrets",
    } <= names
