# Minimax Rebalancing Strategy Design

**Date:** 2026-08-27  
**Status:** Approved design

## Purpose

Replace the current order-dependent greedy rebalancing strategy with a portfolio-level optimizer. The optimizer must allocate a limited contribution fairly across asset classes by minimizing the worst post-trade allocation drift, while respecting currencies, executable lot sizes, optional selling, and optional foreign exchange.

The motivating failure is a portfolio in which gold is already below its 10% target and becomes even more underweight after the proposed trades because larger absolute CNY deficits consume the available cash first. The new strategy must compare complete portfolios rather than fill deficits sequentially.

## Scope

This change redesigns the rebalancing domain algorithm, the service input assembled for that algorithm, the preview and saved-plan result metadata, and the rebalance page's explanation of the result.

It does not add brokerage execution, transaction-fee modelling, a cash asset class, asset-level targets inside an asset class, or a general-purpose mathematical-programming dependency.

## User Decisions

The approved behavior is:

- Drift is measured in absolute percentage points, not relative to an asset class's target.
- The primary objective is to minimize the largest post-trade absolute drift across asset classes.
- Available CNY and USD are upper bounds, not amounts that must be invested.
- Unused cash remains outside the portfolio and is excluded from projected-weight denominators.
- The optimizer first finds the best buy-only plan. Selling is considered only when that plan remains outside tolerance and selling is enabled.
- Foreign exchange, when enabled, may be CNY-to-USD or USD-to-CNY, but a plan has only one net direction.
- Targets and drift apply to asset classes. Trades use each class's preferred rebalance holding.
- Among plans with the same worst drift at 1 bp precision, minimize total absolute drift.
- If allocation quality is still equal, minimize sale amount, then FX amount, then total traded amount, then trade count.
- There is no portfolio-wide minimum trade amount. Each holding's lot size is the hard quantity increment: commonly 100 shares for domestic ETFs and 0.01 shares for fractionally tradable US holdings.
- Improvements below 1 bp are not operationally meaningful.
- Results must be certified to within 1 bp of the continuous theoretical lower bound.
- Fees are excluded from this redesign.

## Objective and Deterministic Ordering

For asset class `i`, let:

- `w_i` be its target weight;
- `v_i` be its post-trade market value in CNY;
- `V = sum(v_i)` be post-trade invested value, excluding unused cash;
- `d_i = abs(v_i / V - w_i)` be its absolute allocation drift.

The two allocation objectives are:

```text
Dmax = max(d_i)
Dsum = sum(d_i)
```

One basis point in allocation space is `epsilon = 0.0001`, equivalent to 0.01 percentage points. Define the comparison bucket:

```text
bucket(x) = ceil(x / epsilon)
```

Candidate plans are compared by the following lexicographic score:

```text
(
  bucket(Dmax),
  bucket(Dsum),
  total_sale_cny,
  absolute_net_fx_cny,
  total_traded_cny,
  trade_count,
  stable_trade_key,
)
```

Using buckets for the first two objectives means an allocation improvement smaller than 1 bp is treated as equivalent. The later objectives then remove negligible fragmented trades. The chosen `Dmax` is less than 1 bp worse than the unbucketed theoretical optimum.

`stable_trade_key` is the ordered tuple of asset-class IDs, symbols, directions, and quantities. It is a final deterministic tie-breaker only; it has no financial meaning.

## Two-Phase Sell Policy

The optimizer runs in two phases:

1. Find and certify the best plan with buys only.
2. If that plan has `Dmax > tolerance`, and selling is enabled, solve again with buys and sells.

If the buy-only plan is already within tolerance, no sell is permitted even if selling could improve the allocation further. This preserves the product's contribution-first intent and the existing promise that selling is used when new funds are insufficient.

When selling is disabled, the certified buy-only result is final. A certified result outside tolerance is returned normally with `feasible = false`; infeasibility is not a solver error.

## Domain Inputs

The service layer converts database state and effective market data into one immutable optimizer input per active asset class:

- asset-class ID;
- target weight;
- current total class value in CNY, including every active holding in the class;
- preferred rebalance symbol and trade currency;
- preferred holding's unit price in CNY and trade currency;
- preferred holding's lot size;
- preferred holding's current quantity and therefore maximum executable sell quantity.

The current implementation derives a sale cap from the entire asset-class value. That can overstate executable inventory when a class contains multiple holdings. The redesigned contract must cap a sale at the preferred holding's own quantity while continuing to count all class holdings in allocation weights.

Global inputs remain:

- available CNY and USD;
- effective USD/CNY rate;
- tolerance;
- allow-sell flag;
- allow-FX flag.

Prices, weights, quantities, exchange rates, and calculations continue to use `Decimal`. Targets must sum exactly to one under the existing validation rules.

## Executable Trade Model

For each asset class, the signed trade quantity is:

```text
trade_quantity_i = integer_lots_i * lot_size_i
```

A positive quantity buys the preferred holding; a negative quantity sells it. Post-trade class value cannot be negative, and a sell cannot exceed the preferred holding's current executable quantity. There is no CNY-value threshold on an otherwise valid lot.

The cash ledger preserves trade currencies:

- CNY purchases use input CNY, CNY sale proceeds, or net USD-to-CNY conversion.
- USD purchases use input USD, USD sale proceeds, or net CNY-to-USD conversion.
- No currency balance may become negative.
- FX uses the effective preview exchange rate and has no fee or spread in this scope.

FX is represented by one signed net CNY-equivalent variable. Its sign determines direction, so a plan cannot contain a round trip. With FX disabled, the variable is fixed to zero.

Unused balances are returned as `remaining_cny` and `remaining_usd`. They do not contribute to `V` or appear as an asset class.

## Solver Architecture

The domain implementation is split into focused units:

1. **Model validation** validates immutable inputs and constructs executable lot bounds.
2. **Continuous relaxation** ignores integer-lot constraints while preserving portfolio values, buy/sell gates, sale caps, cash currencies, and FX policy. It produces a theoretical lower bound and a continuous guide solution.
3. **Discrete branch search** explores integer-lot decisions near the guide solution and expands outward only when lower bounds show that a better score remains possible.
4. **Cash and FX evaluator** validates a complete candidate's currency feasibility and computes its unique minimum-absolute net FX requirement.
5. **Plan scorer** computes the lexicographic score and deterministic tie-break key.
6. **Result builder** nets all activity into at most one direction per preferred symbol and produces projected weights, trades, remaining cash, and optimization metadata.

At every search node, a continuous relaxation supplies an optimistic lexicographic lower bound. A node is pruned when that bound cannot beat the incumbent plan. Asset branching order is deterministic and independent of caller input order.

Search completes only when no open node can beat the incumbent score. Certification additionally compares the incumbent `Dmax` with the global continuous lower bound and requires a gap no greater than 1 bp.

The search uses a deterministic budget of 250,000 branch nodes rather than a wall-clock cutoff. This prevents identical inputs from succeeding or failing according to machine speed. The product requirement is that a normal five-class preview completes within 500 ms on the supported local environment; exhausting the node budget is permitted to take longer but must end in the typed certification failure.

If the node budget is exhausted before certification, the optimizer returns a typed failure. It must never silently return the old greedy result or label an uncertified result as optimal.

No third-party MILP solver is introduced. If the supported number of asset classes grows enough that the bounded search no longer meets the latency target, adopting a dedicated solver is a separate design decision.

## Service and API Flow

The request flow remains:

```text
preview request
  -> load active classes, holdings, prices, and FX
  -> construct immutable optimizer inputs
  -> run buy-only optimization
  -> conditionally run buy/sell optimization
  -> serialize result and alternate valuation-basis comparison
```

New result metadata is returned for the selected valuation basis and its comparison result:

- `optimization_precision`: `"0.0001"` in ratio units;
- `optimality_gap`: certified difference between the plan's `Dmax` and the continuous lower bound;
- `buy_only_max_drift`: certified `Dmax` from phase one;
- `sell_phase_used`: whether phase two supplied the final plan;
- `net_fx_direction`: `cny_to_usd`, `usd_to_cny`, or `none`;
- `net_fx_amount_cny`: absolute CNY-equivalent net conversion.

Existing `max_drift_before`, `max_drift_after`, projected weights, trades, and remaining balances remain available. `feasible` continues to mean `max_drift_after <= tolerance`.

Trade reason codes are redesigned around optimizer intent rather than the incidental source of funds:

- reducing the portfolio's maximum drift;
- reducing total drift within the best maximum-drift bucket;
- selling and reallocating because the certified buy-only plan remained outside tolerance.

The result builder may determine a trade's reason by rescoring the complete plan without that net order. Reason text is explanatory and does not affect optimization.

## Minimum-Trade Compatibility

The active strategy no longer consumes `minimum_trade_cny`. New preview and plan-create request schemas remove the field. The rebalance form and general/rebalance settings forms stop presenting it as an active constraint and stop sending it in updates.

The existing persisted setting, settings response fields, and historical JSON values remain readable as deprecated compatibility data in this change. Settings updates preserve the stored legacy value without requiring it from the client. They are not used for new previews or plans. This avoids coupling the algorithm redesign to a backup-format migration. A later cleanup may remove the dormant storage field and response fields with an explicit archive migration.

The plan response changes `minimum_trade_cny` to an optional legacy field. Historical saved plans retain their original serialized value; newly created plans store and return `null`. The API must not imply that the legacy value affected a newly calculated plan. New result metadata and UI copy identify lot size as the executable minimum.

## User Interface

The rebalance form removes the minimum-transaction-amount control. Holding configuration remains the source of each symbol's minimum trading unit.

The summary presents:

```text
Maximum drift: before -> best buy-only -> final
Certified within 1 bp
```

If the sell phase is not used, buy-only and final may be shown as one value rather than duplicated. The summary continues to show remaining CNY and USD and adds the net FX direction and amount when nonzero.

Trade explanations use the optimizer-intent reasons defined above. The allocation section continues to show actual, planned, target, and tolerance values. All displayed weights exclude unused contribution cash.

If optimization cannot be certified, the page shows an actionable calculation error and no trade list. It must not render a partial or fallback plan as a normal recommendation.

## Error Handling

The following are typed input or data failures before search:

- targets are invalid or do not sum to 100%;
- an active asset class has no preferred rebalance holding;
- required price or exchange-rate data is absent or invalid;
- lot size is nonpositive or invalid;
- preferred sell inventory is negative or inconsistent with holding state.

Node-budget exhaustion before 1 bp certification is a typed optimization failure. Its public message explains that no certified plan could be produced under the current problem size; internal diagnostics may report explored nodes and the remaining bound gap without exposing sensitive data.

A certified result outside tolerance is a successful response with `feasible = false`, projected allocations, and the best executable trade list under the selected constraints.

## Verification Strategy

### Exhaustive Oracle Tests

Small portfolios with deliberately bounded lot counts are exhaustively enumerated. The production optimizer must return a lexicographic score no worse than the oracle after applying the 1 bp buckets. These tests cover buy-only, sell-enabled, FX-disabled, and bidirectional-FX cases.

### Regression Scenarios

- Reproduce the gold-starvation portfolio and verify that the new plan improves the worst drift and does not depend on asset ordering.
- Verify that an asset currently above target can still receive a buy when optional new capital would otherwise dilute it enough to become a limiting underweight.
- Verify that a class containing multiple holdings cannot sell more than the preferred holding owns.
- Verify that domestic 100-share lots and US 0.01-share lots are both honored without a CNY minimum amount.

### Property Tests

Randomized tests assert:

- no negative cash balance;
- no sale above preferred inventory;
- every quantity is an exact lot-size multiple;
- disabled selling and FX never appear;
- FX has at most one net direction;
- final weights correspond exactly to current values plus net trades;
- `Dmax` and `Dsum` match projected weights;
- output is invariant under input permutations;
- ambient decimal precision does not change results;
- the optimizer does not mutate inputs;
- identical inputs produce byte-for-byte stable trade ordering and metadata.

### Strategy Semantics

- A buy-only result within tolerance prevents the sell phase.
- A buy-only result outside tolerance permits, but does not require, sales when enabled.
- The secondary objective improves total drift only within the best 1 bp `Dmax` bucket.
- Allocation-equivalent candidates prefer less selling, then less FX, then less total activity and fewer orders.
- Sub-1-bp improvements do not create otherwise unnecessary fractional orders.
- `feasible` distinguishes a certified best effort from a certified in-tolerance plan.

### Integration and UI Tests

Preview, plan creation, saved-plan rendering, alternate valuation basis, and email trade rendering consume the new result shape. UI tests cover the three-stage drift summary, certification label, net FX display, removal of the minimum-amount input, optimizer-intent reasons, and typed certification failure.

### Performance Tests

Representative five-class portfolios cover small and large account values, mixed lot sizes, both currencies, phase-two selling, and tight tolerance. The normal preview target is 500 ms. A deterministic adversarial fixture verifies that node-budget exhaustion produces the typed failure rather than an uncertified result.

## Acceptance Criteria

The redesign is complete when:

- the greedy deficit-order passes are no longer used to select trades;
- the returned plan is certified within 1 bp of the continuous `Dmax` lower bound;
- result selection follows the approved lexicographic objectives;
- sell gating, bidirectional net FX, currency budgets, lot sizes, and preferred-holding sale caps are enforced;
- unused cash stays outside projected allocation weights;
- the gold-starvation regression produces a fairer, order-independent result;
- the UI explains buy-only drift, final drift, certification, FX, and trade intent;
- exhaustive, property, integration, UI, and performance tests pass.
