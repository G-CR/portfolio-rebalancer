# Market Data Auto-Sync Design

## Goal

Keep an already-open browser session synchronized with market data refreshed by the backend, without requiring a manual page reload. The behavior is optimized for a single-user local deployment and should remain quiet, predictable, and inexpensive.

## Scope

- Poll the existing `GET /api/market-data` endpoint while the page is visible.
- Refetch immediately when the browser window regains focus or the network reconnects.
- Propagate genuine market-data changes to dependent frontend queries.
- Preserve the existing manual refresh behavior and incomplete-data loop guard.

The change does not add a backend endpoint, server-sent events, WebSockets, onboarding, or new user settings.

## Synchronization Behavior

The market-data query remains mounted in `AppShell` and becomes the single source of truth for both manual and automatic updates.

- Poll every 30 seconds while the page is visible.
- Pause interval polling while the tab is in the background; returning focus triggers an immediate refetch.
- Refetch immediately after network reconnection.
- Keep the current cached response visible during background fetching.

The frontend derives a deterministic revision signature from the market-data collection. The signature covers each item's key, effective value, status, source, market time, fetch time, and error state in stable key order. A response with the same signature is treated as unchanged and does not invalidate dependent queries.

When the signature changes after the initial load, the synchronization layer:

1. Updates the market-data cache through React Query's normal query result handling.
2. Advances the existing market-data refresh version so a stale rebalance preview is cleared.
3. Invalidates holdings and snapshot query roots.
4. Invalidates portfolio analytics only when every required item has an effective value, preserving the existing protection against incomplete-data refresh loops.

Manual refresh writes its returned collection into the same market-data cache and explicitly asks the shared synchronization layer to propagate the result once. Unlike automatic polling, an explicit manual refresh propagates even when the returned revision is unchanged; this preserves the existing behavior that clears a rebalance preview after the user requests fresh data. The synchronization layer records the applied revision so the cache observer does not repeat the same invalidations.

The first successful market-data load establishes the baseline signature and does not invalidate downstream queries. This avoids redundant requests during initial application startup.

## User Experience and Failure Handling

Automatic synchronization is intentionally quiet:

- Background fetches do not show a page loading state or block controls.
- Cached values remain visible while a request is in progress or after an automatic request fails.
- An automatic failure does not display the manual-refresh failure alert.
- The next interval, window-focus event, or reconnect event retries naturally.
- The refresh button's pending label and failure alert continue to describe only an explicit manual refresh.

When fresh data is detected, mounted screens rerender from updated queries without a full browser reload. A rebalance result based on the previous market-data revision is cleared so the user cannot unknowingly continue with an outdated calculation.

## Components and Boundaries

- `useMarketData` owns the query timing policy: 30-second interval, focus refetch, and reconnect refetch.
- A small market-data synchronization helper/hook owns revision calculation, first-load baselining, and downstream cache invalidation.
- `useRefreshMarketData` remains responsible for the POST request, placing the returned collection in the market-data cache, and requesting one forced propagation through the shared synchronization path.
- Global React Query defaults remain unchanged so unrelated application queries do not begin polling or refetching on focus.

The synchronization helper depends only on a `MarketDataCollection` and React Query's `QueryClient`, making its change-detection behavior independently testable.

## Testing

Automated tests must prove:

- The market-data query polls every 30 seconds and opts into focus and reconnect refetching.
- Interval polling is not configured to continue in a hidden/background tab.
- The initial response establishes a baseline without invalidating downstream queries.
- An identical response does not invalidate downstream queries or advance the refresh version.
- A changed response advances the refresh version and invalidates holdings and snapshots.
- A complete changed response invalidates portfolio analytics.
- An incomplete changed response does not invalidate portfolio analytics.
- Manual refresh produces one dependent synchronization even when the returned revision is unchanged, without duplicate invalidations.
- Background failure retains cached data and does not activate the manual-refresh alert.
- A market-data revision change clears an existing rebalance preview through the current refresh-version contract.

Frontend tests use fake timers and mocked API responses only. They must not access Docker, external market-data providers, or the production database.

## Acceptance Criteria

- With the application left open, backend-refreshed market data appears within 30 seconds while the tab is visible.
- Returning to the application after it was in the background checks for new data immediately.
- Unchanged polling responses do not cause dependent screens to refetch.
- Automatic failures leave the last usable data on screen and recover on a later attempt.
- Manual refresh behavior and incomplete-data protections remain intact.
- No test reads from or writes to the production environment.
