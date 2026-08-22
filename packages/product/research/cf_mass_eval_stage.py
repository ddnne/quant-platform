"""COMPLETE-backed r2_panels staging for CF mass-eval.

Period-net panels are bar-native auxiliary. Candidate SoT is daily_path.
Loaders come from eval_loaders (bars/nky/opt/margin/repo). Universe pick is
``select_eval_universe`` — never head-N.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PERMANENT_DEFER_IDS,
)
from research.eval_loaders import (
    bars_rich_to_close_panel,
    build_repo_curve_series,
    load_bars_from_sqlite_rich,
    load_bars_ndjson_rich,
    load_fins_events_from_sqlite,
    load_margin_from_sqlite,
    load_margin_ndjson,
    load_nky_vol_series_from_sqlite,
    load_opt225_regime_bundle_for_eval,
    load_repo_rows_all_tenors_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    resolve_bars_path,
    resolve_margin_path,
)
from research.eval_universe import DEFAULT_SQLITE, select_eval_universe
from research.eval_windows import DEFAULT_REAL_MULTIYEAR_PERIODS
from research.single_shot_job import COMPLETE_21_DATASETS, default_r2_put

RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/mass_eval"
# Default is the liq_large track (ADV 100). mid_n_explore uses 80.
# Never fall back to head-N list order.
DEFAULT_MAX_CODES: int = 100
DEFAULT_MAX_DAYS: int = 120

# COMPLETE 22 = COMPLETE 21 + fins_earnings_date (W68 tip4 seal).
# Permanent DEFER residual (n=4) stays PARTIAL / tip-only.
COMPLETE_22_DATASETS: tuple[str, ...] = tuple(
    sorted(set(COMPLETE_21_DATASETS) | {"fins_earnings_date"})
)
COMPLETE_22_DATASET_SET: frozenset[str] = frozenset(COMPLETE_22_DATASETS)
PRIMARY_BARS_DATASET: str = "equities_bars_daily"
PRIMARY_INDEX_DATASETS: tuple[str, ...] = (
    "indices_bars_daily_topix",
    "indices_bars_daily",
)
THICKEN_PANEL_DATASETS: tuple[str, ...] = (
    "markets_calendar",
    "jsda_tokyo_repo_rates",
    "markets_margin_interest",
    "markets_short_ratio",
    "fins_summary",
    "indices_bars_daily_topix",
)

if len(COMPLETE_22_DATASETS) != 22:
    raise RuntimeError(
        f"COMPLETE_22_DATASETS must have 22 ids, got {len(COMPLETE_22_DATASETS)}"
    )
if COMPLETE_22_DATASET_SET & PERMANENT_DEFER_DATASETS:
    raise RuntimeError(
        "COMPLETE_22_DATASETS must not intersect permanent DEFER: "
        f"{sorted(COMPLETE_22_DATASET_SET & PERMANENT_DEFER_DATASETS)}"
    )


def _mass_eval_identity() -> tuple[str, str]:
    from research.cf_mass_eval_job import CF_MASS_EVAL_VERSION, CF_MASS_EVAL_WAVE

    return CF_MASS_EVAL_WAVE, CF_MASS_EVAL_VERSION


def normalize_period_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize period dict to worker shape (period_start/end + year)."""
    p = dict(raw)
    pid = str(p.get("period_id") or p.get("id") or "period")
    start = p.get("period_start") or p.get("start") or ""
    end = p.get("period_end") or p.get("end") or ""
    year = p.get("year")
    if year is None and start:
        try:
            year = int(str(start)[:4])
        except ValueError:
            year = None
    if year is None:
        for token in pid.replace("-", "_").split("_"):
            if token.startswith("y") and token[1:].isdigit() and len(token) == 5:
                year = int(token[1:])
                break
            if token.isdigit() and len(token) == 4:
                year = int(token)
                break
    out: dict[str, Any] = {"period_id": pid}
    if year is not None:
        out["year"] = int(year)
    if start:
        out["period_start"] = str(start)[:10]
        out["start"] = str(start)[:10]
    if end:
        out["period_end"] = str(end)[:10]
        out["end"] = str(end)[:10]
    if p.get("window_kind"):
        out["window_kind"] = p["window_kind"]
    return out


def inventory_complete22() -> dict[str, Any]:
    """Machine inventory of COMPLETE 22 + permanent DEFER residual."""
    wave, _ver = _mass_eval_identity()
    return {
        "wave": wave,
        "dataset_complete_n": len(COMPLETE_22_DATASETS),
        "complete_22": list(COMPLETE_22_DATASETS),
        "primary_bars_dataset": PRIMARY_BARS_DATASET,
        "primary_index_datasets": list(PRIMARY_INDEX_DATASETS),
        "thicken_panel_datasets": list(THICKEN_PANEL_DATASETS),
        "permanent_defer_n": len(PERMANENT_DEFER_DATASETS),
        "permanent_defer": sorted(PERMANENT_DEFER_DATASETS),
        "permanent_defer_ids": dict(PERMANENT_DEFER_IDS),
        "note": (
            "COMPLETE 22 = COMPLETE 21 + fins_earnings_date (W68). "
            "History research must exclude permanent DEFER."
        ),
    }


def _load_markets_calendar_map(
    *,
    start: str | None,
    end: str | None,
    sqlite_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compact markets_calendar HolDiv map for one period window."""
    db = Path(sqlite_path) if sqlite_path else DEFAULT_SQLITE
    if not db.exists():
        return {
            "dataset": "markets_calendar",
            "status": "sqlite_missing",
            "hol_div_by_date": {},
            "n_dates": 0,
        }
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_calendar'"
        )
        params: list[Any] = []
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        hol: dict[str, str] = {}
        trading_dates: list[str] = []
        for event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not d:
                continue
            hol_div = pl.get("HolDiv")
            if hol_div is None:
                hol_div = pl.get("HolidayDivision")
            hol[d] = str(hol_div) if hol_div is not None else ""
            if str(hol_div) in {"0", "1"}:
                trading_dates.append(d)
        return {
            "dataset": "markets_calendar",
            "status": "ok" if hol else "empty",
            "source": "local_sqlite_jquants_records",
            "hol_div_by_date": hol,
            "trading_dates": trading_dates,
            "n_dates": len(hol),
            "n_trading_dates": len(trading_dates),
        }
    finally:
        con.close()


def _build_thicken_sidecars(
    period: Mapping[str, Any],
    *,
    codes: Sequence[str],
    sqlite_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compact rate/flow/fund/calendar sidecars. Gaps disclosed; no invent/ffill."""
    from research.cost_models import load_repo_rate_series_from_rows

    wave, ver = _mass_eval_identity()
    db = Path(sqlite_path) if sqlite_path else DEFAULT_SQLITE
    p_start = str(period.get("period_start") or period.get("start") or "")[:10]
    p_end = str(period.get("period_end") or period.get("end") or "")[:10]
    burn_start = p_start
    if p_start:
        try:
            y, m, d = int(p_start[:4]), int(p_start[5:7]), int(p_start[8:10])
            y -= 2
            burn_start = f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            burn_start = p_start

    out: dict[str, Any] = {
        "thicken_wave": wave,
        "thicken_version": ver,
    }

    try:
        cal = _load_markets_calendar_map(
            start=burn_start or None, end=p_end or None, sqlite_path=db
        )
        out["markets_calendar"] = cal
        out["calendar"] = {
            "dataset": "markets_calendar",
            "hol_div_by_date": cal.get("hol_div_by_date") or {},
            "n_dates": cal.get("n_dates") or 0,
            "n_trading_dates": cal.get("n_trading_dates") or 0,
        }
    except Exception as exc:  # pragma: no cover - best-effort
        out["markets_calendar"] = {
            "dataset": "markets_calendar",
            "status": "error",
            "error": str(exc),
        }

    try:
        overnight = load_repo_rows_from_sqlite(
            db, start=burn_start or None, end=p_end or None
        )
        series = (
            load_repo_rate_series_from_rows(overnight) if overnight else None
        )
        all_tenors = load_repo_rows_all_tenors_from_sqlite(
            db, start=burn_start or None, end=p_end or None
        )
        curve = build_repo_curve_series(all_tenors) if all_tenors else {}
        rates_by_date = dict((series or {}).get("rates_by_date") or {})
        if p_start or p_end:
            rates_by_date = {
                d: float(v)
                for d, v in rates_by_date.items()
                if (not burn_start or d >= burn_start)
                and (not p_end or d <= p_end)
            }
        spread_by = dict(curve.get("spread_by_date") or {})
        if p_start or p_end:
            spread_by = {
                d: float(v)
                for d, v in spread_by.items()
                if (not burn_start or d >= burn_start)
                and (not p_end or d <= p_end)
            }
        out["repo_rate_regime"] = {
            "dataset": "jsda_tokyo_repo_rates",
            "status": "ok" if rates_by_date else "empty",
            "source": "local_sqlite_jsda_repo_rates",
            "rates_by_date": rates_by_date,
            "spread_by_date": spread_by,
            "short_tenor": curve.get("short_tenor"),
            "long_tenor": curve.get("long_tenor"),
            "n_rates": len(rates_by_date),
            "n_spread": len(spread_by),
            "ffill_applied": False,
            "invent_fill": False,
            "role": "funding_rate_sot",
        }
    except Exception as exc:  # pragma: no cover
        out["repo_rate_regime"] = {
            "dataset": "jsda_tokyo_repo_rates",
            "status": "error",
            "error": str(exc),
        }

    try:
        margin_levels: dict[str, list[tuple[str, float]]] = {}
        margin_source = "local_sqlite_jquants_records"
        pid = str(period.get("period_id") or "")
        margin_path = resolve_margin_path(pid) if pid else None
        margin_levels = load_margin_from_sqlite(
            db,
            codes=codes,
            start=burn_start or None,
            end=p_end or None,
        )
        if margin_path is not None and Path(margin_path).exists():
            nd = load_margin_ndjson(margin_path, codes=codes)
            if nd:
                for code, pairs in nd.items():
                    existing = {d: float(v) for d, v in (margin_levels.get(code) or [])}
                    for d, v in pairs:
                        existing.setdefault(str(d)[:10], float(v))
                    margin_levels[code] = sorted(existing.items())
                margin_source = f"sqlite+complete22_mirror:{Path(margin_path).name}"
        level_by_code: dict[str, dict[str, float]] = {}
        change_by_code: dict[str, dict[str, float]] = {}
        for code, pairs in margin_levels.items():
            clipped = [
                (d, float(v))
                for d, v in pairs
                if (not burn_start or d >= burn_start)
                and (not p_end or d <= p_end)
            ]
            if not clipped:
                continue
            level_by_code[code] = {d: v for d, v in clipped}
            chg: dict[str, float] = {}
            for i in range(1, len(clipped)):
                d0, v0 = clipped[i - 1]
                d1, v1 = clipped[i]
                if v0 != 0:
                    chg[d1] = (v1 / v0) - 1.0
            change_by_code[code] = chg
        out["flow_regime"] = {
            "dataset_margin": "markets_margin_interest",
            "dataset_short": "markets_short_ratio",
            "status": "ok" if level_by_code else "empty",
            "source": margin_source,
            "margin_level_by_code": level_by_code,
            "margin_change_by_code": change_by_code,
            "n_codes": len(level_by_code),
            "n_obs": sum(len(v) for v in level_by_code.values()),
            "role": "flow_demand_sidecar",
        }
    except Exception as exc:  # pragma: no cover
        out["flow_regime"] = {
            "dataset_margin": "markets_margin_interest",
            "status": "error",
            "error": str(exc),
        }

    try:
        short_pairs = load_short_ratio_series_from_sqlite(
            db,
            section="0050",
            start=burn_start or None,
            end=p_end or None,
        )
        short_by = {
            d: float(v)
            for d, v in short_pairs
            if (not burn_start or d >= burn_start) and (not p_end or d <= p_end)
        }
        fr = dict(out.get("flow_regime") or {})
        fr["short_ratio_by_date"] = short_by
        fr["short_section"] = "0050"
        fr["n_short_obs"] = len(short_by)
        if fr.get("status") == "empty" and short_by:
            fr["status"] = "ok"
        out["flow_regime"] = fr
    except Exception as exc:  # pragma: no cover
        fr = dict(out.get("flow_regime") or {})
        fr["short_ratio_error"] = str(exc)
        out["flow_regime"] = fr

    try:
        events = load_fins_events_from_sqlite(
            db,
            codes=codes,
            start=burn_start or "2014-01-01",
            end=p_end or None,
        )
        compact: dict[str, list[dict[str, Any]]] = {}
        for code, evs in events.items():
            rows: list[dict[str, Any]] = []
            for ev in evs:
                d = str(ev.get("disc_date") or "")[:10]
                if not d:
                    continue
                if p_end and d > p_end:
                    continue
                rows.append(
                    {
                        "disc_date": d,
                        "disc_time": ev.get("disc_time"),
                        "eps": ev.get("eps"),
                        "feps": ev.get("feps"),
                        "prior_eps": ev.get("prior_eps"),
                        "bps": ev.get("bps"),
                        "roe": ev.get("roe"),
                        "div_ann": ev.get("div_ann"),
                        "np": ev.get("np"),
                        "sales": ev.get("sales"),
                        "eq": ev.get("eq"),
                        "ta": ev.get("ta"),
                        "eq_ar": ev.get("eq_ar"),
                        "prior_ta": ev.get("prior_ta"),
                    }
                )
            if rows:
                compact[code] = rows
        out["fund_regime"] = {
            "dataset": "fins_summary",
            "status": "ok" if compact else "empty",
            "source": "local_sqlite_jquants_records",
            "events_by_code": compact,
            "n_codes": len(compact),
            "n_events": sum(len(v) for v in compact.values()),
            "role": "fundamentals_sidecar",
            "note": (
                "Compact fins_summary disclosures for panel codes. "
                "W94 CF fund_* / mf_value_mom_rate consume when present; "
                "empty → disclosed MDH fallback."
            ),
        }
    except Exception as exc:  # pragma: no cover
        out["fund_regime"] = {
            "dataset": "fins_summary",
            "status": "error",
            "error": str(exc),
        }

    out["index_proxy"] = {
        "dataset": "indices_bars_daily_topix",
        "label": "TOPIX",
        "role": "nky_vol_proxy_compare_only",
        "note": (
            "TOPIX closes staged as __NKY_PROXY__ for nky_vol_* only. "
            "Canonical Nikkei vol SoT remains derivatives_bars_daily_options_225."
        ),
    }
    out["thicken_counts"] = {
        "calendar_n_dates": int(
            (out.get("calendar") or {}).get("n_dates") or 0
        ),
        "repo_n_rates": int(
            (out.get("repo_rate_regime") or {}).get("n_rates") or 0
        ),
        "repo_n_spread": int(
            (out.get("repo_rate_regime") or {}).get("n_spread") or 0
        ),
        "flow_n_codes": int((out.get("flow_regime") or {}).get("n_codes") or 0),
        "flow_n_short": int(
            (out.get("flow_regime") or {}).get("n_short_obs") or 0
        ),
        "fund_n_codes": int((out.get("fund_regime") or {}).get("n_codes") or 0),
        "fund_n_events": int(
            (out.get("fund_regime") or {}).get("n_events") or 0
        ),
    }

    rates = dict((out.get("repo_rate_regime") or {}).get("rates_by_date") or {})
    out["repo_rate_by_date"] = rates
    if isinstance(out.get("repo_rate_regime"), dict):
        out["repo_rate_regime"] = {
            **out["repo_rate_regime"],
            "rate_by_date": rates,
            "n_obs": len(rates),
            "units": "percent",
        }
    cal = out.get("calendar") or {}
    hol = dict(cal.get("hol_div_by_date") or {})
    out["calendar_dates"] = sorted(hol.keys())
    fr = out.get("flow_regime") or {}
    margin_compact: dict[str, list[list[Any]]] = {}
    for code, dmap in dict(fr.get("margin_level_by_code") or {}).items():
        margin_compact[str(code)] = [
            [d, float(v)] for d, v in sorted(dict(dmap).items())
        ]
    out["margin_interest"] = margin_compact
    out["margin_n_obs"] = int(fr.get("n_obs") or 0)
    out["short_ratio_by_date"] = dict(fr.get("short_ratio_by_date") or {})
    fund = out.get("fund_regime") or {}
    out["fins_summary_n_events"] = int(fund.get("n_events") or 0)
    out["fins_summary_n_codes"] = int(fund.get("n_codes") or 0)
    status: dict[str, str] = {
        "equities_bars_daily": "DONE",
        "derivatives_bars_daily_options_225": "DONE_via_opt225",
        "indices_bars_daily_topix": "DONE_via_nky_proxy",
        "markets_calendar": (
            "DONE"
            if int((out.get("calendar") or {}).get("n_dates") or 0) > 0
            else "EMPTY"
        ),
        "jsda_tokyo_repo_rates": "DONE" if rates else "EMPTY",
        "markets_margin_interest": "DONE" if margin_compact else "EMPTY",
        "markets_short_ratio": (
            "DONE" if out.get("short_ratio_by_date") else "EMPTY"
        ),
        "fins_summary": (
            "DONE"
            if int(out.get("fins_summary_n_events") or 0) > 0
            else "EMPTY"
        ),
    }
    out["thicken_datasets_requested"] = list(THICKEN_PANEL_DATASETS)
    out["thicken_status"] = status
    out["thicken_done"] = sorted(
        k for k, v in status.items() if str(v).startswith("DONE")
    )
    out["thicken_todo"] = [
        "rate_abs_level_xs_and_rate_curve_shape_xs_on_cf_pure_ts",
    ]
    out["thicken_consumed_on_cf"] = [
        "macro_repo_rate_*",
        "flow_margin_*",
        "fund_*",
        "mf_value_mom_rate",
        "mf_flow_price",
    ]
    out["panel_thicken"] = True
    return out


def build_real_period_panel(
    period: Mapping[str, Any],
    *,
    codes: Sequence[str] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    mirror_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load one real bars panel from COMPLETE-backed local R2 mirrors.

    Returns worker-ready panel JSON:
      {period_id, year, period_start, period_end, bars: {code: [[d, px], ...]},
       dataset, source, status, n_codes, n_days}
    """
    p = normalize_period_row(period)
    pid = str(p["period_id"])
    pool = (
        None
        if codes is None
        else [str(c).strip() for c in codes if str(c).strip()]
    )
    selected = select_eval_universe(max_codes=int(max_codes), pool=pool)
    if mirror_dir is not None:
        bars_path = resolve_bars_path(
            pid, mirror_dir=mirror_dir, prefer_full=True
        )
    else:
        bars_path = resolve_bars_path(pid, prefer_full=True)
    if bars_path is None or not Path(bars_path).exists():
        return {
            **p,
            "status": "missing_bars",
            "bars": {},
            "dataset": PRIMARY_BARS_DATASET,
            "source": "mirror_missing",
            "n_codes": 0,
            "n_days": 0,
            "bars_path": str(bars_path) if bars_path else None,
        }
    rich = load_bars_ndjson_rich(
        bars_path,
        codes=selected,
        max_days=int(max_days),
        period_start=p.get("period_start"),
        period_end=p.get("period_end"),
    )
    missing = [c for c in selected if c not in rich]
    if missing:
        extra = load_bars_from_sqlite_rich(
            codes=missing,
            period_start=str(p.get("period_start") or ""),
            period_end=str(p.get("period_end") or ""),
            max_days=int(max_days),
        )
        rich.update(extra)
    close = bars_rich_to_close_panel(rich)
    bars_json: dict[str, list[list[Any]]] = {
        code: [[d, float(px)] for d, px in pairs]
        for code, pairs in close.items()
        if pairs
    }
    adv_by_code: dict[str, float] = {}
    for code, pairs in (rich or {}).items():
        vals: list[float] = []
        for _d, rec in pairs:
            va = rec.get("Va") if isinstance(rec, dict) else None
            try:
                if va is not None:
                    vals.append(float(va))
                    continue
            except (TypeError, ValueError):
                pass
            try:
                vo = rec.get("Vo") if isinstance(rec, dict) else None
                px = rec.get("close") if isinstance(rec, dict) else None
                if vo is not None and px is not None:
                    vals.append(float(vo) * float(px))
            except (TypeError, ValueError):
                continue
        if vals:
            adv_by_code[str(code)] = sum(vals) / len(vals)
    nky_meta: dict[str, Any] = {}
    try:
        nky = load_nky_vol_series_from_sqlite(
            start=p.get("period_start"),
            end=p.get("period_end"),
            prefer="ndjson_topix",
        )
        closes_by = dict(nky.get("closes_by_date") or {})
        p_start = str(p.get("period_start") or "")[:10]
        p_end = str(p.get("period_end") or "")[:10]
        idx_pairs = [
            [d, float(px)]
            for d, px in sorted(closes_by.items())
            if (not p_start or d >= p_start) and (not p_end or d <= p_end)
        ]
        if closes_by:
            all_pairs = sorted(closes_by.items())
            if p_start:
                burn = [x for x in all_pairs if x[0] < p_start][-80:]
                in_win = [
                    x
                    for x in all_pairs
                    if x[0] >= p_start and (not p_end or x[0] <= p_end)
                ]
                idx_pairs = [[d, float(px)] for d, px in (burn + in_win)]
            if idx_pairs:
                bars_json["__NKY_PROXY__"] = idx_pairs
                nky_meta = {
                    "nky_proxy": nky.get("source"),
                    "nky_dataset": nky.get("dataset"),
                    "nky_n_closes": len(idx_pairs),
                    "nky_vol_series": {
                        "source": nky.get("source"),
                        "dataset": nky.get("dataset"),
                        "short_n": nky.get("short_n"),
                        "long_n": nky.get("long_n"),
                        "rv_short_by_date": nky.get("rv_short_by_date") or {},
                        "rv_long_by_date": nky.get("rv_long_by_date") or {},
                        "rv_abs_by_date": nky.get("rv_abs_by_date") or {},
                        "rv_ratio_by_date": nky.get("rv_ratio_by_date") or {},
                    },
                }
    except Exception as exc:  # pragma: no cover - best-effort
        nky_meta = {"nky_proxy_error": str(exc)}

    opt225_meta: dict[str, Any] = {}
    try:
        opt225 = load_opt225_regime_bundle_for_eval()
        if opt225:
            compact: dict[str, Any] = {
                "spread_convention": opt225.get("spread_convention"),
                "units": opt225.get("units"),
                "dataset": opt225.get("dataset"),
                "version": opt225.get("version"),
            }
            for kind in (
                "basevol",
                "atm_iv",
                "spread",
                "spread_change",
                "skew",
                "cm_term",
                "basevol_delta",
            ):
                ser = dict(opt225.get(kind) or {})
                if not ser:
                    continue
                entry = {
                    "source": ser.get("source"),
                    "dataset": ser.get("dataset"),
                    "series_kind": ser.get("series_kind"),
                    "units": ser.get("units"),
                    "short_n": ser.get("short_n"),
                    "long_n": ser.get("long_n"),
                    "rv_abs_by_date": ser.get("rv_abs_by_date") or {},
                    "rv_short_by_date": ser.get("rv_short_by_date") or {},
                    "rv_long_by_date": ser.get("rv_long_by_date") or {},
                    "rv_ratio_by_date": ser.get("rv_ratio_by_date") or {},
                    "n_obs_level": ser.get("n_obs_level"),
                }
                if kind == "atm_iv":
                    entry["compare_only"] = True
                    entry["role"] = "compare_only"
                if kind == "basevol":
                    entry["role"] = "canonical_level"
                compact[kind] = entry
            compact["canonical_level"] = opt225.get("canonical_level") or "basevol"
            compact["atm_iv_role"] = opt225.get("atm_iv_role") or "compare_only"
            compact["skew_convention"] = opt225.get("skew_convention")
            compact["cm_term_convention"] = opt225.get("cm_term_convention")
            compact["basevol_delta_convention"] = opt225.get(
                "basevol_delta_convention"
            )
            base_vol_series = dict(
                (compact.get("basevol") or {}).get("rv_abs_by_date") or {}
            )
            atm_iv_series = dict(
                (compact.get("atm_iv") or {}).get("rv_abs_by_date") or {}
            )
            iv_base_spread = dict(
                (compact.get("spread") or {}).get("rv_abs_by_date") or {}
            )
            skew_series = dict(
                (compact.get("skew") or {}).get("rv_abs_by_date") or {}
            )
            cm_term_series = dict(
                (compact.get("cm_term") or {}).get("rv_abs_by_date") or {}
            )
            basevol_delta_series = dict(
                (compact.get("basevol_delta") or {}).get("rv_abs_by_date") or {}
            )
            opt225_meta = {
                "opt225_regime": compact,
                "base_vol_series": base_vol_series,
                "atm_iv_series": atm_iv_series,
                "iv_base_spread": iv_base_spread,
                "skew_series": skew_series,
                "cm_term_series": cm_term_series,
                "basevol_delta_series": basevol_delta_series,
                "opt225_dataset": "derivatives_bars_daily_options_225",
                "opt225_role": "canonical_nky_vol_sot",
                "opt225_canonical_level": "basevol",
                "opt225_atm_iv_role": "compare_only",
                "opt225_spread_convention": compact.get("spread_convention")
                or "atm_iv - base_vol",
                "opt225_skew_convention": compact.get("skew_convention"),
                "opt225_cm_term_convention": compact.get("cm_term_convention"),
                "opt225_n_base_vol": len(base_vol_series),
                "opt225_n_atm_iv": len(atm_iv_series),
                "opt225_n_spread": len(iv_base_spread),
                "opt225_n_skew": len(skew_series),
                "opt225_n_cm_term": len(cm_term_series),
                "opt225_n_basevol_delta": len(basevol_delta_series),
            }
    except Exception as exc:  # pragma: no cover - best-effort
        opt225_meta = {"opt225_error": str(exc)}

    thicken_meta = _build_thicken_sidecars(p, codes=selected)

    n_days = max(
        (len(v) for k, v in bars_json.items() if not str(k).startswith("__")),
        default=0,
    )
    n_eq = sum(1 for k in bars_json if not str(k).startswith("__"))
    return {
        **p,
        "status": "ok" if n_eq > 0 else "empty_bars",
        "bars": bars_json,
        "adv_by_code": adv_by_code,
        "dataset": PRIMARY_BARS_DATASET,
        "source": f"complete22_mirror:{Path(bars_path).name}",
        "n_codes": n_eq,
        "n_days": n_days,
        "bars_path": str(bars_path),
        "codes": sorted(k for k in bars_json if not str(k).startswith("__")),
        **nky_meta,
        **opt225_meta,
        **thicken_meta,
    }


def stage_real_panels_to_r2(
    job_id: str,
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    codes: Sequence[str] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    r2_put: Callable[..., Mapping[str, Any]] | None = None,
    panels_prefix: str | None = None,
) -> dict[str, Any]:
    """Build real multi-year panels and put under job-scoped R2 prefix.

    Keys: research/mass_eval/job={id}/panels/{period_id}.json
    ``panels_prefix`` overrides the default job-scoped prefix (cache reuse).
    """
    wave, _ver = _mass_eval_identity()
    jid = str(job_id).strip() or "unknown"
    period_list = [
        normalize_period_row(p)
        for p in (periods or DEFAULT_REAL_MULTIYEAR_PERIODS)
    ]
    prefix = panels_prefix or f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/panels"
    put_fn = r2_put or (
        lambda bucket, key, body: default_r2_put(
            bucket,
            key,
            body,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )
    )
    panels: list[dict[str, Any]] = []
    puts: list[dict[str, Any]] = []
    for raw in period_list:
        panel = build_real_period_panel(
            raw,
            codes=codes,
            max_codes=max_codes,
            max_days=max_days,
        )
        key = f"{prefix}/{panel['period_id']}.json"
        body = json.dumps(panel, indent=2, default=str).encode("utf-8")
        meta = put_fn(RESEARCH_ARTIFACT_BUCKET, key, body)
        puts.append(dict(meta) if isinstance(meta, Mapping) else {"key": key})
        panels.append(
            {
                "period_id": panel.get("period_id"),
                "year": panel.get("year"),
                "period_start": panel.get("period_start"),
                "period_end": panel.get("period_end"),
                "status": panel.get("status"),
                "n_codes": panel.get("n_codes"),
                "n_days": panel.get("n_days"),
                "source": panel.get("source"),
                "dataset": panel.get("dataset"),
                "r2_key": key,
                "bars_path": panel.get("bars_path"),
                "thicken_counts": panel.get("thicken_counts"),
                "thicken_done": panel.get("thicken_done"),
                "opt225_n_base_vol": panel.get("opt225_n_base_vol"),
                "repo_n_rates": (panel.get("repo_rate_regime") or {}).get(
                    "n_rates"
                )
                or (panel.get("repo_rate_regime") or {}).get("n_obs"),
                "calendar_n_dates": (panel.get("calendar") or {}).get("n_dates"),
                "flow_n_codes": (panel.get("flow_regime") or {}).get("n_codes"),
                "fund_n_events": (panel.get("fund_regime") or {}).get(
                    "n_events"
                ),
            }
        )
    n_ok = sum(1 for p in panels if p.get("status") == "ok")
    return {
        "job_id": jid,
        "panels_prefix": prefix,
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "n_periods": len(panels),
        "n_ok": n_ok,
        "n_missing": len(panels) - n_ok,
        "panels": panels,
        "puts": puts,
        "dataset": PRIMARY_BARS_DATASET,
        "complete22": inventory_complete22(),
        "wave": wave,
        "dry_run": bool(dry_run),
    }


__all__ = [
    "COMPLETE_22_DATASETS",
    "COMPLETE_22_DATASET_SET",
    "DEFAULT_MAX_CODES",
    "DEFAULT_MAX_DAYS",
    "PRIMARY_BARS_DATASET",
    "PRIMARY_INDEX_DATASETS",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "THICKEN_PANEL_DATASETS",
    "build_real_period_panel",
    "inventory_complete22",
    "normalize_period_row",
    "stage_real_panels_to_r2",
]
