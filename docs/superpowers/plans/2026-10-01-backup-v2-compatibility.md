# Backup v2 Compatibility Implementation Plan

**Goal:** Include ledger and decision business records in full backups while restoring verified v1 archives with empty new collections.

**Architecture:** Freeze v1 member set; add explicit v2 contracts. Verify each source version's original manifest, member digests and logical checksum before migration. Synthesize only the eight new empty collections for v1. Continue streaming rows and use SQLite for identity, relationship and uniqueness validation.

1. Add unit regression tests for versioned allowlists, v1 migration/checksum tampering and contract coverage; run tests to observe failures.
2. Add v2 constants/contracts and v1 migration. Adjust source checksums and manifests to their versioned member set.
3. Extend semantic scalar, uniqueness and reference checks for new model constraints. Extend restore lock/delete/insert ordering and handle self-referenced ledger entries safely.
4. Run backend backup unit tests with the explicitly isolated test identity and unreachable database URL. Parent runs Docker integration for export/restore, including golden v1 restore and populated v2 round trip.

No shared model, router, worker, frontend or conftest edits; no commits.

Final root integration: full isolated Docker suite passed (673 passed, 3 skipped), including v1 golden restore, populated v2 restore and checksum round trips.
