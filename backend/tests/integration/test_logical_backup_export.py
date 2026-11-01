from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backups.archive import ArchiveMetadata, inspect_archive, iter_current_rows, write_archive
from app.backups.canonical import encode_json_value
from app.backups.constants import DATA_MEMBERS
from app.backups.contracts import CREDENTIAL_CONTRACT, TABLE_CONTRACTS
from app.core.secrets import SecretStore
from app.db.models import (
    AssetClass,
    CostAdjustment,
    EncryptedSecret,
    Holding,
    HoldingDefault,
    MarketData,
    MarketDataOverride,
    RebalancePlan,
    Setting,
    Snapshot,
    SnapshotItem,
    DEFAULT_SETTINGS_ID,
)
from app.services import backup_export as backup_export_module
from app.services.backup_export import (
    BackupExportError,
    DatabaseLogicalSource,
    export_database_backup,
    export_logical_backup,
)
from app.services.backup_validation import validate_backup


FIXED_TIME = datetime(2026, 8, 23, 9, 10, 11, 123456, tzinfo=timezone(timedelta(hours=8)))
STORED_DECIMAL = Decimal("1234567890123456.123456789012")


def _id(value: int) -> UUID:
    return UUID(int=value)


def _metadata() -> ArchiveMetadata:
    return ArchiveMetadata(
        source_application_version="0.1.0-test",
        exported_at=FIXED_TIME,
        display_timezone="Asia/Shanghai",
    )


def _row(model: object, columns: tuple[str, ...]) -> dict[str, object]:
    return {column: getattr(model, column) for column in columns}


async def _stored_rows(session: AsyncSession, model: type[Any]) -> list[Any]:
    rows = await session.scalars(select(model).order_by(model.id))
    return list(rows)


async def _expected_document(
    session: AsyncSession,
    plaintext_by_provider: Mapping[str, str],
) -> dict[str, list[dict[str, object]]]:
    session.expire_all()
    document: dict[str, list[dict[str, object]]] = {}
    for contract in TABLE_CONTRACTS:
        models = await _stored_rows(session, contract.model)
        document[contract.member] = [
            encode_json_value(_row(model, contract.columns)) for model in models
        ]
    credentials = await _stored_rows(session, EncryptedSecret)
    document[CREDENTIAL_CONTRACT.member] = [
        encode_json_value(
            {
                column: (
                    plaintext_by_provider[credential.provider]
                    if column == "value"
                    else getattr(credential, column)
                )
                for column in CREDENTIAL_CONTRACT.columns
            }
        )
        for credential in credentials
    ]
    return document


def _archive_document(path: Path) -> dict[str, list[dict[str, object]]]:
    with inspect_archive(path) as archive:
        document = {member: list(iter_current_rows(archive, member)) for member in DATA_MEMBERS}
    return _normalize_parsed_json_numbers(document)


def _normalize_parsed_json_numbers(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_normalize_parsed_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_parsed_json_numbers(item) for key, item in value.items()}
    return value


async def _seed_complete_logical_state(
    session: AsyncSession,
    secret_store: SecretStore,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, str]]:
    active_class = AssetClass(
        id=_id(10),
        name="全球股票（主动）",
        target_weight=Decimal("0.600000000001"),
        display_order=2,
        is_active=True,
        notes="中文备注：保留原始字段",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME + timedelta(seconds=1),
    )
    inactive_class = AssetClass(
        id=_id(20),
        name="已停用债券",
        target_weight=Decimal("0.399999999999"),
        display_order=1,
        is_active=False,
        notes=None,
        created_at=FIXED_TIME + timedelta(seconds=2),
        updated_at=FIXED_TIME + timedelta(seconds=3),
    )
    session.add_all([inactive_class, active_class])

    active_holding = Holding(
        id=_id(30),
        asset_class_id=active_class.id,
        symbol="SYNTH-A",
        name="合成主动持仓",
        market="US",
        account_name="测试账户甲",
        trade_currency="USD",
        quantity=STORED_DECIMAL,
        average_cost_price=Decimal("12.123456789012"),
        cost_fx_to_cny=Decimal("7.123456789012"),
        baseline_fx_to_cny=Decimal("7.000000000001"),
        lot_size=Decimal("0.000000000001"),
        quantity_precision=12,
        preferred_data_source="synthetic-provider",
        is_rebalance_preferred=True,
        is_active=True,
        version=7,
        created_at=FIXED_TIME + timedelta(seconds=4),
        updated_at=FIXED_TIME + timedelta(seconds=5),
    )
    inactive_holding = Holding(
        id=_id(40),
        asset_class_id=inactive_class.id,
        symbol="SYNTH-I",
        name="已归档持仓",
        market="CN",
        account_name="测试账户乙",
        trade_currency="CNY",
        quantity=Decimal("0"),
        average_cost_price=Decimal("0"),
        cost_fx_to_cny=Decimal("1"),
        baseline_fx_to_cny=Decimal("1"),
        lot_size=Decimal("100"),
        quantity_precision=0,
        preferred_data_source=None,
        is_rebalance_preferred=False,
        is_active=False,
        version=3,
        created_at=FIXED_TIME + timedelta(seconds=6),
        updated_at=FIXED_TIME + timedelta(seconds=7),
    )
    session.add_all([inactive_holding, active_holding])
    session.add(
        HoldingDefault(
            id=_id(50),
            holding_id=active_holding.id,
            fee_currency="USD",
            commission_rate=Decimal("0.000123456789"),
            minimum_commission=Decimal("1.000000000001"),
            per_share_fee=Decimal("0.005000000001"),
            fixed_fee=Decimal("2.123456789012"),
            default_data_source="synthetic-provider",
            created_at=FIXED_TIME + timedelta(seconds=8),
            updated_at=FIXED_TIME + timedelta(seconds=9),
        )
    )
    session.add_all(
        [
            MarketData(
                id=_id(60),
                data_type="price",
                symbol=active_holding.symbol,
                source="synthetic-provider",
                value=Decimal("99.123456789012"),
                market_time=FIXED_TIME - timedelta(minutes=1),
                fetched_at=FIXED_TIME,
                status="success",
                error_summary=None,
                created_at=FIXED_TIME + timedelta(seconds=10),
            ),
            MarketData(
                id=_id(70),
                data_type="fx",
                symbol="USD/CNY",
                source="synthetic-provider",
                value=None,
                market_time=None,
                fetched_at=FIXED_TIME + timedelta(seconds=1),
                status="failed",
                error_summary="synthetic timeout without credentials",
                created_at=FIXED_TIME + timedelta(seconds=11),
            ),
        ]
    )
    session.add_all(
        [
            MarketDataOverride(
                id=_id(80),
                data_type="price",
                symbol=active_holding.symbol,
                value=Decimal("101.123456789012"),
                note="已过期人工覆盖",
                effective_at=FIXED_TIME - timedelta(days=2),
                expires_at=FIXED_TIME - timedelta(days=1),
                created_at=FIXED_TIME + timedelta(seconds=12),
                updated_at=FIXED_TIME + timedelta(seconds=13),
            ),
            MarketDataOverride(
                id=_id(90),
                data_type="fx",
                symbol="USD/CNY",
                value=Decimal("7.234567890123"),
                note="当前人工覆盖",
                effective_at=FIXED_TIME,
                expires_at=None,
                created_at=FIXED_TIME + timedelta(seconds=14),
                updated_at=FIXED_TIME + timedelta(seconds=15),
            ),
        ]
    )
    session.add(
        CostAdjustment(
            id=_id(100),
            holding_id=active_holding.id,
            operation_type="manual_correction",
            before_quantity=Decimal("1.000000000001"),
            before_average_cost_price=Decimal("2.000000000002"),
            before_cost_fx_to_cny=Decimal("3.000000000003"),
            after_quantity=Decimal("4.000000000004"),
            after_average_cost_price=Decimal("5.000000000005"),
            after_cost_fx_to_cny=Decimal("6.000000000006"),
            input_summary={"nested": {"ratio": 1.25}, "labels": ["中文", "synthetic"]},
            note="完整审计记录",
            created_at=FIXED_TIME + timedelta(seconds=16),
        )
    )

    snapshots = [
        Snapshot(
            id=_id(110),
            snapshot_type="daily",
            local_date=date(2026, 8, 20),
            captured_at=FIXED_TIME,
            note=None,
            data_complete=True,
            has_stale_data=False,
            has_manual_data=False,
            created_at=FIXED_TIME + timedelta(seconds=17),
        ),
        Snapshot(
            id=_id(120),
            snapshot_type="manual",
            local_date=date(2026, 8, 21),
            captured_at=FIXED_TIME + timedelta(hours=1),
            note="手工快照",
            data_complete=True,
            has_stale_data=True,
            has_manual_data=True,
            created_at=FIXED_TIME + timedelta(seconds=18),
        ),
        Snapshot(
            id=_id(130),
            snapshot_type="rebalance_before",
            local_date=date(2026, 8, 22),
            captured_at=FIXED_TIME + timedelta(hours=2),
            note="调仓前",
            data_complete=False,
            has_stale_data=True,
            has_manual_data=False,
            created_at=FIXED_TIME + timedelta(seconds=19),
        ),
        Snapshot(
            id=_id(140),
            snapshot_type="rebalance_after",
            local_date=date(2026, 8, 23),
            captured_at=FIXED_TIME + timedelta(hours=3),
            note="调仓后",
            data_complete=True,
            has_stale_data=False,
            has_manual_data=True,
            created_at=FIXED_TIME + timedelta(seconds=20),
        ),
    ]
    session.add_all(snapshots)
    await session.flush()
    session.add_all(
        [
            SnapshotItem(
                id=_id(150 + index),
                snapshot_id=snapshot.id,
                holding_id=active_holding.id if index != 2 else None,
                asset_class_name="全球股票（主动）",
                holding_name=f"不可变持仓副本 {index}",
                symbol=active_holding.symbol,
                account_name="测试账户甲",
                trade_currency="USD",
                quantity=Decimal(f"{index + 1}.123456789012"),
                market_price=None if index == 2 else Decimal("99.123456789012"),
                current_fx_to_cny=None if index == 2 else Decimal("7.123456789012"),
                baseline_fx_to_cny=Decimal("7.000000000001"),
                average_cost_price=Decimal("12.123456789012"),
                cost_fx_to_cny=Decimal("7.012345678901"),
                target_weight=Decimal("0.600000000001"),
                market_value_cny=None if index == 2 else Decimal("100.000000000001"),
                fx_neutral_value_cny=None if index == 2 else Decimal("98.000000000001"),
                cost_value_cny=None if index == 2 else Decimal("80.000000000001"),
                unrealized_pnl_amount_cny=None if index == 2 else Decimal("20.000000000001"),
                unrealized_pnl_rate=None if index == 2 else Decimal("0.250000000001"),
                price_effect_cny=None if index == 2 else Decimal("18.000000000001"),
                fx_effect_cny=None if index == 2 else Decimal("2.000000000001"),
                actual_weight=None if index == 2 else Decimal("0.610000000001"),
                fx_neutral_weight=None if index == 2 else Decimal("0.590000000001"),
                price_status="missing" if index == 2 else "fresh",
                fx_status="missing" if index == 2 else "manual",
                created_at=FIXED_TIME + timedelta(seconds=21 + index),
            )
            for index, snapshot in enumerate(snapshots)
        ]
    )

    plan_states = (
        ("draft", None, None, None),
        ("started", FIXED_TIME, None, None),
        ("cancelled", FIXED_TIME, FIXED_TIME + timedelta(minutes=1), None),
        ("completed", FIXED_TIME, None, FIXED_TIME + timedelta(minutes=2)),
    )
    for index, (status, started_at, cancelled_at, completed_at) in enumerate(plan_states):
        session.add(
            RebalancePlan(
                id=_id(170 + index),
                strategy_mode="full" if index % 2 else "cash_only",
                status=status,
                data_version=f"synthetic-version-{index}",
                create_idempotency_key=f"create-{index}",
                input_summary={"状态": status, "weights": [0.6, 0.4]},
                suggested_actions={"actions": [{"symbol": "SYNTH-A", "amount": 1.25}]},
                projected_result={"feasible": index != 2, "reason": None},
                before_snapshot_id=snapshots[2].id if index else None,
                after_snapshot_id=snapshots[3].id if status == "completed" else None,
                started_at=started_at,
                cancelled_at=cancelled_at,
                created_at=FIXED_TIME + timedelta(seconds=30 + index),
                updated_at=FIXED_TIME + timedelta(seconds=40 + index),
                baseline_reset_at=completed_at,
                start_market_data_record_ids={"price": str(_id(60))} if started_at else None,
                completion_market_data_record_ids={"fx": str(_id(70))} if completed_at else None,
                start_idempotency_key=f"start-{index}" if started_at else None,
                cancel_idempotency_key=f"cancel-{index}" if cancelled_at else None,
                complete_idempotency_key=f"complete-{index}" if completed_at else None,
                completed_at=completed_at,
            )
        )

    session.add(
        Setting(
            id=_id(1),
            refresh_hour=7,
            refresh_minute=45,
            provider_priority=["synthetic-provider", "备用源"],
            default_tolerance=Decimal("0.012345678901"),
            minimum_trade_amount_cny=Decimal("88.123456789012"),
            allow_sell=False,
            allow_fx=True,
            rebalance_available_cny=Decimal("1000.123456789012"),
            rebalance_available_usd=Decimal("200.123456789012"),
            rebalance_valuation_basis="fx_neutral",
            email_enabled=True,
            email_recipient="synthetic@example.test",
            email_smtp_host="smtp.example.test",
            email_smtp_port=465,
            email_smtp_security="ssl",
            email_smtp_username="synthetic-user@example.test",
            email_from="synthetic-sender@example.test",
            created_at=FIXED_TIME + timedelta(seconds=50),
            updated_at=FIXED_TIME + timedelta(seconds=51),
        )
    )

    plaintext_by_provider = {
        "synthetic-provider": "synthetic-api-secret",
        "smtp": "synthetic-smtp-secret",
    }
    session.add_all(
        [
            EncryptedSecret(
                id=_id(200 + index),
                provider=provider,
                encrypted_value=secret_store.encrypt(plaintext).decode("ascii"),
                masked_value="****etic",
                validation_status="valid" if index == 0 else "untested",
                validation_message="合成验证通过" if index == 0 else None,
                last_validated_at=FIXED_TIME if index == 0 else None,
                created_at=FIXED_TIME + timedelta(seconds=60 + index),
                updated_at=FIXED_TIME + timedelta(seconds=70 + index),
            )
            for index, (provider, plaintext) in enumerate(plaintext_by_provider.items())
        ]
    )
    await session.commit()
    expected = await _expected_document(session, plaintext_by_provider)
    await session.rollback()
    return expected, plaintext_by_provider


@pytest.mark.asyncio
async def test_export_contains_every_business_row_and_plaintext_secret(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    secret_store = SecretStore(tmp_path / "synthetic-fernet.key")
    expected, plaintext_by_provider = await _seed_complete_logical_state(db_session, secret_store)
    destination = tmp_path / "complete-state.portfolio-backup"

    async with db_session.begin():
        summary = await export_logical_backup(
            db_session,
            destination,
            secret_store=secret_store,
            metadata=_metadata(),
        )
        assert db_session.in_transaction()

    actual = _archive_document(destination)
    assert actual == expected
    assert summary.record_counts == {member: len(rows) for member, rows in expected.items()}
    credential_rows = actual[CREDENTIAL_CONTRACT.member]
    assert {row["provider"]: row["value"] for row in credential_rows} == plaintext_by_provider
    assert all("encrypted_value" not in row for row in credential_rows)


@pytest.mark.asyncio
async def test_export_then_validate_preserves_seed_and_legacy_provider_priority(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    key_path = tmp_path / "synthetic-fernet.key"
    SecretStore(key_path)
    monkeypatch.setattr(
        backup_export_module,
        "SessionFactory",
        async_sessionmaker(db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        backup_export_module,
        "get_settings",
        lambda: SimpleNamespace(secret_key_path=str(key_path), timezone="Asia/Shanghai"),
    )
    db_session.add(AssetClass(
        id=_id(901), name="Synthetic", target_weight=Decimal("1"),
        display_order=0, is_active=True, created_at=now, updated_at=now,
    ))
    setting = Setting(
        id=DEFAULT_SETTINGS_ID, refresh_hour=7, refresh_minute=30,
        provider_priority=[], default_tolerance=Decimal("0.01"),
        minimum_trade_amount_cny=Decimal("100"), allow_sell=True, allow_fx=True,
        rebalance_available_cny=Decimal("0"), rebalance_available_usd=Decimal("0"),
        rebalance_valuation_basis="actual", email_enabled=False,
        email_recipient=None, email_smtp_host=None, email_smtp_port=465,
        email_smtp_security="ssl", email_smtp_username=None, email_from=None,
        created_at=now, updated_at=now,
    )
    db_session.add(setting)
    await db_session.commit()
    for index, priority in enumerate(
        [[], ["akshare", "yahoo", "tushare", "alpha_vantage"]]
    ):
        setting.provider_priority = priority
        await db_session.commit()
        destination = tmp_path / f"priority-{index}.portfolio-backup"

        await export_database_backup(destination)
        validate_backup(destination, path_id="upload:test", workspace_root=tmp_path)

        with inspect_archive(destination) as inspected:
            [settings] = list(iter_current_rows(inspected, "data/settings.json"))
        assert settings["provider_priority"] == priority


@pytest.mark.asyncio
async def test_every_collection_is_keyset_batched_and_archive_rows_are_in_id_order(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = SecretStore(tmp_path / "synthetic-fernet.key")
    observed_batches: list[tuple[str, UUID | None, int]] = []
    original_fetch_batch = DatabaseLogicalSource._fetch_batch

    async def track_fetch_batch(
        self: DatabaseLogicalSource,
        contract: Any,
        last_id: UUID | None,
    ) -> list[dict[str, object]]:
        rows = await original_fetch_batch(self, contract, last_id)
        observed_batches.append((contract.member, last_id, len(rows)))
        return rows

    monkeypatch.setattr(DatabaseLogicalSource, "_fetch_batch", track_fetch_batch)
    ids = [_id(value) for value in range(3000, 4001)]
    db_session.add_all(
        [
            AssetClass(
                id=row_id,
                name=f"synthetic-{row_id}",
                target_weight=Decimal("0"),
                display_order=index,
                is_active=True,
                notes=None,
                created_at=FIXED_TIME,
                updated_at=FIXED_TIME,
            )
            for index, row_id in enumerate(reversed(ids))
        ]
    )
    await db_session.commit()
    destination = tmp_path / "batched.portfolio-backup"

    async with db_session.begin():
        await export_logical_backup(
            db_session,
            destination,
            secret_store=secret_store,
            metadata=_metadata(),
        )

    actual_ids = [row["id"] for row in _archive_document(destination)["data/asset_classes.json"]]
    assert actual_ids == [str(row_id) for row_id in ids]
    assert len(actual_ids) == 1001
    assert {member for member, last_id, _ in observed_batches if last_id is None} == set(DATA_MEMBERS)
    assert [
        (last_id, size)
        for member, last_id, size in observed_batches
        if member == "data/asset_classes.json"
    ] == [(None, 1000), (_id(3999), 1)]


@pytest.mark.asyncio
async def test_plaintext_credentials_never_enter_the_adapter_disk_spool(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    secret_store = SecretStore(tmp_path / "synthetic-fernet.key")
    plaintext = "synthetic-api-secret-only-in-memory"
    db_session.add(
        EncryptedSecret(
            id=_id(4500),
            provider="synthetic-provider",
            encrypted_value=secret_store.encrypt(plaintext).decode("ascii"),
            masked_value="****mory",
            validation_status=None,
            validation_message=None,
            last_validated_at=None,
            created_at=FIXED_TIME,
            updated_at=FIXED_TIME,
        )
    )
    await db_session.commit()
    workspace = tmp_path / "adapter-spool"
    workspace.mkdir()

    async with db_session.begin():
        source = await DatabaseLogicalSource(
            db_session,
            secret_store=secret_store,
        ).stage(workspace)

    assert [row["value"] for row in source[CREDENTIAL_CONTRACT.member]] == [plaintext]
    assert all(plaintext.encode("utf-8") not in path.read_bytes() for path in workspace.iterdir())
    assert not any("credentials" in path.name for path in workspace.iterdir())


@pytest.mark.asyncio
async def test_manual_export_uses_one_read_only_repeatable_read_snapshot(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "synthetic-fernet.key"
    SecretStore(key_path)
    first_batch_ready = asyncio.Event()
    release_export = asyncio.Event()
    transaction_modes: dict[str, str] = {}
    initial_ids = [_id(value) for value in range(5000, 6000)]
    db_session.add_all(
        [
            AssetClass(
                id=row_id,
                name=f"initial-{row_id}",
                target_weight=Decimal("0"),
                display_order=index,
                is_active=True,
                notes=None,
                created_at=FIXED_TIME,
                updated_at=FIXED_TIME,
            )
            for index, row_id in enumerate(initial_ids)
        ]
    )
    await db_session.commit()

    original_fetch_batch = DatabaseLogicalSource._fetch_batch

    async def controlled_fetch_batch(
        self: DatabaseLogicalSource,
        contract: Any,
        last_id: UUID | None,
    ) -> list[dict[str, object]]:
        rows = await original_fetch_batch(self, contract, last_id)
        if contract.member == "data/asset_classes.json" and last_id is None:
            isolation = await self.session.scalar(select_transaction_setting("transaction_isolation"))
            read_only = await self.session.scalar(select_transaction_setting("transaction_read_only"))
            transaction_modes.update(isolation=str(isolation), read_only=str(read_only))
            first_batch_ready.set()
            await release_export.wait()
        return rows

    monkeypatch.setattr(DatabaseLogicalSource, "_fetch_batch", controlled_fetch_batch)
    monkeypatch.setattr(
        backup_export_module,
        "get_settings",
        lambda: SimpleNamespace(
            secret_key_path=str(key_path),
            timezone="Asia/Shanghai",
        ),
    )
    destination = tmp_path / "consistent.portfolio-backup"
    export_task = asyncio.create_task(export_database_backup(destination))
    await asyncio.wait_for(first_batch_ready.wait(), timeout=10)

    concurrent_id = _id(6001)
    concurrent_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with concurrent_factory() as concurrent_session:
        concurrent_session.add(
            AssetClass(
                id=concurrent_id,
                name="concurrent-row",
                target_weight=Decimal("0"),
                display_order=1001,
                is_active=True,
                notes=None,
                created_at=FIXED_TIME,
                updated_at=FIXED_TIME,
            )
        )
        await concurrent_session.commit()
    release_export.set()
    await export_task

    actual_ids = {
        row["id"] for row in _archive_document(destination)["data/asset_classes.json"]
    }
    assert actual_ids == {str(row_id) for row_id in initial_ids}
    assert str(concurrent_id) not in actual_ids
    assert transaction_modes == {"isolation": "repeatable read", "read_only": "on"}


def select_transaction_setting(name: str) -> Any:
    from sqlalchemy import text

    return text(f"SELECT current_setting('{name}')")


class _ExitFailingTransaction:
    def __init__(self, delegate: Any, *, fail: bool) -> None:
        self.delegate = delegate
        self.fail = fail

    async def __aenter__(self) -> Any:
        return await self.delegate.__aenter__()

    async def __aexit__(self, *args: Any) -> bool:
        result = await self.delegate.__aexit__(*args)
        if self.fail:
            raise RuntimeError("injected transaction exit failure")
        return result


class _ExitFailingSession:
    def __init__(self, delegate: AsyncSession, *, failure_phase: str) -> None:
        self.delegate = delegate
        self.failure_phase = failure_phase

    async def __aenter__(self) -> _ExitFailingSession:
        await self.delegate.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool:
        result = await self.delegate.__aexit__(*args)
        if self.failure_phase == "session":
            raise RuntimeError("injected session exit failure")
        return result

    def begin(self) -> _ExitFailingTransaction:
        return _ExitFailingTransaction(
            self.delegate.begin(),
            fail=self.failure_phase == "transaction",
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["transaction", "session"])
async def test_manual_export_publishes_only_after_transaction_and_session_exit(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    key_path = tmp_path / "synthetic-fernet.key"
    SecretStore(key_path)
    destination = tmp_path / "existing.portfolio-backup"
    write_archive(destination, {member: [] for member in DATA_MEMBERS}, _metadata())
    sentinel_bytes = destination.read_bytes()
    real_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    monkeypatch.setattr(
        backup_export_module,
        "SessionFactory",
        lambda: _ExitFailingSession(
            real_factory(),
            failure_phase=failure_phase,
        ),
    )
    monkeypatch.setattr(
        backup_export_module,
        "get_settings",
        lambda: SimpleNamespace(
            secret_key_path=str(key_path),
            timezone="Asia/Shanghai",
        ),
    )

    with pytest.raises(RuntimeError, match=f"injected {failure_phase} exit failure"):
        await export_database_backup(destination)

    assert destination.read_bytes() == sentinel_bytes
    assert not list(tmp_path.glob(f".{destination.name}.*.complete"))


@pytest.mark.asyncio
async def test_decryption_failure_is_sanitized_and_leaves_no_archive(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    secret_store = SecretStore(tmp_path / "synthetic-fernet.key")
    db_session.add(
        EncryptedSecret(
            id=_id(7000),
            provider="synthetic-provider",
            encrypted_value="not-a-fernet-token",
            masked_value="****etic",
            validation_status=None,
            validation_message=None,
            last_validated_at=None,
            created_at=FIXED_TIME,
            updated_at=FIXED_TIME,
        )
    )
    await db_session.commit()
    destination = tmp_path / "must-not-exist.portfolio-backup"

    async with db_session.begin():
        with pytest.raises(BackupExportError, match="credential decryption failed") as exc_info:
            await export_logical_backup(
                db_session,
                destination,
                secret_store=secret_store,
                metadata=_metadata(),
            )

    assert "not-a-fernet-token" not in str(exc_info.value)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.asyncio
async def test_unicode_decryption_failure_does_not_retain_or_log_plaintext_bytes(
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_store = SecretStore(tmp_path / "synthetic-fernet.key")
    secret_bytes = b"\xffsynthetic-plaintext-must-not-escape"
    db_session.add(
        EncryptedSecret(
            id=_id(7100),
            provider="synthetic-provider",
            encrypted_value=secret_store.fernet.encrypt(secret_bytes).decode("ascii"),
            masked_value="****cape",
            validation_status=None,
            validation_message=None,
            last_validated_at=None,
            created_at=FIXED_TIME,
            updated_at=FIXED_TIME,
        )
    )
    await db_session.commit()

    async with db_session.begin():
        with pytest.raises(BackupExportError, match="credential decryption failed") as exc_info:
            await export_logical_backup(
                db_session,
                tmp_path / "must-not-exist.portfolio-backup",
                secret_store=secret_store,
                metadata=_metadata(),
            )

    error = exc_info.value
    assert error.__cause__ is None
    assert error.__context__ is None
    exposed_text = "\n".join((repr(error), caplog.text))
    assert "synthetic-plaintext-must-not-escape" not in exposed_text
