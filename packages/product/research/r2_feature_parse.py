"""R2 structured JSONL/NDJSON parse authority.

Public import remains ``research.r2_feature_context``. Envelope dicts only;
normalization lives in r2_feature_normalize; available_at policy stays in
r2_feature_context.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def _decode_json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value
    return value


def parse_r2_structured_line(line: str | bytes | Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse one R2 JSONL / archive NDJSON line into an envelope dict."""
    if isinstance(line, Mapping):
        obj = dict(line)
    else:
        text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
        text = text.strip()
        if not text:
            return None
        try:
            loaded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(loaded, dict):
            return None
        obj = loaded

    dataset = obj.get("dataset")
    if dataset is None or str(dataset).strip() == "":
        return None

    payload = _maybe_json(obj.get("payload"))
    raw_payload = _maybe_json(obj.get("raw_payload"))
    if raw_payload is None:
        raw_payload = payload
    natural_key = obj.get("natural_key")
    if isinstance(natural_key, dict):
        natural_key_out: Any = json.dumps(natural_key, ensure_ascii=True, sort_keys=True)
        natural_key_obj = natural_key
    else:
        natural_key_out = natural_key
        natural_key_obj = _decode_json_obj(natural_key)

    return {
        "source": str(obj.get("source") or "jquants"),
        "dataset": str(dataset).strip(),
        "natural_key": natural_key_out,
        "natural_key_obj": natural_key_obj,
        "event_time": obj.get("event_time"),
        "available_at": obj.get("available_at"),
        "ingested_at": obj.get("ingested_at"),
        "payload": payload if isinstance(payload, dict) else _decode_json_obj(payload),
        "raw_payload": (
            raw_payload if isinstance(raw_payload, dict) else _decode_json_obj(raw_payload)
        ),
        "rid": obj.get("rid"),
    }


def parse_r2_structured_bytes(body: bytes | str) -> list[dict[str, Any]]:
    """Parse a full JSONL/NDJSON object body into envelope dicts."""
    text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        row = parse_r2_structured_line(line)
        if row is not None:
            out.append(row)
    return out


__all__ = [
    "parse_r2_structured_bytes",
    "parse_r2_structured_line",
]
