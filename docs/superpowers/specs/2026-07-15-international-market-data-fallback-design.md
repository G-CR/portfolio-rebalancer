# International Market Data Fallback Design

## Goal

Restore automatic SPY, QQQ, and USD/CNY market data when Yahoo Finance rejects requests or returns noisy floating-point values, without requiring an API key.

## Provider Strategy

- Keep Yahoo Finance as the first provider for US prices and FX.
- Add Sina Finance as the second provider for US prices and USD/CNY.
- Keep Alpha Vantage as the final configurable provider.
- Persist and display the provider that actually returned the quote. A Sina quote uses source `sina`; it is never labeled as Yahoo.
- Preserve ordered safe failure diagnostics for every attempted provider.

## Yahoo Normalization

Yahoo requests use an explicit browser-compatible User-Agent and `Accept: application/json` to avoid the 429 response caused by Python's default User-Agent. Yahoo price and FX values are rounded to 12 decimal places before `MarketQuote` storage validation so binary floating-point noise fits PostgreSQL `NUMERIC(28,12)`.

## Sina Provider

Create a focused `SinaProvider` that requests `hq.sinajs.cn` with the required Referer and User-Agent headers. US symbols map to lowercase `gb_<symbol>` keys. USD/CNY maps to `fx_susdcny`. The provider parses only the documented fields needed by the application: current value and timestamp. Unsupported FX pairs raise `ProviderNotConfigured` so another provider can be tried.

## Settings And UI

Add `sina` to supported provider names, default priority, holding source choices, settings labels, and frontend types. Sina needs no credential and cannot expose secrets. Existing settings rows that predate Sina remain valid: normalization inserts Sina after Yahoo and before Alpha Vantage.

## Error Handling

Network and decoding failures become `ProviderRequestError`; missing or malformed values become `ProviderPayloadError`. Stored summaries continue to contain provider names and safe categories only.

## Verification

- Unit tests cover Yahoo headers and rounding, Sina price/FX parsing, unsupported FX, and fallback selection.
- Integration tests cover settings normalization and safe market-data persistence.
- Full backend and frontend suites pass.
- Production containers are rebuilt with the existing `portfolio-v1` volumes.
- A live refresh returns positive SPY, QQQ, and USD/CNY values, using Yahoo when available or Sina when Yahoo is rate-limited.
