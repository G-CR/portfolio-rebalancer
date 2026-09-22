# Domestic ETF Sina Fallback Design

## Problem

The deployed server can reach Sina quotes but its AKShare Eastmoney ETF snapshot requests consistently end with `RemoteDisconnected`. AKShare already retries each HTTP request three times. A failed shared snapshot leaves all required domestic ETF prices marked stale, so a manual digest shows the stale-data warning even when earlier prices exist.

## Decision

Keep AKShare first for domestic ETF prices. Add Sina after AKShare in the domestic provider order and before Tushare, so no credential is needed when Eastmoney is unavailable. The existing international price and FX orders stay as they are.

Sina receives the holding's exchange (`SH` or `SZ`) and six-digit symbol. Request its exchange-qualified quote. Accept only a matching quote identifier, a positive current price, and a parseable exchange-local market timestamp. Return a `MarketQuote` with the original symbol, `CNY`, `sina`, and an aware timestamp. Invalid or unavailable Sina responses remain ordinary provider failures and preserve the existing last-valid-value behavior.

## Boundaries and verification

Do not add an outer AKShare retry loop: the library already has bounded exponential retries, and nine live requests from the server failed. Extend `SinaProvider` with one domestic-price method, route domestic Sina attempts through it in `ProviderRegistry`, and add focused unit tests for parsing, rejection, and the fallback path. Verify the live server refresh returns valid quotes for its three active domestic ETF holdings, while database and credentials remain untouched during deployment.
