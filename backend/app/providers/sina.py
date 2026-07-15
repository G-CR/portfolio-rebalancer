from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.providers.base import (
    MarketQuote,
    ProviderNotConfigured,
    ProviderPayloadError,
    ProviderRequestError,
    decimal_from_value,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PAYLOAD_PATTERN = re.compile(r'^var hq_str_[^=]+="(.*)";\s*$', re.DOTALL)
_REQUEST_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
}


class SinaProvider:
    source = "sina"

    async def fetch_price(self, symbol: str) -> MarketQuote:
        fetched_at = datetime.now(UTC)
        query = urlencode({"list": f"gb_{symbol.lower()}"})
        payload = await asyncio.to_thread(
            self._blocking_get_text,
            f"https://hq.sinajs.cn/?{query}",
        )
        return self.normalize_price(symbol, payload, fetched_at=fetched_at)

    async def fetch_fx(self, base: str, quote: str) -> MarketQuote:
        if (base.upper(), quote.upper()) != ("USD", "CNY"):
            raise ProviderNotConfigured("Sina currently supports only USD/CNY FX.")

        fetched_at = datetime.now(UTC)
        query = urlencode({"list": "fx_susdcny"})
        payload = await asyncio.to_thread(
            self._blocking_get_text,
            f"https://hq.sinajs.cn/?{query}",
        )
        return self.normalize_fx(base, quote, payload, fetched_at=fetched_at)

    def normalize_price(
        self,
        symbol: str,
        payload: str,
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        fields = _payload_fields(payload)
        if len(fields) < 4:
            raise ProviderPayloadError("Sina payload did not include a US quote.")

        return MarketQuote(
            key=f"price:{symbol}",
            symbol=symbol,
            value=decimal_from_value(fields[1]),
            currency="USD",
            source=self.source,
            as_of=_parse_shanghai_timestamp(fields[3]),
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def normalize_fx(
        self,
        base: str,
        quote: str,
        payload: str,
        *,
        fetched_at: datetime | None = None,
    ) -> MarketQuote:
        fields = _payload_fields(payload)
        if len(fields) < 18:
            raise ProviderPayloadError("Sina payload did not include a USD/CNY quote.")

        return MarketQuote(
            key=f"fx:{base}/{quote}",
            symbol=f"{base}/{quote}",
            value=decimal_from_value(fields[1]),
            currency=quote,
            source=self.source,
            as_of=_parse_shanghai_timestamp(f"{fields[-1]} {fields[0]}"),
            fetched_at=fetched_at or datetime.now(UTC),
        )

    def _blocking_get_text(self, url: str) -> str:
        request = Request(url, headers=_REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=15) as response:
                return response.read().decode("gb18030")
        except Exception as exc:  # pragma: no cover - network behavior
            raise ProviderRequestError("Sina request failed.") from exc


def _payload_fields(payload: str) -> list[str]:
    match = _PAYLOAD_PATTERN.fullmatch(payload.strip())
    if match is None or not match.group(1):
        raise ProviderPayloadError("Sina payload did not include quote data.")
    return match.group(1).split(",")


def _parse_shanghai_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_SHANGHAI
        )
    except ValueError as exc:
        raise ProviderPayloadError("Sina payload included an invalid timestamp.") from exc
