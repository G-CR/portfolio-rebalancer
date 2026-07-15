# Manual Rebalance Preview Design

## Goal

Let the user configure every rebalance input before the application refreshes market data or calculates a preview.

## Initial State

Opening the rebalance page must not call `POST /api/rebalance/preview`. The input panel remains fully interactive and uses the existing default values. The result area shows a neutral prompt telling the user to configure the available funds and constraints before starting a calculation.

The primary calculation button reads `开始测算` while no preview has been produced.

## Manual Calculation

Changing available CNY, available USD, tolerance, minimum trade amount, allow-sell, allow-FX, or valuation basis only updates local form state. In particular, switching between actual and FX-neutral valuation must not trigger a preview request.

Clicking `开始测算` submits the current form values. Market-data refresh remains part of the existing backend preview flow, so automatic quote retrieval begins only after this explicit action.

## Existing Preview

After a successful preview, the calculation button reads `重新测算`. Changing any input keeps the existing preview visible, marks it as outdated through the existing dirty-state notice, and disables plan lifecycle actions until the user recalculates.

Changing valuation basis follows the same dirty-state behavior as every other input. It no longer receives a special automatic-submit path.

## Error Handling

Preview loading, stale-data acknowledgement, API errors, save, start, cancel, and complete behavior remain unchanged once the user explicitly starts a calculation.

## Verification

- A component test verifies that opening the page does not request a preview and shows `开始测算`.
- A component test verifies that changing valuation basis before the first calculation does not request a preview.
- Existing preview, dirty-state, lifecycle, accessibility, build, and Playwright tests continue to pass after being updated to start the first calculation explicitly.
