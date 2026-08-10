"""Normalize J-Quants V2 payloads into PIT-annotated structured rows.

Every row gets ``source='jquants'`` and the four PIT columns. ``available_at``
defaults to the fetch time (``ingested_at``), which is always a safe,
non-look-ahead value; pass an explicit ``available_at`` when the true
publication time is known. Exact per-source publication timing is **仮**
pending confirmation — see ``docs/data_sources.md``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional

from ..common.timeutil import parse_dt, to_iso


def _num(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _s(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s or None


def _avail(available_at: Optional[str], ingested_at: str) -> str:
    return available_at or ingested_at


def normalize_daily_bars(
    rows: Iterable[dict], *, ingested_at: str, available_at: Optional[str] = None
) -> List[dict]:
    av = _avail(available_at, ingested_at)
    out: List[dict] = []
    for r in rows:
        d = _s(r.get("Date"))
        if not d:
            continue
        try:
            et = to_iso(parse_dt(f"{d[:10]}T15:00:00"))  # trade close, JST
        except ValueError:
            et = to_iso(parse_dt(d[:10]))
        out.append(
            {
                "source": "jquants",
                "code": _s(r.get("Code")),
                "date": d[:10],
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "open": _num(r.get("Open")),
                "high": _num(r.get("High")),
                "low": _num(r.get("Low")),
                "close": _num(r.get("Close")),
                "volume": _num(r.get("Volume")),
                "turnover_value": _num(r.get("TurnoverValue")),
                "adjustment_open": _num(r.get("AdjustmentOpen")),
                "adjustment_high": _num(r.get("AdjustmentHigh")),
                "adjustment_low": _num(r.get("AdjustmentLow")),
                "adjustment_close": _num(r.get("AdjustmentClose")),
                "adjustment_volume": _num(r.get("AdjustmentVolume")),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out


def normalize_listed_info(
    rows: Iterable[dict],
    *,
    ingested_at: str,
    snapshot_date: str,
    available_at: Optional[str] = None,
) -> List[dict]:
    av = _avail(available_at, ingested_at)
    sd = str(snapshot_date)[:10]
    et = to_iso(parse_dt(f"{sd}T09:00:00"))
    out: List[dict] = []
    for r in rows:
        out.append(
            {
                "source": "jquants",
                "code": _s(r.get("Code")),
                "snapshot_date": sd,
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "company_name": _s(r.get("CompanyName")),
                "company_name_en": _s(r.get("CompanyNameEnglish")),
                "sector_17_code": _s(r.get("Sector17Code")),
                "sector_17_name": _s(r.get("Sector17CodeName")),
                "sector_33_code": _s(r.get("Sector33Code")),
                "sector_33_name": _s(r.get("Sector33CodeName")),
                "scale_category": _s(r.get("ScaleCategory")),
                "market_code": _s(r.get("MarketCode")),
                "market_name": _s(r.get("MarketCodeName")),
                "listing_date": _s(r.get("ListingDate")),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out


def normalize_market_calendar(
    rows: Iterable[dict], *, ingested_at: str, available_at: Optional[str] = None
) -> List[dict]:
    av = _avail(available_at, ingested_at)
    out: List[dict] = []
    for r in rows:
        d = _s(r.get("Date"))
        if not d:
            continue
        et = to_iso(parse_dt(f"{d[:10]}T09:00:00"))
        out.append(
            {
                "source": "jquants",
                "date": d[:10],
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "holiday_division": _s(r.get("HolidayDivision")),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out
