# Minimax Rebalancing Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace order-dependent greedy rebalancing with a deterministic, contribution-first optimizer that minimizes the worst post-trade asset-class drift and certifies the result within 1 bp.

**Architecture:** Keep `app.domain.rebalance` as the stable public domain facade and move scoring, continuous relaxation, currency evaluation, and discrete branch search into a focused `app.domain.rebalance_optimizer` module. The service layer supplies class totals plus preferred-holding execution limits; API and UI expose certification, buy-only drift, sell-phase use, and bidirectional net FX without treating unused cash as an asset.

**Tech Stack:** Python 3.13, `Decimal`, dataclasses, FastAPI/Pydantic, SQLAlchemy/PostgreSQL, pytest/Hypothesis, React 19, TypeScript 5.9, TanStack Query, Vitest/Testing Library, Playwright.

## Global Constraints

- Allocation drift is absolute percentage-point drift: `abs(projected_weight - target_weight)`.
- Compare plans lexicographically by 1 bp buckets of `Dmax`, 1 bp buckets of `Dsum`, sale CNY, absolute net-FX CNY, total traded CNY, trade count, then a stable trade key.
- `epsilon = Decimal("0.0001")`, equal to 0.01 percentage points.
- Available CNY and USD are upper bounds; unused balances remain outside projected-weight denominators.
- Solve buy-only first. Run a sell-enabled phase only when the certified buy-only `Dmax` exceeds tolerance and selling is enabled.
- FX may be CNY-to-USD or USD-to-CNY but must be one signed net direction per plan.
- Each trade is an exact multiple of the preferred holding's `lot_size`; there is no CNY minimum-trade threshold.
- A sell cannot exceed the preferred holding's own quantity even when other holdings contribute to the class value.
- The chosen `Dmax` must be certified within 1 bp of the best executable discrete plan; continuous relaxations are search lower bounds only.
- Search is deterministic, capped at 250,000 branch nodes, and never silently falls back to the greedy algorithm.
- Normal five-class previews target 500 ms on the supported local environment.
- Fees, brokerage execution, a cash asset class, and intra-class target weights remain out of scope.
- Database-changing backend tests run only through the isolated `portfolio-rebalancer-test` project via `make test-backend`.

---

## File Structure

- `backend/app/domain/rebalance.py`: public immutable inputs/results, validation, two-phase orchestration, and result construction.
- `backend/app/domain/rebalance_optimizer.py`: private score types, continuous relaxation, cash/FX feasibility, branch-and-bound search, and certification.
- `backend/tests/unit/test_rebalance_optimizer.py`: exhaustive-oracle and optimizer-unit tests.
- `backend/tests/unit/test_rebalance.py`: public facade, regression, validation, and serialization tests.
- `backend/tests/unit/test_rebalance_properties.py`: randomized invariants and permutation/precision stability.
- `backend/app/services/rebalancing.py`: database-to-domain mapping, preferred sell inventory, response serialization, saved-plan compatibility, and reason text.
- `backend/app/schemas/rebalance.py`: active request contract and optimizer metadata response schema.
- `backend/app/schemas/settings.py`, `backend/app/services/settings.py`: preserve legacy stored minimum values while removing them from update requirements.
- `backend/tests/integration/test_rebalance_api.py`, `backend/tests/integration/test_rebalance_defaults_preview.py`, `backend/tests/integration/test_settings_api.py`: API, persistence, and compatibility coverage.
- `backend/app/services/backup_validation.py`, `backend/app/services/email_digest.py`: tolerate optional legacy plan minimums and render new reason/result fields.
- `frontend/src/api/types.ts`: TypeScript contract for active requests, optional legacy plan fields, and optimization metadata.
- `frontend/src/pages/RebalancePage.tsx`: payload/default hydration without minimum amount and typed optimizer failure rendering.
- `frontend/src/features/rebalance/RebalanceInputs.tsx`: lot-size-only form copy and bidirectional FX copy.
- `frontend/src/features/rebalance/RebalanceSummary.tsx`: before/buy-only/final drift, certification, and net FX.
- `frontend/src/features/rebalance/TradeSuggestions.tsx`: optimizer-intent reasons.
- `frontend/src/features/settings/ProviderSettings.tsx`, `frontend/src/features/settings/api.ts`: stop editing/sending the deprecated minimum field while preserving response compatibility.
- `frontend/tests/fixtures.ts`, `frontend/tests/RebalancePage.test.tsx`, `frontend/tests/RebalanceLifecycle.test.tsx`, `frontend/tests/ProviderSettings.test.tsx`: updated fixtures and behavior.
- `frontend/e2e/rebalance.spec.ts`, `frontend/e2e/fixtures/portfolio.ts`: end-to-end contract and presentation.
- `docs/user-guide.md`: user-facing minimax, lot-size, sell-gate, FX, and certification behavior.

---

### Task 1: Define the optimizer contract and lexicographic score

**Files:**
- Modify: `backend/app/domain/rebalance.py`
- Create: `backend/app/domain/rebalance_optimizer.py`
- Create: `backend/tests/unit/test_rebalance_optimizer.py`
- Modify: `backend/tests/unit/test_rebalance.py`

**Interfaces:**
- Consumes: existing `Decimal` domain values and `Currency = Literal["CNY", "USD"]`.
- Produces: `CandidatePlan`, `PlanScore`, `ContinuousBound`, `CertifiedPlan`, `OptimizationFailure`, `score_candidate()`, and updated public `AssetInput`, `RebalanceOptions`, `RebalanceResult` contracts.

- [ ] **Step 1: Write failing contract and score tests**

Add tests that construct two candidates whose drifts differ by less than 1 bp and prove later activity fields decide, while candidates in different buckets prefer the lower worst drift:

```python
from decimal import Decimal

from app.domain.rebalance_optimizer import CandidatePlan, score_candidate


def _candidate(*, max_drift: str, total_drift: str, sale: str = "0", fx: str = "0") -> CandidatePlan:
    return CandidatePlan.for_test(
        lot_counts=(0, 0),
        final_values=(Decimal("50"), Decimal("50")),
        max_drift=Decimal(max_drift),
        total_drift=Decimal(total_drift),
        total_sale_cny=Decimal(sale),
        net_fx_cny=Decimal(fx),
    )


def test_score_uses_one_basis_point_buckets_before_activity() -> None:
    quiet = _candidate(max_drift="0.020001", total_drift="0.030001")
    noisy = _candidate(max_drift="0.020099", total_drift="0.030099", sale="100")
    assert score_candidate(quiet) < score_candidate(noisy)


def test_score_never_trades_a_full_basis_point_for_lower_activity() -> None:
    better = _candidate(max_drift="0.0201", total_drift="0.04", sale="1000")
    worse = _candidate(max_drift="0.0202", total_drift="0.02")
    assert score_candidate(better) < score_candidate(worse)
```

Update `test_pnl_fields_cannot_influence_the_engine_contract` to expect `max_sell_quantity`, and update constructor tests to prove it rejects negative or non-finite inventory. Inventory itself may contain a residual fraction; the executable sell bound is `floor(max_sell_quantity / lot_size)` lots.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py tests/unit/test_rebalance.py -q`

Expected: FAIL because `rebalance_optimizer` and the new fields do not exist.

- [ ] **Step 3: Add immutable contracts and exact score comparison**

In `rebalance.py`, replace the minimum-amount option and extend results:

```python
@dataclass(frozen=True)
class AssetInput:
    asset_class_id: str
    symbol: str
    currency: Currency
    current_value_cny: Decimal
    target_weight: Decimal
    unit_price_cny: Decimal
    lot_size: Decimal
    max_sell_quantity: Decimal


@dataclass(frozen=True)
class RebalanceOptions:
    tolerance: Decimal
    allow_sell: bool
    allow_fx: bool


@dataclass(frozen=True)
class RebalanceResult:
    feasible: bool
    max_drift_before: Decimal
    max_drift_after: Decimal
    buy_only_max_drift: Decimal
    optimization_precision: Decimal
    optimization_certified: bool
    optimality_gap: Decimal
    sell_phase_used: bool
    net_fx_direction: Literal["cny_to_usd", "usd_to_cny", "none"]
    net_fx_amount_cny: Decimal
    fx_required_cny: Decimal
    remaining_cny: Decimal
    remaining_usd: Decimal
    projected_weights: tuple[ProjectedWeight, ...]
    trades: tuple[TradeSuggestion, ...]
```

In the new optimizer module, implement exact bucketing and a stable score:

```python
OPTIMIZATION_EPSILON = Decimal("0.0001")
NODE_BUDGET = 250_000


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    lot_counts: tuple[int, ...]
    final_values: tuple[Decimal, ...]
    max_drift: Decimal
    total_drift: Decimal
    total_sale_cny: Decimal
    net_fx_cny: Decimal
    total_traded_cny: Decimal
    trade_count: int
    remaining_cny: Decimal
    remaining_usd: Decimal
    stable_trade_key: tuple[tuple[str, str, Decimal], ...]


@dataclass(frozen=True, slots=True)
class ContinuousBound:
    max_drift: Decimal
    total_drift: Decimal
    guide_values: tuple[Decimal, ...]
    lot_bounds: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class CertifiedPlan:
    candidate: CandidatePlan
    best_open_lower_bound: Decimal
    optimality_gap: Decimal
    explored_nodes: int


class OptimizationFailure(RuntimeError):
    def __init__(self, code: str, explored_nodes: int, gap: Decimal) -> None:
        super().__init__(code)
        self.code = code
        self.explored_nodes = explored_nodes
        self.gap = gap


def _bucket(value: Decimal) -> int:
    return int((value / OPTIMIZATION_EPSILON).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True, order=True, slots=True)
class PlanScore:
    max_drift_bucket: int
    total_drift_bucket: int
    total_sale_cny: Decimal
    absolute_net_fx_cny: Decimal
    total_traded_cny: Decimal
    trade_count: int
    stable_trade_key: tuple[tuple[str, str, Decimal], ...]


def score_candidate(candidate: CandidatePlan) -> PlanScore:
    return PlanScore(
        _bucket(candidate.max_drift),
        _bucket(candidate.total_drift),
        candidate.total_sale_cny,
        abs(candidate.net_fx_cny),
        candidate.total_traded_cny,
        candidate.trade_count,
        candidate.stable_trade_key,
    )
```

`CandidatePlan.for_test()` fills remaining balances, activity totals, and the stable key with deterministic defaults while requiring the drift and lot/value fields shown in the test. Production code constructs `CandidatePlan` directly after cash-ledger evaluation.

- [ ] **Step 4: Run focused tests**

Run: `cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py tests/unit/test_rebalance.py -q`

Expected: PASS for contract/scoring tests; legacy greedy-behavior tests may still fail only where their constructor signatures intentionally changed.

- [ ] **Step 5: Commit the contract**

```bash
git add backend/app/domain/rebalance.py backend/app/domain/rebalance_optimizer.py backend/tests/unit/test_rebalance.py backend/tests/unit/test_rebalance_optimizer.py
git commit -m "refactor: define minimax rebalance contract"
```

---

### Task 2: Implement continuous bounds and bidirectional cash feasibility

**Files:**
- Modify: `backend/app/domain/rebalance_optimizer.py`
- Modify: `backend/tests/unit/test_rebalance_optimizer.py`

**Interfaces:**
- Consumes: public `AssetInput`, `CashInput`, `allow_fx`, and signed continuous trade bounds.
- Produces: `ContinuousBound`, `continuous_relaxation()`, and `evaluate_cash_ledger()` for Task 3.

- [ ] **Step 1: Write failing continuous-bound and currency-ledger tests**

Cover a two-class exact solution, CNY-to-USD, USD-to-CNY, disabled FX, sale proceeds, and the absence of round trips:

```python
def asset(asset_class_id: str, currency: str, current: str, target: str) -> AssetInput:
    return AssetInput(
        asset_class_id=asset_class_id,
        symbol=asset_class_id.upper(),
        currency=currency,
        current_value_cny=Decimal(current),
        target_weight=Decimal(target),
        unit_price_cny=Decimal("10"),
        lot_size=Decimal("1"),
        max_sell_quantity=Decimal(current) / Decimal("10"),
    )


def test_continuous_relaxation_returns_exact_two_class_lower_bound() -> None:
    bound = continuous_relaxation(
        assets=(asset("a", "CNY", "80", "0.5"), asset("b", "CNY", "20", "0.5")),
        cash=CashInput(Decimal("60"), Decimal("0"), Decimal("7.2")),
        allow_sell=False,
        allow_fx=False,
    )
    assert bound.max_drift == 0
    assert bound.guide_values == (Decimal("80"), Decimal("80"))


def test_cash_ledger_uses_one_net_usd_to_cny_direction() -> None:
    ledger = evaluate_cash_ledger(
        assets=(asset("cn", "CNY", "50", "0.5"), asset("us", "USD", "50", "0.5")),
        lot_counts=(5, 0),
        cash=CashInput(Decimal("0"), Decimal("10"), Decimal("7")),
        allow_fx=True,
    )
    assert ledger.feasible
    assert ledger.net_fx_cny == Decimal("-50")
    assert ledger.remaining_cny == 0
    assert ledger.remaining_usd == Decimal("20") / Decimal("7")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py -q`

Expected: FAIL because relaxation and ledger functions are undefined.

- [ ] **Step 3: Implement the signed net-FX ledger**

For a complete signed lot vector, aggregate CNY and USD buys and sales. Compute the smallest signed transfer that makes both balances nonnegative:

```python
cny_before_fx = cash.cny + cny_sales - cny_buys
usd_cny_before_fx = cash.usd * cash.usd_cny + usd_sales_cny - usd_buys_cny
if not allow_fx:
    feasible = cny_before_fx >= 0 and usd_cny_before_fx >= 0
    net_fx_cny = Decimal("0")
elif cny_before_fx < 0:
    net_fx_cny = cny_before_fx  # negative means USD -> CNY
elif usd_cny_before_fx < 0:
    net_fx_cny = -usd_cny_before_fx  # positive means CNY -> USD
else:
    net_fx_cny = Decimal("0")
feasible = feasible and cny_before_fx - net_fx_cny >= 0 and usd_cny_before_fx + net_fx_cny >= 0
```

Return exact post-FX balances. Never create two conversion legs.

- [ ] **Step 4: Implement the continuous relaxation**

Use fixed-`Dmax` feasibility with bisection. For trial drift `d` and invested total `V`, every final value must satisfy:

```text
max(min_value_i, (target_i - d) * V)
    <= final_value_i <=
min(max_value_i, (target_i + d) * V)
```

`min_value_i` is current value in buy-only mode and current value minus preferred executable inventory in sell mode. `max_value_i` is current value plus the maximum affordable contribution/sale-proceeds upper bound. Intersect the summed intervals with currency-ledger feasibility; bisect `d` until the remaining interval is narrower than `OPTIMIZATION_EPSILON / 16`. Return the lowest feasible `d`, guide values chosen by water-filling inside the intervals, and exact per-node lot bounds derived from those values.

Implement the relaxation with `Decimal`, stable asset ordering, and a calculation context derived from input digit counts. Do not convert to float.

- [ ] **Step 5: Run focused tests**

Run: `cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py -q`

Expected: PASS, including exact bidirectional ledger balances and the two-class zero-drift bound.

- [ ] **Step 6: Commit relaxation and currency feasibility**

```bash
git add backend/app/domain/rebalance_optimizer.py backend/tests/unit/test_rebalance_optimizer.py
git commit -m "feat: bound minimax rebalance allocations"
```

---

### Task 3: Add certified discrete branch search and exhaustive oracle coverage

**Files:**
- Modify: `backend/app/domain/rebalance_optimizer.py`
- Modify: `backend/tests/unit/test_rebalance_optimizer.py`

**Interfaces:**
- Consumes: `continuous_relaxation()`, `evaluate_cash_ledger()`, `score_candidate()`, and `NODE_BUDGET`.
- Produces: `optimize_discrete(assets, cash, *, allow_sell, allow_fx) -> CertifiedPlan` and typed `OptimizationFailure(code, explored_nodes, gap)`.

- [ ] **Step 1: Write a bounded exhaustive oracle in tests**

Implement a test-only enumerator over small signed lot ranges and compare production scores:

```python
SMALL_ASSETS = (
    asset("a", "CNY", "40", "0.5"),
    asset("b", "USD", "60", "0.5"),
)
SMALL_CASH = CashInput(Decimal("30"), Decimal("20") / Decimal("7"), Decimal("7"))


def exhaustive_best(assets, cash, *, allow_sell, allow_fx):
    ranges = [range(-int(a.max_sell_quantity / a.lot_size), 7) for a in assets]
    candidates = []
    for lots in product(*ranges):
        candidate = candidate_from_lots(assets, cash, lots, allow_fx=allow_fx)
        if candidate is not None and (allow_sell or all(lot >= 0 for lot in lots)):
            candidates.append(candidate)
    return min(candidates, key=score_candidate)


@pytest.mark.parametrize("allow_sell,allow_fx", [(False, False), (False, True), (True, False), (True, True)])
def test_search_matches_exhaustive_oracle(allow_sell: bool, allow_fx: bool) -> None:
    expected = exhaustive_best(SMALL_ASSETS, SMALL_CASH, allow_sell=allow_sell, allow_fx=allow_fx)
    actual = optimize_discrete(SMALL_ASSETS, SMALL_CASH, allow_sell=allow_sell, allow_fx=allow_fx)
    assert score_candidate(actual.candidate) == score_candidate(expected)
    assert actual.optimality_gap <= OPTIMIZATION_EPSILON
```

Add a fixture where the preferred holding owns only two lots while other holdings make the class much larger; assert the lower lot bound never permits selling a third lot.

- [ ] **Step 2: Run oracle tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py -q`

Expected: FAIL because `optimize_discrete` is undefined.

- [ ] **Step 3: Implement deterministic branch-and-bound**

Represent a node as immutable inclusive lot intervals ordered by asset-class ID. Seed the incumbent by rounding the continuous guide toward zero and evaluating neighboring floor/ceiling lots. Push the root into a heap keyed by its optimistic `PlanScore` lower bound and stable interval key.

For each popped node:

```python
while heap:
    if explored_nodes == NODE_BUDGET:
        raise OptimizationFailure("REBALANCE_OPTIMIZATION_UNCERTIFIED", explored_nodes, incumbent_gap())
    node = heappop(heap)
    explored_nodes += 1
    bound = continuous_relaxation_for_node(node, ...)
    if incumbent is not None and bound.cannot_beat(score_candidate(incumbent)):
        continue
    if node.is_singleton:
        candidate = candidate_from_lots(...)
        if candidate is not None and (incumbent is None or score_candidate(candidate) < score_candidate(incumbent)):
            incumbent = candidate
        continue
    left, right = node.split_largest_value_interval_near(bound.guide_values)
    heappush(heap, left)
    heappush(heap, right)
```

Stop exactly when the heap is exhausted. The search may stop earlier only when the incumbent is within 1 bp of the best optimistic `Dmax` bound remaining in the heap:

```python
if not heap:
    return CertifiedPlan(incumbent, incumbent.max_drift, Decimal("0"), explored_nodes)
best_open_bound = min(node.max_drift_lower_bound for node in heap)
gap = max(Decimal("0"), incumbent.max_drift - best_open_bound)
if gap <= OPTIMIZATION_EPSILON:
    return CertifiedPlan(incumbent, best_open_bound, gap, explored_nodes)
```

The node's optimistic score must lower-bound both drift buckets and use zero for activity components that remain undecided. Stable heap keys and split rules make input permutation irrelevant. A large integrality gap from a 100-share lot is valid: exhausting all competitive branches certifies the best executable plan with gap zero even when the root continuous bound is much better.

- [ ] **Step 4: Add node-budget failure coverage**

Monkeypatch `NODE_BUDGET` to `1`, provide a root requiring a split, and assert the exact typed code, explored-node count, and positive remaining gap. Assert that no `CandidatePlan` is returned alongside the error.

- [ ] **Step 5: Run optimizer tests**

Run: `cd backend && uv run pytest tests/unit/test_rebalance_optimizer.py -q`

Expected: PASS for exhaustive oracle, inventory cap, deterministic order, certification gap, and node-budget failure.

- [ ] **Step 6: Commit the certified search**

```bash
git add backend/app/domain/rebalance_optimizer.py backend/tests/unit/test_rebalance_optimizer.py
git commit -m "feat: certify executable rebalance plans"
```

---

### Task 4: Replace the greedy public facade and lock strategy semantics

**Files:**
- Modify: `backend/app/domain/rebalance.py`
- Modify: `backend/tests/unit/test_rebalance.py`
- Modify: `backend/tests/unit/test_rebalance_properties.py`

**Interfaces:**
- Consumes: `optimize_discrete()` and updated public contracts from Tasks 1–3.
- Produces: stable `rebalance(assets, cash, options) -> RebalanceResult` with two-phase selling and net trade reasons.

- [ ] **Step 1: Replace greedy-order tests with approved behavior tests**

Delete assertions that encode “largest deficit then symbol.” Add the gold-starvation regression, sale gate, lot-only minimum, and sub-1-bp suppression:

```python
GOLD_STARVATION_ASSETS = (
    AssetInput("sp500", "VOO", "USD", Decimal("31300"), Decimal("0.30"), Decimal("4869"), Decimal("0.01"), Decimal("6.43")),
    AssetInput("nasdaq", "QQQ", "USD", Decimal("20500"), Decimal("0.20"), Decimal("3575"), Decimal("0.01"), Decimal("5.73")),
    AssetInput("dividend", "159209", "CNY", Decimal("20200"), Decimal("0.20"), Decimal("1.145"), Decimal("100"), Decimal("17600")),
    AssetInput("quality", "563020", "CNY", Decimal("19300"), Decimal("0.20"), Decimal("1.184"), Decimal("100"), Decimal("16300")),
    AssetInput("gold", "518880", "CNY", Decimal("8700"), Decimal("0.10"), Decimal("20"), Decimal("100"), Decimal("400")),
)
GOLD_STARVATION_CASH = CashInput(Decimal("10000"), Decimal("1500"), Decimal("7.2"))


def test_minimax_contribution_does_not_starve_underweight_gold() -> None:
    result = rebalance(GOLD_STARVATION_ASSETS, GOLD_STARVATION_CASH, RebalanceOptions(Decimal("0.04"), True, True))
    gold = next(weight for weight in result.projected_weights if weight.asset_class_id == "gold")
    assert any(trade.symbol == "518880" and trade.action == "buy" for trade in result.trades)
    assert gold.after > gold.before
    assert result.max_drift_after < Decimal("0.01")


def test_buy_only_within_tolerance_never_uses_sell_phase() -> None:
    assets = (
        AssetInput("a", "AAA", "CNY", Decimal("51"), Decimal("0.5"), Decimal("1"), Decimal("1"), Decimal("51")),
        AssetInput("b", "BBB", "CNY", Decimal("49"), Decimal("0.5"), Decimal("1"), Decimal("1"), Decimal("49")),
    )
    result = rebalance(assets, CashInput(Decimal("2"), Decimal("0"), Decimal("7.2")), RebalanceOptions(Decimal("0.02"), True, True))
    assert result.buy_only_max_drift <= Decimal("0.02")
    assert not result.sell_phase_used
    assert all(trade.action == "buy" for trade in result.trades)
```

- [ ] **Step 2: Run public-domain tests and verify failure**

Run: `cd backend && uv run pytest tests/unit/test_rebalance.py tests/unit/test_rebalance_properties.py -q`

Expected: FAIL because the facade still executes greedy passes and uses the removed minimum amount.

- [ ] **Step 3: Implement two-phase orchestration and result construction**

Sort assets once, compute original weights, and call `optimize_discrete(..., allow_sell=False)`. Only call again with sales when the buy-only candidate exceeds tolerance and `options.allow_sell` is true. Build net trades from signed lots and assign reason codes:

```python
ReasonCode = Literal[
    "REDUCE_MAX_DRIFT",
    "REDUCE_TOTAL_DRIFT",
    "REALLOCATE_OUTSIDE_TOLERANCE",
]

buy_only = optimize_discrete(asset_list, cash, allow_sell=False, allow_fx=options.allow_fx)
selected = buy_only
sell_phase_used = False
if options.allow_sell and buy_only.candidate.max_drift > options.tolerance:
    selected = optimize_discrete(asset_list, cash, allow_sell=True, allow_fx=options.allow_fx)
    sell_phase_used = True
```

For each net order, rescore the plan with that order removed. Use `REDUCE_MAX_DRIFT` when the maximum-drift bucket worsens, `REDUCE_TOTAL_DRIFT` when only the total-drift bucket worsens, and `REALLOCATE_OUTSIDE_TOLERANCE` for sell-phase orders required by the certified phase-two plan.

Keep `fx_required_cny` as a compatibility alias: it equals `net_fx_amount_cny` only for `cny_to_usd`, otherwise zero.

- [ ] **Step 4: Rewrite properties around the new contract**

Remove generated `minimum_trade` inputs. Generate nonnegative `max_sell_quantity` values aligned to lot size. Assert exact lot multiples, sale inventory caps, currency conservation, at most one net FX direction, no disabled action, stable permutation results, immutable inputs, and precision independence.

- [ ] **Step 5: Run all domain tests**

Run: `cd backend && uv run pytest tests/unit/test_rebalance.py tests/unit/test_rebalance_optimizer.py tests/unit/test_rebalance_properties.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the domain cutover**

```bash
git add backend/app/domain/rebalance.py backend/tests/unit/test_rebalance.py backend/tests/unit/test_rebalance_properties.py
git commit -m "feat: use minimax portfolio rebalancing"
```

---

### Task 5: Integrate preferred inventory, schemas, persistence, and settings compatibility

**Files:**
- Modify: `backend/app/services/rebalancing.py`
- Modify: `backend/app/schemas/rebalance.py`
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/services/settings.py`
- Modify: `backend/tests/integration/test_rebalance_api.py`
- Modify: `backend/tests/integration/test_rebalance_defaults_preview.py`
- Modify: `backend/tests/integration/test_settings_api.py`

**Interfaces:**
- Consumes: Task 4 `AssetInput`, `RebalanceOptions`, and `RebalanceResult`.
- Produces: active request schemas without `minimum_trade_cny`, optional plan legacy minimum, serialized optimization metadata, preserved legacy settings values, and typed optimizer service errors.

- [ ] **Step 1: Write failing schema and integration assertions**

Assert new preview requests do not contain `minimum_trade_cny`; new plans return `minimum_trade_cny: null`; old stored plans still return their string; settings PUT requests omit the legacy value and preserve the database column. Add a multi-holding class and assert the service passes only the preferred holding quantity as sell inventory.

Add expected result metadata:

```python
assert payload["result"]["optimization_precision"] == "0.0001"
assert payload["result"]["optimization_certified"] is True
assert Decimal(payload["result"]["optimality_gap"]) <= Decimal("0.0001")
assert payload["result"]["net_fx_direction"] in {"cny_to_usd", "usd_to_cny", "none"}
assert payload["result"]["sell_phase_used"] is False
```

- [ ] **Step 2: Run isolated backend integration suite and verify failure**

Run: `make test-backend`

Expected: FAIL in rebalance/settings contract tests because schemas and service still require and use the minimum amount.

- [ ] **Step 3: Update Pydantic schemas and serialization**

Remove `minimum_trade_cny` from `RebalancePreviewRequest`. Change `RebalancePlanResponse.minimum_trade_cny` to `DecimalString | None`. Extend `RebalanceResultResponse` with the exact Task 1 metadata and constrain direction to its three literals. Add the three optimizer-intent reason codes while retaining legacy funding-source literals for historical response validation; newly calculated results emit only the new codes.

Catch `OptimizationFailure` in the service boundary and raise:

```python
raise ServiceError(
    422,
    "REBALANCE_OPTIMIZATION_UNCERTIFIED",
    "无法在 1bp 精度内生成可认证的再平衡方案。",
    {"explored_nodes": exc.explored_nodes, "optimality_gap": format(exc.gap, "f")},
)
```

- [ ] **Step 4: Map preferred sell inventory and remove active minimum resolution**

When building each `AssetInput`, pass `max_sell_quantity=preferred.quantity`. Remove `minimum_trade_cny` from `_ResolvedConstraints`, `_run_engine`, defaults preview construction, new plan `resolved_constraints`, and new plan responses. Serialize new metadata and map reason codes to approved Chinese explanations.

- [ ] **Step 5: Preserve legacy settings without requiring updates**

Remove minimum fields from `GeneralSettingsUpdate` and `RebalanceDefaultsUpdate`, but retain them on response types. In both update services, stop assigning `setting.minimum_trade_amount_cny`; response builders continue exposing its stored value for compatibility. New plan input summaries store `minimum_trade_cny: None`; `_plan_response` reads absent/legacy values with `.get("minimum_trade_cny")`.

- [ ] **Step 6: Run isolated backend suite**

Run: `make test-backend`

Expected: PASS for all unit and integration tests in the disposable `portfolio_test` database.

- [ ] **Step 7: Commit backend integration**

```bash
git add backend/app/services/rebalancing.py backend/app/schemas/rebalance.py backend/app/schemas/settings.py backend/app/services/settings.py backend/tests/integration/test_rebalance_api.py backend/tests/integration/test_rebalance_defaults_preview.py backend/tests/integration/test_settings_api.py
git commit -m "feat: expose certified rebalance results"
```

---

### Task 6: Remove minimum-amount inputs from frontend requests and settings

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/RebalancePage.tsx`
- Modify: `frontend/src/features/rebalance/RebalanceInputs.tsx`
- Modify: `frontend/src/features/settings/ProviderSettings.tsx`
- Modify: `frontend/src/features/settings/api.ts`
- Modify: `frontend/tests/RebalancePage.test.tsx`
- Modify: `frontend/tests/ProviderSettings.test.tsx`
- Modify: `frontend/tests/fixtures.ts`

**Interfaces:**
- Consumes: Task 5 API shape.
- Produces: payloads with no minimum amount, form state with no `minimumTradeCny`, optional legacy plan field, and settings mutations that preserve deprecated response-only fields.

- [ ] **Step 1: Write failing frontend payload and form tests**

Assert that neither rebalance preview/default PUT nor general settings PUT contains `minimum_trade_cny`/`minimum_trade_amount_cny`; assert “最小交易金额” is absent and FX copy says “人民币与美元可按需要双向净换汇”.

- [ ] **Step 2: Run focused frontend tests and verify failure**

Run: `cd frontend && npm test -- --run tests/RebalancePage.test.tsx tests/ProviderSettings.test.tsx`

Expected: FAIL because inputs and payloads still contain minimum-amount fields.

- [ ] **Step 3: Update TypeScript contracts and request builders**

Remove the field from `RebalancePreviewPayload` and active settings update payload types. Keep `GeneralSettings.minimum_trade_amount_cny` and `RebalanceDefaults.minimum_trade_cny` response-only, and change `RebalancePlan.minimum_trade_cny` to `DecimalString | null`. Add all Task 5 optimization result fields and the three direction literals.

Use explicit update payload types rather than `Omit<Response, "updated_at">`, so deprecated response-only fields cannot leak into PUT requests.

- [ ] **Step 4: Remove UI state and controls**

Delete `minimumTradeCny` from `RebalanceFormState`, initial state, hydration, active-plan restoration, `defaultsPayloadFor`, and `payloadFor`. Remove the form field from `RebalanceInputs` and the general settings editor. Preserve tolerance, sell, and FX behavior.

- [ ] **Step 5: Run focused tests and build**

Run: `cd frontend && npm test -- --run tests/RebalancePage.test.tsx tests/ProviderSettings.test.tsx && npm run build`

Expected: PASS; TypeScript build reports no contract mismatch.

- [ ] **Step 6: Commit frontend request cleanup**

```bash
git add frontend/src/api/types.ts frontend/src/pages/RebalancePage.tsx frontend/src/features/rebalance/RebalanceInputs.tsx frontend/src/features/settings/ProviderSettings.tsx frontend/src/features/settings/api.ts frontend/tests/RebalancePage.test.tsx frontend/tests/ProviderSettings.test.tsx frontend/tests/fixtures.ts
git commit -m "feat: use lot sizes for rebalance orders"
```

---

### Task 7: Explain minimax certification, sell gating, and net FX in the UI

**Files:**
- Modify: `frontend/src/features/rebalance/RebalanceSummary.tsx`
- Modify: `frontend/src/features/rebalance/TradeSuggestions.tsx`
- Modify: `frontend/src/features/rebalance/Rebalance.module.css`
- Create: `frontend/tests/RebalanceSummary.test.tsx`
- Modify: `frontend/tests/RebalancePage.test.tsx`

**Interfaces:**
- Consumes: Task 6 `RebalanceResult` metadata and existing formatting helpers.
- Produces: accessible before/buy-only/final drift summary, certification label, net-FX text, and optimizer-intent trade reasons.

- [ ] **Step 1: Write failing summary tests**

Render fixtures for buy-only, sell-phase, CNY-to-USD, USD-to-CNY, and uncertified API error states. Assert visible text such as:

```text
最大偏离 3.20pp → 1.40pp
已在 1bp 精度内认证
纯补仓 2.30pp，卖出转配后 1.40pp
净换汇：美元换人民币 ¥5,000
```

Assert the certification label has accessible text and is not conveyed by color alone. Add a historical fixture with `optimization_certified: false` and assert that it shows “历史方案未经过新优化器认证” instead of the certification label.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend && npm test -- --run tests/RebalanceSummary.test.tsx tests/RebalancePage.test.tsx`

Expected: FAIL because current summary has only before/final drift and one-way FX fields.

- [ ] **Step 3: Implement summary and trade explanations**

Show before and final drift always. Show the intermediate buy-only value only when `sell_phase_used` is true. When `optimization_certified` is true, format `optimization_precision` as `1bp` and show `optimality_gap` in an accessible detail string; otherwise show the historical-unverified copy. Render signed FX direction without a round-trip representation.

Keep trade reason text supplied by the API; add no client-side inference. Update summary layout for narrow widths and ensure labels remain readable at 200% zoom.

- [ ] **Step 4: Run component and page tests**

Run: `cd frontend && npm test -- --run tests/RebalanceSummary.test.tsx tests/RebalancePage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit result explanation UI**

```bash
git add frontend/src/features/rebalance/RebalanceSummary.tsx frontend/src/features/rebalance/TradeSuggestions.tsx frontend/src/features/rebalance/Rebalance.module.css frontend/tests/RebalanceSummary.test.tsx frontend/tests/RebalancePage.test.tsx
git commit -m "feat: explain minimax rebalance plans"
```

---

### Task 8: Update saved-plan, backup, email, fixtures, and end-to-end compatibility

**Files:**
- Modify: `backend/app/services/backup_validation.py`
- Modify: `backend/app/services/email_digest.py`
- Modify: `backend/tests/unit/test_backup_validation.py`
- Modify: `backend/tests/integration/test_email_digest.py`
- Modify: `frontend/tests/fixtures.ts`
- Modify: `frontend/tests/RebalanceLifecycle.test.tsx`
- Modify: `frontend/e2e/fixtures/portfolio.ts`
- Modify: `frontend/e2e/rebalance.spec.ts`

**Interfaces:**
- Consumes: optional historical `minimum_trade_cny`, new result metadata, and optimizer-intent reason codes.
- Produces: restore compatibility for old plans, valid current saved plans, named email trades, and complete browser workflow coverage.

- [ ] **Step 1: Write failing legacy/current compatibility tests**

Use one backup fixture with a historical string minimum and legacy reason/result shape, and one current fixture with `null` minimum plus full optimization metadata. Assert both validate and restore. Assert email digest renders the new reason text and does not require the old funding-source reason code.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `make test-backend`

Expected: FAIL on current plan shape and new reason codes in the isolated `portfolio_test` project.

- [ ] **Step 3: Extend backup compatibility normalization**

Normalize legacy plans before current strict validation by adding default metadata derived from their stored result:

```python
result.setdefault("optimization_precision", "0.0001")
result.setdefault("optimization_certified", False)
result.setdefault("optimality_gap", "0")
result.setdefault("buy_only_max_drift", result["max_drift_after"])
result.setdefault("sell_phase_used", any(t["action"] == "sell" for t in result["trades"]))
result.setdefault("net_fx_direction", "cny_to_usd" if Decimal(result["fx_required_cny"]) > 0 else "none")
result.setdefault("net_fx_amount_cny", result["fx_required_cny"])
```

This normalization supports rendering only. The UI shows the certification label only when `optimization_certified` is true, so historical plans are not relabelled as newly certified. Preserve legacy reason strings as stored.

- [ ] **Step 4: Update downstream fixtures and end-to-end assertions**

Add metadata to current frontend fixtures, make plan minimum nullable, and assert the browser workflow displays certification, no minimum-amount input, a fair gold allocation, and the correct net-FX direction.

- [ ] **Step 5: Run backend, frontend, and E2E focused tests**

Run: `make test-backend`

Expected: PASS in the isolated test project.

Run: `cd frontend && npm test -- --run tests/RebalanceLifecycle.test.tsx tests/RebalancePage.test.tsx tests/RebalanceSummary.test.tsx`

Expected: PASS.

Run: `cd frontend && npm run test:e2e -- rebalance.spec.ts`

Expected: PASS.

- [ ] **Step 6: Commit compatibility work**

```bash
git add backend/app/services/backup_validation.py backend/app/services/email_digest.py backend/tests/unit/test_backup_validation.py backend/tests/integration/test_email_digest.py frontend/tests/fixtures.ts frontend/tests/RebalanceLifecycle.test.tsx frontend/e2e/fixtures/portfolio.ts frontend/e2e/rebalance.spec.ts
git commit -m "test: preserve rebalance plan compatibility"
```

---

### Task 9: Document and verify the complete strategy

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `backend/tests/unit/test_rebalance_optimizer.py`
- Modify: `frontend/e2e/accessibility.spec.ts`

**Interfaces:**
- Consumes: completed backend/frontend behavior.
- Produces: user documentation, deterministic performance coverage, accessibility verification, and final release evidence.

- [ ] **Step 1: Add deterministic performance and adversarial tests**

Add representative five-class fixtures for large values, 100-share CNY lots, 0.01-share USD lots, both FX directions, sell phase, and tight tolerance. Measure the normal fixture around `rebalance()` with `time.perf_counter()` and assert `< 0.5` seconds in the project CI environment. Keep the node-exhaustion test deterministic by lowering the node budget, not by asserting a timeout.

- [ ] **Step 2: Update the user guide**

Explain in Chinese that the optimizer minimizes the worst absolute percentage-point drift, then total drift; available cash is a cap; unused cash is excluded; selling starts only when buy-only remains outside tolerance; FX is bidirectional net conversion; lot size is the only trade minimum; and the result is certified within 1 bp.

- [ ] **Step 3: Run complete verification**

Run: `make test-backend`

Expected: all backend unit/integration/property tests PASS against `portfolio_test`, with cleanup succeeding.

Run: `cd frontend && npm test && npm run build && npm run test:e2e`

Expected: all Vitest tests PASS, Vite build succeeds, and all Playwright tests PASS.

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 4: Review the final diff against the design acceptance criteria**

Confirm every acceptance criterion in `docs/superpowers/specs/2026-08-27-minimax-rebalancing-strategy-design.md` has a corresponding passing test and that no production reference to greedy deficit ordering remains:

```bash
rg -n "largest deficit|UNDERWEIGHT_WITH_CASH|minimum_trade_cny" backend/app frontend/src
```

Expected: no active greedy reason/order logic; only explicitly deprecated response compatibility references to `minimum_trade_cny` remain.

- [ ] **Step 5: Commit documentation and final verification fixtures**

```bash
git add docs/user-guide.md backend/tests/unit/test_rebalance_optimizer.py frontend/e2e/accessibility.spec.ts
git commit -m "docs: explain minimax rebalancing"
```
