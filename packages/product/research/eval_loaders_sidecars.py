"""Nky / opt225 / margin / repo / fins sidecar loaders. Skip missing. Never invent.

Public import remains ``research.eval_loaders``. Empty / missing → empty or None.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from features.class_signals import (
    DEFAULT_NKY_VOL_LONG_N,
    DEFAULT_NKY_VOL_SHORT_N,
    NKY_VOL_PROXY_NK225F,
    NKY_VOL_PROXY_TOPIX,
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    TRADING_DAYS_ANN,
)
from research.eval_loaders import (
    DEFAULT_BARS_MIRROR_DIR,
    _code_like,
    _code_of,
    _date_of,
    _event_time_filters,
    _fnum,
    _iter_ndjson,
    _open_ro,
    _payload_map,
    _period_year,
)
from research.eval_universe import DEFAULT_SQLITE
from research.unique_logic.constants import (
    FINS_SUMMARY_EQ_KEY,
    FINS_SUMMARY_EQAR_KEY,
    FINS_SUMMARY_OFFICIAL_KEYS,
    FINS_SUMMARY_TA_KEY,
)


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
    con: sqlite3.Connection, sql: str, params: Sequence[Any]
) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for _nk, event_time, payload in con.execute(sql, params):
        pl = _payload_map(payload)
        if pl is None:
            continue
        d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
        c = pl.get("C") if pl.get("C") is not None else pl.get("Close")
        if not d or c is None or c == "":
            continue
        try:
            out.append((d, float(c)))
        except (TypeError, ValueError):
            continue
    return out


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
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load TOPIX closes from indices_bars_daily_topix (prefer) or code 0000."""
    con = _open_ro(db_path)
    if con is None:
        return []
    try:
        filt, params = _event_time_filters(start, end)
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'indices_bars_daily_topix'"
            f"{filt} ORDER BY event_time ASC"
        )
        out = _index_close_pairs(con, sql, params)
        if out:
            return out
        sql2 = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'indices_bars_daily' "
            "AND (natural_key LIKE '%\"Code\":\"0000\"%' "
            "OR natural_key LIKE '%\"code\":\"0000\"%')"
            f"{filt} ORDER BY event_time ASC"
        )
        return _index_close_pairs(con, sql2, params)
    finally:
        con.close()


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


def load_topix_close_series_from_ndjson(
    path: str | Path,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load TOPIX closes from a local indices_bars_daily_topix ndjson mirror."""
    p = Path(path)
    if not p.is_file():
        return []
    p_start = str(start)[:10] if start else None
    p_end = str(end)[:10] if end else None
    by_date: dict[str, float] = {}
    for payload in _iter_ndjson(p, payload_or_row=True):
        d = str(payload.get("Date") or payload.get("date") or "")[:10]
        if not d:
            continue
        if p_start and d < p_start:
            continue
        if p_end and d > p_end:
            continue
        c = payload.get("C")
        if c is None:
            c = payload.get("Close") or payload.get("close")
        try:
            px = float(c)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if px > 0:
            by_date[d] = px
    return sorted(by_date.items(), key=lambda x: x[0])


def load_nky_vol_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
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

    nk_pairs: list[tuple[str, float]] = []
    if pref in {"ndjson_topix", "topix", "auto", "ndjson"}:
        topix_ndjson = (
            repo_root()
            / ".glm-logs"
            / "w0815ba_w60_long_multisignal"
            / "r2_mirror"
            / "indices_bars_daily_topix.ndjson"
        )
        nk_pairs = load_topix_close_series_from_ndjson(
            topix_ndjson, start=load_start, end=end
        )
    if (not nk_pairs) and pref in {
        "nk225f",
        "sqlite",
        "sqlite_topix",
        "sqlite_nk225f",
    }:
        nk_pairs = load_topix_close_series_from_sqlite(
            db_path, start=load_start, end=end
        )
    return build_nky_vol_series(
        nk_pairs,
        short_n=short_n,
        long_n=long_n,
        source=NKY_VOL_PROXY_TOPIX,
        dataset="indices_bars_daily_topix",
    )


def load_opt225_regime_bundle_for_eval(
    *,
    log_dir: str | Path | None = None,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
) -> dict[str, Any] | None:
    """Load cached options_225 series and build regime maps for factory/CF."""
    try:
        from research.options_225_vol_series import (
            DEFAULT_OPT225_LONG_N,
            DEFAULT_OPT225_SHORT_N,
            build_opt225_regime_bundle,
            load_opt225_series_cache,
        )
    except Exception:
        return None
    cache = load_opt225_series_cache(log_dir)
    if not cache:
        return None
    sn = int(short_n) if short_n else DEFAULT_OPT225_SHORT_N
    ln = int(long_n) if long_n else DEFAULT_OPT225_LONG_N
    return build_opt225_regime_bundle(
        cache.get("base_vol_series") or [],
        cache.get("atm_iv_series") or [],
        cache.get("spread_series"),
        skew_rows=cache.get("skew_series") or None,
        term_rows=cache.get("cm_term_series") or None,
        basevol_delta_rows=cache.get("basevol_delta_series") or None,
        short_n=sn,
        long_n=ln,
    )


def fins_summary_ta_eqar_stats(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Count TA / EqAR / Eq non-null rates in fins_summary payloads."""
    db = Path(db_path)
    out: dict[str, Any] = {
        "dataset": "fins_summary",
        "official_keys": dict(FINS_SUMMARY_OFFICIAL_KEYS),
        "n_rows": 0,
        "n_ta_nonnull": 0,
        "n_eqar_nonnull": 0,
        "n_eq_nonnull": 0,
        "ncta_nonnull": 0,
        "invent": False,
    }
    if not db.exists():
        out["error"] = "sqlite_missing"
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = "SELECT payload FROM jquants_records WHERE dataset = 'fins_summary'"
        if limit:
            sql += f" LIMIT {int(limit)}"
        n = n_ta = n_eqar = n_eq = n_ncta = 0
        for (payload,) in con.execute(sql):
            pl = _payload_map(payload)
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
    finally:
        con.close()
    return out


def repo_history_plane_status(
    db_path: str | Path = DEFAULT_SQLITE,
) -> dict[str, Any]:
    """Disclose sqlite history vs D1 hot tip vs PIT fail-closed."""
    db = Path(db_path)
    n = 0
    mn = mx = None
    tenors = 0
    missing = not db.is_file()
    if not missing:
        con = sqlite3.connect(str(db))
        try:
            n, mn, mx = con.execute(
                "SELECT COUNT(*), MIN(as_of_date), MAX(as_of_date) "
                "FROM jsda_repo_rates"
            ).fetchone()
            tenors = int(
                con.execute(
                    "SELECT COUNT(DISTINCT tenor) FROM jsda_repo_rates"
                ).fetchone()[0]
                or 0
            )
        except sqlite3.Error:
            n = 0
        finally:
            con.close()
    return {
        "dataset": "jsda_tokyo_repo_rates",
        "table": "jsda_repo_rates",
        "sqlite_rows": int(n or 0),
        "sqlite_min": mn,
        "sqlite_max": mx,
        "sqlite_tenors": int(tenors or 0),
        "sqlite_missing": missing,
        "d1_role": "hot_tip_only",
        "pit_path": "fail_closed_until_READY",
        "invent_complete": False,
        "ffill_applied": False,
    }


def load_repo_rows_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    as_of: str,
    start: str | None = None,
    end: str | None = None,
    tenor_contains: str | None = "overnight",
) -> list[dict[str, Any]]:
    """Load jsda_repo_rates rows from local SQLite with PIT available_at gate.

    ``as_of`` is required (keyword-only). SQL always applies
    ``available_at IS NOT NULL AND available_at <= as_of``.
    ``start`` / ``end`` bound ``as_of_date`` only (additive range, not a PIT
    substitute). Missing ``as_of`` / empty string raises.
    """
    as_of_s = str(as_of).strip() if as_of is not None else ""
    if not as_of_s:
        raise ValueError("as_of is required (PIT has no latest default)")
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        sql = (
            "SELECT as_of_date, tenor, rate_type, rate, available_at, event_time "
            "FROM jsda_repo_rates WHERE rate IS NOT NULL "
            "AND available_at IS NOT NULL AND available_at <= ?"
        )
        params: list[Any] = [as_of_s]
        if start:
            sql += " AND as_of_date >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND as_of_date <= ?"
            params.append(str(end)[:10])
        if tenor_contains:
            sql += " AND lower(tenor) LIKE ?"
            params.append(f"%{str(tenor_contains).lower()}%")
        sql += " ORDER BY as_of_date ASC"
        rows: list[dict[str, Any]] = []
        for as_of_date, tenor, rate_type, rate, available_at, event_time in con.execute(
            sql, params
        ):
            rows.append(
                {
                    "as_of_date": str(as_of_date)[:10],
                    "tenor": tenor,
                    "rate_type": rate_type,
                    "rate": float(rate) if rate is not None else None,
                    "available_at": available_at,
                    "event_time": event_time,
                }
            )
        return rows
    finally:
        con.close()


def load_repo_rows_all_tenors_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    as_of: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Load all JSDA Tokyo repo tenors (for curve-shape proxy). PIT-gated on as_of."""
    return load_repo_rows_from_sqlite(
        db_path, as_of=as_of, start=start, end=end, tenor_contains=None
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


def resolve_margin_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
) -> Path | None:
    """Map period_id → markets_margin_interest local ndjson if present."""
    d = Path(mirror_dir)
    year = _period_year(period_id)
    if year is None:
        return None
    for c in (
        d / f"markets_margin_interest_y{year}_q4.ndjson",
        d / f"markets_margin_interest_y{year}_full.ndjson",
    ):
        if c.exists():
            return c
    return None


def load_margin_ndjson(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load markets_margin_interest ndjson → ``{code: [(date, total_vol), ...]}``."""
    code_filter = {str(c).strip() for c in codes} if codes else None
    by_code: dict[str, dict[str, float]] = {}
    for payload in _iter_ndjson(path):
        code = _code_of(payload)
        date = _date_of(payload)
        if not code or not date:
            continue
        if code_filter is not None and code not in code_filter:
            continue
        total = _margin_total(payload)
        if total is None:
            continue
        by_code.setdefault(code, {})[date] = total
    return {code: sorted(dmap.items(), key=lambda x: x[0]) for code, dmap in by_code.items()}


def load_margin_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load margin interest levels from jquants_records (research offline)."""
    con = _open_ro(db_path)
    if con is None:
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    try:
        filt, params = _event_time_filters(start, end)
        like_sql, like_params = _code_like(code_list)
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_margin_interest'"
            f"{filt}{like_sql} ORDER BY event_time ASC"
        )
        params.extend(like_params)
        by_code: dict[str, dict[str, float]] = {}
        code_set = set(code_list) if code_list else None
        for _nk, event_time, payload in con.execute(sql, params):
            pl = _payload_map(payload)
            if pl is None:
                continue
            code = str(pl.get("Code") or "").strip()
            if not code or (code_set is not None and code not in code_set):
                continue
            date = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not date:
                continue
            total = _margin_total(pl)
            if total is None:
                continue
            by_code.setdefault(code, {})[date] = total
        return {
            c: sorted(dmap.items(), key=lambda x: x[0]) for c, dmap in by_code.items()
        }
    finally:
        con.close()


def load_short_ratio_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    section: str = "0050",
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load market-level short ratio for one S33 section → sorted (date, ratio)."""
    con = _open_ro(db_path)
    if con is None:
        return []
    try:
        filt, params = _event_time_filters(start, end)
        sql = (
            "SELECT event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_short_ratio' AND natural_key LIKE ?"
            f"{filt} ORDER BY event_time ASC"
        )
        params = [f'%"{section}"%', *params]
        out: dict[str, float] = {}
        for event_time, payload in con.execute(sql, params):
            pl = _payload_map(payload)
            if pl is None:
                continue
            date = str(pl.get("Date") or str(event_time or "")[:10])[:10]
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
        return sorted(out.items(), key=lambda x: x[0])
    finally:
        con.close()


def load_fins_events_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_summary disclosure events → ``{code: [event_dict, ...]}``."""
    con = _open_ro(db_path)
    if con is None:
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    try:
        cols = {
            r[1]
            for r in con.execute("PRAGMA table_info(jquants_records)").fetchall()
        }
        has_aa = "available_at" in cols
        aa_sel = ", available_at" if has_aa else ""
        filt, params = _event_time_filters(start, end)
        like_sql, like_params = _code_like(code_list)
        sql = (
            "SELECT natural_key, event_time, payload"
            f"{aa_sel} FROM jquants_records "
            "WHERE dataset = 'fins_summary'"
            f"{filt}{like_sql} ORDER BY event_time ASC"
        )
        params.extend(like_params)
        code_set = set(code_list) if code_list else None
        by_code: dict[str, list[dict[str, Any]]] = {}
        for row in con.execute(sql, params):
            if has_aa:
                _nk, event_time, payload, row_aa = row
            else:
                _nk, event_time, payload = row
                row_aa = None
            pl = _payload_map(payload)
            if pl is None:
                continue
            code = str(pl.get("Code") or "").strip()
            if not code or (code_set is not None and code not in code_set):
                continue
            disc = str(
                pl.get("DiscDate") or pl.get("DisclosedDate") or str(event_time or "")[:10]
            )[:10]
            if not disc:
                continue
            disc_time = pl.get("DiscTime") or pl.get("DisclosedTime")
            if disc_time is not None:
                disc_time = str(disc_time).strip() or None
            eq = _fnum(pl.get(FINS_SUMMARY_EQ_KEY))
            if eq is None:
                eq = _fnum(pl.get("ShEq"))
            by_code.setdefault(code, []).append(
                {
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
                    "available_at": str(row_aa) if row_aa else None,
                    "source": "fins_summary",
                }
            )
        for _code, events in by_code.items():
            events.sort(key=lambda e: e["disc_date"])
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
    finally:
        con.close()


def load_fins_earnings_date_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_earnings_date calendar. Missing PubDate uses SchDate."""
    con = _open_ro(db_path)
    if con is None:
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    try:
        filt, params = _event_time_filters(start, end)
        like_sql, like_params = _code_like(code_list)
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'fins_earnings_date'"
            f"{filt}{like_sql} ORDER BY event_time ASC"
        )
        params.extend(like_params)
        code_set = set(code_list) if code_list else None
        by_code: dict[str, list[dict[str, Any]]] = {}
        for _nk, event_time, payload in con.execute(sql, params):
            pl = _payload_map(payload)
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
            by_code.setdefault(code, []).append(
                {
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
            )
        for _code, events in by_code.items():
            events.sort(key=lambda e: e["disc_date"])
        return by_code
    finally:
        con.close()


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
        pairs = [
            (str(e["disc_date"])[:10], dict(e))
            for e in events
            if e.get("disc_date")
        ]
        pairs.sort(key=lambda x: x[0])
        out[str(code)] = pairs
    return out


def fins_asof(
    series: Sequence[tuple[str, dict[str, Any]]],
    date: str,
) -> dict[str, Any] | None:
    """Last fins event with disc_date <= date (PIT by event date; disclosed)."""
    d = str(date)[:10]
    hit = None
    for ed, ev in series:
        if ed <= d:
            hit = ev
        else:
            break
    return hit
