"""Bar / index / options loaders for research eval. Skip missing. Never invent.

CF staging imports these instead of the class_hyp_eval loader block.
No ffill. Empty / missing inputs return empty or None.
"""
from __future__ import annotations

import json
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
    TRADING_DAYS_ANN,
)
from research.eval_universe import DEFAULT_SQLITE

DEFAULT_BARS_MIRROR_DIR: Path = (
    repo_root() / ".glm-logs" / "w0815bd_w63_multiyear" / "r2_mirror"
)
DEFAULT_BARS_FULL_MIRROR_DIR: Path = (
    repo_root() / ".glm-logs" / "w0815be_w64_cost_full" / "r2_mirror"
)


def load_bars_ndjson_rich(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
    max_days: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load bars with close + liquidity fields for W80 cost modulation.

    Each value: ``(date, {close, Va, Vo, AdjC, AdjVo, Code, Date})``.
    """
    p = Path(path)
    code_filter = {str(c).strip() for c in codes} if codes else None
    p_start = str(period_start)[:10] if period_start else None
    p_end = str(period_end)[:10] if period_end else None
    by_code: dict[str, dict[str, dict[str, Any]]] = {}
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            if not isinstance(payload, Mapping):
                continue
            code = str(payload.get("Code") or payload.get("code") or "").strip()
            date = str(payload.get("Date") or payload.get("date") or "")[:10]
            if not code or not date:
                continue
            if code_filter is not None and code not in code_filter:
                continue
            if p_start and date < p_start:
                continue
            if p_end and date > p_end:
                continue
            close = payload.get("C")
            if close is None:
                close = payload.get("Close") or payload.get("AdjC")
            try:
                c = float(close)
            except (TypeError, ValueError):
                continue
            rec = {
                "close": c,
                "C": c,
                "Close": c,
                "Code": code,
                "Date": date,
                "date": date,
                "Va": payload.get("Va") or payload.get("AVa") or payload.get("MVa"),
                "Vo": payload.get("Vo") or payload.get("AVo") or payload.get("MVo"),
                "AdjC": payload.get("AdjC") or payload.get("AAdjC"),
                "AdjVo": payload.get("AdjVo") or payload.get("AAdjVo"),
            }
            by_code.setdefault(code, {})[date] = rec

    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for code, dmap in by_code.items():
        pairs = sorted(dmap.items(), key=lambda x: x[0])
        if max_days is not None and len(pairs) > int(max_days):
            pairs = pairs[-int(max_days) :]
        out[code] = pairs
    return out


def bars_rich_to_close_panel(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> dict[str, list[tuple[str, float]]]:
    """Strip rich bars to (date, close) panel."""
    return {
        str(c): [(d, float(r["close"])) for d, r in pairs]
        for c, pairs in rich.items()
    }


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
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out: list[tuple[str, float]] = []
        # Prefer dedicated TOPIX dataset
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'indices_bars_daily_topix'"
        )
        params: list[Any] = []
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        for _nk, event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            c = pl.get("C") if pl.get("C") is not None else pl.get("Close")
            if not d or c is None or c == "":
                continue
            try:
                out.append((d, float(c)))
            except (TypeError, ValueError):
                continue
        if out:
            return out
        # Fallback: indices_bars_daily code 0000 (TOPIX)
        sql2 = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'indices_bars_daily' "
            "AND (natural_key LIKE '%\"Code\":\"0000\"%' OR natural_key LIKE '%\"code\":\"0000\"%')"
        )
        params2: list[Any] = []
        if start:
            sql2 += " AND event_time >= ?"
            params2.append(str(start)[:10])
        if end:
            sql2 += " AND event_time <= ?"
            params2.append(str(end)[:10] + "T23:59:59")
        sql2 += " ORDER BY event_time ASC"
        for _nk, event_time, payload in con.execute(sql2, params2):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
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
    finally:
        con.close()


def load_nk225f_front_close_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Continuous front Nikkei 225 futures closes (max open interest per day).

    Cash Nikkei average is not in indices_bars_daily; NK225F front is the
    primary price proxy for Nikkei realized-vol construction.
    """
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'derivatives_bars_daily_futures' "
            "AND payload LIKE '%\"ProdCat\":\"NK225F\"%'"
        )
        params: list[Any] = []
        if start:
            # lookback buffer for long RV window
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        by_date: dict[str, list[tuple[float, float]]] = {}
        for _nk, event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            if str(pl.get("ProdCat") or "") != "NK225F":
                continue
            d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not d:
                continue
            px = pl.get("C")
            if px is None or px == "" or float(px or 0) <= 0:
                px = pl.get("Settle")
            if px is None or px == "" or float(px or 0) <= 0:
                px = pl.get("AC")
            try:
                px_f = float(px) if px is not None and px != "" else 0.0
            except (TypeError, ValueError):
                continue
            if px_f <= 0:
                continue
            try:
                oi = float(pl.get("OI") or 0.0)
            except (TypeError, ValueError):
                oi = 0.0
            by_date.setdefault(d, []).append((oi, px_f))
        out: list[tuple[str, float]] = []
        for d in sorted(by_date.keys()):
            best = max(by_date[d], key=lambda x: x[0])
            out.append((d, best[1]))
        return out
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
    """Build date-keyed short/long annualized realized vol + ratio.

    Gaps disclosed; no invent/ffill of missing sessions.
    """
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
    # de-dup last wins
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
        "proxy_note": (
            "Cash Nikkei not in indices_bars_daily. Prefer NK225F front "
            "realized; TOPIX fallback. NKVIF is implied-vol futures (optional)."
        ),
        "short_n": sn,
        "long_n": ln,
        "annualization": f"sample_stdev * sqrt({TRADING_DAYS_ANN})",
        "closes_by_date": dict(sorted(by_d.items())),
        "rv_short_by_date": dict(sorted(short_by.items())),
        "rv_long_by_date": dict(sorted(long_by.items())),
        "rv_ratio_by_date": dict(sorted(ratio_by.items())),
        # abs-level uses short window by default
        "rv_abs_by_date": dict(sorted(short_by.items())),
        "n_close_obs": len(by_d),
        "n_obs_short": len(short_by),
        "n_obs_long": len(long_by),
        "n_obs_ratio": len(ratio_by),
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
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload") if isinstance(row, Mapping) else None
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            if not isinstance(payload, Mapping):
                payload = row if isinstance(row, Mapping) else None
            if not isinstance(payload, Mapping):
                continue
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
    """Load Nikkei-proxy closes and build short/long realized-vol series.

    Priority (wall-clock safe):
      1. Local TOPIX ndjson mirror (fast, multi-year COMPLETE-backed)
      2. Optional sqlite NK225F / TOPIX (slow on full D1 dump — skipped by default)
    Prefer=ndjson_topix is the default for factory/CF staging.
    """
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
    source = NKY_VOL_PROXY_TOPIX
    dataset = "indices_bars_daily_topix"

    # Fast path: local TOPIX ndjson (W60 multi-signal mirror).
    if pref in {"ndjson_topix", "topix", "auto", "ndjson"}:
        topix_ndjson = (
            repo_root()
            / ".glm-logs"
            / "w0815ba_w60_long_multisignal"
            / "r2_mirror"
            / "indices_bars_daily_topix.ndjson"
        )
        if topix_ndjson.is_file():
            nk_pairs = load_topix_close_series_from_ndjson(
                topix_ndjson, start=load_start, end=end
            )
            if nk_pairs:
                source = NKY_VOL_PROXY_TOPIX
                dataset = "indices_bars_daily_topix"
                return build_nky_vol_series(
                    nk_pairs,
                    short_n=short_n,
                    long_n=long_n,
                    source=source,
                    dataset=dataset,
                )

    # Slow optional path: sqlite (only when explicitly requested).
    if pref in {"nk225f", "sqlite", "sqlite_nk225f"}:
        nk_pairs = load_nk225f_front_close_series_from_sqlite(
            db_path, start=load_start, end=end
        )
        source = NKY_VOL_PROXY_NK225F
        dataset = "derivatives_bars_daily_futures"
    if len(nk_pairs) < max(int(long_n) + 2, 30) and pref in {
        "nk225f",
        "sqlite",
        "sqlite_topix",
        "sqlite_nk225f",
    }:
        topix = load_topix_close_series_from_sqlite(
            db_path, start=load_start, end=end
        )
        if len(topix) > len(nk_pairs):
            nk_pairs = topix
            source = NKY_VOL_PROXY_TOPIX
            dataset = "indices_bars_daily_topix"
    return build_nky_vol_series(
        nk_pairs, short_n=short_n, long_n=long_n, source=source, dataset=dataset
    )


def _period_year(period_id: str) -> int | None:
    for token in str(period_id).split("_"):
        if token.startswith("y") and token[1:].isdigit():
            return int(token[1:])
    if str(period_id).isdigit():
        return int(period_id)
    return None


def resolve_bars_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
    prefer_full: bool = True,
) -> Path | None:
    """Map period_id like y2015_q4 / y2015_full → local ndjson mirror path.

    W80: prefer full-year W64 mirrors when ``prefer_full`` and period is full
    or period_id contains ``full``.
    """
    d = Path(mirror_dir)
    year = _period_year(period_id)
    if year is None:
        return None
    pid = str(period_id).lower()
    want_full = prefer_full and ("full" in pid or not pid.endswith("q4"))
    full_path = (
        DEFAULT_BARS_FULL_MIRROR_DIR / f"equities_bars_daily_y{year}_full.ndjson"
    )
    q4_path = d / f"equities_bars_daily_y{year}_q4.ndjson"
    candidates: list[Path] = []
    if want_full:
        candidates.extend(
            [
                full_path,
                d / f"equities_bars_daily_y{year}_full.ndjson",
                q4_path,
            ]
        )
    else:
        candidates.extend(
            [
                q4_path,
                full_path,
                d / f"equities_bars_daily_y{year}_full.ndjson",
            ]
        )
    for c in candidates:
        if c.exists():
            return c
    return None


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


__all__ = [
    "DEFAULT_BARS_FULL_MIRROR_DIR",
    "DEFAULT_BARS_MIRROR_DIR",
    "bars_rich_to_close_panel",
    "build_nky_vol_series",
    "load_bars_ndjson_rich",
    "load_nk225f_front_close_series_from_sqlite",
    "load_nky_vol_series_from_sqlite",
    "load_opt225_regime_bundle_for_eval",
    "load_topix_close_series_from_ndjson",
    "load_topix_close_series_from_sqlite",
    "resolve_bars_path",
]
