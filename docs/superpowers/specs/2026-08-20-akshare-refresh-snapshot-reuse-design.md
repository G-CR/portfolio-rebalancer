# AKShare Refresh Snapshot Reuse Design

## Goal

Reduce a full market-data refresh from one complete AKShare ETF download per domestic holding to one complete download per refresh cycle, without changing provider priority, fallback behavior, or persisted market-data semantics.

## Scope

- Optimize only AKShare price retrieval for supported domestic markets.
- Keep the existing provider order unchanged: domestic prices use AKShare and then Tushare; international prices and FX retain their current providers and fallbacks.
- Do not require or configure a Tushare token.
- Do not change the frontend, API response contracts, database schema, Compose configuration, or scheduled-refresh behavior.
- Do not introduce a process-wide or time-based cache.

## Architecture

`refresh_all_required_data` creates one `ProviderRegistry` for each refresh. That registry owns one `AkshareProvider` instance. The provider will lazily create and retain a single asynchronous snapshot task the first time `fetch_price` is called.

The snapshot consists of:

- the complete rows returned by `ak.fund_etf_spot_em()`; and
- one `fetched_at` timestamp representing when that snapshot request began.

Every later AKShare price request through the same provider instance awaits the same task and normalizes its requested symbol from the shared rows. A new refresh creates a new registry and provider, so it always starts with an empty cache and fetches a fresh snapshot.

## Data Flow

1. The refresh service collects and sorts all required market-data keys exactly as it does today.
2. The first SH or SZ price request reaches `AkshareProvider.fetch_price` and creates the snapshot task.
3. The task runs the blocking AKShare download once in a worker thread.
4. The requested symbol is normalized from the returned rows.
5. Further SH or SZ price requests during the same refresh await the completed task and normalize their own symbols without another network request.
6. The service validates and persists each quote independently using the existing write path.

The optimization is internal to the provider. Callers continue using `fetch_price(symbol)` and do not need AKShare-specific batching logic.

## Concurrency and Failure Handling

The shared object is an `asyncio.Task`, not only a completed row list. Sequential and concurrent calls therefore both share one in-flight request.

If the snapshot request fails, the failed task remains cached for that provider instance. Each domestic symbol observes the same AKShare request failure and continues through the existing per-symbol fallback to Tushare. This guarantees one AKShare network attempt per refresh even during an outage.

The failure is not retained across refresh cycles. A later refresh creates a new provider instance and retries AKShare normally.

Symbol-specific normalization errors remain independent. For example, if one requested symbol is absent from a successful snapshot, that symbol can fall back while other symbols still use the shared snapshot successfully.

## Testing

Add focused backend tests that prove:

- sequential price requests for different domestic symbols invoke the blocking AKShare download once and return symbol-specific quotes;
- concurrent price requests share one in-flight snapshot request;
- a failed snapshot request is invoked once and the same provider-level request failure is observed by all calls;
- a new `AkshareProvider` instance performs a fresh request;
- existing normalization and provider-selection tests remain green;
- the complete backend suite passes through the isolated `make test-backend` target.

Tests must use deterministic in-memory rows or controlled provider doubles and must not access external market-data services.

## Success Criteria

- One market-data refresh performs at most one `fund_etf_spot_em()` call, regardless of the number of domestic holdings.
- All domestic symbols are still persisted and diagnosed independently.
- Existing provider order, fallback summaries, API schemas, and frontend behavior are unchanged.
- A subsequent refresh performs a new AKShare request.
