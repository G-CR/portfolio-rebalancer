# Long-term Ledger Implementation Plan

> **For agentic workers:** Execute inline using executing-plans. Development is already approved; commits are coordinated by the parent agent.

**Goal:** Freeze a current-day opening and record original-currency investment performance with auditable reference CNY conversions.

**Architecture:** A pure decimal replay domain owns average cost and original-currency performance. SQLAlchemy ledger services serialize writes, freeze daily FX and provide previews; a dedicated page consumes these APIs.

**Tech Stack:** Python, SQLAlchemy async, FastAPI, PostgreSQL, React, TypeScript.

## Global Constraints

- Shanghai dates; no fabricated foreign exchange rates; fallback at most seven calendar days and never forward.
- Original funds are not cash accounts. Rebalancing algorithms remain unchanged.
- Opening preview precedes confirmation. Corrections retain reversal and replacement audit links.
- Parent owns shared router, metadata imports, worker, backups and shared TypeScript types.

### Task 1: Pure average-cost replay

**Files:** `backend/app/domain/ledger.py`, `backend/tests/unit/test_ledger.py`.

**Interfaces:** `replay(quantity, cost, entries)` returns final quantity, cost, realized profit, dividends and completeness reasons. Entries sort by occurrence date and sequence. Reference amounts are independent of original cost.

- [x] Write assertions: opening 10 units at 5; buy 2 at 10 plus 1 fee; sell 3 at 12; split 2:1 preserves cost; historical oversell rejected; correction produces incomplete status.
- [x] Run isolated unit test command with safe environment, confirm missing-module failure.
- [x] Implement Decimal replay with positive/nonnegative validation and stable ordering.
- [x] Re-run unit tests and validate reference fallback boundary separately.

### Task 2: Persisted opening, FX and transactions

**Files:** `backend/app/db/ledger_models.py`, `backend/alembic/versions/20261001_0010_long_term_ledger.py`, `backend/app/schemas/ledger.py`, `backend/app/services/ledger.py`, `backend/app/services/reference_fx.py`, `backend/app/api/routes/ledger.py`.

**Interfaces:** `/ledger/opening/preview`, `/ledger/opening/confirm`, `/ledger/entries/preview`, `/ledger/entries/confirm`, `/ledger/statistics`, `/ledger/entries`; worker calls `freeze_reference_fx(session, local_date)`.

- [x] Add integration assertions for current-day opening confirmation, idempotency, transaction rollback, missing reference rates, corrections and archived entries.
- [x] Implement singleton period lock, holding lock and request fingerprints; commit only at route transaction boundary.
- [x] Freeze valid same-date market quotes with source metadata; fallback uses final prior daily values and preserves revision records.
- [x] Calculate per-currency period profit and CNY reference cash-flow profit; list incomplete reasons rather than returning fabricated totals.

### Task 3: User recording and existing holding actions

**Files:** `frontend/src/features/ledger/api.ts`, `frontend/src/pages/LedgerPage.tsx`, existing purchase/sale drawers and cost services.

- [x] Add UI assertions for pending CNY, separate currencies and preview confirmation.
- [x] Show opening preview, filtered investment records, transaction/dividend/split entry and correction audit links.
- [x] Route existing confirmed purchases and sales into ledger atomically; retain pre-opening compatibility and flag manual changes/replacement gaps.
- [x] Run frontend tests/typecheck and safe backend checks, send parent exact integration requirements.


## Final integrated verification

- Isolated Docker/PostgreSQL full backend suite: 673 passed, 3 skipped.
- Original-currency results remain visible when current FX is missing.
- Latest valuation FX does not mutate frozen opening/operation references.
- Browser ledger/monthly-review scenarios and ledger accessibility verified.
- Full frontend tests/build are recorded in docs/long-term-investing-verification.md.
