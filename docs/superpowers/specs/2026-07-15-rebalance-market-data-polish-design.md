# Rebalance And Market Data Polish Design

## Goal

Improve scanability in the rebalance trade list and correct alignment defects on the market-data page.

## Rebalance Trade Names

The rebalance page already loads active holdings through the existing holdings API. It builds a symbol-to-name lookup and passes it to the trade list. Each trade row shows the symbol as the primary data label and the user-entered holding name below it. If no matching holding is available, the row remains symbol-only.

## FX Comparison Formatting

`max_drift_after` is a ratio, not display-ready text. Render it with the existing percentage formatter at two decimal places. The underlying API precision remains unchanged.

## Provider Settings Alignment

Keep the five-column provider grid: identity, priority, credential/source type, status, and actions. Give credential/source and status cells the same label slot and control height as `FormField`, and reserve the same top label space above actions. This aligns public and keyed providers without changing their behavior.

## Effective Values Row Rules

Table cells remain native table cells. Multi-line symbol and status content moves into inner grid wrappers. Borders stay on `th` and `td`, so every cell contributes to one shared row boundary and horizontal rules remain level.

## Verification

- Component tests cover trade names and percentage formatting.
- Market-data tests cover all provider rows and status content wrappers.
- Production build and Playwright pass.
- Desktop screenshots verify provider columns and level table rules.
