from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TypeAlias
from uuid import UUID

JsonScalar: TypeAlias = None | bool | int | float | Decimal | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def encode_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON floats must be finite")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimals must be finite")
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetimes must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: encode_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_json_value(item) for item in value]
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    encoded = encode_json_value(value)
    return json.dumps(
        encoded,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_parsed_json_bytes(value: object) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON floats must be finite")
        value = Decimal(str(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("JSON decimals must be finite")
        return format(value, "f").encode("ascii")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonical_parsed_json_bytes(item) for item in value) + b"]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        members = (
            canonical_parsed_json_bytes(key) + b":" + canonical_parsed_json_bytes(value[key])
            for key in sorted(value)
        )
        return b"{" + b",".join(members) + b"}"
    raise TypeError(f"unsupported parsed JSON value type: {type(value).__name__}")


def _canonical_document(document: dict[str, object]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for member, raw_rows in document.items():
        if member == "manifest.json":
            continue
        encoded_rows = encode_json_value(raw_rows)
        if isinstance(encoded_rows, list) and all(isinstance(row, dict) for row in encoded_rows):
            encoded_rows = sorted(encoded_rows, key=lambda row: str(row.get("id", "")))
        result[member] = encoded_rows
    return result


def logical_checksum(document: dict[str, object]) -> str:
    return hashlib.sha256(canonical_parsed_json_bytes(_canonical_document(document))).hexdigest()
