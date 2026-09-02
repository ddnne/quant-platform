"""Normalize J-Quants V2 payloads into PIT-annotated structured rows.

Every row gets ``source='jquants'`` and the four PIT columns. Premium-core
``available_at`` values follow the canonical dataset contract; any policy
without enough evidence falls back conservatively to ``ingested_at``. The
keyword-only ``available_at`` argument is a trusted-caller/testing capability;
a same-named field in an upstream source row is retained in raw payload only
and can never override trusted PIT metadata.

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

import json
from typing import Any, Iterable, List, Optional

from data_contracts.identity import (
    available_at_for as contract_available_at,
    canonical_json,
    event_time_for as contract_event_time,
    natural_key as contract_natural_key,
    sha256_fallback,
)

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
    """Normalize bars; ``available_at`` is trusted caller metadata, not payload."""
    out: List[dict] = []
    for r in rows:
        d = _pick_str(r, "Date")
        if not d:
            continue
        try:
            et = _close_event_time(d[:10])  # trade close, JST
        except ValueError:
            et = to_iso(parse_dt(d[:10]))
        av = available_at or contract_available_at(
            r, "equities_bars_daily", ingested_at
        )
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
                # Vendor point-in-time daily market capitalization.  Keep it
                # as an optional level; relative-size strategies normalize it
                # within the PIT sector/market cross-section.
                "market_cap": _pick_num(
                    r, "MarketCapitalization", "MarketCap", "MktCap"
                ),
                # All-day adjusted series only. V2 also publishes session-split
                # fields (MAdj* morning / AAdj* afternoon) — those are *not*
                # aliases of Adj* and must not backfill when Adj* is null.
                "adjustment_open": _pick_num(
                    r, "AdjustmentOpen", "AdjOpen", "AdjO"
                ),
                "adjustment_high": _pick_num(
                    r, "AdjustmentHigh", "AdjHigh", "AdjH"
                ),
                "adjustment_low": _pick_num(
                    r, "AdjustmentLow", "AdjLow", "AdjL"
                ),
                "adjustment_close": _pick_num(
                    r, "AdjustmentClose", "AdjClose", "AdjC"
                ),
                "adjustment_volume": _pick_num(
                    r, "AdjustmentVolume", "AdjVolume", "AdjVo"
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
    """Normalize master rows with an optional trusted availability override."""
    sd = str(snapshot_date)[:10]
    out: List[dict] = []
    for r in rows:
        identity_row = r if _pick(r, "Date") else {**r, "Date": sd}
        et = contract_event_time(identity_row, "equities_master") or ingested_at
        av = available_at or contract_available_at(
            identity_row, "equities_master", ingested_at
        )
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
                # V2 short: S17/S17Nm/S33/S33Nm/Mkt/MktNm (live SoT 2026-08).
                # Longer Sec*/Market* aliases retained for historical payloads.
                "sector_17_code": _pick_str(
                    r, "Sector17Code", "Sec17Code", "S17"
                ),
                "sector_17_name": _pick_str(
                    r, "Sector17CodeName", "Sec17CodeName", "S17Nm"
                ),
                "sector_33_code": _pick_str(
                    r, "Sector33Code", "Sec33Code", "S33"
                ),
                "sector_33_name": _pick_str(
                    r, "Sector33CodeName", "Sec33CodeName", "S33Nm"
                ),
                "scale_category": _pick_str(r, "ScaleCategory", "ScaleCat"),
                "market_code": _pick_str(
                    r, "MarketCode", "MktCode", "Mkt"
                ),
                "market_name": _pick_str(
                    r, "MarketCodeName", "MktCodeName", "MktNm"
                ),
                # ListingDate/ListDate are absent from V2 /v2/equities/master
                # (always-missing source field; not a mapping miss).
                "listing_date": _pick_str(r, "ListingDate", "ListDate"),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out


def normalize_market_calendar(
    rows: Iterable[dict], *, ingested_at: str, available_at: Optional[str] = None
) -> List[dict]:
    """Normalize calendar rows with an optional trusted availability override."""
    out: List[dict] = []
    for r in rows:
        d = _pick_str(r, "Date")
        if not d:
            continue
        et = contract_event_time(r, "markets_calendar") or ingested_at
        av = available_at or contract_available_at(
            r, "markets_calendar", ingested_at
        )
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


def _canonical_minute_time(row: dict) -> Optional[str]:
    """Canonical ``HH:MM`` minute discriminator for a minute-bar row.

    The bulk-CSV surface carries a per-minute ``DateTime`` (full JST timestamp);
    the REST surface splits the same instant into ``Date`` + ``Time``. Either
    way it is the *same observation*, so the natural key must not depend on
    which transport produced the row. Reduce both forms to the JST wall-clock
    minute ``HH:MM`` — ``parse_dt`` normalizes any offset to JST first, so a
    UTC-anchored ``DateTime`` still matches the JST ``Time`` value.

    Returns ``None`` only when neither field is present (a malformed row).
    """
    dt = _pick(row, "DateTime", "datetime")
    if dt:
        try:
            return parse_dt(str(dt)).strftime("%H:%M")
        except ValueError:
            pass
    t = _pick_str(row, "Time", "time")
    if t:
        return t[:5]  # HH:MM (drop any trailing :SS)
    return None


def _natural_key(row: dict, key_fields: Iterable[str], dataset: str = "") -> str:
    """Build a JSON-serializable natural key from the catalog's identity fields.

    For each catalog ``key`` field, take the first present, non-empty value
    among that field and its lowercase alias — V2 publishes mixed casing across
    payloads (``DateTime`` vs ``datetime``, ``Time`` vs ``time``), so the key
    is stable either way and always recorded under the canonical name.

    Multi-observation series (minute bars, ticks, option contracts, TDnet
    disclosures) MUST list their per-observation discriminator here. Without it
    upsert collapses every observation sharing a ``(Code, Date)`` — or just a
    ``Date`` — onto the last row written (the P1 natural-key bug).

    Minute bars additionally canonicalize their timestamp: bulk ``DateTime`` and
    REST ``Time`` are two transports for one observation, so both are collapsed
    onto a single ``Time`` = ``HH:MM`` (see :func:`_canonical_minute_time`).
    Without this, re-ingesting the same bar via the other transport would
    insert a duplicate row instead of upserting (the inverse-collapse bug).

    Premium-core keys are selected solely by the canonical dataset contract and
    reject missing governed discriminators. Add-ons retain their catalog-specific
    fields until they receive contracts and use a row hash only when none exist.
    """
    if catalog.is_premium_core(dataset):
        return contract_natural_key(row, dataset)
    nk: dict[str, Any] = {}
    for f in key_fields:
        v = _pick(row, f, f.lower())
        if v is not None and v != "":
            nk[f] = v
    if dataset == "equities_bars_minute":
        t = _canonical_minute_time(row)
        if t is not None:
            nk["Time"] = t
            nk.pop("DateTime", None)  # folded into the canonical ``Time``
    if nk:
        return canonical_json(nk)
    return sha256_fallback(row)


def _event_time_for(row: dict, dataset: str) -> Optional[str]:
    """Best-effort ``event_time`` for a generic row.

    Daily equity bars use the session-close time (honoring the 2024-11-05
    15:00 -> 15:30 move); minute bars expose ``DateTime``; everything else
    falls back to the first disclosed/announcement/date field at 09:00 JST.
    Returns ``None`` when no date-ish field is present (caller uses
    ``available_at``/``ingested_at``).
    """
    if catalog.is_premium_core(dataset):
        return contract_event_time(row, dataset)
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

    The natural key comes from :func:`_natural_key`; governed premium rows must
    contain their complete contract identity, while ungoverned add-ons may use
    the legacy row-hash fallback. ``payload`` is a stable (key-sorted)
    serialization of the row for easy diffing; ``raw_payload`` keeps the
    verbatim source order for traceability and amendment detection in the
    store. ``available_at`` is an explicit trusted-caller capability and is
    never read from ``rows``.
    """
    entry = catalog.get(dataset)
    key_fields = entry.get("key", [])
    out: List[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if available_at is not None:
            av = available_at
        elif catalog.is_premium_core(dataset):
            av = contract_available_at(r, dataset, ingested_at)
        else:
            av = ingested_at
        et = _event_time_for(r, dataset) or av
        out.append(
            {
                "source": "jquants",
                "dataset": dataset,
                "natural_key": _natural_key(r, key_fields, dataset),
                "event_time": et,
                "available_at": av,
                "ingested_at": ingested_at,
                "payload": canonical_json(r),
                "raw_payload": json.dumps(r, ensure_ascii=False),
            }
        )
    return out
