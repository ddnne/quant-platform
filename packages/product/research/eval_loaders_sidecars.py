"""Nky / opt225 / margin / repo / fins sidecar loaders. Skip missing. Never invent.

Public import remains ``research.eval_loaders``. Empty / missing → empty or None.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any, Mapping, Sequence
from features.class_signals import (
    DEFAULT_NKY_VOL_LONG_N,
    DEFAULT_NKY_VOL_SHORT_N,
    NKY_VOL_PROXY_NK225F,
    NKY_VOL_PROXY_TOPIX,
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    TRADING_DAYS_ANN,
)
from pit.history_reads import HISTORY_READ_PAGE_SIZE
from pit.personal_research_view import PersonalResearchDataView
from research.eval_loaders import (
    _fnum,
    _payload_map,
)
from core.execution import close_as_of, morning_close_as_of
from research.fins_summary_keys import (
    FINS_SUMMARY_EQ_KEY,
    FINS_SUMMARY_EQAR_KEY,
    FINS_SUMMARY_OFFICIAL_KEYS,
    FINS_SUMMARY_TA_KEY,
)


def _require_view(view: Any) -> PersonalResearchDataView:
    if not isinstance(view, PersonalResearchDataView):
        raise TypeError("eval sqlite loaders require PersonalResearchDataView")
    return view


def _dataset_pages(
    view: PersonalResearchDataView,
    *,
    dataset: str,
    codes: Sequence[str] = (),
    start: str | None = None,
    end: str | None = None,
):
    bound = _require_view(view)
    window_start = str(start or end or "")[:10]
    window_end = str(end or start or "")[:10]
    if not window_start or not window_end:
        raise ValueError("as_of is required (PIT has no latest default)")
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    cursor = _date.fromisoformat(window_start)
    stop = _date.fromisoformat(window_end)
    while cursor <= stop:
        day = cursor.isoformat()
        yield from bound.iter_decision_pages(
            decision_date=day,
            dataset=dataset,
            codes=codes,
            start=day,
            end=day,
            page_size=HISTORY_READ_PAGE_SIZE,
        )
        cursor += _timedelta(days=1)


def _wall_as_of(
    end: str | None, start: str | None = None, *, cutoff: str = "morning_close"
) -> str:
    day = str(end or start or "").strip()[:10]
    if not day:
        raise ValueError("as_of is required (PIT has no latest default)")
    if cutoff == "morning_close":
        return morning_close_as_of(day)
    return close_as_of(day)


def _visible_at(
    available: str,
    day: str,
    cutoff: str,
    *,
    event_time: str = "",
    decision_date: str | None = None,
) -> bool:
    if not available:
        return False
    limit_day = str(decision_date or day)[:10]
    limit = (
        morning_close_as_of(limit_day)
        if cutoff == "morning_close"
        else close_as_of(limit_day)
    )
    if available > limit:
        return False
    et = str(event_time or "")
    if et and et > limit:
        return False
    return True


def _margin_total(pl: Mapping[str, Any]) -> float | None:
    long_v = pl.get("LongVol")
    shrt_v = pl.get("ShrtVol")
    try:
        if long_v is not None and shrt_v is not None:
            return float(long_v) + float(shrt_v)
        if long_v is not None:
            return float(long_v)
        if shrt_v is not None:
            return float(shrt_v)
    except (TypeError, ValueError):
        return None
    return None


def _index_close_pairs(
    rows: Sequence[Mapping[str, Any]],
    *,
    cutoff: str = "morning_close",
    decision_date: str | None = None,
) -> list[tuple[str, float]]:
    chosen: dict[str, tuple[str, str, float]] = {}
    for row in rows:
        pl = _payload_map(row.get("payload"))
        if pl is None:
            continue
        event_time = row.get("event_time")
        d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
        c = pl.get("C") if pl.get("C") is not None else pl.get("Close")
        if not d or c is None or c == "":
            continue
        available = str(row.get("available_at") or "")
        if not _visible_at(
            available,
            d,
            cutoff,
            event_time=str(event_time or ""),
            decision_date=decision_date or d,
        ):
            continue
        try:
            price = float(c)
        except (TypeError, ValueError):
            continue
        ingested = str(row.get("ingested_at") or "")
        previous = chosen.get(d)
        if previous is None or (available, ingested) >= previous[:2]:
            chosen[d] = (available, ingested, price)
    return sorted((day, rec[2]) for day, rec in chosen.items())


def _annualized_realized_vol(
    closes: Sequence[float], end_i: int, window: int
) -> float | None:
    """Sample stdev of 1-session returns over ``window``, annualized √252."""
    if end_i < window or window < 2:
        return None
    rets: list[float] = []
    for j in range(end_i - window + 1, end_i + 1):
        if j < 1:
            return None
        c0, c1 = closes[j - 1], closes[j]
        if c0 is None or c1 is None or float(c0) == 0.0:
            return None
        rets.append((float(c1) / float(c0)) - 1.0)
    if len(rets) < 2:
        return None
    m = mean(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    if var < 0:
        return None
    return float(var ** 0.5) * (float(TRADING_DAYS_ANN) ** 0.5)


def load_topix_close_series_from_sqlite(
    view: PersonalResearchDataView,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load TOPIX closes from indices_bars_daily_topix (prefer) or code 0000."""
    rows = [
        row
        for page in _dataset_pages(
            view,
            dataset="indices_bars_daily_topix",
            start=start,
            end=end,
        )
        for row in page
    ]
    out = _index_close_pairs(rows)
    if out:
        return out
    rows = [
        row
        for page in _dataset_pages(
            view,
            dataset="indices_bars_daily",
            codes=("0000",),
            start=start,
            end=end,
        )
        for row in page
    ]
    return _index_close_pairs(rows)


def build_nky_vol_series(
    close_pairs: Sequence[tuple[str, float]] | None,
    *,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
    source: str = NKY_VOL_PROXY_NK225F,
    dataset: str = "derivatives_bars_daily_futures",
) -> dict[str, Any]:
    """Build date-keyed short/long annualized realized vol + ratio."""
    sn = int(short_n)
    ln = int(long_n)
    if sn < 2:
        sn = DEFAULT_NKY_VOL_SHORT_N
    if ln < sn:
        ln = max(sn + 1, DEFAULT_NKY_VOL_LONG_N)
    pairs = sorted(
        [(str(d)[:10], float(c)) for d, c in (close_pairs or []) if d and c is not None],
        key=lambda x: x[0],
    )
    by_d: dict[str, float] = {}
    for d, c in pairs:
        by_d[d] = c
    dates = sorted(by_d.keys())
    closes = [by_d[d] for d in dates]
    short_by: dict[str, float] = {}
    long_by: dict[str, float] = {}
    ratio_by: dict[str, float] = {}
    for i, d in enumerate(dates):
        s = _annualized_realized_vol(closes, i, sn)
        lo = _annualized_realized_vol(closes, i, ln)
        if s is not None:
            short_by[d] = s
        if lo is not None:
            long_by[d] = lo
        if s is not None and lo is not None and lo > 1e-12:
            ratio_by[d] = s / lo
    return {
        "kind": "nky_vol_series",
        "dataset": dataset,
        "source": source,
        "short_n": sn,
        "long_n": ln,
        "closes_by_date": dict(sorted(by_d.items())),
        "rv_short_by_date": dict(sorted(short_by.items())),
        "rv_long_by_date": dict(sorted(long_by.items())),
        "rv_ratio_by_date": dict(sorted(ratio_by.items())),
        "rv_abs_by_date": dict(sorted(short_by.items())),
        "ffill_applied": False,
        "invent_fill": False,
    }


def load_nky_vol_series_from_sqlite(
    view: PersonalResearchDataView,
    *,
    start: str | None = None,
    end: str | None = None,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
    prefer: str = "ndjson_topix",
) -> dict[str, Any]:
    """Load Nikkei-proxy closes and build short/long realized-vol series."""
    pref = str(prefer or "ndjson_topix").strip().lower()
    lookback_days = max(int(long_n) * 3, 120)
    load_start = start
    if start:
        try:
            from datetime import date as _date
            from datetime import timedelta

            ds = _date.fromisoformat(str(start)[:10])
            load_start = (ds - timedelta(days=lookback_days)).isoformat()
        except ValueError:
            load_start = start

    del pref
    nk_pairs = load_topix_close_series_from_sqlite(
        view, start=load_start, end=end
    )
    return build_nky_vol_series(
        nk_pairs,
        short_n=short_n,
        long_n=long_n,
        source=NKY_VOL_PROXY_TOPIX,
        dataset="indices_bars_daily_topix",
    )


def load_opt225_regime_bundle_for_eval(
    view: PersonalResearchDataView,
    *,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
) -> dict[str, Any] | None:
    """Load digest-locked option sidecar via the typed view. HOLD if absent."""
    bound = _require_view(view)
    payload = bound.read_option_sidecar()
    if payload is None:
        return None
    try:
        from research.options_225_vol_series import (
            DATASET_ID,
            DEFAULT_OPT225_LONG_N,
            DEFAULT_OPT225_SHORT_N,
            OPTIONS_225_VOL_SERIES_VERSION,
            build_opt225_regime_bundle,
        )
    except Exception:
        return None
    sn = int(short_n) if short_n else DEFAULT_OPT225_SHORT_N
    ln = int(long_n) if long_n else DEFAULT_OPT225_LONG_N
    if payload.get("opt225_regime"):
        regime = dict(payload["opt225_regime"])
        source = dict(regime.get("source") or {})
        dataset = str(source.get("dataset") or payload.get("dataset") or "")
        version = str(source.get("version") or payload.get("version") or "")
        if dataset != DATASET_ID or version != OPTIONS_225_VOL_SERIES_VERSION:
            return None
        return regime
    return build_opt225_regime_bundle(
        list(payload.get("base_vol_series") or []),
        list(payload.get("atm_iv_series") or []),
        payload.get("spread_series"),
        skew_rows=payload.get("skew_series") or None,
        term_rows=payload.get("cm_term_series") or None,
        basevol_delta_rows=payload.get("basevol_delta_series") or None,
        short_n=sn,
        long_n=ln,
    )


def fins_summary_ta_eqar_stats(
    view: PersonalResearchDataView,
    *,
    as_of: str,
    limit: int | None = None,
) -> dict[str, Any]:
    """Count TA / EqAR / Eq non-null rates in fins_summary payloads."""
    _require_view(view)
    out: dict[str, Any] = {
        "dataset": "fins_summary",
        "official_keys": dict(FINS_SUMMARY_OFFICIAL_KEYS),
        "n_rows": 0,
        "n_ta_nonnull": 0,
        "n_eqar_nonnull": 0,
        "n_eq_nonnull": 0,
        "ncta_nonnull": 0,
        "invent": False,
        "evidence_kind": "PERSONAL_RETROSPECTIVE_DIAGNOSTIC",
        "feeds_controlled": False,
        "feeds_comparable_strategy_metrics": False,
    }
    decision = str(as_of)[:10]
    rows = [
        row
        for page in view.iter_decision_pages(
            decision_date=decision,
            dataset="fins_summary",
            codes=(),
            start="1900-01-01",
            end=decision,
            page_size=HISTORY_READ_PAGE_SIZE,
        )
        for row in page
    ]
    if limit is not None:
        rows = rows[: int(limit)]
    n = n_ta = n_eqar = n_eq = n_ncta = 0
    for row in rows:
        pl = _payload_map(row.get("payload"))
        if pl is None:
            continue
        n += 1
        if _fnum(pl.get(FINS_SUMMARY_TA_KEY)) is not None:
            n_ta += 1
        if _fnum(pl.get(FINS_SUMMARY_EQAR_KEY)) is not None:
            n_eqar += 1
        if _fnum(pl.get(FINS_SUMMARY_EQ_KEY)) is not None:
            n_eq += 1
        if _fnum(pl.get("NCTA")) is not None:
            n_ncta += 1
    out.update(
        {
            "n_rows": n,
            "n_ta_nonnull": n_ta,
            "n_eqar_nonnull": n_eqar,
            "n_eq_nonnull": n_eq,
            "ncta_nonnull": n_ncta,
            "ta_rate": (n_ta / n) if n else None,
            "eqar_rate": (n_eqar / n) if n else None,
            "eq_rate": (n_eq / n) if n else None,
            "ncta_rate": (n_ncta / n) if n else None,
        }
    )
    return out


def repo_history_plane_status(
    view: PersonalResearchDataView,
) -> dict[str, Any]:
    """JSDA repo is not a compact personal-view dataset."""
    _require_view(view)
    return {
        "dataset": "jsda_tokyo_repo_rates",
        "table": "jsda_repo_rates",
        "sqlite_rows": 0,
        "sqlite_min": None,
        "sqlite_max": None,
        "sqlite_tenors": 0,
        "sqlite_missing": True,
        "d1_role": "hot_tip_only",
        "pit_path": "fail_closed_until_READY",
        "invent_complete": False,
        "ffill_applied": False,
    }


def load_repo_rows_from_sqlite(
    view: PersonalResearchDataView,
    *,
    as_of: str,
    start: str | None = None,
    end: str | None = None,
    tenor_contains: str | None = "overnight",
) -> list[dict[str, Any]]:
    """Repo rows are not served through the personal compact view."""
    del as_of, start, end, tenor_contains
    _require_view(view)
    return []


def load_repo_rows_all_tenors_from_sqlite(
    view: PersonalResearchDataView,
    *,
    as_of: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Load all JSDA Tokyo repo tenors (for curve-shape proxy). PIT-gated on as_of."""
    return load_repo_rows_from_sqlite(
        view, as_of=as_of, start=start, end=end, tenor_contains=None
    )


def build_repo_curve_series(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    short_tenor: str = REPO_CURVE_SHORT_TENOR,
    long_tenor: str = REPO_CURVE_LONG_TENOR,
) -> dict[str, Any]:
    """Build date-keyed short/long rates + spread. Missing either leg → gap."""
    by_date_tenor: dict[str, dict[str, float]] = {}
    for raw in rows or []:
        d = str(raw.get("as_of_date") or raw.get("date") or "")[:10]
        if not d or len(d) < 10:
            continue
        t = str(raw.get("tenor") or "")
        rate_f = _fnum(raw.get("rate"))
        if rate_f is None:
            continue
        by_date_tenor.setdefault(d, {})[t] = rate_f

    short_by: dict[str, float] = {}
    long_by: dict[str, float] = {}
    spread_by: dict[str, float] = {}
    for d, tenors in sorted(by_date_tenor.items()):
        s = tenors.get(short_tenor)
        lo = tenors.get(long_tenor)
        if s is not None:
            short_by[d] = s
        if lo is not None:
            long_by[d] = lo
        if s is not None and lo is not None:
            spread_by[d] = lo - s

    return {
        "kind": "repo_curve_series",
        "dataset": "jsda_tokyo_repo_rates",
        "short_tenor": short_tenor,
        "long_tenor": long_tenor,
        "short_rates_by_date": dict(sorted(short_by.items())),
        "long_rates_by_date": dict(sorted(long_by.items())),
        "spread_by_date": dict(sorted(spread_by.items())),
        "rates_by_date": dict(sorted(short_by.items())),
        "ffill_applied": False,
        "invent_fill": False,
    }


def load_margin_from_sqlite(
    view: PersonalResearchDataView,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load margin interest levels from a typed research view."""
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    by_code: dict[str, dict[str, float]] = {}
    code_set = set(code_list) if code_list else None
    for page in _dataset_pages(
        view,
        dataset="markets_margin_interest",
        codes=code_list,
        start=start,
        end=end,
    ):
        for row in page:
            pl = _payload_map(row.get("payload"))
            if pl is None:
                continue
            code = str(pl.get("Code") or "").strip()
            if not code or (code_set is not None and code not in code_set):
                continue
            date = str(pl.get("Date") or str(row.get("event_time") or "")[:10])[:10]
            if not date:
                continue
            total = _margin_total(pl)
            if total is None:
                continue
            by_code.setdefault(code, {})[date] = total
    return {
        c: sorted(dmap.items(), key=lambda item: item[0])
        for c, dmap in by_code.items()
    }


def load_short_ratio_series_from_sqlite(
    view: PersonalResearchDataView,
    *,
    section: str = "0050",
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load market-level short ratio for one S33 section → sorted (date, ratio)."""
    out: dict[str, float] = {}
    for page in _dataset_pages(
        view,
        dataset="markets_short_ratio",
        start=start,
        end=end,
    ):
        for row in page:
            pl = _payload_map(row.get("payload"))
            if pl is None:
                continue
            if str(pl.get("S33") or pl.get("Section") or "") != str(section):
                continue
            date = str(pl.get("Date") or str(row.get("event_time") or "")[:10])[:10]
            if not date:
                continue
            try:
                with_r = float(pl.get("ShrtWithResVa") or 0.0)
                no_r = float(pl.get("ShrtNoResVa") or 0.0)
                sell = float(pl.get("SellExShortVa") or 0.0)
            except (TypeError, ValueError):
                continue
            if sell == 0.0:
                continue
            out[date] = (with_r + no_r) / sell
    return sorted(out.items(), key=lambda item: item[0])


def _fins_event_from_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    event_time = row.get("event_time")
    pl = _payload_map(row.get("payload"))
    if pl is None:
        return None
    code = str(pl.get("Code") or "").strip()
    disc = str(
        pl.get("DiscDate")
        or pl.get("DisclosedDate")
        or str(event_time or "")[:10]
    )[:10]
    if not code or not disc:
        return None
    disc_time = pl.get("DiscTime") or pl.get("DisclosedTime")
    if disc_time is not None:
        disc_time = str(disc_time).strip() or None
    eq = _fnum(pl.get(FINS_SUMMARY_EQ_KEY))
    if eq is None:
        eq = _fnum(pl.get("ShEq"))
    return {
        "code": code,
        "disc_no": str(pl.get("DiscNo") or ""),
        "natural_key": str(row.get("natural_key") or ""),
        "disc_date": disc,
        "disc_time": disc_time,
        "eps": _fnum(pl.get("EPS")),
        "feps": _fnum(pl.get("FEPS")),
        "bps": _fnum(pl.get("BPS")),
        "roe": _fnum(pl.get("ROE")),
        "div_ann": _fnum(pl.get("DivAnn")),
        "np": _fnum(pl.get("NP")),
        "sales": _fnum(pl.get("Sales")),
        "eq": eq,
        "ta": _fnum(pl.get(FINS_SUMMARY_TA_KEY)),
        "eq_ar": _fnum(pl.get(FINS_SUMMARY_EQAR_KEY)),
        "event_time": str(event_time) if event_time else None,
        "available_at": str(row.get("available_at") or "") or None,
        "ingested_at": str(row.get("ingested_at") or "") or None,
        "source": "fins_summary",
    }


def _fins_vintage_visible_at(event: Mapping[str, Any]) -> str:
    walls = [
        str(event.get(name) or "")
        for name in ("event_time", "available_at", "ingested_at")
        if str(event.get(name) or "")
    ]
    return max(walls, default="")


def _fins_effective_date(visible_at: str, cutoff: str) -> str:
    day = str(visible_at)[:10]
    if not day:
        return ""
    wall = morning_close_as_of(day) if cutoff == "morning_close" else close_as_of(day)
    if len(str(visible_at)) == 10 or str(visible_at) <= wall:
        return day
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def load_fins_events_from_sqlite(
    view: PersonalResearchDataView,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_summary events via one forward revision sweep."""
    bound = _require_view(view)
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    code_set = set(code_list) if code_list else None
    window_start = str(start or end or "")[:10]
    window_end = str(end or start or "")[:10]
    if not window_start or not window_end:
        raise ValueError("as_of is required (PIT has no latest default)")
    vintages: dict[str, list[dict[str, Any]]] = {}
    for page in bound.iter_revision_pages(
        dataset="fins_summary",
        codes=code_list,
        start=window_start,
        end=window_end,
        page_size=HISTORY_READ_PAGE_SIZE,
    ):
        for row in page:
            event = _fins_event_from_row(row)
            if event is None:
                continue
            code = str(event.pop("code"))
            if code_set is not None and code not in code_set:
                continue
            disc_no = str(event.pop("disc_no") or "")
            key = str(event.pop("natural_key") or "") or (
                f"{code}|{event['disc_date']}|{disc_no}"
            )
            event["_code"] = code
            event["_natural_key"] = key
            event["_decision_cutoff"] = bound.decision_cutoff
            vintages.setdefault(key, []).append(event)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for key, rows in vintages.items():
        rows.sort(
            key=lambda event: (
                _fins_vintage_visible_at(event),
                str(event.get("ingested_at") or ""),
            )
        )
        latest = dict(rows[-1])
        code = str(latest.pop("_code"))
        latest["_natural_key"] = key
        latest["_revision_vintages"] = tuple(
            {name: value for name, value in row.items() if name != "_code"}
            for row in rows
        )
        visible_at = _fins_vintage_visible_at(latest)
        latest["source_disc_date"] = latest.get("disc_date")
        latest["source_event_time"] = latest.get("event_time")
        latest["disc_date"] = _fins_effective_date(
            visible_at,
            str(latest.get("_decision_cutoff") or "morning_close"),
        )
        latest["event_time"] = visible_at or latest.get("event_time")
        by_code.setdefault(code, []).append(latest)
    for _code, events in by_code.items():
        events.sort(key=lambda e: (e["disc_date"], str(e.get("event_time") or "")))
        last_eps = None
        last_ta = None
        for ev in events:
            ev["prior_eps"] = last_eps
            ev["prior_ta"] = last_ta
            if ev.get("eps") is not None:
                last_eps = ev["eps"]
            if ev.get("ta") is not None:
                last_ta = ev["ta"]
    return by_code


def load_fins_earnings_date_from_sqlite(
    view: PersonalResearchDataView,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_earnings_date calendar. Missing PubDate uses SchDate."""
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    code_set = set(code_list) if code_list else None
    rows = [
        row
        for page in _dataset_pages(
            view,
            dataset="fins_earnings_date",
            codes=code_list,
            start=start,
            end=end,
        )
        for row in page
    ]
    chosen: dict[tuple[str, str], tuple[str, str, dict[str, Any]]] = {}
    for row in rows:
        event_time = row.get("event_time")
        pl = _payload_map(row.get("payload"))
        if pl is None:
            continue
        code = str(pl.get("Code") or "").strip()
        if not code or (code_set is not None and code not in code_set):
            continue
        pub = str(pl.get("PubDate") or "")[:10] or None
        sch = str(pl.get("SchDate") or "")[:10] or None
        disc = pub or sch or str(event_time or "")[:10]
        if not disc:
            continue
        available = str(row.get("available_at") or "")
        if not _visible_at(available, disc, "morning_close", event_time=str(row.get("event_time") or ""), decision_date=end or disc):
            continue
        ingested = str(row.get("ingested_at") or "")
        event = {
            "disc_date": disc,
            "pub_date": pub,
            "sch_date": sch,
            "eps": None,
            "feps": None,
            "bps": None,
            "prior_eps": None,
            "source": "fins_earnings_date",
            "event_time": str(event_time) if event_time else None,
            "fq_name": pl.get("FQName"),
        }
        previous = chosen.get((code, disc))
        if previous is None or (available, ingested) >= previous[:2]:
            chosen[(code, disc)] = (available, ingested, event)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for (code, _disc), (_a, _i, event) in chosen.items():
        by_code.setdefault(code, []).append(event)
    for _code, events in by_code.items():
        events.sort(key=lambda e: e["disc_date"])
    return by_code


def merge_event_calendars(
    fins_summary: Mapping[str, Sequence[Mapping[str, Any]]],
    earnings_date: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Thicken event calendar: fins_summary primary; earnings_date fills gaps."""
    out: dict[str, list[dict[str, Any]]] = {}
    codes = set(fins_summary.keys()) | set((earnings_date or {}).keys())
    for code in codes:
        by_date: dict[str, dict[str, Any]] = {}
        for ev in earnings_date.get(code, []) if earnings_date else []:
            d = str(ev.get("disc_date") or "")[:10]
            if not d:
                continue
            by_date[d] = dict(ev)
            by_date[d]["source"] = "fins_earnings_date"
        for ev in fins_summary.get(code, []) or []:
            d = str(ev.get("disc_date") or "")[:10]
            if not d:
                continue
            base = by_date.get(d, {})
            merged = dict(base)
            merged.update(dict(ev))
            merged["source"] = "fins_summary"
            if base.get("source") == "fins_earnings_date":
                merged["thickened_from_earnings_date"] = True
            by_date[d] = merged
        events = list(by_date.values())
        events.sort(key=lambda e: e["disc_date"])
        last_eps = None
        for ev in events:
            if ev.get("prior_eps") is None:
                ev["prior_eps"] = last_eps
            if ev.get("eps") is not None:
                last_eps = ev["eps"]
        out[str(code)] = events
    return out


def load_fins_latest_asof_map(
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Per code: sorted (disc_date, event) for as-of PIT lookup."""
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for code, events in events_by_code.items():
        pairs: list[tuple[str, dict[str, Any]]] = []
        for event in events:
            stream = event.get("_revision_vintages")
            revisions = (
                stream
                if isinstance(stream, (tuple, list)) and stream
                else (event,)
            )
            for raw in revisions:
                if not isinstance(raw, Mapping) or not raw.get("disc_date"):
                    continue
                vintage = dict(raw)
                visible_at = _fins_vintage_visible_at(vintage)
                if not visible_at:
                    visible_at = str(vintage["disc_date"])[:10]
                pairs.append((visible_at, vintage))
        pairs.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("_natural_key") or ""),
                str(item[1].get("ingested_at") or ""),
            )
        )
        out[str(code)] = pairs
    return out


def fins_asof(
    series: Sequence[tuple[str, dict[str, Any]]],
    date: str,
) -> dict[str, Any] | None:
    """Resolve each natural-key vintage at ``date``, then choose latest filing."""
    d = str(date)[:10]
    current: dict[str, dict[str, Any]] = {}
    for visible_at, raw in series:
        event = dict(raw)
        cutoff = str(event.get("_decision_cutoff") or "morning_close")
        decision_at = (
            morning_close_as_of(d)
            if cutoff == "morning_close"
            else close_as_of(d)
        )
        visible = str(visible_at)
        if len(visible) == 10:
            is_visible = visible <= d
        else:
            is_visible = visible <= decision_at
        if not is_visible:
            continue
        natural = str(event.get("_natural_key") or "") or (
            f"{event.get('disc_date')}|{event.get('event_time')}"
        )
        current[natural] = event
    if not current:
        return None
    ordered = sorted(
        current.values(),
        key=lambda event: (
            str(event.get("disc_date") or "")[:10],
            str(event.get("event_time") or ""),
            str(event.get("available_at") or ""),
            str(event.get("ingested_at") or ""),
        ),
    )
    hit = dict(ordered[-1])
    prior = ordered[-2] if len(ordered) > 1 else None
    hit["prior_eps"] = None if prior is None else prior.get("eps")
    hit["prior_ta"] = None if prior is None else prior.get("ta")
    for name in ("_revision_vintages", "_natural_key", "_decision_cutoff"):
        hit.pop(name, None)
    return hit
