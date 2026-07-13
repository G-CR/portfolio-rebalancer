from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from app.providers.base import MarketQuote, ProviderPayloadError, ProviderRequestError, decimal_from_value


class AkshareProvider:
    source = "akshare"

    async def fetch_price(self, symbol: str) -> MarketQuote:
        fetched_at = datetime.now(UTC)
        payload = await asyncio.to_thread(self._blocking_fetch_price_rows, symbol)
        return self.normalize_price(symbol, payload, fetched_at=fetched_at)

    async def fetch_fx(self, base: str, quote: str) -> MarketQuote:
        raise ProviderRequestError("AKShare FX refresh is not configured for this service.")

    def normalize_price(
        self,
        symbol: str,
        payload: Iterable[Mapping[str, Any]],
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        row = next((item for item in payload if str(item.get("代码") or item.get("symbol")) == symbol), None)
        if row is None:
            raise ProviderPayloadError("AKShare payload did not include the requested symbol.")

        timestamp_text = (
            row.get("时间")
            or row.get("最新交易日")
            or row.get("日期")
            or row.get("date")
        )
        if not timestamp_text:
            raise ProviderPayloadError("AKShare payload did not include a market timestamp.")

        try:
            as_of = datetime.fromisoformat(str(timestamp_text).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProviderPayloadError("AKShare payload included an invalid market timestamp.") from exc
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)

        currency = str(row.get("币种") or row.get("currency") or "CNY")
        return MarketQuote(
            key=f"price:{symbol}",
            symbol=symbol,
            value=decimal_from_value(row.get("最新价") or row.get("price")),
            currency=currency,
            source=self.source,
            as_of=as_of,
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def _blocking_fetch_price_rows(self, symbol: str) -> list[dict[str, Any]]:
        try:
            import akshare as ak  # pragma: no cover - import exercised only in real refreshes
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderRequestError("AKShare is not installed.") from exc

        try:  # pragma: no cover - network behavior
            frame = ak.fund_etf_spot_em()
            return frame.to_dict("records")
        except Exception as exc:  # pragma: no cover - network behavior
            raise ProviderRequestError("AKShare request failed.") from exc
