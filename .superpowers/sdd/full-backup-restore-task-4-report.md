# Full Backup Restore — Task 4 Report

## Status

Implemented upload and safety-archive preview validation without business-database writes or external provider/SMTP calls.

## Implementation

- Added `ValidatedBackup`, a bounded descriptor containing only retained path identity, archive and logical hashes, versions, fixed-size record-count/preview metadata, credential provider categories, and expiry.
- Reused Task 1's anonymous verified archive snapshot through an explicit context manager. The external snapshot and ZIP handle close on both success and failure.
- Added disk-backed SQLite semantic indexes containing only row IDs, uniqueness keys, relationship edges, snapshot types, and lifecycle metadata. Plaintext credentials and full rows are not written to descriptor/token journals or semantic indexes.
- Enforced current row contracts, PostgreSQL `NUMERIC(28,12)` and `Integer` bounds, string lengths, enums, ISO-3 currencies, JSON shapes, singleton settings, duplicate database identities, all model foreign keys, market-data/manual-override references, and rebalance lifecycle/snapshot-type rules.
- Added sanitized error mapping for corrupt archives, future versions, unavailable migrations, incompatible data, relationship failures, streamed/archive resource limits, and SQLite/temporary-disk exhaustion.
- Added raw `application/octet-stream` upload streaming through `Request.stream()` into a UUID-named `0600` partial file. The 500 MiB limit is checked during arrival; failures remove partials. Successful validation fsyncs and atomically retains the archive for 30 minutes.
- Added identical safety-backup preview validation and current-versus-backup record-count comparison using read-only database queries.
- Added cryptographically random restore tokens. Durable records contain only token hash, archive SHA-256, opaque path ID, and expiry. Consumption uses an atomic claim so concurrent callers cannot both succeed.
- Preserved expiry metadata as a non-reusable consumed tombstone. Periodic backup maintenance deletes expired upload archives and token/tombstone records; failed deletes restore the journal for bounded retry. Crash-left claims remain discoverable.
- Added no restore HTTP endpoint.

## TDD Evidence

Initial RED:

```text
tests/unit/test_backup_validation.py collection
ModuleNotFoundError: No module named 'app.services.backup_validation'
```

HTTP RED:

```text
3 failed
- POST /api/backups/upload returned 404
- POST /api/backups/safety/{backup_id}/preview returned 404
- streamed-size test found no MAX_COMPRESSED_BYTES route seam
```

Hardening RED/GREEN cycles also demonstrated:

- two concurrent consumers initially both succeeded;
- periodic maintenance initially left expired uploads behind;
- expiry deletion failure initially lost the retry journal;
- valid manual-override references, PostgreSQL integer overflow, consumed/crashed token expiry metadata, and SQLite resource sanitization initially produced five failures.

Each failure received a minimal implementation change and focused GREEN rerun before the next cycle.

## Verification

Required focused suite, final candidate:

```text
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/full-backup-restore \
  /usr/bin/make test-backend \
  "PYTEST_ARGS=tests/unit/test_backup_validation.py tests/integration/test_backup_api.py -q"

48 passed in 3.24s
```

Final fresh full backend suite:

```text
wsl.exe --cd /mnt/c/Users/12067/Documents/code/portfolio-rebalancer/.worktrees/full-backup-restore \
  /usr/bin/make test-backend "PYTEST_ARGS=-q"

445 passed, 3 skipped, 29 warnings in 49.16s
```

The warnings are existing Starlette/httpx and Alembic deprecation warnings.

## Security and Safety Review

- The upload integration test hashes every business table before and after preview; all hashes remain unchanged.
- Tests use only synthetic credentials and assert secret/mask text is absent from response bodies and journals.
- Filenames are never used as filesystem paths.
- Uploaded archives and journals are `0600`; storage directories remain `0700`.
- Token binding is checked against the retained archive hash at consumption.
- Safety preview neither consumes its token nor mutates/deletes the safety archive.
- Reviewer findings for manual override references, int32 bounds, expiry tombstones/crash claims, SQLite resource typing, and deterministic concurrency coverage were resolved before final verification.

## Concerns

No known blocking concerns. The final suite retains 29 pre-existing deprecation warnings noted above.
