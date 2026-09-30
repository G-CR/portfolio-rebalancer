# Long-term decision and notifications implementation plan

> **For agentic workers:** Execute inline as authorized; shared integration belongs to root.

**Goal:** Persist daily decision observations and deliver low-frequency attention notifications.

**Architecture:** Pure date/streak helpers, dedicated singleton policy and dated observations, transactional outbox, read-only decision endpoint. Existing daily digest remains default; homepage queries decision independently.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, React Query, Vitest.

## Global Constraints
- Three same-class same-direction valid scheduled daily observations; invalid days break streak.
- Shanghai dates, monthly day 1–31 clamped to month end.
- No optimizer in attention mode; manual digest preserves behavior.
- Shared files integrated by root; no commits in shared workspace.

### Task 1: Pure decision rules
- [x] Write tests for direction streaks, anomaly interruption, monthly clamp and precedence.
- [x] Run isolated unittest tests and confirm missing module fails.
- [x] Implement backend/app/domain/decision.py and rerun tests.

### Task 2: Persistence and API
- [x] Add dedicated models and migration 20261001_0011.
- [x] Persist one observation per date under policy row lock; fingerprint allocation rules and clear old streaks on change.
- [x] Expose GET /decision, GET/PUT /decision/settings, POST /decision/review.
- [x] Queue stable event keys and claim pending mail with PostgreSQL row locks; failed mail remains retryable.

### Task 3: Existing email and frontend
- [x] Preserve daily default; route attention auto-mail to outbox delivery.
- [x] Add independent decision hooks, banner, review controls and notification settings.
- [x] Run frontend tests/build, report exact shared integration contracts to root.

## Validation evidence
- Safe local rules plus existing digest-render tests: 16 passed.
- Full frontend suite: 31 files / 213 tests passed.
- Production Vite build passed. TypeScript check retains unrelated existing errors outside this module; module retryLabel error fixed.
- PostgreSQL integration test module delivered to root for isolated Docker execution.
- Root owns metadata/router/worker wiring and backup compatibility.

Final root integration: full isolated Docker suite passed (673 passed, 3 skipped), including all five notification integration cases and independent worker delivery.
