from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.providers import alpha_vantage as alpha_vantage_module
from app.providers import sina as sina_module
from app.providers import yahoo as yahoo_module
from app.providers.akshare import AkshareProvider
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.base import (
    MarketQuote,
    NullCredentialReader,
    ProviderNotConfigured,
    ProviderPayloadError,
    ProviderRequestError,
)
from app.providers.sina import SinaProvider
from app.providers.tushare import TushareProvider
from app.providers.yahoo import YahooProvider
from app.services.market_data import (
    ProviderRegistry,
    ProviderSelectionError,
    _provider_order_for_fx,
    _provider_order_for_price,
    _safe_failure_summary,
)


class _NoCredentialReader:
    def get_api_key(self, provider: str) -> str | None:
        return None


class _FailedPriceProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def fetch_price(self, symbol: str):
        raise self.error


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


def test_yahoo_rounds_binary_float_noise_to_storage_scale() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1784035800],
                    "indicators": {"quote": [{"close": [751.8300170898438]}]},
                }
            ]
        }
    }

    quote = YahooProvider().normalize_price("SPY", payload)

    assert quote.value == Decimal("751.830017089844")


def test_yahoo_sends_headers_accepted_by_chart_api(monkeypatch) -> None:
    captured_request = None

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return b'{"chart":{"result":[]}}'

    def fake_urlopen(request, *, timeout):
        nonlocal captured_request
        captured_request = request
        assert timeout == 15
        return _Response()

    monkeypatch.setattr(yahoo_module, "urlopen", fake_urlopen)

    YahooProvider()._blocking_get_json("https://query1.finance.yahoo.com/chart/SPY")

    assert captured_request.get_header("User-agent")
    assert captured_request.get_header("Accept") == "application/json"


def test_sina_normalizes_us_etf_quote() -> None:
    payload = (
        'var hq_str_gb_spy="SPDR标普500 ETF,751.8300,0.36,'
        '2026-07-15 09:48:43,2.6600,750.9100";'
    )

    quote = SinaProvider().normalize_price("SPY", payload)

    assert quote.symbol == "SPY"
    assert quote.value == Decimal("751.8300")
    assert quote.currency == "USD"
    assert quote.source == "sina"
    assert quote.as_of == datetime(
        2026, 7, 15, 9, 48, 43, tzinfo=ZoneInfo("Asia/Shanghai")
    )


def test_sina_normalizes_usd_cny_quote() -> None:
    payload = (
        'var hq_str_fx_susdcny="11:13:41,6.7683000000,6.7693000000,'
        '6.7766000000,202.0000000000,6.7731000000,6.7731000000,'
        '6.7529000000,6.7688000000,在岸人民币,-0.1151,-0.0078,'
        '0.0202,此行情由新浪财经计算得出,0.0000,0.0000,,2026-07-15";'
    )

    quote = SinaProvider().normalize_fx("USD", "CNY", payload)

    assert quote.symbol == "USD/CNY"
    assert quote.value == Decimal("6.7683000000")
    assert quote.currency == "CNY"
    assert quote.source == "sina"
    assert quote.as_of == datetime(
        2026, 7, 15, 11, 13, 41, tzinfo=ZoneInfo("Asia/Shanghai")
    )


def test_sina_sends_required_headers(monkeypatch) -> None:
    captured_request = None

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return b'var hq_str_gb_spy="SPY,1.0,0,2026-07-15 09:00:00";'

    def fake_urlopen(request, *, timeout):
        nonlocal captured_request
        captured_request = request
        assert timeout == 15
        return _Response()

    monkeypatch.setattr(sina_module, "urlopen", fake_urlopen)

    SinaProvider()._blocking_get_text("https://hq.sinajs.cn/list=gb_spy")

    assert captured_request.get_header("User-agent")
    assert captured_request.get_header("Referer") == "https://finance.sina.com.cn/"


@pytest.mark.asyncio
async def test_sina_rejects_unsupported_fx_pair() -> None:
    with pytest.raises(ProviderNotConfigured, match="USD/CNY"):
        await SinaProvider().fetch_fx("EUR", "CNY")


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


def test_akshare_normalizes_current_etf_spot_timestamp_fields() -> None:
    payload = [
        {
            "代码": "563020",
            "最新价": 1.136,
            "数据日期": "2026-07-15 00:00:00",
            "更新时间": "2026-07-15 10:21:26+08:00",
        }
    ]

    quote = AkshareProvider().normalize_price("563020", payload)

    assert quote.value == Decimal("1.136")
    assert quote.as_of == datetime.fromisoformat("2026-07-15 10:21:26+08:00")


def test_akshare_runtime_dependency_is_installed() -> None:
    import akshare

    assert callable(akshare.fund_etf_spot_em)


@pytest.mark.asyncio
async def test_provider_selection_keeps_primary_failure_when_backup_is_unconfigured() -> None:
    registry = ProviderRegistry()
    registry._providers["akshare"] = _FailedPriceProvider(
        ProviderRequestError("request contains https://secret.invalid")
    )
    registry._providers["tushare"] = _FailedPriceProvider(
        ProviderNotConfigured("token SECRET is missing")
    )

    with pytest.raises(ProviderSelectionError) as exc_info:
        await registry.fetch_price("563020", market="SH")

    assert exc_info.value.provider_name == "akshare"
    assert [
        (item.provider_name, item.failure_category)
        for item in exc_info.value.attempts
    ] == [
        ("akshare", "provider_request_failed"),
        ("tushare", "provider_not_configured"),
    ]
    summary = _safe_failure_summary(exc_info.value)
    assert summary == (
        "akshare: provider_request_failed; tushare: provider_not_configured"
    )
    assert "secret.invalid" not in summary
    assert "SECRET" not in summary


def test_international_default_order_uses_sina_before_alpha_vantage() -> None:
    assert _provider_order_for_price(
        market="US",
        preferred_source=None,
        provider_priority=[],
    ) == ["yahoo", "sina", "alpha_vantage"]
    assert _provider_order_for_fx(
        preferred_source=None,
        provider_priority=[],
    ) == ["yahoo", "sina", "alpha_vantage"]


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


def test_market_quote_rejects_value_outside_numeric_storage_bounds() -> None:
    with pytest.raises(ProviderPayloadError, match=r"NUMERIC\(28,12\)"):
        MarketQuote(
            key="price:SPY",
            symbol="SPY",
            value=Decimal("10000000000000000"),
            currency="USD",
            source="yahoo",
            as_of=datetime(2026, 7, 13, 10, 40, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 13, 10, 41, tzinfo=UTC),
        )


def test_task_9_credential_reader_stays_unconfigured_until_task_15() -> None:
    reader = NullCredentialReader()

    assert reader.get_api_key("tushare") is None
    assert reader.get_api_key("alpha_vantage") is None


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


@pytest.mark.asyncio
async def test_alpha_vantage_request_error_does_not_expose_key_or_url(monkeypatch) -> None:
    class _CredentialReader:
        def get_api_key(self, provider: str) -> str | None:
            return "TOP-SECRET-TOKEN"

    def fail_request(*args, **kwargs):
        raise RuntimeError(
            "GET https://example.invalid/query?apikey=TOP-SECRET-TOKEN failed"
        )

    monkeypatch.setattr(alpha_vantage_module, "urlopen", fail_request)

    with pytest.raises(ProviderRequestError) as exc_info:
        await AlphaVantageProvider(_CredentialReader()).fetch_price("SPY")

    assert str(exc_info.value) == "Alpha Vantage request failed."
    assert "TOP-SECRET-TOKEN" not in str(exc_info.value)
    assert "example.invalid" not in str(exc_info.value)
