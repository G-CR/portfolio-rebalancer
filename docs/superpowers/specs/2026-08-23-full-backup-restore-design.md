# Full Backup and Restore Design

## Goal

Provide a browser-based full backup and restore workflow that can return the application to the exact logical state captured at export time. The workflow must preserve all business history and relationships, include external-service credentials in plaintext for portability, support restoring older backup formats into newer application versions, and replace current data atomically.

This feature is a versioned logical backup system. It complements rather than replaces the existing `make backup` / `make restore` PostgreSQL disaster-recovery tools.

## Confirmed Product Decisions

- The primary entry point is a new **完整备份与恢复** section at the top of the existing history snapshots page.
- Restore replaces all current business data atomically; it does not merge.
- The backup contains plaintext provider API keys and the SMTP password for convenience.
- Older backup formats must remain importable by newer application versions.
- All historical market-data rows are included, not only current effective values.
- The first release provides manual export, manual import, and automatic pre-restore safety backups. It does not schedule periodic backups.
- Pre-restore safety backups live in an independent persistent volume and retain the five most recent successful files.
- Safety backups can be listed, downloaded, restored, and deleted from the UI.
- Final restore confirmation requires typing `恢复`.
- Restore runs online as an atomic background job; no Docker restart is required.
- Deployment configuration such as Compose files, `.env`, database credentials, ports, images, and logs is outside the logical backup boundary.

## Scope

The logical backup contains every row and field needed to reproduce the application's persisted state:

1. Asset classes, including inactive rows, ordering, notes, IDs, and timestamps.
2. Holdings, including archived holdings, precise cost fields, version counters, preferred-source state, and rebalance preference.
3. Per-holding fee and source defaults.
4. Every market-data success and failure record.
5. Every active or expired manual market-data override.
6. The append-only cost-adjustment history.
7. Snapshots and immutable snapshot items for all snapshot types.
8. Rebalance plans, inputs, suggestions, projected results, idempotency keys, market-data references, snapshot references, lifecycle timestamps, and baseline-reset state.
9. General, rebalance, and email settings.
10. Plaintext provider credentials and SMTP password together with non-secret validation metadata.

The backup preserves original UUIDs, exact decimal strings, timestamps, row versions, null values, JSON payloads, and cross-row relationships.

The logical backup excludes:

- Docker and Compose configuration;
- `.env` and database credentials;
- host ports, container images, and application logs;
- the PostgreSQL data volume and Fernet key volume;
- generated backup files and backup-operation journals.

## Archive Format

The downloaded file is named `portfolio-backup-YYYYMMDD-HHmmss.portfolio-backup`. It is a ZIP archive with a strict allowlisted structure:

```text
manifest.json
credentials.json
data/asset_classes.json
data/holdings.json
data/holding_defaults.json
data/market_data.json
data/market_data_overrides.json
data/cost_adjustments.json
data/snapshots.json
data/snapshot_items.json
data/rebalance_plans.json
data/settings.json
```

`manifest.json` contains:

- `format_version`, starting at integer `1`;
- source application version;
- UTC export timestamp and configured display timezone;
- an explicit `contains_plaintext_credentials: true` marker;
- record counts for every data collection;
- uncompressed byte lengths and SHA-256 hashes for every member;
- the canonical logical-state checksum used for post-restore verification.

JSON encoding rules are lossless and deterministic:

- UUID, decimal, date, datetime, and time values are strings.
- Decimals are never converted through binary floating point.
- Timestamps retain timezone offsets and are normalized when hashed.
- Object keys and row ordering are canonicalized for checksums.
- Null remains JSON `null`; missing and null are not interchangeable.
- UTF-8 is used without ASCII escaping, preserving Chinese text.

Credentials are deliberately plaintext inside `credentials.json`. The UI and manifest state this explicitly. Credentials must never appear in archive names, logs, metrics, validation errors, or operation journals.

## Compatibility Contract

The importer accepts the current format and any older format for which a registered migration path exists. It applies pure, ordered migrations one version at a time, then validates the resulting current-format document.

- Newer applications must continue to import committed older golden fixtures.
- Adding or changing a persisted field requires either a default for old backups or a format migration.
- A backup with a format version newer than the running application is rejected before any write.
- Forward import means old backup to same/new application. New backup to old application is not supported.
- Unknown fields are rejected after migration instead of being silently discarded.

## Export Flow

`POST /api/backups/export` starts a serialized export operation and returns an operation ID. The browser polls operation status and downloads the completed archive through a separate attachment endpoint.

The backend:

1. Acquires the backup-operation lock so only one export, import, or safety backup runs at a time.
2. Opens a PostgreSQL `REPEATABLE READ`, read-only transaction to obtain one consistent logical point in time while ordinary application work continues.
3. Reads large tables in deterministic keyset batches.
4. Decrypts credentials in memory and writes them directly into the temporary archive.
5. Writes every member to a temporary file while computing counts, lengths, and hashes.
6. Writes the manifest last, closes the archive, reopens it through the same validator, and only then exposes it for download.
7. Deletes completed manual-export files after a completed transfer when possible and always expires them after 30 minutes; partial files are removed immediately on failure.

The archive is never assembled entirely in memory. A failed operation removes partial files and records a sanitized failure category. Download responses use attachment headers and disable browser/proxy caching.

## Server-Side Safety Backups

Compose adds an independent `backup_data` volume mounted only into the API service. It is separate from both `postgres_data` and `secret_data`.

Before every confirmed restore, the backend creates a current-state logical archive through the same serialization code but using the restore transaction's already locked session and consistent snapshot; it must not open a second database transaction that would wait on its own table locks. It writes to a partial path, validates the result, applies `0700` directory and `0600` file permissions, and atomically renames it into the safety-backup directory. Restore does not begin until this succeeds.

The newest five successful safety backups are retained. The sixth successful write is made durable before the oldest file is deleted. A failed creation never removes an older backup.

The UI lists each safety backup's ID, export time, application/format version, file size, and record counts. It supports download, restore through the normal preview/confirmation flow, and separately confirmed deletion. Backup archives never include the safety-backup directory or operation journals.

## Upload and Validation Flow

Uploading a file does not mutate the database. The upload endpoint streams into a temporary file with a default compressed-size limit of 500 MB.

The archive must contain exactly the allowlisted members shown above. Compressed upload size is limited to 500 MB, total declared and observed uncompressed size to 2 GB, and the aggregate compression ratio to 100:1. The validator rejects:

- path traversal, absolute paths, symlinks, duplicate entries, and non-allowlisted members;
- any member-count, compressed-size, uncompressed-size, or compression-ratio limit violation;
- truncated members and length/hash mismatches;
- malformed manifest or JSON;
- unsupported future versions or a missing migration path;
- invalid UUIDs, dates, timezone-aware timestamps, decimals, enums, or JSON shapes;
- numeric values outside the database precision contract;
- count mismatches, duplicate logical identities, broken foreign keys, invalid lifecycle combinations, or inconsistent snapshot/rebalance references.

Validation proceeds in this order:

1. Archive safety and resource limits.
2. Manifest structure and member hashes.
3. Ordered migration to the current logical format.
4. Strict schema validation with unknown-field rejection.
5. Cross-collection semantic validation.
6. Canonical logical-state checksum calculation.

The preview response contains export time, source application and format versions, record counts, named credential categories, current-versus-backup count comparison, warnings, and an opaque one-time restore token. The server retains the validated upload for 30 minutes, bound to its hash and token, then deletes it.

External providers and SMTP are never contacted during validation.

## Restore Execution

The confirmation endpoint requires the validated one-time token and the exact confirmation text `恢复`. It consumes the token once and immediately returns a restore-operation ID. Status is polled so long restores do not depend on a proxy request timeout.

The background restore job:

1. Acquires the global backup-operation lock.
2. Revalidates the retained archive hash and token binding.
3. Opens a database transaction and locks all restored business tables in a fixed order, causing concurrent reads/writes to wait rather than interleave.
4. Creates, validates, and durably stores the pre-restore safety backup while the current state is locked.
5. Deletes existing rows in dependency-safe order.
6. Inserts restored rows in dependency-safe order with original IDs, timestamps, versions, and relationships.
7. Encrypts plaintext credentials using the current deployment's Fernet key before insertion. Functional plaintext and validation metadata are restored; ciphertext bytes need not match the source system.
8. Recomputes record counts and the canonical logical-state checksum from the inserted database state.
9. Commits only if both match the validated archive.

Any database, serialization, encryption, storage, or verification failure rolls back the entire database transaction. The previous business state remains visible. A successfully written safety backup is retained even if the later restore rolls back.

Restore-operation status is stored in the independent backup volume, not in the database being replaced. If the API process exits before commit, PostgreSQL rolls back. On restart, the journal marks the operation interrupted instead of reporting success.

After success, the browser clears its query cache and performs a full reload. The worker compares the persisted refresh schedule tuple with its active schedule every 30 seconds and reschedules when it changes, so restored or normally edited settings take effect within 60 seconds without a container restart.

## User Interface

The history snapshots page begins with a compact **完整备份与恢复** card above existing snapshot filters and charts.

The card contains:

- a persistent warning that archives contain plaintext API keys and email passwords;
- **导出完整备份** and **选择备份文件** primary actions;
- export/import operation progress and sanitized errors;
- the validated restore preview and exact-text confirmation control;
- a **恢复前安全备份** table with download, restore, and delete actions.

Restore progress uses these stages:

1. 校验完成
2. 锁定数据
3. 创建安全备份
4. 写入数据
5. 完整性复核
6. 完成

While any backup operation is active, other backup actions are disabled. The rest of the application is not put into a permanent maintenance state; during the short table-lock window, affected requests wait.

Errors are categorized as file corruption, future version, incompatible structure, invalid relationships, upload/resource limit, insufficient disk space, operation conflict, rollback, or interrupted operation. UI and API errors must not expose secrets, raw SQL, filesystem paths, or stack traces.

Successful restore displays the safety-backup identifier, then reloads the application. Deleting a safety backup uses a separate confirmation and never shares the destructive restore token.

## Security Boundary

This is a local single-user service, but plaintext credentials make exported files sensitive. The design prioritizes convenience while applying these minimum controls:

- explicit warnings before export and restore;
- restrictive server-side permissions;
- no response caching;
- no secret values in logs, names, status records, or errors;
- strict archive parsing and bounded resource use;
- serialized backup operations;
- no Docker socket or host filesystem control exposed to the API.

The feature does not claim confidentiality for a downloaded backup. Anyone who can read the archive can read its credentials.

## Testing Strategy

### Serialization and Compatibility

- Round-trip every persisted model and field, including nulls, 12-decimal values, UUIDs, timezone timestamps, JSON payloads, and Chinese text.
- Commit a synthetic, secret-free v1 golden archive and keep it permanently importable.
- Require a compatibility test whenever the current format version changes.
- Verify canonical checksums are stable across row ordering and JSON object ordering.

### Full Restore Integration

Using only the isolated `portfolio_test` database, seed a state containing:

- active and archived holdings;
- fee defaults and full cost-adjustment history;
- valid, failed, and stale market-data records;
- active and expired manual overrides;
- daily, manual, rebalance-before, and rebalance-after snapshots;
- draft, in-progress, cancelled, and completed rebalance plans;
- settings and synthetic provider/SMTP credentials.

Run export, deliberately rewrite or clear the database, restore, and compare normalized per-collection hashes. Confirm restored synthetic credentials decrypt with the current test key.

### Failure and Concurrency

- Inject failures during safety-backup creation, deletion, insertion, credential encryption, and post-write verification; the original database must remain unchanged.
- Verify only one backup operation can run at a time.
- Verify ordinary writes wait during the restore lock and cannot partially interleave.
- Verify API interruption before commit results in rollback and an interrupted journal state.
- Verify retention removes an old safety backup only after a new valid backup is durable.

### Archive Security

- Reject traversal, absolute paths, symlinks, duplicate members, unknown members, ZIP bombs, ratios above 100:1, compressed uploads above 500 MB, uncompressed archives above 2 GB, corrupted hashes, malformed JSON, and future versions.
- Use synthetic credentials only and assert they never appear in captured logs or error bodies.

### Frontend

- Cover export initiation/download, warning copy, upload preview, count comparison, exact confirmation text, progress, rollback messaging, interrupted tasks, retry, and success reload.
- Cover list/download/restore/delete behavior for safety backups.
- Verify backup actions are disabled during an active task and ordinary history UI remains usable otherwise.

### Isolation

Backend verification must run only through the repository's guarded isolated test entry point with `portfolio_test`, the separate test Compose project, disposable volumes, and a synthetic Fernet key. Tests must never use the production Compose project, production database volume, production credentials, or real providers. Frontend tests use MSW only.

Existing `make backup` / `make restore` coverage remains in place to protect database-level disaster recovery.

## Acceptance Criteria

- A user can download one versioned `.portfolio-backup` file from the history page.
- The archive includes every persisted business record and plaintext external-service credentials, but no deployment configuration.
- Upload validation performs no database writes and produces a complete preview.
- Confirmed restore first creates a durable safety backup, then atomically replaces all business data.
- Failure at any restore stage leaves the previous database state intact.
- Restored normalized state matches the exported logical checksum exactly.
- The five newest safety backups are manageable from the UI.
- An older supported backup imports into a newer application through explicit migrations; a future format is rejected.
- Restored worker schedule applies within 60 seconds without restarting containers.
- No test accesses or mutates the production environment.

## Operational Limitation

If PostgreSQL is damaged badly enough that the API cannot start, browser restore is unavailable. The existing command-line `make backup` / `make restore` workflow remains the recovery path for that class of failure.
