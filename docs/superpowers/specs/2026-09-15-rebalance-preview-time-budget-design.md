# Rebalance preview time budget

## Context

The asynchronous preview worker protects the web API from long-running discrete
optimization. Production evidence shows the current portfolio reached the
15-second optimization deadline after 10,289 nodes. Market-data refresh had
already completed, so this is a calculation-budget limit rather than a request
or provider failure.

## Decision

Increase the worker's preview optimization budget from 15 seconds to 300
seconds. Keep the existing node budget, persistent job state, 120-second stale
job recovery, and frontend polling unchanged.

## Behaviour

- A preview continues to run in the worker while the page polls its job status.
- The API remains responsive regardless of calculation duration.
- A calculation still ends with a typed timeout if it exceeds five minutes.
- The existing node cap still prevents unbounded search even before the time
  limit is reached.
- No portfolio, holding, market-data, or configuration records are changed by
  this adjustment.

## Verification

Add a unit-level assertion for the five-minute worker budget and run the worker
and optimizer tests in the isolated test Compose environment.
