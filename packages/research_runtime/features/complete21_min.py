"""Minimal COMPLETE-21-only features (W49–W51 / w0815ar_g2).

All features:

* declare required datasets from COMPLETE 21 only;
* call :func:`require_feature_datasets` (permanent DEFER fail-closed) before
  any PIT read;
* stay ``status="candidate"`` — no READY / strategy default claim.

Implemented (W49–W50, 7):

* ``volume_change_1d`` — one-session volume change from equity daily bars.
* ``topix_relative_1d`` — equity 1d return minus TOPIX 1d return.
* ``disclosure_flag_fins`` — binary flag if any ``fins_summary`` row is visible.
* ``margin_interest_change_1d`` — session-over-session margin interest change.
* ``short_ratio_level`` — short-sale ratio level for a sector (S33).
* ``is_trading_day`` — calendar utility: 1.0 if ``date`` is a trading day.
* ``repo_rate_level`` — latest Tokyo repo rate level (JSDA).

Implemented (W51 expand, +3):

* ``return_1d_c21`` — complete21-path export of the 1d simple-return formula
  (``require_feature_datasets`` + bars). Does **not** replace approved v0
  ``return_1d``; stays ``candidate``.
* ``margin_alert_flag`` — binary flag if any ``markets_margin_alert`` row is
  PIT-visible for ``code``.
* ``futures_activity_proxy`` — sum of latest-session futures volumes from
  ``derivatives_bars_daily_futures`` (optional contract ``code`` filter).

Approved v0 ``return_1d`` remains in ``features.v0`` (DEFER-guarded via
``get_equity_bars_daily``). This wave does **not** promote any candidate.
"""

from __future__ import annotations

import json
from typing import Any

from price_basis import RAW

from .dataset_guard import require_feature_datasets
from .registry import register
from .types import FeatureDefinition, FeatureInput, FeatureOutput, FeatureVersion


# ---------------------------------------------------------------------------
# pure helpers (data-free unit tests)
# ---------------------------------------------------------------------------

def volume_change_from_pairs(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """Compute 1d volume change from sorted ``(date, volume)`` pairs."""
    if len(pairs) < 2:
        return None, {
            "rows_seen": len(pairs),
            "reason": "insufficient history (need >= 2 volumes)",
        }
    (d0, v0), (d1, v1) = pairs[-2], pairs[-1]
    if v0 == 0:
        return None, {
            "rows_seen": len(pairs),
            "reason": "zero prior volume",
            "prior_date": d0,
            "last_date": d1,
        }
    return (v1 - v0) / v0, {
        "rows_seen": len(pairs),
        "prior_date": d0,
        "prior_volume": v0,
        "last_date": d1,
        "last_volume": v1,
    }


def simple_return_from_closes(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """One-session simple return from sorted ``(date, close)`` pairs."""
    if len(pairs) < 2:
        return None, {
            "rows_seen": len(pairs),
            "reason": "insufficient history (need >= 2 closes)",
        }
    (d0, c0), (d1, c1) = pairs[-2], pairs[-1]
    if c0 == 0:
        return None, {
            "rows_seen": len(pairs),
            "reason": "zero prior close",
            "prior_date": d0,
            "last_date": d1,
        }
    return (c1 - c0) / c0, {
        "rows_seen": len(pairs),
        "prior_date": d0,
        "prior_close": c0,
        "last_date": d1,
        "last_close": c1,
    }


def topix_relative_from_returns(
    equity_ret: float | None,
    topix_ret: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Equity return minus TOPIX return; None if either leg is missing."""
    if equity_ret is None or topix_ret is None:
        return None, {
            "reason": "missing equity or topix return leg",
            "equity_ret": equity_ret,
            "topix_ret": topix_ret,
        }
    return equity_ret - topix_ret, {
        "equity_ret": equity_ret,
        "topix_ret": topix_ret,
    }


def disclosure_flag_from_count(n_rows: int) -> tuple[float, dict[str, Any]]:
    """1.0 if any disclosure row is visible, else 0.0."""
    flag = 1.0 if n_rows > 0 else 0.0
    return flag, {"rows_seen": n_rows, "flag": flag}


def margin_interest_change_from_pairs(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """Session-over-session change of total margin interest (Long+Short)."""
    if len(pairs) < 2:
        return None, {
            "rows_seen": len(pairs),
            "reason": "insufficient history (need >= 2 margin observations)",
        }
    (d0, m0), (d1, m1) = pairs[-2], pairs[-1]
    if m0 == 0:
        return None, {
            "rows_seen": len(pairs),
            "reason": "zero prior margin interest",
            "prior_date": d0,
            "last_date": d1,
        }
    return (m1 - m0) / m0, {
        "rows_seen": len(pairs),
        "prior_date": d0,
        "prior_margin": m0,
        "last_date": d1,
        "last_margin": m1,
    }


def short_ratio_level_from_components(
    short_with_res: float | None,
    short_no_res: float | None,
    sell_ex_short: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Short ratio = (with-restriction + no-restriction) / sell-ex-short.

    Uses J-Quants short-ratio fields ``ShrtWithResVa`` / ``ShrtNoResVa`` /
    ``SellExShortVa``. Returns None when the denominator is missing or zero.
    """
    if sell_ex_short is None or sell_ex_short == 0:
        return None, {
            "reason": "missing or zero SellExShortVa denominator",
            "short_with_res": short_with_res,
            "short_no_res": short_no_res,
            "sell_ex_short": sell_ex_short,
        }
    with_r = 0.0 if short_with_res is None else float(short_with_res)
    no_r = 0.0 if short_no_res is None else float(short_no_res)
    ratio = (with_r + no_r) / float(sell_ex_short)
    return ratio, {
        "short_with_res": with_r,
        "short_no_res": no_r,
        "sell_ex_short": float(sell_ex_short),
        "ratio": ratio,
    }


def is_trading_day_from_division(
    holiday_division: str | int | None,
) -> tuple[float | None, dict[str, Any]]:
    """1.0 if holiday_division marks a trading day (\"1\"), else 0.0.

    Returns None when no calendar observation is present.
    """
    if holiday_division is None or holiday_division == "":
        return None, {
            "reason": "no calendar row / holiday_division",
            "holiday_division": holiday_division,
        }
    div = str(holiday_division).strip()
    flag = 1.0 if div == "1" else 0.0
    return flag, {"holiday_division": div, "flag": flag}


def repo_rate_level_from_rows(
    rows: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any]]:
    """Latest non-null rate from sorted repo-rate rows (by as_of_date)."""
    ranked: list[tuple[str, float, dict[str, Any]]] = []
    for r in rows:
        rate = r.get("rate")
        d = r.get("as_of_date") or r.get("date")
        if rate is None or d is None:
            continue
        try:
            ranked.append((str(d)[:10], float(rate), r))
        except (TypeError, ValueError):
            continue
    if not ranked:
        return None, {
            "rows_seen": len(rows),
            "reason": "no repo rate observations visible",
        }
    ranked.sort(key=lambda x: x[0])
    d, rate, last = ranked[-1]
    return rate, {
        "rows_seen": len(rows),
        "as_of_date": d,
        "tenor": last.get("tenor"),
        "rate_type": last.get("rate_type"),
        "rate": rate,
    }


def margin_alert_flag_from_count(n_rows: int) -> tuple[float, dict[str, Any]]:
    """1.0 if any margin-alert row is visible, else 0.0."""
    flag = 1.0 if n_rows > 0 else 0.0
    return flag, {"rows_seen": n_rows, "flag": flag}


def futures_activity_from_volume_pairs(
    pairs: list[tuple[str, float]],
) -> tuple[float | None, dict[str, Any]]:
    """Sum volumes on the latest date as a futures activity proxy.

    ``pairs`` are sorted ``(date, volume)`` observations (any contract).
    Returns None when no volume observations are present.
    """
    if not pairs:
        return None, {
            "rows_seen": 0,
            "reason": "no futures volume observations visible",
        }
    last_date = pairs[-1][0]
    total = 0.0
    n_on_date = 0
    for d, v in pairs:
        if d == last_date:
            total += v
            n_on_date += 1
    return total, {
        "rows_seen": len(pairs),
        "activity_date": last_date,
        "contracts_on_date": n_on_date,
        "volume_sum": total,
    }


def _parse_volume_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in rows:
        v = r.get("volume")
        d = r.get("date")
        if v is None or d is None:
            continue
        try:
            out.append((str(d), float(v)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _parse_close_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in rows:
        c = r.get("close")
        d = r.get("date")
        if c is None or d is None:
            # jquants_records payload shape
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            if c is None:
                c = payload.get("Close") or payload.get("close")
            if d is None:
                d = (
                    payload.get("Date")
                    or payload.get("date")
                    or r.get("event_time")
                )
                if d is not None:
                    d = str(d)[:10]
        if c is None or d is None:
            continue
        try:
            out.append((str(d)[:10], float(c)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Best-effort payload dict from a jquants_records (or flattened) row."""
    p = row.get("payload")
    if isinstance(p, dict):
        return p
    if isinstance(p, str) and p:
        try:
            loaded = json.loads(p)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    raw = row.get("raw_payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {}


def _parse_margin_interest_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Extract ``(date, LongVol + ShrtVol)`` from margin-interest catalog rows."""
    out: list[tuple[str, float]] = []
    for r in rows:
        payload = _row_payload(r)
        d = (
            payload.get("Date")
            or payload.get("date")
            or r.get("date")
            or (str(r.get("event_time"))[:10] if r.get("event_time") else None)
        )
        long_v = payload.get("LongVol")
        short_v = payload.get("ShrtVol")
        if long_v is None and short_v is None:
            long_v = r.get("LongVol")
            short_v = r.get("ShrtVol")
        if d is None or (long_v is None and short_v is None):
            continue
        try:
            total = float(long_v or 0.0) + float(short_v or 0.0)
            out.append((str(d)[:10], total))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _latest_short_ratio_row(
    rows: list[dict[str, Any]],
    *,
    section: str,
) -> dict[str, Any] | None:
    """Pick the latest short-ratio row for ``section`` (S33)."""
    section_s = str(section).strip()
    candidates: list[tuple[str, dict[str, Any]]] = []
    for r in rows:
        payload = _row_payload(r)
        s33 = payload.get("S33") or payload.get("section") or r.get("S33")
        if s33 is None or str(s33).strip() != section_s:
            continue
        d = (
            payload.get("Date")
            or payload.get("date")
            or (str(r.get("event_time"))[:10] if r.get("event_time") else None)
        )
        if d is None:
            continue
        candidates.append((str(d)[:10], {**payload, **{k: v for k, v in r.items() if k not in ("payload", "raw_payload")}}))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def _parse_futures_volume_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Extract ``(date, volume)`` from derivatives futures catalog rows."""
    out: list[tuple[str, float]] = []
    for r in rows:
        payload = _row_payload(r)
        d = (
            payload.get("Date")
            or payload.get("date")
            or r.get("date")
            or (str(r.get("event_time"))[:10] if r.get("event_time") else None)
        )
        vol = (
            payload.get("Volume")
            or payload.get("volume")
            or r.get("volume")
            or r.get("Volume")
        )
        if d is None or vol is None:
            continue
        try:
            out.append((str(d)[:10], float(vol)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# volume_change_1d
# ---------------------------------------------------------------------------

_VOLUME_DATASETS = ("equities_bars_daily",)


def _volume_change_1d(ctx) -> FeatureOutput:
    require_feature_datasets(
        _VOLUME_DATASETS, context="feature volume_change_1d"
    )
    code = ctx.get_input("code")
    res = ctx.get_equity_bars_daily(code=code)
    pairs = _parse_volume_rows(res.rows)
    value, meta = volume_change_from_pairs(pairs)
    meta = {**meta, "code": code, "datasets": list(_VOLUME_DATASETS)}
    return FeatureOutput(value=value, metadata=meta)


VolumeChange1d: FeatureDefinition = register(
    FeatureDefinition(
        id="volume_change_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "One-session volume change (COMPLETE 21: equities_bars_daily only). "
            "Returns None when fewer than two volumes are visible at as_of. "
            "Permanent DEFER datasets are rejected before PIT reads."
        ),
        compute=_volume_change_1d,
        tags=("volume", "daily", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# topix_relative_1d
# ---------------------------------------------------------------------------

_TOPIX_REL_DATASETS = ("equities_bars_daily", "indices_bars_daily_topix")


def _topix_relative_1d(ctx) -> FeatureOutput:
    require_feature_datasets(
        _TOPIX_REL_DATASETS, context="feature topix_relative_1d"
    )
    code = ctx.get_input("code")
    bar_res = ctx.get_equity_bars_daily(code=code)
    eq_pairs = _parse_close_rows(bar_res.rows)
    equity_ret, eq_meta = simple_return_from_closes(eq_pairs)

    topix_res = ctx.get_jquants_records(dataset="indices_bars_daily_topix")
    tx_pairs = _parse_close_rows(topix_res.rows)
    topix_ret, tx_meta = simple_return_from_closes(tx_pairs)

    value, rel_meta = topix_relative_from_returns(equity_ret, topix_ret)
    meta = {
        "code": code,
        "datasets": list(_TOPIX_REL_DATASETS),
        "equity": eq_meta,
        "topix": tx_meta,
        **rel_meta,
    }
    return FeatureOutput(value=value, metadata=meta)


TopixRelative1d: FeatureDefinition = register(
    FeatureDefinition(
        id="topix_relative_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Equity 1d return minus TOPIX 1d return "
            "(COMPLETE 21: equities_bars_daily + indices_bars_daily_topix). "
            "Permanent DEFER datasets are rejected before PIT reads."
        ),
        compute=_topix_relative_1d,
        tags=("return", "relative", "topix", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=RAW,
    )
)


# ---------------------------------------------------------------------------
# disclosure_flag_fins
# ---------------------------------------------------------------------------

_DISC_DATASETS = ("fins_summary",)


def _disclosure_flag_fins(ctx) -> FeatureOutput:
    require_feature_datasets(
        _DISC_DATASETS, context="feature disclosure_flag_fins"
    )
    code = ctx.get_input("code")
    res = ctx.get_jquants_records(dataset="fins_summary", code=code)
    n = len(res.rows) if res is not None and getattr(res, "rows", None) is not None else 0
    value, meta = disclosure_flag_from_count(n)
    meta = {**meta, "code": code, "datasets": list(_DISC_DATASETS)}
    return FeatureOutput(value=value, metadata=meta)


DisclosureFlagFins: FeatureDefinition = register(
    FeatureDefinition(
        id="disclosure_flag_fins",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Binary disclosure flag: 1.0 if any PIT-visible fins_summary row "
            "exists for code at as_of, else 0.0. COMPLETE 21 only "
            "(fins_summary). Permanent DEFER (e.g. fins_earnings_date) excluded."
        ),
        compute=_disclosure_flag_fins,
        tags=("disclosure", "fins", "flag", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# margin_interest_change_1d
# ---------------------------------------------------------------------------

_MARGIN_DATASETS = ("markets_margin_interest",)


def _margin_interest_change_1d(ctx) -> FeatureOutput:
    require_feature_datasets(
        _MARGIN_DATASETS, context="feature margin_interest_change_1d"
    )
    code = ctx.get_input("code")
    res = ctx.get_jquants_records(dataset="markets_margin_interest", code=code)
    pairs = _parse_margin_interest_rows(res.rows)
    value, meta = margin_interest_change_from_pairs(pairs)
    meta = {
        **meta,
        "code": code,
        "datasets": list(_MARGIN_DATASETS),
        "metric": "LongVol+ShrtVol",
    }
    return FeatureOutput(value=value, metadata=meta)


MarginInterestChange1d: FeatureDefinition = register(
    FeatureDefinition(
        id="margin_interest_change_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Session-over-session change in total margin interest "
            "(LongVol + ShrtVol) for code. COMPLETE 21: markets_margin_interest. "
            "Returns None with <2 PIT-visible observations. Permanent DEFER "
            "datasets are rejected before PIT reads."
        ),
        compute=_margin_interest_change_1d,
        tags=("margin", "interest", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# short_ratio_level
# ---------------------------------------------------------------------------

_SHORT_RATIO_DATASETS = ("markets_short_ratio",)


def _short_ratio_level(ctx) -> FeatureOutput:
    require_feature_datasets(
        _SHORT_RATIO_DATASETS, context="feature short_ratio_level"
    )
    section = ctx.get_input("section")
    res = ctx.get_jquants_records(dataset="markets_short_ratio")
    row = _latest_short_ratio_row(res.rows, section=str(section))
    if row is None:
        return FeatureOutput(
            value=None,
            metadata={
                "section": section,
                "datasets": list(_SHORT_RATIO_DATASETS),
                "rows_seen": len(res.rows) if res is not None else 0,
                "reason": "no short_ratio row for section at as_of",
            },
        )
    value, ratio_meta = short_ratio_level_from_components(
        row.get("ShrtWithResVa"),
        row.get("ShrtNoResVa"),
        row.get("SellExShortVa"),
    )
    meta = {
        "section": section,
        "datasets": list(_SHORT_RATIO_DATASETS),
        "date": row.get("Date") or row.get("date"),
        **ratio_meta,
    }
    return FeatureOutput(value=value, metadata=meta)


ShortRatioLevel: FeatureDefinition = register(
    FeatureDefinition(
        id="short_ratio_level",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("section",),
            as_of_rule="session_close",
        ),
        description=(
            "Latest short-sale ratio level for a TSE 33-sector (S33): "
            "(ShrtWithResVa + ShrtNoResVa) / SellExShortVa. COMPLETE 21: "
            "markets_short_ratio. Permanent DEFER datasets rejected before "
            "PIT reads."
        ),
        compute=_short_ratio_level,
        tags=("short", "ratio", "sector", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# is_trading_day
# ---------------------------------------------------------------------------

_CALENDAR_DATASETS = ("markets_calendar",)


def _is_trading_day(ctx) -> FeatureOutput:
    require_feature_datasets(
        _CALENDAR_DATASETS, context="feature is_trading_day"
    )
    # Optional override; default is calendar date of as_of.
    date = ctx.get_input("date", None)
    if date is None:
        date = str(ctx.as_of)[:10]
    else:
        date = str(date)[:10]
    res = ctx.get_market_calendar(from_date=date, to_date=date)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    if not rows:
        value, meta = is_trading_day_from_division(None)
    else:
        # Prefer an explicit trading-day hit if multiple rows exist.
        divisions = [r.get("holiday_division") for r in rows]
        if any(str(d).strip() == "1" for d in divisions if d is not None):
            value, meta = is_trading_day_from_division("1")
        else:
            value, meta = is_trading_day_from_division(divisions[0])
    meta = {
        **meta,
        "date": date,
        "datasets": list(_CALENDAR_DATASETS),
        "rows_seen": len(rows),
    }
    return FeatureOutput(value=value, metadata=meta)


IsTradingDay: FeatureDefinition = register(
    FeatureDefinition(
        id="is_trading_day",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"date": None},
            as_of_rule="session_close",
        ),
        description=(
            "Structural/utility flag: 1.0 if markets_calendar marks date as a "
            "trading day (holiday_division=='1'), 0.0 if non-trading, None if "
            "no calendar row is PIT-visible. Default date = as_of calendar day. "
            "COMPLETE 21: markets_calendar. Permanent DEFER rejected."
        ),
        compute=_is_trading_day,
        tags=("calendar", "trading_day", "complete21"),
        intended_role="utility",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# repo_rate_level
# ---------------------------------------------------------------------------

_REPO_DATASETS = ("jsda_tokyo_repo_rates",)


def _repo_rate_level(ctx) -> FeatureOutput:
    require_feature_datasets(
        _REPO_DATASETS, context="feature repo_rate_level"
    )
    tenor = ctx.get_input("tenor", None)
    rate_type = ctx.get_input("rate_type", None)
    kwargs: dict[str, Any] = {}
    if tenor is not None:
        kwargs["tenor"] = tenor
    if rate_type is not None:
        kwargs["rate_type"] = rate_type
    res = ctx.get_jsda_repo_rates(**kwargs)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    value, meta = repo_rate_level_from_rows(rows)
    meta = {
        **meta,
        "datasets": list(_REPO_DATASETS),
        "tenor_filter": tenor,
        "rate_type_filter": rate_type,
    }
    return FeatureOutput(value=value, metadata=meta)


RepoRateLevel: FeatureDefinition = register(
    FeatureDefinition(
        id="repo_rate_level",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"tenor": None, "rate_type": None},
            as_of_rule="session_close",
        ),
        description=(
            "Latest Tokyo repo rate level visible at as_of (JSDA). COMPLETE 21: "
            "jsda_tokyo_repo_rates. Optional tenor / rate_type filters. "
            "Permanent DEFER datasets rejected before PIT reads."
        ),
        compute=_repo_rate_level,
        tags=("repo", "rate", "jsda", "macro", "complete21"),
        intended_role="state",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# return_1d_c21 — complete21-path export of 1d simple return (candidate)
# ---------------------------------------------------------------------------

_RETURN_C21_DATASETS = ("equities_bars_daily",)


def _return_1d_c21(ctx) -> FeatureOutput:
    require_feature_datasets(
        _RETURN_C21_DATASETS, context="feature return_1d_c21"
    )
    code = ctx.get_input("code")
    res = ctx.get_equity_bars_daily(code=code)
    pairs = _parse_close_rows(res.rows)
    value, meta = simple_return_from_closes(pairs)
    meta = {
        **meta,
        "code": code,
        "datasets": list(_RETURN_C21_DATASETS),
        "export_of": "return_1d",
        "path": "complete21_min",
    }
    return FeatureOutput(value=value, metadata=meta)


Return1dC21: FeatureDefinition = register(
    FeatureDefinition(
        id="return_1d_c21",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "COMPLETE-21 path export of one-session simple return "
            "(close-to-close) from equities_bars_daily. Calls "
            "require_feature_datasets before PIT reads. Candidate twin of "
            "approved v0 return_1d — does not replace it; no promotion this wave."
        ),
        compute=_return_1d_c21,
        tags=("return", "daily", "complete21", "export"),
        intended_role="signal",
        status="candidate",
        price_basis=RAW,
    )
)


# ---------------------------------------------------------------------------
# margin_alert_flag
# ---------------------------------------------------------------------------

_MARGIN_ALERT_DATASETS = ("markets_margin_alert",)


def _margin_alert_flag(ctx) -> FeatureOutput:
    require_feature_datasets(
        _MARGIN_ALERT_DATASETS, context="feature margin_alert_flag"
    )
    code = ctx.get_input("code")
    res = ctx.get_jquants_records(dataset="markets_margin_alert", code=code)
    n = len(res.rows) if res is not None and getattr(res, "rows", None) is not None else 0
    value, meta = margin_alert_flag_from_count(n)
    meta = {**meta, "code": code, "datasets": list(_MARGIN_ALERT_DATASETS)}
    return FeatureOutput(value=value, metadata=meta)


MarginAlertFlag: FeatureDefinition = register(
    FeatureDefinition(
        id="margin_alert_flag",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Binary margin-alert flag: 1.0 if any PIT-visible "
            "markets_margin_alert row exists for code at as_of, else 0.0. "
            "COMPLETE 21 only. Permanent DEFER datasets rejected before PIT reads."
        ),
        compute=_margin_alert_flag,
        tags=("margin", "alert", "flag", "complete21"),
        intended_role="signal",
        status="candidate",
        price_basis=None,
    )
)


# ---------------------------------------------------------------------------
# futures_activity_proxy
# ---------------------------------------------------------------------------

_FUTURES_DATASETS = ("derivatives_bars_daily_futures",)


def _futures_activity_proxy(ctx) -> FeatureOutput:
    require_feature_datasets(
        _FUTURES_DATASETS, context="feature futures_activity_proxy"
    )
    code = ctx.get_input("code", None)
    kwargs: dict[str, Any] = {"dataset": "derivatives_bars_daily_futures"}
    if code is not None:
        kwargs["code"] = code
    res = ctx.get_jquants_records(**kwargs)
    rows = res.rows if res is not None and getattr(res, "rows", None) else []
    pairs = _parse_futures_volume_rows(rows)
    value, meta = futures_activity_from_volume_pairs(pairs)
    meta = {
        **meta,
        "code": code,
        "datasets": list(_FUTURES_DATASETS),
        "metric": "volume_sum_latest_date",
    }
    return FeatureOutput(value=value, metadata=meta)


FuturesActivityProxy: FeatureDefinition = register(
    FeatureDefinition(
        id="futures_activity_proxy",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"code": None},
            as_of_rule="session_close",
        ),
        description=(
            "Futures activity proxy: sum of Volume on the latest PIT-visible "
            "date from derivatives_bars_daily_futures. Optional contract code "
            "filter. Returns None when no volumes are visible. COMPLETE 21 only. "
            "Permanent DEFER datasets rejected before PIT reads."
        ),
        compute=_futures_activity_proxy,
        tags=("futures", "derivatives", "activity", "complete21"),
        intended_role="state",
        status="candidate",
        price_basis=None,
    )
)


__all__ = [
    "VolumeChange1d",
    "TopixRelative1d",
    "DisclosureFlagFins",
    "MarginInterestChange1d",
    "ShortRatioLevel",
    "IsTradingDay",
    "RepoRateLevel",
    "Return1dC21",
    "MarginAlertFlag",
    "FuturesActivityProxy",
    "volume_change_from_pairs",
    "simple_return_from_closes",
    "topix_relative_from_returns",
    "disclosure_flag_from_count",
    "margin_interest_change_from_pairs",
    "short_ratio_level_from_components",
    "is_trading_day_from_division",
    "repo_rate_level_from_rows",
    "margin_alert_flag_from_count",
    "futures_activity_from_volume_pairs",
]
