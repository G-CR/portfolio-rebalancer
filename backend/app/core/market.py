from __future__ import annotations

import re

SUPPORTED_MARKETS = ("US", "SH", "SZ")
_MARKET_ALIASES = {
    "US": "US",
    "SH": "SH",
    "SSE": "SH",
    "SZ": "SZ",
    "SZSE": "SZ",
}
_CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")


def normalize_market_code(value: str) -> str:
    normalized = value.strip().upper()
    try:
        return _MARKET_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError("Unsupported market code.") from exc


def normalize_currency_code(value: str) -> str:
    normalized = value.strip()
    if _CURRENCY_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Currency code must be exactly three ASCII letters.")
    return normalized.upper()
