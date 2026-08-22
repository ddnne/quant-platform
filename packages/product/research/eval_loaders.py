"""Bar / index / options loaders for research eval. Skip missing. Never invent.

CF staging imports this module. Offline bar eval is ``research.offline.bar_eval``.
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
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    TRADING_DAYS_ANN,
)
from research.eval_universe import DEFAULT_SQLITE
from research.unique_logic.constants import (
    FINS_SUMMARY_EQ_KEY,
    FINS_SUMMARY_EQAR_KEY,
    FINS_SUMMARY_OFFICIAL_KEYS,
    FINS_SUMMARY_TA_KEY,
)

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


def load_bars_ndjson(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
    max_days: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load equities_bars_daily ndjson → ``{code: [(date, close), ...]}`` sorted."""
    rich = load_bars_ndjson_rich(
        path,
        codes=codes,
        max_days=max_days,
        period_start=period_start,
        period_end=period_end,
    )
    return {c: [(d, float(r["close"])) for d, r in pairs] for c, pairs in rich.items()}


def fins_summary_ta_eqar_stats(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Count TA / EqAR / Eq non-null rates in fins_summary payloads. No invent."""
    db = Path(db_path)
    out: dict[str, Any] = {
        "dataset": "fins_summary",
        "official_keys": dict(FINS_SUMMARY_OFFICIAL_KEYS),
        "n_rows": 0,
        "n_ta_nonnull": 0,
        "n_eqar_nonnull": 0,
        "n_eq_nonnull": 0,
        "ncta_nonnull": 0,
        "sample_ta": [],
        "sample_eqar": [],
        "invent": False,
        "note": (
            "NCTA is a non-consolidated alias and is sparse. Official v2 "
            "summary uses TA (total assets) and EqAR (equity/assets)."
        ),
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
        samples_ta: list[dict[str, Any]] = []
        samples_eqar: list[dict[str, Any]] = []
        for (payload,) in con.execute(sql):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            n += 1

            def _ok(key: str) -> bool:
                v = pl.get(key)
                if v in (None, ""):
                    return False
                try:
                    float(v)
                    return True
                except (TypeError, ValueError):
                    return False

            if _ok(FINS_SUMMARY_TA_KEY):
                n_ta += 1
                if len(samples_ta) < 3:
                    samples_ta.append(
                        {
                            "code": pl.get("Code"),
                            "disc": pl.get("DiscDate"),
                            "ta": pl.get(FINS_SUMMARY_TA_KEY),
                            "doctype": pl.get("DocType"),
                        }
                    )
            if _ok(FINS_SUMMARY_EQAR_KEY):
                n_eqar += 1
                if len(samples_eqar) < 3:
                    samples_eqar.append(
                        {
                            "code": pl.get("Code"),
                            "disc": pl.get("DiscDate"),
                            "eq_ar": pl.get(FINS_SUMMARY_EQAR_KEY),
                            "doctype": pl.get("DocType"),
                        }
                    )
            if _ok(FINS_SUMMARY_EQ_KEY):
                n_eq += 1
            if _ok("NCTA"):
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
                "sample_ta": samples_ta,
                "sample_eqar": samples_eqar,
            }
        )
    finally:
        con.close()
    return out


def collect_liquidity_bar_rows(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    """Flatten rich bars to rows for ``compute_liquidity_proxy_from_bars``."""
    rows: list[dict[str, Any]] = []
    for code, pairs in rich.items():
        for d, r in pairs:
            row = dict(r)
            row.setdefault("Code", code)
            row.setdefault("Date", d)
            rows.append(row)
    return rows


def repo_history_plane_status(
    db_path: str | Path = DEFAULT_SQLITE,
) -> dict[str, Any]:
    """Disclose sqlite history vs D1 hot tip vs PIT fail-closed.

    Coverage V2 COMPLETE is receipt-owned (quant-mcp). This helper does not
    invent COMPLETE, does not ffill, and does not declare READY.
    """
    db = Path(db_path)
    n = 0
    mn = mx = None
    tenors = 0
    if db.exists():
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
        "d1_role": "hot_tip_only",
        "pit_path": "fail_closed_until_READY",
        "research_loader": "load_repo_rows_all_tenors_from_sqlite",
        "invent_complete": False,
        "ffill_applied": False,
        "note": (
            "D1 jsda_repo_rates is hot tip (~days). Historical eval reads "
            "this sqlite / R2. PIT get_jsda_repo_rates stays fail-closed "
            "while production READY is undeclared."
        ),
    }


def load_repo_rows_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
    tenor_contains: str | None = "overnight",
) -> list[dict[str, Any]]:
    """Load jsda_repo_rates rows from local SQLite (research offline path).

    Not the PIT path. PIT ``get_jsda_repo_rates`` is fail-closed until READY.
    D1 holds hot tip only; this sqlite holds the COMPLETE time-series history.
    """
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        sql = (
            "SELECT as_of_date, tenor, rate_type, rate, available_at, event_time "
            "FROM jsda_repo_rates WHERE rate IS NOT NULL"
        )
        params: list[Any] = []
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
        cur = con.execute(sql, params)
        rows: list[dict[str, Any]] = []
        for as_of_date, tenor, rate_type, rate, available_at, event_time in cur:
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
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Load all JSDA Tokyo repo tenors (for curve-shape proxy; no invent)."""
    return load_repo_rows_from_sqlite(
        db_path, start=start, end=end, tenor_contains=None
    )


def build_repo_curve_series(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    short_tenor: str = REPO_CURVE_SHORT_TENOR,
    long_tenor: str = REPO_CURVE_LONG_TENOR,
) -> dict[str, Any]:
    """Build date-keyed short/long rates + spread from multi-tenor rows.

    Curve definition (documented):
    ``spread[d] = rate(long_tenor, d) − rate(short_tenor, d)``.
    Only observed JSDA repo tenors; missing either leg → gap (no invent/ffill).
    This is a **funding term-structure proxy**, not a sovereign JGB/OIS curve.
    """
    by_date_tenor: dict[str, dict[str, float]] = {}
    for raw in rows or []:
        d = str(raw.get("as_of_date") or raw.get("date") or "")[:10]
        if not d or len(d) < 10:
            continue
        t = str(raw.get("tenor") or "")
        rate = raw.get("rate")
        if rate is None or rate == "":
            continue
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            continue
        by_date_tenor.setdefault(d, {})[t] = rate_f

    short_by: dict[str, float] = {}
    long_by: dict[str, float] = {}
    spread_by: dict[str, float] = {}
    gap_dates: list[str] = []
    for d, tenors in sorted(by_date_tenor.items()):
        s = tenors.get(short_tenor)
        lo = tenors.get(long_tenor)
        if s is not None:
            short_by[d] = s
        if lo is not None:
            long_by[d] = lo
        if s is not None and lo is not None:
            spread_by[d] = lo - s
        else:
            gap_dates.append(d)

    return {
        "kind": "repo_curve_series",
        "dataset": "jsda_tokyo_repo_rates",
        "short_tenor": short_tenor,
        "long_tenor": long_tenor,
        "definition": "spread = long_tenor_rate - short_tenor_rate (same as_of_date)",
        "note": (
            "Funding term-structure proxy from JSDA Tokyo repo tenors only. "
            "Not JGB/OIS. Gaps disclosed; never ffilled or invented."
        ),
        "short_rates_by_date": dict(sorted(short_by.items())),
        "long_rates_by_date": dict(sorted(long_by.items())),
        "spread_by_date": dict(sorted(spread_by.items())),
        # Alias used by rate-level path when overnight preferred
        "rates_by_date": dict(sorted(short_by.items())),
        "n_obs_short": len(short_by),
        "n_obs_long": len(long_by),
        "n_obs_spread": len(spread_by),
        "n_gap_either_leg": len(gap_dates),
        "gap_dates_sample": gap_dates[:20],
        "ffill_applied": False,
        "invent_fill": False,
        "tenors_observed": sorted(
            {t for m in by_date_tenor.values() for t in m.keys()}
        ),
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
    candidates = [
        d / f"markets_margin_interest_y{year}_q4.ndjson",
        d / f"markets_margin_interest_y{year}_full.ndjson",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_margin_ndjson(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load markets_margin_interest ndjson → ``{code: [(date, total_vol), ...]}``.

    total_vol = LongVol + ShrtVol when both present, else LongVol or ShrtVol.
    """
    p = Path(path)
    code_filter = {str(c).strip() for c in codes} if codes else None
    by_code: dict[str, dict[str, float]] = {}
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
            long_v = payload.get("LongVol")
            shrt_v = payload.get("ShrtVol")
            total = None
            try:
                if long_v is not None and shrt_v is not None:
                    total = float(long_v) + float(shrt_v)
                elif long_v is not None:
                    total = float(long_v)
                elif shrt_v is not None:
                    total = float(shrt_v)
            except (TypeError, ValueError):
                continue
            if total is None:
                continue
            by_code.setdefault(code, {})[date] = total
    out: dict[str, list[tuple[str, float]]] = {}
    for code, dmap in by_code.items():
        out[code] = sorted(dmap.items(), key=lambda x: x[0])
    return out


def load_margin_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load margin interest levels from jquants_records (research offline)."""
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_margin_interest'"
        )
        params: list[Any] = []
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        if code_list:
            # natural_key is JSON {"Code":"...","Date":"..."} — LIKE filter
            clauses = " OR ".join(["natural_key LIKE ?" for _ in code_list])
            sql += f" AND ({clauses})"
            params.extend([f'%"{c}"%' for c in code_list])
        sql += " ORDER BY event_time ASC"
        cur = con.execute(sql, params)
        by_code: dict[str, dict[str, float]] = {}
        code_set = set(code_list) if code_list else None
        for natural_key, event_time, payload in cur:
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            code = str(pl.get("Code") or "").strip()
            if not code:
                continue
            if code_set is not None and code not in code_set:
                continue
            date = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not date:
                continue
            long_v = pl.get("LongVol")
            shrt_v = pl.get("ShrtVol")
            try:
                if long_v is not None and shrt_v is not None:
                    total = float(long_v) + float(shrt_v)
                elif long_v is not None:
                    total = float(long_v)
                elif shrt_v is not None:
                    total = float(shrt_v)
                else:
                    continue
            except (TypeError, ValueError):
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
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_short_ratio' AND natural_key LIKE ?"
        )
        params: list[Any] = [f'%"{section}"%']
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        out: dict[str, float] = {}
        for event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
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


def load_fins_earnings_date_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_earnings_date calendar → ``{code: [event_dict, ...]}``.

    Event keys: disc_date (PubDate prefer, else SchDate), sch_date, pub_date,
    source=fins_earnings_date. No invent; missing PubDate uses SchDate.
    """
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'fins_earnings_date'"
        )
        params: list[Any] = []
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        if code_list:
            clauses = " OR ".join(["natural_key LIKE ?" for _ in code_list])
            sql += f" AND ({clauses})"
            params.extend([f'%"{c}"%' for c in code_list])
        sql += " ORDER BY event_time ASC"
        code_set = set(code_list) if code_list else None
        by_code: dict[str, list[dict[str, Any]]] = {}
        for _nk, event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            code = str(pl.get("Code") or "").strip()
            if not code:
                continue
            if code_set is not None and code not in code_set:
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
        for code, events in by_code.items():
            events.sort(key=lambda e: e["disc_date"])
        return by_code
    finally:
        con.close()


def merge_event_calendars(
    fins_summary: Mapping[str, Sequence[Mapping[str, Any]]],
    earnings_date: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Thicken event calendar: fins_summary primary; earnings_date fills gaps.

    Same (code, disc_date) prefers fins_summary (has EPS/FEPS for surprise).
    Earnings-only dates enter with null surprise (skipped by scoring unless
    later joined). Disclosed; no invent of surprise.
    """
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
        # re-attach prior_eps from fins_summary eps chain
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


def momentum_series(
    closes: Sequence[tuple[str, float]],
    *,
    n: int,
) -> list[tuple[str, float | None]]:
    """Per-date momentum_n from sorted (date, close) pairs."""
    n_i = int(n)
    out: list[tuple[str, float | None]] = []
    for i, (d, _) in enumerate(closes):
        if i < n_i:
            out.append((d, None))
            continue
        base = closes[i - n_i][1]
        last = closes[i][1]
        if base == 0:
            out.append((d, None))
        else:
            out.append((d, (last - base) / base))
    return out


__all__ = [
    "DEFAULT_BARS_FULL_MIRROR_DIR",
    "DEFAULT_BARS_MIRROR_DIR",
    "bars_rich_to_close_panel",
    "build_nky_vol_series",
    "build_repo_curve_series",
    "collect_liquidity_bar_rows",
    "fins_asof",
    "fins_summary_ta_eqar_stats",
    "load_bars_ndjson",
    "load_bars_ndjson_rich",
    "load_fins_earnings_date_from_sqlite",
    "load_fins_latest_asof_map",
    "load_margin_from_sqlite",
    "load_margin_ndjson",
    "load_nk225f_front_close_series_from_sqlite",
    "load_nky_vol_series_from_sqlite",
    "load_opt225_regime_bundle_for_eval",
    "load_repo_rows_all_tenors_from_sqlite",
    "load_repo_rows_from_sqlite",
    "load_short_ratio_series_from_sqlite",
    "load_topix_close_series_from_ndjson",
    "load_topix_close_series_from_sqlite",
    "merge_event_calendars",
    "momentum_series",
    "repo_history_plane_status",
    "resolve_bars_path",
    "resolve_margin_path",
]
