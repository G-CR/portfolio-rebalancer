# Full Backup and Restore Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Add a browser-based, versioned logical backup workflow that exports every persisted business record and plaintext external-service credential, validates uploads without writes, and atomically replaces the current state only after creating a durable pre-restore safety backup.

**Architecture:** Keep archive formatting, database export/import, storage, operation coordination, and HTTP routing as separate layers. A single API-process operation manager serializes export/restore work and persists sanitized journals on an API-only `backup_data` volume. Restore uses one PostgreSQL transaction for fixed-order table locking, safety export, replacement, and post-write logical checksum verification; archive compatibility is handled by explicit pure migrations before database code sees the document.

**Tech Stack:** FastAPI, SQLAlchemy async/PostgreSQL, Pydantic, `zipfile`, `ijson`, Fernet, React 19, TanStack Query, Vitest/MSW, pytest, Docker Compose.

---

## Guardrails and final file map

- Run every database-changing test only with `make test-backend`; it enforces `COMPOSE_PROJECT_NAME=portfolio-rebalancer-test`, `POSTGRES_DB=portfolio_test`, a reset token, disposable test volumes, and cleanup. Never point ad-hoc pytest commands at the normal Compose project.
- Use synthetic credentials only. Assert they do not appear in logs, API error bodies, archive filenames, or operation journals.
- Keep `scripts/backup.sh`, `scripts/restore.sh`, and their existing integration coverage unchanged; the logical backup is an additional recovery layer.
- Use atomic temp-file replacement for archives and journals. The API container owns `/var/lib/portfolio-backups` with directory mode `0700` and file mode `0600`.

Create:

- `backend/app/backups/__init__.py`
- `backend/app/backups/constants.py`
- `backend/app/backups/contracts.py`
- `backend/app/backups/canonical.py`
- `backend/app/backups/migrations.py`
- `backend/app/backups/archive.py`
- `backend/app/services/backup_export.py`
- `backend/app/services/backup_storage.py`
- `backend/app/services/backup_validation.py`
- `backend/app/services/backup_restore.py`
- `backend/app/services/backup_operations.py`
- `backend/app/schemas/backup.py`
- `backend/app/api/routes/backups.py`
- `backend/tests/fixtures/backups/v1-minimal.portfolio-backup`
- `backend/tests/unit/test_backup_archive.py`
- `backend/tests/unit/test_backup_operations.py`
- `backend/tests/unit/test_backup_validation.py`
- `backend/tests/integration/test_logical_backup_export.py`
- `backend/tests/integration/test_logical_backup_restore.py`
- `backend/tests/integration/test_backup_api.py`
- `frontend/src/features/backups/api.ts`
- `frontend/src/features/backups/BackupRestorePanel.tsx`
- `frontend/src/features/backups/BackupRestore.module.css`
- `frontend/tests/BackupRestorePanel.test.tsx`

Modify:

- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/app/api/router.py`
- `backend/app/worker.py`
- `backend/tests/conftest.py`
- `backend/tests/unit/test_worker.py`
- `compose.yaml`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/pages/SnapshotsPage.tsx`
- `frontend/tests/SnapshotsPage.test.tsx`
- `README.md`

## Task 1: Freeze the v1 archive contract and safe streaming codec

**Files:**

- Create: `backend/app/backups/__init__.py`
- Create: `backend/app/backups/constants.py`
- Create: `backend/app/backups/contracts.py`
- Create: `backend/app/backups/canonical.py`
- Create: `backend/app/backups/migrations.py`
- Create: `backend/app/backups/archive.py`
- Create: `backend/tests/unit/test_backup_archive.py`
- Create: `backend/tests/fixtures/backups/v1-minimal.portfolio-backup`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`

### Step 1: Write the failing archive-contract tests

Cover exact allowlisted members, duplicate/unknown/path-traversal/absolute/symlink rejection, 500 MB compressed limit, 2 GB uncompressed limit, 100:1 aggregate ratio, per-member SHA-256 and length checks, malformed JSON, future-version rejection, unknown-field rejection, stable canonical checksums, exact decimal/date/datetime/UUID encoding, Chinese text, nulls, and the committed v1 golden fixture.

Also compare every SQLAlchemy model column with the explicit v1 table contract so a future persisted-field change cannot silently disappear from backups:

```python
def test_v1_contract_covers_every_persisted_column() -> None:
    for contract in TABLE_CONTRACTS:
        assert tuple(column.name for column in contract.model.__table__.columns) == contract.columns

def test_canonical_checksum_ignores_input_row_and_object_order() -> None:
    assert logical_checksum(shuffled_document()) == logical_checksum(canonical_document())

def test_future_archive_is_rejected_before_document_validation(tmp_path: Path) -> None:
    archive = write_test_archive(tmp_path, format_version=CURRENT_FORMAT_VERSION + 1)
    with pytest.raises(UnsupportedBackupVersion):
        read_and_validate_archive(archive)
```

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_backup_archive.py -q'
```

Expected: FAIL because the backup package does not exist.

### Step 2: Implement explicit contracts and canonical values

Define `CURRENT_FORMAT_VERSION = 1`, exact member names, limits, and a `TableContract` per non-secret collection. Every contract lists columns in model order plus type codecs; `encrypted_secrets` is represented separately as credential records containing the plaintext value and all non-secret metadata except `encrypted_value`.

```python
@dataclass(frozen=True, slots=True)
class TableContract:
    member: str
    model: type[Base]
    columns: Sequence[str]
    order_key: str = "id"

TABLE_CONTRACTS = (
    TableContract(
        "data/asset_classes.json",
        AssetClass,
        ("id", "name", "target_weight", "display_order", "is_active", "notes", "created_at", "updated_at"),
    ),
)
```

The production tuple must contain the other nine collections listed in the archive layout and every column shown by their corresponding models. The coverage test above enforces the exact list at runtime; do not derive it dynamically.

Canonicalize dictionaries by Unicode key order and collection rows by stringified primary key. Encode `Decimal` with `format(value, "f")`, UUID/date/datetime as strings, require timezone-aware datetimes, and hash the canonical current-format logical document excluding `manifest.json`.

### Step 3: Add streamed JSON-array and ZIP validation

Add `ijson>=3.4,<4` and lock it with the repository's normal `uv lock` workflow. Use `ijson.items(member_stream, "item")` so a 2 GB declared archive is never loaded as one Python object. Check `ZipInfo` metadata before extraction, stream each allowlisted member while measuring observed bytes/hash, and reject any exact-member or resource-limit violation.

Expose four typed core interfaces: `write_archive(destination, source, metadata) -> ArchiveSummary`, `inspect_archive(path) -> InspectedArchive`, `iter_current_rows(archive, member) -> Iterator[dict[str, JsonValue]]`, and `migrate_to_current(archive) -> MigratedArchive`.

`migrations.py` contains a registry keyed by source version. Version 1 is identity; missing paths and future versions raise typed sanitized exceptions. Generate the secret-free deterministic golden archive through the production writer, commit it, and make the fixture test open it through the production reader.

### Step 4: Verify and commit

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_backup_archive.py -q'
```

Expected: PASS.

Commit:

```bash
git add backend/app/backups backend/tests/unit/test_backup_archive.py backend/tests/fixtures/backups backend/pyproject.toml backend/uv.lock
git commit -m "feat: define versioned logical backup archive"
```

## Task 2: Export a consistent logical database snapshot

**Files:**

- Create: `backend/app/services/backup_export.py`
- Create: `backend/tests/integration/test_logical_backup_export.py`

### Step 1: Write the failing full-export integration test

Seed every table with active/inactive holdings, 12-place decimals, failed/successful market data, expired overrides, all snapshot and rebalance states, Chinese text, and synthetic provider/SMTP secrets encrypted by the test Fernet key. Export, inspect, and assert every normalized field, relationship, original ID/timestamp/version, record count, and plaintext credential is present.

```python
async def test_export_contains_every_business_row_and_plaintext_secret(db_session, tmp_path):
    expected = await seed_complete_logical_state(db_session)
    result = await export_database_backup(db_session, tmp_path / "state.portfolio-backup")
    inspected = inspect_archive(result.path)
    assert inspected.summary.record_counts == expected.record_counts
    assert normalize_archive(inspected) == expected.logical_document
    assert b"synthetic-api-secret" in read_member(result.path, "credentials.json")
```

Run:

```bash
make test-backend PYTEST_ARGS='tests/integration/test_logical_backup_export.py -q'
```

Expected: FAIL because the export service does not exist.

### Step 2: Implement transaction-owned, keyset-batched export

The core exporter accepts an already-open `AsyncSession`; it never opens or commits a transaction. That permits both manual read-only export and the pre-restore safety export to reuse exactly the restore transaction and its held locks.

```python
async def export_logical_backup(
    session: AsyncSession,
    destination: Path,
    *,
    secret_store: SecretStore,
    metadata: ExportMetadata,
) -> ArchiveSummary:
    source = DatabaseLogicalSource(session, secret_store=secret_store, batch_size=1000)
    return await write_archive_async(destination, source, metadata)

async def export_database_backup(destination: Path) -> ArchiveSummary:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            return await export_logical_backup(
                session,
                destination,
                secret_store=SecretStore(Path(get_settings().secret_key_path)),
                metadata=build_export_metadata(get_settings()),
            )
```

For each collection query `ORDER BY id` and keyset with `WHERE id > :last_id LIMIT 1000`. Decrypt `EncryptedSecret.encrypted_value` in memory and emit plaintext only to `credentials.json`; never log rows or exception values.

### Step 3: Prove snapshot consistency and batching

Add tests that insert a concurrent row after the first batch and prove it is not partially included, and that a table larger than one batch is exported in stable ID order. Add a test that the exporter fails cleanly on decryption error without leaving a complete destination file.

### Step 4: Verify and commit

Run:

```bash
make test-backend PYTEST_ARGS='tests/integration/test_logical_backup_export.py -q'
```

Expected: PASS.

Commit:

```bash
git add backend/app/services/backup_export.py backend/tests/integration/test_logical_backup_export.py
git commit -m "feat: export complete logical portfolio state"
```

## Task 3: Add durable storage, serialized operations, and export/safety APIs

**Files:**

- Create: `backend/app/services/backup_storage.py`
- Create: `backend/app/services/backup_operations.py`
- Create: `backend/app/schemas/backup.py`
- Create: `backend/app/api/routes/backups.py`
- Create: `backend/tests/unit/test_backup_operations.py`
- Create: `backend/tests/integration/test_backup_api.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/tests/conftest.py`
- Modify: `compose.yaml`

### Step 1: Write failing operation/storage/API tests

Test atomic journal writes, `0700` directories, `0600` files, one active operation only, sanitized failures, startup transition from `running` to `interrupted`, manual-export expiry after 30 minutes, safety list/download/delete, no-store response headers, and retention of exactly five validated safety archives only after the sixth is durable.

Test these endpoints and schemas:

```text
POST   /api/backups/export
GET    /api/backups/operations/{operation_id}
GET    /api/backups/operations/{operation_id}/download
GET    /api/backups/safety
GET    /api/backups/safety/{backup_id}/download
DELETE /api/backups/safety/{backup_id}
```

```python
class BackupOperationResponse(BaseModel):
    id: UUID
    kind: Literal["export", "restore"]
    status: Literal["pending", "running", "succeeded", "failed", "interrupted"]
    stage: BackupStage
    error: BackupError | None = None
    download_ready: bool = False
```

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_backup_operations.py tests/integration/test_backup_api.py -q'
```

Expected: FAIL because storage, manager, and routes do not exist.

### Step 2: Implement volume-backed storage and operation manager

Add settings for `backup_root=/var/lib/portfolio-backups`, 30-minute upload/export TTL, five-file retention, and limits from Task 1. Create subdirectories `operations`, `exports`, `uploads`, `safety`, and `tmp` with restrictive modes.

The manager owns an `asyncio.Lock` plus a short state mutex around `_active_operation_id`; a second start returns `409 BACKUP_OPERATION_CONFLICT` instead of queueing. It creates background tasks with fresh `SessionFactory` sessions, writes stage/status journals by temp-file + `os.replace`, catches all internal exceptions into allowlisted error categories, and never stores raw exception text. Startup recovery marks unfinished journals interrupted and removes orphan partial files.

```python
async def start(self, kind: OperationKind, runner: OperationRunner) -> BackupOperation:
    async with self._state_lock:
        if self._active_operation_id is not None:
            raise BackupOperationConflict()
        operation = self._new_operation(kind)
        self._active_operation_id = operation.id
    self._tasks[operation.id] = asyncio.create_task(self._run(operation, runner))
    return operation
```

### Step 3: Wire export and safety storage routes

`POST /export` returns `202`; status polling returns the journal; download only succeeds after export completion and sends `Content-Disposition`, `Cache-Control: no-store`, and `Pragma: no-cache`. A completed download attempts deletion, while periodic cleanup guarantees 30-minute expiry. Safety deletion rejects an active/referenced item and uses its own explicit `confirm=true` query/body contract, not a restore token.

Modify `main.py` lifespan to initialize storage, recover interrupted operations, start cleanup, and stop manager tasks before disposing the engine. Mount `backup_data:/var/lib/portfolio-backups` only on `api`, add the named volume, and ensure test configuration points backup storage at a disposable temporary directory/volume.

### Step 4: Verify and commit

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_backup_operations.py tests/integration/test_backup_api.py -q'
```

Expected: PASS.

Commit:

```bash
git add backend/app/services/backup_storage.py backend/app/services/backup_operations.py backend/app/schemas/backup.py backend/app/api/routes/backups.py backend/app/core/config.py backend/app/main.py backend/app/api/router.py backend/tests/conftest.py backend/tests/unit/test_backup_operations.py backend/tests/integration/test_backup_api.py compose.yaml
git commit -m "feat: expose durable backup export operations"
```

## Task 4: Validate uploaded and safety archives without database writes

**Files:**

- Create: `backend/app/services/backup_validation.py`
- Create: `backend/tests/unit/test_backup_validation.py`
- Modify: `backend/app/api/routes/backups.py`
- Modify: `backend/app/schemas/backup.py`
- Modify: `backend/tests/integration/test_backup_api.py`

### Step 1: Write failing validation and preview tests

Cover strict types/enums/NUMERIC(28,12), duplicate identities, every foreign-key relationship, invalid rebalance lifecycle/reference combinations, count/checksum mismatch, missing migration path, future version, token expiry/one-time binding, and zero database writes. Capture SQL or compare all table hashes before/after upload.

Test:

```text
POST /api/backups/upload                  (raw application/octet-stream body)
POST /api/backups/safety/{backup_id}/preview
```

The preview includes export/source versions, record counts, current count comparison, warnings, named credential categories only, and an opaque 30-minute restore token.

```python
async def test_upload_validation_never_mutates_database(api_client, seeded_hashes, archive_bytes):
    response = await api_client.post(
        "/api/backups/upload",
        content=archive_bytes,
        headers={"Content-Type": "application/octet-stream", "X-Backup-Filename": "state.portfolio-backup"},
    )
    assert response.status_code == 200
    assert await current_table_hashes() == seeded_hashes
```

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_backup_validation.py tests/integration/test_backup_api.py -q'
```

Expected: FAIL because semantic validation and preview routes do not exist.

### Step 2: Implement strict streamed validation

Create a `ValidatedBackup` descriptor that contains the retained archive path, archive SHA-256, canonical logical checksum, migrated current version, counts, preview metadata, and expiry—not the full dataset or plaintext secrets. Validate in the design's fixed order: ZIP safety, manifest/hashes, migrations, strict row schema, cross-collection semantics, canonical checksum.

Use disk-backed identity indexes (temporary SQLite or sorted temporary files) for large cross-collection checks so 2 GB input does not imply 2 GB RAM. Reject unknown fields after migration. Do not contact providers or SMTP.

### Step 3: Implement upload streaming and token binding

Read `Request.stream()` into a `.partial` file, enforcing the compressed limit while bytes arrive. Validate, atomically retain it for 30 minutes, then issue a cryptographically random one-time token whose journal stores only a token hash, archive hash, path ID, and expiry. Safety preview passes an existing server archive through the identical validator.

Return typed public codes such as `BACKUP_CORRUPT`, `BACKUP_FUTURE_VERSION`, `BACKUP_INCOMPATIBLE`, `BACKUP_RELATIONSHIP_INVALID`, and `BACKUP_RESOURCE_LIMIT`; never return raw ZIP/JSON/SQL exceptions.

### Step 4: Verify and commit

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_backup_validation.py tests/integration/test_backup_api.py -q'
```

Expected: PASS.

Commit:

```bash
git add backend/app/services/backup_validation.py backend/app/api/routes/backups.py backend/app/schemas/backup.py backend/tests/unit/test_backup_validation.py backend/tests/integration/test_backup_api.py
git commit -m "feat: validate logical backups before restore"
```

## Task 5: Replace business state atomically with a pre-restore safety backup

**Files:**

- Create: `backend/app/services/backup_restore.py`
- Create: `backend/tests/integration/test_logical_backup_restore.py`
- Modify: `backend/app/services/backup_operations.py`
- Modify: `backend/app/api/routes/backups.py`
- Modify: `backend/tests/integration/test_backup_api.py`

### Step 1: Write the failing round-trip and rollback suite

In `portfolio_test`, export a complete state, deliberately replace it, restore it, decrypt synthetic restored credentials with the current test Fernet key, and compare per-collection counts plus the canonical logical checksum.

Inject failure at safety creation, deletion, insertion, credential encryption, and post-write verification. For every injection assert the pre-restore database checksum remains unchanged. Also verify one durable safety backup remains after a later rollback, ordinary writes wait behind table locks, concurrent backup operations get 409, and an API interruption before commit rolls back.

```python
@pytest.mark.parametrize("failure_stage", [
    "safety_backup", "delete", "insert", "encrypt", "verify",
])
async def test_restore_failure_preserves_original_state(failure_stage, seeded_database):
    before = await logical_database_checksum()
    with inject_restore_failure(failure_stage):
        result = await run_restore(validated_backup)
    assert result.status == "failed"
    assert await logical_database_checksum() == before
```

Run:

```bash
make test-backend PYTEST_ARGS='tests/integration/test_logical_backup_restore.py tests/integration/test_backup_api.py -q'
```

Expected: FAIL because restore is not implemented.

### Step 2: Implement the single-transaction restore engine

Expose `restore_validated_backup(session, validated, *, storage, secret_store, progress) -> RestoreResult` as the transaction-owned entry point.

Inside one transaction:

1. Recheck archive hash/token binding.
2. Acquire a stable PostgreSQL advisory transaction lock and one deterministic `LOCK TABLE encrypted_secrets, rebalance_plans, snapshot_items, cost_adjustments, holding_defaults, market_data_overrides, market_data, snapshots, holdings, asset_classes, settings IN ACCESS EXCLUSIVE MODE` statement.
3. Call `export_logical_backup(session, partial_safety_path, secret_store=secret_store, metadata=metadata)` with this same already-locked session; validate, fsync, chmod, and atomically rename it before modifying rows.
4. Delete children before parents: encrypted secrets, rebalance plans, snapshot items, cost adjustments, holding defaults, market overrides, market data, snapshots, holdings, asset classes, settings.
5. Insert parents before children: asset classes, holdings, holding defaults, market data, overrides, cost adjustments, snapshots, snapshot items, rebalance plans, settings, then encrypted credentials.
6. Re-encrypt plaintext credentials with the current Fernet key while preserving functional plaintext and validation metadata.
7. Re-export the inserted state through the same session to a temporary logical sink, and compare counts and canonical checksum exactly.
8. Return; the caller commits only after verification.

Never open a second session during the locked safety export. Preserve original IDs, timestamps, row versions, nulls, and JSON. Use batched inserts without invoking defaults that would alter restored values.

### Step 3: Wire confirmation, progress, token consumption, and retention

Add:

```text
POST /api/backups/restore
body: {"restore_token": "opaque-one-time-token", "confirmation": "恢复"}
```

Reject any other confirmation text. Atomically consume the one-time token before returning `202`. Report only the six approved stages. On success include the new safety backup ID, clear the active operation, retain the newest five validated safety files, and leave the operation journal outside the restored database. On process startup, an unfinished restore becomes `interrupted`; PostgreSQL supplies rollback guarantees.

### Step 4: Verify and commit

Run:

```bash
make test-backend PYTEST_ARGS='tests/integration/test_logical_backup_restore.py tests/integration/test_backup_api.py -q'
```

Expected: PASS.

Commit:

```bash
git add backend/app/services/backup_restore.py backend/app/services/backup_operations.py backend/app/api/routes/backups.py backend/tests/integration/test_logical_backup_restore.py backend/tests/integration/test_backup_api.py
git commit -m "feat: restore logical backups atomically"
```

## Task 6: Apply restored schedules in the worker within 60 seconds

**Files:**

- Modify: `backend/app/worker.py`
- Modify: `backend/tests/unit/test_worker.py`

### Step 1: Write failing scheduler-reconciliation tests

Test unchanged tuples do nothing, changed hour/minute replaces only `daily-market-refresh`, invalid database values are logged and keep the current job, transient DB errors are contained, polling repeats every 30 seconds, and cancellation shuts down cleanly.

```python
async def test_reconcile_replaces_job_when_persisted_schedule_changes():
    active = RefreshSchedule(8, 0)
    load = AsyncMock(return_value=RefreshSchedule(9, 30))
    result = await reconcile_refresh_schedule(scheduler, active, loader=load)
    assert result == RefreshSchedule(9, 30)
    assert scheduler.get_job("daily-market-refresh").trigger.fields[5].expressions[0].first == 9
```

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_worker.py -q'
```

Expected: FAIL because the worker only reads settings at startup.

### Step 2: Implement reconciliation loop

Extract one `configure_refresh_job(scheduler, schedule)` function used at startup and during reconciliation. Start a cancellable loop beside APScheduler:

```python
async def watch_refresh_schedule(scheduler, initial: RefreshSchedule) -> None:
    active = initial
    while True:
        await asyncio.sleep(30)
        try:
            configured = await load_refresh_schedule()
            if configured != active:
                configure_refresh_job(scheduler, configured)
                active = configured
        except Exception:
            logger.exception("Worker schedule reconciliation failed")
```

Cancel and await the watcher before `scheduler.shutdown(wait=False)`. This yields a 30-second poll interval and a documented 60-second maximum including one transient missed poll.

### Step 3: Verify and commit

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_worker.py -q'
```

Expected: PASS.

Commit:

```bash
git add backend/app/worker.py backend/tests/unit/test_worker.py
git commit -m "feat: reload worker schedule after restore"
```

## Task 7: Build the history-page backup and restore workflow

**Files:**

- Create: `frontend/src/features/backups/api.ts`
- Create: `frontend/src/features/backups/BackupRestorePanel.tsx`
- Create: `frontend/src/features/backups/BackupRestore.module.css`
- Create: `frontend/tests/BackupRestorePanel.test.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/SnapshotsPage.tsx`
- Modify: `frontend/tests/SnapshotsPage.test.tsx`

### Step 1: Write failing UI/API tests with MSW

Cover plaintext-secret warning, export start/poll/download, raw upload, preview metadata/count comparison, named credential categories without values, exact `恢复` gating, six progress stages, rollback/interrupted/resource/version/conflict messages, disabled backup actions during work, safety list/download/restore/delete, retry, and success full reload/query-cache clear. Assert the existing snapshot filters/chart remain available.

```tsx
expect(screen.getByText(/备份文件包含明文 API 密钥和邮箱密码/)).toBeVisible();
await user.type(screen.getByLabelText("输入“恢复”以确认"), "恢复");
await user.click(screen.getByRole("button", { name: "开始恢复" }));
expect(await screen.findByText("创建安全备份")).toBeVisible();
```

Run:

```bash
cd frontend && npm test -- --run tests/BackupRestorePanel.test.tsx tests/SnapshotsPage.test.tsx
```

Expected: FAIL because the backup panel and hooks do not exist.

### Step 2: Add binary request/download support and typed hooks

Keep JSON `apiRequest` unchanged. Add helpers that reuse the same structured error parser:

```ts
export async function apiUpload<T>(path: string, file: File): Promise<T> {
  return requestResponse<T>(path, {
    method: "POST",
    body: file,
    headers: { Accept: "application/json", "Content-Type": "application/octet-stream", "X-Backup-Filename": file.name },
  });
}

export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(path, { headers: { Accept: "application/octet-stream" } });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? "portfolio-backup.portfolio-backup";
  return { blob: await response.blob(), filename };
}
```

In `features/backups/api.ts`, define query keys, 1-second polling only while pending/running, mutations for export/upload/restore/delete, safety listing, and an object-URL download helper that always revokes its URL. Invalidate safety data after restore/delete and stop polling terminal operations.

### Step 3: Build the compact panel and staged dialogs

Place `<BackupRestorePanel />` immediately below the History page header and above filters. Keep the initial card compact; expand inline for operation status and use accessible dialogs/drawers for preview, typed confirmation, and safety deletion.

Display:

- permanent plaintext-credential warning;
- `导出完整备份` and file-picker actions;
- preview source/export versions, counts and current comparison;
- named credential categories only;
- six-stage progress with sanitized localized errors;
- safety table with time, versions, size, counts, and actions.

Disable only backup controls during active backup work. On successful restore show the safety ID, clear TanStack Query state, then call `window.location.reload()`.

### Step 4: Verify accessibility, responsive behavior, and commit

Run:

```bash
cd frontend && npm test -- --run tests/BackupRestorePanel.test.tsx tests/SnapshotsPage.test.tsx
cd frontend && npm run build
```

Expected: all tests PASS and Vite build exits 0.

Commit:

```bash
git add frontend/src/features/backups frontend/src/api/client.ts frontend/src/api/types.ts frontend/src/pages/SnapshotsPage.tsx frontend/tests/BackupRestorePanel.test.tsx frontend/tests/SnapshotsPage.test.tsx
git commit -m "feat: add backup restore workflow to history"
```

## Task 8: Prove compatibility, isolation, and complete recovery

**Files:**

- Modify: `backend/tests/integration/test_logical_backup_restore.py`
- Modify: `backend/tests/integration/test_backup_api.py`
- Modify: `backend/tests/integration/test_backup_restore.py` only if an assertion is needed to distinguish the existing PostgreSQL disaster-recovery layer; do not change the scripts' behavior.
- Modify: `README.md`

### Step 1: Add the final acceptance tests

Add one end-to-end backend test that imports the committed v1 golden archive into a database with deliberately different data and verifies exact logical state. Add corrupted archive, ZIP bomb metadata, interrupted journal recovery, safety retention, and secret-leak regression cases not already covered.

Add a test assertion that the normal Compose project/data volumes are absent from the test environment and that all fixture secrets use the test key path.

### Step 2: Document both recovery layers and operator warnings

Document browser backup/restore, plaintext credential risk, the five safety backups, compatibility direction, 30-minute file/token expiry, no-schedule limitation, worker schedule reload, and the fact that `make backup` / `make restore` remains necessary when PostgreSQL or the API cannot start.

### Step 3: Run full isolated verification

Run exactly:

```bash
make test-backend
make test-frontend
cd frontend && npm run build
git diff --check
```

Expected:

- all backend tests pass in `portfolio-rebalancer-test` against `portfolio_test`;
- all frontend tests pass against MSW;
- Vite build exits 0;
- `git diff --check` prints nothing.

Do not start the normal Compose project and do not inspect or mutate its database volume during verification.

### Step 4: Review against the design and commit

Check every acceptance criterion in `docs/superpowers/specs/2026-08-23-full-backup-restore-design.md`, scan implementation code for unfinished markers, raw exception exposure, secret logging, and unbounded archive reads. Confirm the v1 golden fixture is secret-free and importable.

Commit:

```bash
git add README.md backend/tests
git commit -m "test: verify complete logical backup recovery"
```

At implementation handoff, report test counts/output, the generated archive format version, the exact production files changed, and explicitly state that no formal environment data or volume was touched.
