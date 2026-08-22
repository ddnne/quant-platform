"""Rate/flow/fund thicken sidecars + NKY/opt225 panel attach.

Period-net panels are bar-native auxiliary. Candidate SoT is daily_path.
Gaps disclosed; no invent/ffill. Not a pass / not GO.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.eval_loaders import (
    build_repo_curve_series,
    load_fins_events_from_sqlite,
    load_margin_from_sqlite,
    load_margin_ndjson,
    load_nky_vol_series_from_sqlite,
    load_opt225_regime_bundle_for_eval,
    load_repo_rows_all_tenors_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    resolve_margin_path,
)
from research.eval_universe import DEFAULT_SQLITE

THICKEN_PANEL_DATASETS: tuple[str, ...] = (
    "markets_calendar",
    "jsda_tokyo_repo_rates",
    "markets_margin_interest",
    "markets_short_ratio",
    "fins_summary",
    "indices_bars_daily_topix",
)


def _mass_eval_identity() -> tuple[str, str]:
    from research.cf_mass_eval_job import CF_MASS_EVAL_VERSION, CF_MASS_EVAL_WAVE

    return CF_MASS_EVAL_WAVE, CF_MASS_EVAL_VERSION


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


def attach_nky_proxy(
    bars_json: dict[str, list[list[Any]]],
    period: Mapping[str, Any],
) -> dict[str, Any]:
    """Stage TOPIX closes as __NKY_PROXY__. Mutates bars_json. Best-effort."""
    p = period
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

    return nky_meta


def attach_opt225_regime() -> dict[str, Any]:
    """Compact opt225 regime maps for the panel. Best-effort."""
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
    return opt225_meta
