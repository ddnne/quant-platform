"""ADV-ranked eval universe. Skip missing bars/TA/EqAR. Never head-N.

Empty pool returns []. No invent.

Bar / sidecar loaders live in eval_loaders (bars/nky/opt225/margin/repo);
shims here re-export those bodies.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.eval_tracks import UNIVERSE_SELECT_ADV
from research.unique_logic.constants import (
    FINS_SUMMARY_EQ_KEY,
    FINS_SUMMARY_EQAR_KEY,
    FINS_SUMMARY_TA_KEY,
)

DEFAULT_SQLITE: Path = repo_root() / "data" / "structured" / "ingestion.sqlite"

# Ranked pool for ADV/fins selection. Not a head-N list. Production
# panels use select_eval_universe (skip missing, no invent).
EVAL_UNIVERSE_POOL: tuple[str, ...] = (
    "13010",
    "72030",
    "67580",
    "99840",
    "68610",
    "40630",
    "65010",
    "80350",
    "45020",
    "94320",
    "72670",
    "77510",
    "69020",
    "63670",
    "60980",
    "79740",
    "69810",
    "45680",
    "80010",
    "80020",
    "80580",
    "94330",
    "29140",
    "33820",
    "46610",
    "49010",
    "51080",
    "54010",
    "57130",
    "65030",
    "62730",
    "63010",
    "83060",
    "72010",
    "72690",
    "67020",
    "67520",
    "69520",
    "77310",
    "84110",
    "86010",
    "90200",
    "91010",
    "25020",
    "34020",
    "45190",
    "54060",
    "64710",
    "88020",
    "95030",
    "28020",
    "34070",
    "40040",
    "41880",
    "44520",
    "45030",
    "49020",
    "50200",
    "54110",
    "58020",
    "63260",
    "64720",
    "69540",
    "72020",
    "72700",
    "77330",
    "77520",
    "78320",
    "83080",
    "83160",
    "85910",
    "86040",
    "86300",
    "87250",
    "87500",
    "87660",
    "88010",
    "88300",
    "92020",
    "95310",
    "79120",
    "69880",
    "34010",
    "34050",
    "41830",
    "18010",
    "18020",
    "18120",
    "19250",
    "19280",
    "19630",
    "20020",
    "22690",
    "22820",
    "25010",
    "25310",
    "28010",
    "90050",
    "90210",
    "95320",
    "70110",
    "72050",
    "72610",
    "73090",
    "80530",
    "82670",
    "86970",
    "90070",
    "90220",
    "91040",
    "91070",
    "95020",
    "95130",
    "57110",
    "63020",
    "65020",
    "67010",
    "67620",
    "68410",
    "70120",
    "77350",
    "79510",
    "80320",
    "82520",
    "83090",
    "84180",
    "84730",
    "85930",
    "86980",
    "87290",
)
UNIVERSE_SELECT_RULE: str = UNIVERSE_SELECT_ADV
UNIVERSE_MIN_BAR_DAYS: int = 40
# One TA/EqAR print is enough to keep a name. Requiring 4 in a 10-month
# window collapsed the pool to quarterly-only names (~7). Skip zero; no invent.
UNIVERSE_MIN_FINS_TA: int = 1
UNIVERSE_MIN_FINS_EQAR: int = 1


def rank_eval_codes(
    scored: Sequence[Mapping[str, Any]],
    *,
    max_codes: int,
    min_bar_days: int = UNIVERSE_MIN_BAR_DAYS,
    min_fins_ta: int = UNIVERSE_MIN_FINS_TA,
    min_fins_eqar: int = UNIVERSE_MIN_FINS_EQAR,
) -> list[str]:
    """Rank by ADV; skip missing bars/TA/EqAR. No invent, not list-order."""
    rows: list[tuple[float, str]] = []
    for raw in scored:
        code = str(raw.get("code") or "").strip()
        if not code:
            continue
        try:
            adv = float(raw.get("adv"))
        except (TypeError, ValueError):
            continue
        if adv <= 0:
            continue
        try:
            n_bars = int(raw.get("n_bars") or 0)
            n_ta = int(raw.get("n_ta") or 0)
            n_eqar = int(raw.get("n_eqar") or 0)
        except (TypeError, ValueError):
            continue
        if n_bars < int(min_bar_days):
            continue
        if n_ta < int(min_fins_ta) or n_eqar < int(min_fins_eqar):
            continue
        rows.append((adv, code))
    rows.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _adv, code in rows:
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
        if len(out) >= int(max_codes):
            break
    return out


def load_bars_from_sqlite_rich(
    *,
    codes: Sequence[str],
    period_start: str,
    period_end: str,
    db_path: str | Path = DEFAULT_SQLITE,
    max_days: int | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load extra names from sqlite ``jquants_records`` via PK range per code.

    Local ndjson mirrors are a 30-name shard. Missing requested codes are
    filled from COMPLETE-backed sqlite (no invent). Empty code → omitted.
    """
    db = Path(db_path)
    want = [str(c).strip() for c in codes if str(c).strip()]
    if not db.exists() or not want:
        return {}
    p0 = str(period_start)[:10]
    p1 = str(period_end)[:10]
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT payload FROM jquants_records "
            "WHERE source = 'jquants' AND dataset = 'equities_bars_daily' "
            "AND natural_key >= ? AND natural_key <= ?"
        )
        for code in want:
            lo = json.dumps({"Code": code, "Date": p0}, separators=(",", ":"))
            hi = json.dumps({"Code": code, "Date": p1 + "~"}, separators=(",", ":"))
            dmap: dict[str, dict[str, Any]] = {}
            for (payload,) in con.execute(sql, (lo, hi)):
                try:
                    pl = json.loads(payload) if isinstance(payload, str) else payload
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(pl, Mapping):
                    continue
                date = str(pl.get("Date") or pl.get("date") or "")[:10]
                if not date or date < p0 or date > p1:
                    continue
                close = pl.get("C")
                if close is None:
                    close = pl.get("Close") or pl.get("AdjC") or pl.get("AAdjC")
                try:
                    c = float(close)
                except (TypeError, ValueError):
                    continue
                dmap[date] = {
                    "close": c,
                    "C": c,
                    "Close": c,
                    "Code": code,
                    "Date": date,
                    "date": date,
                    "Va": pl.get("Va") or pl.get("AVa") or pl.get("MVa"),
                    "Vo": pl.get("Vo") or pl.get("AVo") or pl.get("MVo"),
                    "AdjC": pl.get("AdjC") or pl.get("AAdjC"),
                    "AdjVo": pl.get("AdjVo") or pl.get("AAdjVo"),
                }
            if not dmap:
                continue
            pairs = sorted(dmap.items(), key=lambda x: x[0])
            if max_days is not None and len(pairs) > int(max_days):
                pairs = pairs[-int(max_days) :]
            out[code] = pairs
    finally:
        con.close()
    return out


def load_fins_events_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_summary disclosure events → ``{code: [event_dict, ...]}``.

    Each event: disc_date, disc_time, eps, feps, bps, prior_eps, event_time,
    available_at (row envelope when selected). DiscTime never invented.
    """
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        # Prefer available_at when column present (PIT envelope).
        cols = {
            r[1]
            for r in con.execute("PRAGMA table_info(jquants_records)").fetchall()
        }
        has_aa = "available_at" in cols
        aa_sel = ", available_at" if has_aa else ""
        sql = (
            "SELECT natural_key, event_time, payload"
            f"{aa_sel} FROM jquants_records "
            "WHERE dataset = 'fins_summary'"
        )
        params: list[Any] = []
        if start:
            # include a lookback buffer for prior EPS
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
        for row in con.execute(sql, params):
            if has_aa:
                _nk, event_time, payload, row_aa = row
            else:
                _nk, event_time, payload = row
                row_aa = None
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
            disc = str(pl.get("DiscDate") or pl.get("DisclosedDate") or str(event_time or "")[:10])[:10]
            if not disc:
                continue
            disc_time = pl.get("DiscTime") or pl.get("DisclosedTime")
            if disc_time is not None:
                disc_time = str(disc_time).strip() or None

            def _f(key: str) -> float | None:
                v = pl.get(key)
                if v is None or v == "":
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            by_code.setdefault(code, []).append(
                {
                    "disc_date": disc,
                    "disc_time": disc_time,
                    "eps": _f("EPS"),
                    "feps": _f("FEPS"),
                    "bps": _f("BPS"),
                    "roe": _f("ROE"),
                    "div_ann": _f("DivAnn"),
                    "np": _f("NP"),
                    "sales": _f("Sales"),
                    "eq": (
                        _f(FINS_SUMMARY_EQ_KEY)
                        if _f(FINS_SUMMARY_EQ_KEY) is not None
                        else _f("ShEq")
                    ),
                    "ta": _f(FINS_SUMMARY_TA_KEY),
                    "eq_ar": _f(FINS_SUMMARY_EQAR_KEY),
                    "event_time": str(event_time) if event_time else None,
                    "available_at": str(row_aa) if row_aa else None,
                    "source": "fins_summary",
                }
            )
        # Attach prior_eps chronologically
        for code, events in by_code.items():
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


def select_eval_universe(
    *,
    max_codes: int,
    pool: Sequence[str] | None = None,
    period_start: str = "2019-01-01",
    period_end: str = "2019-10-21",
) -> list[str]:
    """Liquidity-first universe. Missing bars/fins → skip. Never invent."""
    src = EVAL_UNIVERSE_POOL if pool is None else pool
    want = [str(c).strip() for c in src if str(c).strip()]
    n = max(1, int(max_codes))
    if not want:
        # Head-N list slice is forbidden on both eval tracks.
        return []
    rich = load_bars_from_sqlite_rich(
        codes=want,
        period_start=period_start,
        period_end=period_end,
    )
    fins = load_fins_events_from_sqlite(
        codes=want, start=period_start, end=period_end
    )
    scored: list[dict[str, Any]] = []
    for code in want:
        pairs = list(rich.get(code) or [])
        adv_vals: list[float] = []
        for _d, rec in pairs:
            if not isinstance(rec, Mapping):
                continue
            va = rec.get("Va")
            try:
                if va is not None:
                    adv_vals.append(float(va))
                    continue
            except (TypeError, ValueError):
                pass
            try:
                vo = rec.get("Vo")
                px = rec.get("close")
                if vo is not None and px is not None:
                    adv_vals.append(float(vo) * float(px))
            except (TypeError, ValueError):
                continue
        evs = list(fins.get(code) or [])
        scored.append(
            {
                "code": code,
                "adv": (sum(adv_vals) / len(adv_vals)) if adv_vals else 0.0,
                "n_bars": len(pairs),
                "n_ta": sum(1 for e in evs if e.get("ta") is not None),
                "n_eqar": sum(1 for e in evs if e.get("eq_ar") is not None),
            }
        )
    ranked = rank_eval_codes(scored, max_codes=n)
    if len(ranked) >= n:
        return ranked
    # Fill only from ranked-eligible remainder; never invent empty names.
    return ranked


def bars_rich_to_close_panel(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> dict[str, list[tuple[str, float]]]:
    from research.eval_loaders import bars_rich_to_close_panel as _impl

    return _impl(rich)


def load_bars_ndjson_rich(*args, **kwargs):
    from research.eval_loaders import load_bars_ndjson_rich as _impl

    return _impl(*args, **kwargs)


def resolve_bars_path(*args, **kwargs):
    from research.eval_loaders import resolve_bars_path as _impl

    return _impl(*args, **kwargs)


def resolve_margin_path(*args, **kwargs):
    from research.eval_loaders import resolve_margin_path as _impl

    return _impl(*args, **kwargs)


def load_nky_vol_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE, **kwargs
):
    from research.eval_loaders import load_nky_vol_series_from_sqlite as _impl

    return _impl(db_path, **kwargs)


def load_opt225_regime_bundle_for_eval(**kwargs):
    from research.eval_loaders import load_opt225_regime_bundle_for_eval as _impl

    return _impl(**kwargs)


def load_margin_from_sqlite(db_path: str | Path = DEFAULT_SQLITE, **kwargs):
    from research.eval_loaders import load_margin_from_sqlite as _impl

    return _impl(db_path, **kwargs)


def load_margin_ndjson(*args, **kwargs):
    from research.eval_loaders import load_margin_ndjson as _impl

    return _impl(*args, **kwargs)


def load_repo_rows_from_sqlite(db_path: str | Path = DEFAULT_SQLITE, **kwargs):
    from research.eval_loaders import load_repo_rows_from_sqlite as _impl

    return _impl(db_path, **kwargs)


def load_repo_rows_all_tenors_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE, **kwargs
):
    from research.eval_loaders import load_repo_rows_all_tenors_from_sqlite as _impl

    return _impl(db_path, **kwargs)


def load_short_ratio_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE, **kwargs
):
    from research.eval_loaders import load_short_ratio_series_from_sqlite as _impl

    return _impl(db_path, **kwargs)


def load_topix_close_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE, **kwargs
):
    from research.eval_loaders import load_topix_close_series_from_sqlite as _impl

    return _impl(db_path, **kwargs)


def build_repo_curve_series(*args, **kwargs):
    from research.eval_loaders import build_repo_curve_series as _impl

    return _impl(*args, **kwargs)


def repo_history_plane_status(db_path: str | Path = DEFAULT_SQLITE, **kwargs):
    from research.eval_loaders import repo_history_plane_status as _impl

    return _impl(db_path, **kwargs)


def momentum_series(*args, **kwargs):
    from research.eval_loaders import momentum_series as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "DEFAULT_SQLITE",
    "EVAL_UNIVERSE_POOL",
    "UNIVERSE_MIN_BAR_DAYS",
    "UNIVERSE_MIN_FINS_EQAR",
    "UNIVERSE_MIN_FINS_TA",
    "UNIVERSE_SELECT_ADV",
    "UNIVERSE_SELECT_RULE",
    "bars_rich_to_close_panel",
    "build_repo_curve_series",
    "load_bars_from_sqlite_rich",
    "load_bars_ndjson_rich",
    "load_fins_events_from_sqlite",
    "load_margin_from_sqlite",
    "load_margin_ndjson",
    "load_nky_vol_series_from_sqlite",
    "load_opt225_regime_bundle_for_eval",
    "load_repo_rows_all_tenors_from_sqlite",
    "load_repo_rows_from_sqlite",
    "load_short_ratio_series_from_sqlite",
    "load_topix_close_series_from_sqlite",
    "momentum_series",
    "rank_eval_codes",
    "repo_history_plane_status",
    "resolve_bars_path",
    "resolve_margin_path",
    "select_eval_universe",
]
