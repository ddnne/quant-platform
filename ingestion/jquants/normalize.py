"""Normalize J-Quants V2 payloads into PIT-annotated structured rows.

Every row gets ``source='jquants'`` and the four PIT columns. ``available_at``
defaults to the fetch time (``ingested_at``), which is always a safe,
non-look-ahead value; pass an explicit ``available_at`` when the true
publication time is known. Exact per-source publication timing is **仮**
pending confirmation — see ``docs/data_sources.md``.

Field-name tolerance: V2 publishes long names (``Open`` / ``High`` / …) for
some payloads and abbreviated short names (``O`` / ``H`` / ``CoName`` / …)
for others. :func:`_pick` returns the first present, non-empty value among
the candidate keys, so both shapes normalize correctly.

Two storage targets:

* the Phase-1 **specialized** tables (:func:`normalize_daily_bars` /
  :func:`normalize_listed_info` / :func:`normalize_market_calendar`) for the
  three curated series, and
* the **generic** :func:`normalize_generic` -> ``jquants_records`` table that
  absorbs every other catalog dataset (fins, indices, derivatives, markets,
  EDINET, minute/tick/TDnet add-ons). Phase 1 prefers the generic table for
  speed; specialized tables stay for the curated, query-heavy series.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, List, Optional

from ..common.timeutil import parse_dt, to_iso
from . import catalog

# TSE moved the cash-session close from 15:00 to 15:30 JST starting this date.
CLOSE_CHANGE_DATE = "2024-11-05"


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


def _pick(r: dict, *keys: str) -> Any:
    """First present, non-empty value among ``keys`` (preserves ``0``)."""
    for k in keys:
        if k in r:
            v = r[k]
            if v is not None and v != "":
                return v
    return None


def _pick_num(r: dict, *keys: str) -> Optional[float]:
    """Numeric variant of :func:`_pick` — keeps zero instead of skipping it."""
    v = _pick(r, *keys)
    return _num(v)


def _pick_str(r: dict, *keys: str) -> Optional[str]:
    return _s(_pick(r, *keys))


def _avail(available_at: Optional[str], ingested_at: str) -> str:
    return available_at or ingested_at


def _close_event_time(date_str: str) -> str:
    """Session-close ``event_time`` for a date, honoring the 15:30 move.

    * date < ``2024-11-05`` -> 15:00 JST
    * date >= ``2024-11-05`` -> 15:30 JST (TSE extended close)
    """
    d = date_str[:10]
    hhmmss = "15:30:00" if d >= CLOSE_CHANGE_DATE else "15:00:00"
    return to_iso(parse_dt(f"{d}T{hhmmss}"))


def normalize_daily_bars(
    rows: Iterable[dict], *, ingested_at: str, available_at: Optional[str] = None
) -> List[dict]:
    av = _avail(available_at, ingested_at)
    out: List[dict] = []
    for r in rows:
        d = _pick_str(r, "Date")
        if not d:
            continue
        try:
            et = _close_event_time(d[:10])  # trade close, JST
        except ValueError:
            et = to_iso(parse_dt(d[:10]))
        out.append(
            {
                "source": "jquants",
                "code": _pick_str(r, "Code"),
                "date": d[:10],
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "open": _pick_num(r, "Open", "O"),
                "high": _pick_num(r, "High", "H"),
                "low": _pick_num(r, "Low", "L"),
                "close": _pick_num(r, "Close", "C"),
                "volume": _pick_num(r, "Volume", "Vo"),
                "turnover_value": _pick_num(r, "TurnoverValue", "Va"),
                "adjustment_open": _pick_num(
                    r, "AdjustmentOpen", "AdjOpen", "AdjO", "AAdjO"
                ),
                "adjustment_high": _pick_num(
                    r, "AdjustmentHigh", "AdjHigh", "AdjH", "AAdjH"
                ),
                "adjustment_low": _pick_num(
                    r, "AdjustmentLow", "AdjLow", "AdjL", "AAdjL"
                ),
                "adjustment_close": _pick_num(
                    r, "AdjustmentClose", "AdjClose", "AdjC", "AAdjC"
                ),
                "adjustment_volume": _pick_num(
                    r, "AdjustmentVolume", "AdjVolume", "AdjVo", "AAdjVo"
                ),
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
                "code": _pick_str(r, "Code"),
                "snapshot_date": sd,
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "company_name": _pick_str(r, "CompanyName", "CoName"),
                "company_name_en": _pick_str(
                    r, "CompanyNameEnglish", "CoNameEnglish", "CoNameEn"
                ),
                "sector_17_code": _pick_str(r, "Sector17Code", "Sec17Code"),
                "sector_17_name": _pick_str(
                    r, "Sector17CodeName", "Sec17CodeName"
                ),
                "sector_33_code": _pick_str(r, "Sector33Code", "Sec33Code"),
                "sector_33_name": _pick_str(
                    r, "Sector33CodeName", "Sec33CodeName"
                ),
                "scale_category": _pick_str(r, "ScaleCategory", "ScaleCat"),
                "market_code": _pick_str(r, "MarketCode", "MktCode"),
                "market_name": _pick_str(r, "MarketCodeName", "MktCodeName"),
                "listing_date": _pick_str(r, "ListingDate", "ListDate"),
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
        d = _pick_str(r, "Date")
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
                "holiday_division": _pick_str(r, "HolidayDivision", "HolDiv"),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Generic normalizer -> jquants_records (every other catalog dataset)
# ---------------------------------------------------------------------------

# Fields inspected (in order) to derive an ``event_time`` when the dataset has
# no specialized rule. Disclosed/announcement dates win over a plain Date.
_DATE_FIELDS = ("DisclosedDate", "AnnouncementDate", "DisclosureDate", "Date")


def _natural_key(row: dict, key_fields: Iterable[str]) -> dict:
    """Build a JSON-serializable natural key from the catalog's identity fields.

    For each catalog ``key`` field, take the first present, non-empty value
    among that field and its lowercase alias — V2 publishes mixed casing across
    payloads (``DateTime`` vs ``datetime``, ``Time`` vs ``time``), so the key
    is stable either way and always recorded under the canonical name.

    Multi-observation series (minute bars, ticks, option contracts, TDnet
    disclosures) MUST list their per-observation discriminator here. Without it
    upsert collapses every observation sharing a ``(Code, Date)`` — or just a
    ``Date`` — onto the last row written (the P1 natural-key bug).

    If none of the identity fields are present (an unusual payload shape), fall
    back to a stable SHA-1 of the canonical row so idempotency still holds and
    we never collapse two distinct rows onto the same key.
    """
    nk: dict[str, Any] = {}
    for f in key_fields:
        v = _pick(row, f, f.lower())
        if v is not None and v != "":
            nk[f] = v
    if nk:
        return nk
    canon = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return {"_hash": hashlib.sha1(canon.encode("utf-8")).hexdigest()}


def _event_time_for(row: dict, dataset: str) -> Optional[str]:
    """Best-effort ``event_time`` for a generic row.

    Daily equity bars use the session-close time (honoring the 2024-11-05
    15:00 -> 15:30 move); minute bars expose ``DateTime``; everything else
    falls back to the first disclosed/announcement/date field at 09:00 JST.
    Returns ``None`` when no date-ish field is present (caller uses
    ``available_at``/``ingested_at``).
    """
    if dataset in ("equities_bars_daily", "equities_bars_daily_am"):
        d = _pick_str(row, "Date")
        if d:
            try:
                return _close_event_time(d[:10])
            except ValueError:
                pass
    dt = _pick(row, "DateTime", "datetime")
    if dt:
        try:
            return to_iso(parse_dt(str(dt)))
        except ValueError:
            pass
    for f in _DATE_FIELDS:
        v = _pick_str(row, f)
        if v:
            try:
                return to_iso(parse_dt(f"{v[:10]}T09:00:00"))
            except ValueError:
                continue
    return None


def normalize_generic(
    rows: Iterable[dict],
    *,
    dataset: str,
    ingested_at: str,
    available_at: Optional[str] = None,
) -> List[dict]:
    """Normalize any catalog dataset into ``jquants_records`` rows.

    The natural key comes from :func:`_natural_key` (catalog identity fields,
    row-hash fallback). ``payload`` is a stable (key-sorted) serialization of
    the row for easy diffing; ``raw_payload`` keeps the verbatim source order
    for traceability and amendment detection in the store.
    """
    av = _avail(available_at, ingested_at)
    entry = catalog.get(dataset)
    key_fields = entry.get("key", [])
    out: List[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        et = _event_time_for(r, dataset) or av
        out.append(
            {
                "source": "jquants",
                "dataset": dataset,
                "natural_key": json.dumps(
                    _natural_key(r, key_fields), sort_keys=True, ensure_ascii=False
                ),
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "payload": json.dumps(r, sort_keys=True, ensure_ascii=False),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out
