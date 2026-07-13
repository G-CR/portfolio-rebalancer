from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from app.providers.base import (
    MarketQuote,
    ProviderCredentialReader,
    ProviderNotConfigured,
    ProviderPayloadError,
    ProviderRequestError,
    decimal_from_value,
)


class AlphaVantageProvider:
    source = "alpha_vantage"

    def __init__(self, credentials: ProviderCredentialReader) -> None:
        self._credentials = credentials

    async def fetch_price(self, symbol: str) -> MarketQuote:
        api_key = self._api_key()
        fetched_at = datetime.now(UTC)
        query = urlencode(
            {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": api_key,
            }
        )
        payload = await asyncio.to_thread(self._blocking_get_json, query)
        return self.normalize_price(symbol, payload, fetched_at=fetched_at)

    async def fetch_fx(self, base: str, quote: str) -> MarketQuote:
        api_key = self._api_key()
        fetched_at = datetime.now(UTC)
        query = urlencode(
            {
                "function": "FX_DAILY",
                "from_symbol": base,
                "to_symbol": quote,
                "apikey": api_key,
            }
        )
        payload = await asyncio.to_thread(self._blocking_get_json, query)
        return self.normalize_fx(base, quote, payload, fetched_at=fetched_at)

    def normalize_price(
        self,
        symbol: str,
        payload: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        quote = payload.get("Global Quote") or {}
        timestamp = str(quote.get("07. latest trading day") or "")
        if not timestamp:
            raise ProviderPayloadError("Alpha Vantage payload did not include a trading day.")
        return MarketQuote(
            key=f"price:{symbol}",
            symbol=symbol,
            value=decimal_from_value(quote.get("05. price")),
            currency=str(quote.get("08. currency") or "USD"),
            source=self.source,
            as_of=datetime.fromisoformat(timestamp).replace(tzinfo=UTC),
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def normalize_fx(
        self,
        base: str,
        quote: str,
        payload: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        time_series = payload.get("Time Series FX (Daily)") or {}
        if not time_series:
            raise ProviderPayloadError("Alpha Vantage FX payload did not include time series data.")
        latest_date = sorted(time_series.keys())[-1]
        row = time_series[latest_date]
        return MarketQuote(
            key=f"fx:{base}/{quote}",
            symbol=f"{base}/{quote}",
            value=decimal_from_value(row.get("4. close")),
            currency=quote,
            source=self.source,
            as_of=datetime.fromisoformat(latest_date).replace(tzinfo=UTC),
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def _api_key(self) -> str:
        api_key = self._credentials.get_api_key(self.source)
        if api_key is None:
            raise ProviderNotConfigured("Provider alpha_vantage is not configured.")
        return api_key

    def _blocking_get_json(self, query: str) -> dict[str, Any]:
        url = f"https://www.alphavantage.co/query?{query}"
        try:
            with urlopen(url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network behavior
            raise ProviderRequestError(f"Alpha Vantage request failed: {exc}") from exc
