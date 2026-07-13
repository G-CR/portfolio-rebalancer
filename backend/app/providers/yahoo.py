from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from app.providers.base import MarketQuote, ProviderPayloadError, ProviderRequestError, decimal_from_value


class YahooProvider:
    source = "yahoo"

    async def fetch_price(self, symbol: str) -> MarketQuote:
        fetched_at = datetime.now(UTC)
        query = urlencode({"interval": "1d", "range": "5d"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
        payload = await asyncio.to_thread(self._blocking_get_json, url)
        return self.normalize_price(symbol, payload, fetched_at=fetched_at)

    async def fetch_fx(self, base: str, quote: str) -> MarketQuote:
        fetched_at = datetime.now(UTC)
        pair_symbol = f"{base}{quote}=X"
        query = urlencode({"interval": "1d", "range": "5d"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair_symbol}?{query}"
        payload = await asyncio.to_thread(self._blocking_get_json, url)
        return self.normalize_fx(base, quote, payload, fetched_at=fetched_at)

    def normalize_price(
        self,
        symbol: str,
        payload: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        result = self._chart_result(payload)
        currency = str(result.get("meta", {}).get("currency") or "")
        timestamp = self._last_timestamp(result)
        close_value = self._last_close(result)
        return MarketQuote(
            key=f"price:{symbol}",
            symbol=symbol,
            value=decimal_from_value(close_value),
            currency=currency,
            source=self.source,
            as_of=datetime.fromtimestamp(timestamp, tz=UTC),
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
        result = self._chart_result(payload)
        timestamp = self._last_timestamp(result)
        close_value = self._last_close(result)
        return MarketQuote(
            key=f"fx:{base}/{quote}",
            symbol=f"{base}/{quote}",
            value=decimal_from_value(close_value),
            currency=quote,
            source=self.source,
            as_of=datetime.fromtimestamp(timestamp, tz=UTC),
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def _chart_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        results = payload.get("chart", {}).get("result")
        if not results:
            raise ProviderPayloadError("Yahoo payload did not include chart results.")
        return results[0]

    def _last_timestamp(self, result: dict[str, Any]) -> int:
        timestamps = result.get("timestamp") or []
        if not timestamps:
            raise ProviderPayloadError("Yahoo payload did not include timestamps.")
        return int(timestamps[-1])

    def _last_close(self, result: dict[str, Any]) -> object:
        quote_sets = result.get("indicators", {}).get("quote") or []
        closes = quote_sets[0].get("close") if quote_sets else None
        if not closes:
            raise ProviderPayloadError("Yahoo payload did not include close prices.")
        close_value = closes[-1]
        if close_value is None:
            raise ProviderPayloadError("Yahoo payload did not include a closing value.")
        return close_value

    def _blocking_get_json(self, url: str) -> dict[str, Any]:
        try:
            with urlopen(url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network behavior
            raise ProviderRequestError(f"Yahoo request failed: {exc}") from exc
