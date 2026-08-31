# Final-review fix report

## Scope

This correction addresses the two final-review findings on branch
`codex/minimax-rebalancing`:

1. The branch-and-bound continuous relaxation could use only the smallest
   feasible invested total, then incorrectly prune plans where a larger total
   diluted an overweight allocation.
2. Saved plans from before the certified optimizer had response metadata filled
   with inaccurate hard-coded defaults.

## RED proof

The following sanctioned Docker command reproduced the optimizer failure before
the production change:

```powershell
docker compose run ... api uv run pytest tests/unit/test_rebalance_optimizer.py -k higher_total -q
```

It failed because the root continuous bound was `0.14499664306640625`, greater
than the exact executable oracle value `0.1211627906976744186046511628` for
values `(13, 26, 29)`, targets `(0.03, 0.35, 0.62)`, CNY cash `18`, and lots
`(0, 0, 18)`.

The saved-plan API regression was reproduced with:

```powershell
docker compose run ... api uv run pytest tests/integration/test_rebalance_api.py -k create_plan_persists_exact_preview_contract -q
```

It failed because the historical response exposed
`optimization_precision == "0"` instead of `"0.0001"`.

## Fix and root-bound audit

`continuous_relaxation` now asks whether **any** invested total in the complete
executable interval can satisfy the relaxed allocation constraints. It splits
that interval at every lower/upper allocation breakpoint and, when FX is
disabled, at the currency-cap crossover points. On each affine piece it solves
the complete linear system:

- each asset lower allocation is no greater than its upper allocation;
- aggregate lower allocations fit in the total;
- each currency's lower allocation fits its currency cap;
- the total fits the aggregate capped upper allocation.

For FX-enabled nodes the final condition is the aggregate upper allocation;
for FX-disabled nodes it is the sum of per-currency `min(upper, cap)` values.
Thus every executable discrete candidate is contained by the checked continuous
feasible region. The bisection still returns its last infeasible drift endpoint,
which is a lower bound; it cannot exceed the true discrete optimum. A zero-only
degenerate allocation is not used as a guide, preserving the prior positive
guide behavior. Node budgeting and deterministic queue ordering are unchanged.

The historical schema normalizer now uses the same compatibility semantics as
backup response normalization, unless current serialized metadata is present:

- `optimization_certified=False`, `optimization_precision=0.0001`,
  `optimality_gap=0`;
- `buy_only_max_drift=max_drift_after`;
- `sell_phase_used` is true exactly when stored trades include a sell;
- positive `fx_required_cny` produces `cny_to_usd` and that amount; otherwise
  the direction is `none` and amount is zero.

## GREEN proof

Focused sanctioned Docker verification:

```powershell
docker compose run ... api uv run pytest tests/unit/test_rebalance_optimizer.py tests/integration/test_rebalance_api.py -k 'higher_total or continuous_bound_is_sound or search_matches_exhaustive_oracle or create_plan_persists_exact_preview_contract' -q
```

Result: `10 passed`.

The complete sanctioned backend suite was run in the isolated
`portfolio-rebalancer-test` Compose project:

```powershell
docker compose run ... api uv run pytest -q
```

Result: `599 passed, 3 skipped, 29 warnings in 130.65s`.

Frontend verification after `npm ci`:

```powershell
npm test -- --run --passWithNoTests
npm run build
npm run test:e2e -- rebalance.spec.ts
```

Results: `203 passed`; production Vite build succeeded; `1 passed` for the
rebalance Playwright specification.

## Tests added or strengthened

- The exact three-asset prune counterexample verifies the continuous bound does
  not exceed the exhaustive optimum and the certified result chooses `(0,0,18)`.
- The exhaustive test oracle now uses production `_full_lot_bounds`, rather than
  the previous hard-coded upper range.
- Four additional three-asset small-oracle cases prove continuous-bound
  soundness and exact discrete selection.
- Saved-plan list/detail compatibility asserts both positive-FX/sell and
  zero-FX/no-sell historical metadata, and validates the resulting backup.
- The one existing trade-reason expectation was updated because the corrected
  certified plan really reduces maximum drift when that D buy is removed;
  `REDUCE_MAX_DRIFT` is now the accurate public explanation.

## Files and self-review

- `backend/app/domain/rebalance_optimizer.py`
- `backend/app/schemas/rebalance.py`
- `backend/tests/unit/test_rebalance_optimizer.py`
- `backend/tests/unit/test_rebalance.py`
- `backend/tests/integration/test_rebalance_api.py`

Self-review checked that current certified fields override the compatibility
defaults, the existing exact currency-cap capacity checks remain the final
guard, score-bucket and node-budget behavior are untouched, and `git diff
--check` is clean. No visual snapshots were changed.

## Commit

The first final-review correction was committed as `be5e40e`
(`fix: preserve minimax bound soundness`).

## Follow-up final-review corrections

This follow-up fixes the remaining merge-blocking review findings:

1. An executable all-zero final-value endpoint can be better than every
   positive continuous relaxation in a branch node. The relaxation now detects
   that endpoint only when every asset's exact zero lot lies in the node range
   and the complete cash ledger is feasible. Its exact `Dmax` participates in
   pruning, while a positive guide remains available for deterministic branch
   splitting when one exists.
2. A score is bucketed at one basis point before later tie breakers, so search
   exhaustion proves bucket optimality rather than raw-`Dmax` equality. All
   certified plans therefore report the conservative one-basis-point
   `optimality_gap` certificate instead of an unjustified zero.

## Follow-up RED and GREEN proof

Before the production change, the exact CNY/USD liquidation fixture failed in
both FX modes: its child node `((-3,-2), (0,0), (0,0))` reported a positive
continuous lower bound of `0.899997711181640625`, even though exact liquidation
`(-3,0,0)` has `Dmax = 0.5`. The optimizer selected the worse `(-3,1,0)` plan.
The same RED run showed a bucket-optimal `(1,0,6)` plan returning gap zero even
though executable `(2,0,6)` has a marginally lower raw `Dmax`.

GREEN verification completed with the isolated `portfolio-rebalancer-test`
Compose project:

- Focused optimizer regressions: `3 passed`.
- Optimizer and rebalance unit tests: `73 passed`.
- Full backend suite: `602 passed, 3 skipped, 29 warnings`.
- Frontend Vitest: `203 passed`.
- Production frontend build: succeeded.
- Rebalance Playwright E2E: `1 passed`.

No dashboard visual snapshots were changed. This updated report is committed
with the follow-up final-review corrections.

## Preferred-holding contract correction

The rebalance engine no longer falls back to the first holding of an active
asset class when none is marked `is_rebalance_preferred`. It now returns the
same typed incomplete-data contract used for an active class with no holdings:
HTTP 409 `REBALANCE_DATA_INCOMPLETE`, with the preferred-holding message and
the exact `preferred:<asset-class-id>` item.

RED proof: the new integration test first received `200 OK` and produced a
plan trading the arbitrary `CNY-FUND` holding. GREEN proof through the guarded
`make test-backend` target: the focused regression passed, the rebalance API
file passed `12` tests (including the preferred sell-cap case), and the full
backend suite passed `603`, skipped `3` (29 pre-existing warnings). The
regression also asserts the optimizer is never called. No frontend files
changed, so no frontend verification was applicable.
