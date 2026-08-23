"""R2 structured history row normalization authority.

Public import remains ``research.r2_feature_context``. Envelope → tip-compatible
row shapes only; parse stays in r2_feature_parse; available_at policy lives in
r2_available_at.
"""

from __future__ import annotations

from typing import Any, Mapping

from research.r2_feature_parse import _decode_json_obj


def _pick_num(payload: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        if name not in payload or payload[name] is None or payload[name] == "":
            continue
        try:
            return float(payload[name])
        except (TypeError, ValueError):
            continue
    return None


def _pick_str(payload: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        v = payload.get(name)
        if v is None or v == "":
            continue
        return str(v)
    return None


def _normalize_tip_bar_row(
    *,
    payload: Mapping[str, Any],
    event_time: Any,
    available_at: Any,
    natural_key: Any,
) -> dict[str, Any] | None:
    """Map a bar payload to curated equity-bar fields (no ingestion import)."""
    code = _pick_str(payload, "Code", "code")
    date = _pick_str(payload, "Date", "date")
    if date is None and event_time is not None:
        date = str(event_time)[:10]
    if code is None and natural_key is not None:
        nk = _decode_json_obj(natural_key)
        code = _pick_str(nk, "Code", "code")
        if date is None:
            date = _pick_str(nk, "Date", "date")
    if not code or not date:
        return None
    return {
        "source": "jquants",
        "code": str(code),
        "date": str(date)[:10],
        "event_time": event_time,
        "available_at": available_at,
        "volume": _pick_num(payload, "Volume", "Vo", "AdjVo", "AVo"),
        "close": _pick_num(payload, "Close", "C", "AdjC", "AC"),
        "open": _pick_num(payload, "Open", "O", "AdjO", "AO"),
        "high": _pick_num(payload, "High", "H", "AdjH", "AH"),
        "low": _pick_num(payload, "Low", "L", "AdjL", "AL"),
        "payload": dict(payload),
        "raw_payload": dict(payload),
    }


def _normalize_tip_calendar_row(
    *,
    payload: Mapping[str, Any],
    event_time: Any,
    available_at: Any,
    natural_key: Any,
) -> dict[str, Any] | None:
    date = _pick_str(payload, "Date", "date")
    if date is None and event_time is not None:
        date = str(event_time)[:10]
    if date is None and natural_key is not None:
        nk = _decode_json_obj(natural_key)
        date = _pick_str(nk, "Date", "date")
    if not date:
        return None
    hol = _pick_str(payload, "HolidayDivision", "HolDiv", "holiday_division")
    return {
        "source": "jquants",
        "date": str(date)[:10],
        "event_time": event_time,
        "available_at": available_at,
        "holiday_division": hol,
        "payload": dict(payload),
        "raw_payload": dict(payload),
    }


def _normalize_tip_catalog_row(
    *,
    dataset: str,
    payload: Mapping[str, Any],
    event_time: Any,
    available_at: Any,
    natural_key: Any,
) -> dict[str, Any]:
    """Generic catalog row shape for get_jquants_records (topix etc.)."""
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": natural_key,
        "event_time": event_time,
        "available_at": available_at,
        "payload": dict(payload),
        "raw_payload": dict(payload),
        "date": _pick_str(payload, "Date", "date", "DiscDate", "PublishedDate")
        or (str(event_time)[:10] if event_time else None),
        "close": _pick_num(payload, "Close", "C", "AdjC", "AC"),
        "volume": _pick_num(payload, "Volume", "Vo", "AdjVo", "AVo"),
        "Code": _pick_str(payload, "Code", "code"),
        "Date": _pick_str(payload, "Date", "date", "DiscDate", "PublishedDate"),
        "S33": _pick_str(payload, "S33", "section"),
        "section": _pick_str(payload, "S33", "section"),
    }


def normalize_r2_history_row(
    envelope: Mapping[str, Any],
    *,
    dataset: str | None = None,
) -> dict[str, Any] | None:
    """Map one R2 envelope to FeatureContext tip-compatible row shape."""
    ds = str(dataset or envelope.get("dataset") or "").strip()
    if not ds:
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        payload = _decode_json_obj(payload)
    event_time = envelope.get("event_time")
    available_at = envelope.get("available_at")
    natural_key = envelope.get("natural_key")

    if ds == "equities_bars_daily":
        row = _normalize_tip_bar_row(
            payload=payload or {},
            event_time=event_time,
            available_at=available_at,
            natural_key=natural_key,
        )
    elif ds == "markets_calendar":
        row = _normalize_tip_calendar_row(
            payload=payload or {},
            event_time=event_time,
            available_at=available_at,
            natural_key=natural_key,
        )
        if row is not None and row.get("holiday_division") is None:
            hol = _pick_str(payload or {}, "HolDiv", "HolidayDivision", "holiday_division")
            if hol is not None:
                row["holiday_division"] = hol
    else:
        row = _normalize_tip_catalog_row(
            dataset=ds,
            payload=payload or {},
            event_time=event_time,
            available_at=available_at,
            natural_key=natural_key,
        )
    if row is None:
        return None
    if envelope.get("ingested_at") is not None:
        row["ingested_at"] = envelope.get("ingested_at")
    return row


__all__ = [
    "normalize_r2_history_row",
]
