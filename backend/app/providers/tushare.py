from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import Any
from urllib.request import Request, urlopen

from app.providers.base import (
    MarketQuote,
    ProviderCredentialReader,
    ProviderNotConfigured,
    ProviderPayloadError,
    ProviderRequestError,
    decimal_from_value,
)


class TushareProvider:
    source = "tushare"

    def __init__(self, credentials: ProviderCredentialReader) -> None:
        self._credentials = credentials

    async def fetch_price(self, symbol: str) -> MarketQuote:
        token = self._token()
        fetched_at = datetime.now(UTC)
        payload = await asyncio.to_thread(self._blocking_fetch_price, symbol, token)
        return self.normalize_price(symbol, payload, fetched_at=fetched_at)

    async def fetch_fx(self, base: str, quote: str) -> MarketQuote:
        token = self._token()
        fetched_at = datetime.now(UTC)
        payload = await asyncio.to_thread(self._blocking_fetch_fx, base, quote, token)
        return self.normalize_fx(base, quote, payload, fetched_at=fetched_at)

    def normalize_price(
        self,
        symbol: str,
        payload: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        row = self._first_row(payload)
        trade_date = str(row.get("trade_date") or "")
        if len(trade_date) != 8:
            raise ProviderPayloadError("Tushare payload included an invalid trade date.")
        as_of = datetime.strptime(trade_date, "%Y%m%d").replace(tzinfo=UTC)
        return MarketQuote(
            key=f"price:{symbol}",
            symbol=symbol,
            value=decimal_from_value(row.get("close")),
            currency=str(row.get("currency") or "CNY"),
            source=self.source,
            as_of=as_of,
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
        row = self._first_row(payload)
        trade_date = str(row.get("trade_date") or "")
        if len(trade_date) != 8:
            raise ProviderPayloadError("Tushare payload included an invalid trade date.")
        as_of = datetime.strptime(trade_date, "%Y%m%d").replace(tzinfo=UTC)
        return MarketQuote(
            key=f"fx:{base}/{quote}",
            symbol=f"{base}/{quote}",
            value=decimal_from_value(row.get("close")),
            currency=quote,
            source=self.source,
            as_of=as_of,
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def _token(self) -> str:
        token = self._credentials.get_api_key(self.source)
        if token is None:
            raise ProviderNotConfigured("Provider tushare is not configured.")
        return token

    def _first_row(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("data", {}).get("items") or []
        fields = payload.get("data", {}).get("fields") or []
        if not rows or not fields:
            raise ProviderPayloadError("Tushare payload did not include result rows.")
        return dict(zip(fields, rows[0], strict=False))

    def _blocking_fetch_price(self, symbol: str, token: str) -> dict[str, Any]:
        return self._post_json(
            {
                "api_name": "fund_daily",
                "token": token,
                "params": {"ts_code": symbol},
                "fields": "ts_code,trade_date,close",
            }
        )

    def _blocking_fetch_fx(self, base: str, quote: str, token: str) -> dict[str, Any]:
        return self._post_json(
            {
                "api_name": "fx_daily",
                "token": token,
                "params": {"ts_code": f"{base}{quote}.FXCM"},
                "fields": "ts_code,trade_date,close",
            }
        )

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            "http://api.tushare.pro",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network behavior
            raise ProviderRequestError("Tushare request failed.") from exc
