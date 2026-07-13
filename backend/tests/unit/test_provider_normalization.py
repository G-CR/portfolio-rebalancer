from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.providers.akshare import AkshareProvider
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.base import ProviderNotConfigured, ProviderPayloadError
from app.providers.tushare import TushareProvider
from app.providers.yahoo import YahooProvider


class _NoCredentialReader:
    def get_api_key(self, provider: str) -> str | None:
        return None


def test_yahoo_normalizes_spy_close() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "usd"},
                    "timestamp": [1783939200],
                    "indicators": {"quote": [{"close": [651.28]}]},
                }
            ]
        }
    }

    quote = YahooProvider().normalize_price("SPY", payload)

    assert quote.symbol == "SPY"
    assert quote.value == Decimal("651.28")
    assert quote.currency == "USD"
    assert quote.source == "yahoo"
    assert quote.as_of == datetime(2026, 7, 13, 10, 40, tzinfo=UTC)


def test_akshare_normalizes_cn_etf_code() -> None:
    payload = [
        {
            "代码": "510880",
            "最新价": "3.025",
            "时间": "2026-07-13 15:00:00",
            "币种": "cny",
        }
    ]

    quote = AkshareProvider().normalize_price("510880", payload)

    assert quote.symbol == "510880"
    assert quote.value == Decimal("3.025")
    assert quote.currency == "CNY"
    assert quote.source == "akshare"


def test_invalid_provider_payload_is_rejected() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1783939200],
                    "indicators": {"quote": [{"close": [0]}]},
                }
            ]
        }
    }

    with pytest.raises(ProviderPayloadError, match="positive finite value"):
        YahooProvider().normalize_price("SPY", payload)


@pytest.mark.asyncio
async def test_tushare_requires_key_before_fetch() -> None:
    provider = TushareProvider(_NoCredentialReader())

    with pytest.raises(ProviderNotConfigured, match="tushare"):
        await provider.fetch_price("510300")


@pytest.mark.asyncio
async def test_alpha_vantage_requires_key_before_fetch() -> None:
    provider = AlphaVantageProvider(_NoCredentialReader())

    with pytest.raises(ProviderNotConfigured, match="alpha_vantage"):
        await provider.fetch_fx("USD", "CNY")
