# Rebalance Defaults Persistence Design

## Goal

Persist the last applied rebalance funds and constraints in the database so the same values are restored after navigation, browser refresh, browser restart, or access from another device using the same deployment.

## Storage Model

Extend the singleton `settings` row with three fields:

- `rebalance_available_cny`, default `0`
- `rebalance_available_usd`, default `0`
- `rebalance_valuation_basis`, default `actual`

The remaining defaults reuse the existing settings fields: `default_tolerance`, `minimum_trade_amount_cny`, `allow_sell`, and `allow_fx`. This keeps analytics, the data-source settings page, and rebalance defaults consistent.

Stale-data acknowledgement is never persisted.

## API

Add `GET /api/settings/rebalance-defaults` and `PUT /api/settings/rebalance-defaults`.

The response and update payload contain:

- `available_cny`
- `available_usd`
- `valuation_basis`
- `tolerance`
- `minimum_trade_cny`
- `allow_sell`
- `allow_fx`
- `updated_at` in responses only

Decimal values remain serialized as strings. The API validates nonnegative funds and minimum trade amount, and validates tolerance as a ratio between zero and one.

## Page Loading

The rebalance page loads database defaults before presenting the working form. Tolerance is converted from the stored ratio to the percentage value used by the input. Loading and failure states must not trigger a preview.

If defaults cannot be loaded, the page falls back to current built-in defaults and shows a non-blocking warning. The user can still configure and calculate.

## Save And Calculate Flow

Clicking `开始测算` or `重新测算` sends the current form to the defaults endpoint and uses the same values for the preview request. Saving occurs before preview calculation, but a defaults-save failure does not block calculation.

If preview succeeds while defaults saving fails, the result remains usable and the page displays `测算成功，但默认配置保存失败。` A later calculation retries persistence.

Changing fields without calculating does not write to the database. The stored defaults represent the last configuration used for a calculation, not partially edited input.

## Existing Settings Page

The current general-settings endpoint and data-source settings form remain compatible. Changes to tolerance, minimum trade amount, allow-sell, or allow-FX there become the defaults loaded by the rebalance page. The new funds and valuation-basis values do not need additional controls on the data-source page.

## Verification

- Migration tests cover upgrade, defaults, and downgrade behavior.
- Settings API tests cover read, update, validation, and preservation through the existing general-settings endpoint.
- Frontend tests cover loading defaults without calculating, saving on explicit calculation, and continuing calculation after a defaults-save failure.
- Full backend, frontend, build, and Playwright suites pass before deployment.
