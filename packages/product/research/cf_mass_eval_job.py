"""Cloudflare multi-logic × multi-period mass eval job (W91 / w0818a).

Implements a real CF Worker path for evaluating **multiple economic logics**
across **multiple period windows**, writing artifacts to R2
``quant-structured`` under ``research/mass_eval/job={id}/…``.

Architecture
------------
* **Worker:** ``platform/workers/research-mass-eval`` (TypeScript)
  - ``mode=r2_panels`` — staged COMPLETE-backed real bars (W91 preferred)
  - ``mode=d1_bars`` — D1 ``jquants_records`` tip extract (hot window only)
  - ``mode=synthetic`` — deterministic PRNG (W90 residual smoke)
  - ``mode=nets_only`` — pre-baked period nets
  - Evaluates bar-native logics (mdh / xs / vol) across period shards
  - Writes summary/results/ranking to R2
* **Driver (this module):** builds job payload, stages real panels from
  local COMPLETE-backed R2 mirrors (W63/W64), invokes Worker via HTTPS,
  records job id / counts / artifact keys.

W91 multi-period policy
-----------------------
* ≥4–6 multi-year windows (full-prefer 2015/19/21/23 + Q4 2017/25)
* max_codes ≤ 20, max_days ≤ 200 per period (CF wall-clock safe)
* Heavy multi-year deep eval remains local ``run_mass_factory`` /
  ``class_hyp_eval`` for promising survivors only

Does **not** arm Mass / READY / GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PERMANENT_DEFER_IDS,
)
from research.mass_strategy_factory import (
    CONTINUOUS_PAPER,
    LOGIC_TEMPLATES,
    LOGIC_TEMPLATE_IDS,
    MASS_FACTORY_VERSION,
    MASS_RESEARCH,
    PHASE7,
    MassFactoryConfig,
    generate_strategy_batch,
    run_batch_eval,
)
from research.single_shot_job import COMPLETE_21_DATASETS, default_r2_put

CF_MASS_EVAL_VERSION: str = "cf-mass-eval-job/v4"
CF_MASS_EVAL_WAVE: str = "W93 / w0818c"
RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/mass_eval"
DEFAULT_WORKER_NAME: str = "quant-platform-research-mass-eval"
DEFAULT_WORKER_URL: str = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)
RESEARCH_ARTIFACT_PREFIX_LEGACY: str = "research/mass_factory"
DEFAULT_MAX_CODES: int = 15
DEFAULT_MAX_DAYS: int = 120
DEFAULT_ONE_WAY: float = 0.001

# W91 preferred default is real staged panels (not synthetic).
DEFAULT_W91_MODE: str = "r2_panels"
ALLOWED_MODES: frozenset[str] = frozenset(
    {"r2_panels", "d1_bars", "synthetic", "nets_only"}
)

# COMPLETE 22 = COMPLETE 21 + fins_earnings_date (W68 tip4 seal).
# Permanent DEFER residual (n=4) stays PARTIAL / tip-only.
COMPLETE_22_DATASETS: tuple[str, ...] = tuple(
    sorted(set(COMPLETE_21_DATASETS) | {"fins_earnings_date"})
)
COMPLETE_22_DATASET_SET: frozenset[str] = frozenset(COMPLETE_22_DATASETS)
# Bar-native primary for CF mass-eval real panels.
PRIMARY_BARS_DATASET: str = "equities_bars_daily"
PRIMARY_INDEX_DATASETS: tuple[str, ...] = (
    "indices_bars_daily_topix",
    "indices_bars_daily",
)
# W93 thicken sidecars staged into r2_panels when COMPLETE-backed local data
# is available (never claim COMPLETE missing). TOPIX remains proxy label only.
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

# Bar-native logics the CF Worker can evaluate without extra panels.
# W91: nky_vol_* need staged index closes (__NKY_PROXY__) in panels.
# W92: opt225_* need staged opt225_regime maps (BaseVol/ATM IV/spread).
# W93: macro_repo_rate_* consume staged repo_rate_regime when present.
CF_BAR_NATIVE_LOGIC_IDS: tuple[str, ...] = (
    "mdh_sticky_momentum",
    "mdh_mean_reversion",
    "xs_rank_ls_sticky",
    "xs_rank_ls_daily",
    "vol_risk_adjusted_mom",
    "vol_breakout_expand",
    "nky_vol_abs_level",
    "nky_vol_term_levels",
    "nky_vol_term_ratio",
    "opt225_basevol_abs_level",
    "opt225_basevol_term_levels",
    "opt225_basevol_term_ratio",
    "opt225_atm_iv_abs_level",
    "opt225_atm_iv_term_levels",
    "opt225_atm_iv_term_ratio",
    "opt225_iv_base_spread_abs",
    "opt225_iv_base_spread_change",
    "macro_repo_rate_change",
    "macro_repo_rate_level",
)

# Lite multi-period shards (W90 residual; synthetic / tip smoke).
DEFAULT_LITE_PERIODS: tuple[dict[str, str], ...] = (
    {"period_id": "p2024_q4", "start": "2024-10-01", "end": "2024-12-27"},
    {"period_id": "p2025_q1", "start": "2025-01-06", "end": "2025-03-28"},
    {"period_id": "p2025_q2", "start": "2025-04-01", "end": "2025-06-27"},
    {"period_id": "p2025_q3", "start": "2025-07-01", "end": "2025-09-26"},
    {"period_id": "p2025_q4", "start": "2025-10-01", "end": "2025-12-26"},
    {"period_id": "p2026_h1", "start": "2026-01-05", "end": "2026-06-30"},
)

# W91 real multi-year windows (≥6; longer than W90 Q4-only smoke when data allows).
# Full-prefer 2015/19/21/23 from W64 COMPLETE-backed mirrors; Q4 for 2017/2025.
DEFAULT_REAL_MULTIYEAR_PERIODS: tuple[dict[str, Any], ...] = (
    {
        "period_id": "y2015_full",
        "year": 2015,
        "period_start": "2015-01-05",
        "period_end": "2015-10-21",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2017_q4",
        "year": 2017,
        "period_start": "2017-09-01",
        "period_end": "2017-12-29",
        "window_kind": "q4",
    },
    {
        "period_id": "y2019_full",
        "year": 2019,
        "period_start": "2019-01-04",
        "period_end": "2019-10-18",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2021_full",
        "year": 2021,
        "period_start": "2021-01-04",
        "period_end": "2021-10-15",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2023_full",
        "year": 2023,
        "period_start": "2023-01-04",
        "period_end": "2023-10-13",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2025_q4",
        "year": 2025,
        "period_start": "2025-09-01",
        "period_end": "2025-12-29",
        "window_kind": "q4",
    },
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WRANGLER = (
    _REPO_ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
_WORKER_DIR = _REPO_ROOT / "platform" / "workers" / "research-mass-eval"
_WORKER_CONFIG = _WORKER_DIR / "wrangler.toml"


class CfMassEvalError(RuntimeError):
    """CF mass-eval job failed."""


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "continuous_paper": CONTINUOUS_PAPER,
        "live_orders": False,
        "s1_s5_unreject": False,
        "simple_daily_sign_as_diversity": False,
        "frozen_defaults_retuned": False,
        "factory_version": MASS_FACTORY_VERSION,
    }


def resolve_research_run_token() -> str | None:
    """Token that gates the mass-eval Worker (reuses ingestion run token)."""
    for env_name in (
        "RESEARCH_RUN_TOKEN",
        "INGESTION_RUN_TOKEN",
        "MASS_EVAL_RUN_TOKEN",
    ):
        v = (os.environ.get(env_name) or "").strip()
        if v:
            return v
    for name in ("ingestion_run_token", "data_export_token"):
        p = Path.home() / ".config" / "quant-platform" / name
        if p.is_file():
            try:
                t = p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
                if t:
                    return t
            except OSError:
                continue
    return None


def design_mass_factory_paths(job_id: str) -> dict[str, Any]:
    jid = str(job_id).strip() or "unknown"
    prefix = f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}"
    return {
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "prefix": prefix,
        "job_id": jid,
        "manifest_r2_key": f"{prefix}/manifest.json",
        "input_plan_r2_key": f"{prefix}/input_plan.json",
        "batch_summary_r2_key": f"{prefix}/batch_summary.json",
        "results_r2_key": f"{prefix}/results.json",
        "screens_r2_key": f"{prefix}/screens.json",
        "ranking_r2_key": f"{prefix}/ranking.json",
    }


def default_logic_specs(
    logic_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Build CF-ready logic specs from catalog templates."""
    ids = list(logic_ids) if logic_ids is not None else list(CF_BAR_NATIVE_LOGIC_IDS)
    out: list[dict[str, Any]] = []
    for lid in ids:
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            out.append(
                {
                    "logic_id": lid,
                    "family_id": "unknown",
                    "params": {},
                    "thesis": "",
                    "signal_definition": "",
                    "position_rule": "",
                    "datasets_used": [],
                }
            )
            continue
        out.append(
            {
                "logic_id": tpl.logic_id,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "thesis": tpl.thesis,
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "logic_fingerprint": tpl.logic_fingerprint(),
            }
        )
    return out


def normalize_period_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize period dict to worker shape (period_start/end + year)."""
    p = dict(raw)
    pid = str(p.get("period_id") or p.get("id") or "period")
    start = (
        p.get("period_start")
        or p.get("start")
        or ""
    )
    end = p.get("period_end") or p.get("end") or ""
    year = p.get("year")
    if year is None and start:
        try:
            year = int(str(start)[:4])
        except ValueError:
            year = None
    if year is None:
        # try parse from period_id like y2015_full
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
    return {
        "wave": CF_MASS_EVAL_WAVE,
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
            "History research must exclude permanent DEFER (bars_am, "
            "earn_cal, master, OTC tip-island)."
        ),
        "bars_source_for_w91": (
            "Local R2 mirrors of structured/jsonl equities_bars_daily "
            "(W63 Q4 + W64 full) staged to quant-structured under "
            "research/mass_eval/job={id}/panels/ for mode=r2_panels. "
            "D1 tip (jquants_records) is hot-window only (~2026-07..08)."
        ),
        "thicken_note_w93": (
            "W93 stages denser r2_panels sidecars when COMPLETE-backed "
            "local sqlite/mirrors are available: markets_calendar, "
            "jsda_tokyo_repo_rates, markets_margin_interest, "
            "markets_short_ratio, fins_summary, plus TOPIX proxy label. "
            "Never claim COMPLETE data missing."
        ),
    }


def inventory_cf_panel_wiring() -> dict[str, Any]:
    """Per-COMPLETE-22 wiring status for CF mass-eval panels / factory logics.

    Status values:
      * wired_on_cf — staged onto r2_panels and CF worker eval consumes it
      * local_only — COMPLETE; local factory uses; CF eval factor path absent
        (may still be staged as panel sidecar for future/thicken)
      * not_yet — COMPLETE exists; not required by current CF factory logics
        (or only tip/secondary); do not claim missing
    """
    rows: dict[str, dict[str, Any]] = {
        "equities_bars_daily": {
            "status": "wired_on_cf",
            "reason": (
                "Primary bars panel payload for all CF bar-native logics "
                "(mdh/xs/vol/opt225/macro)."
            ),
            "factory_logics": [
                "mdh_*",
                "xs_*",
                "vol_*",
                "nky_vol_*",
                "opt225_*",
                "macro_repo_rate_*",
            ],
        },
        "indices_bars_daily_topix": {
            "status": "wired_on_cf",
            "reason": (
                "Staged as __NKY_PROXY__ + nky_vol_series for CF nky_vol_*; "
                "explicitly labeled TOPIX proxy/compare only (not primary "
                "Nikkei vol SoT — that is options_225)."
            ),
            "proxy_label": "TOPIX",
            "factory_logics": ["nky_vol_*"],
        },
        "indices_bars_daily": {
            "status": "local_only",
            "reason": (
                "COMPLETE generic indices bars; CF/nky path prefers "
                "indices_bars_daily_topix as TOPIX proxy label."
            ),
            "factory_logics": [],
        },
        "derivatives_bars_daily_options_225": {
            "status": "wired_on_cf",
            "reason": (
                "Canonical Nikkei vol SoT staged as opt225_regime / "
                "base_vol_series / atm_iv_series / iv_base_spread (W92)."
            ),
            "factory_logics": ["opt225_*"],
        },
        "derivatives_bars_daily_options": {
            "status": "not_yet",
            "reason": (
                "COMPLETE options chain (non-225); factory CF path uses "
                "options_225 canonical SoT. Not required for current CF logics."
            ),
            "factory_logics": [],
        },
        "derivatives_bars_daily_futures": {
            "status": "local_only",
            "reason": (
                "COMPLETE futures; local nky/NK225F compare path may use; "
                "CF stages TOPIX proxy, not futures primary."
            ),
            "factory_logics": [],
        },
        "markets_calendar": {
            "status": "wired_on_cf",
            "reason": (
                "W93 thicken: staged as calendar HolDiv map on r2_panels; "
                "available to CF consumers / trading-day filters."
            ),
            "factory_logics": ["* (session calendar)"],
        },
        "jsda_tokyo_repo_rates": {
            "status": "wired_on_cf",
            "reason": (
                "W93 thicken: staged repo_rate_regime (level + curve spread); "
                "CF macro_repo_rate_change/level consume when present."
            ),
            "factory_logics": [
                "macro_repo_rate_change",
                "macro_repo_rate_level",
                "rate_abs_level_xs",
                "rate_curve_shape_xs",
                "mf_value_mom_rate",
            ],
            "cf_eval_note": (
                "macro_repo_* wired on CF; rate_* XS / mf_* remain local_only "
                "factor legs (CF falls back to MDH unless nets_only)."
            ),
        },
        "markets_margin_interest": {
            "status": "local_only",
            "reason": (
                "COMPLETE flow SoT. W93 stages compact margin level/change "
                "by code on r2_panels; CF flow factor eval not-yet "
                "(local factory flow_* logics)."
            ),
            "factory_logics": [
                "flow_margin_pressure",
                "flow_margin_short_hard",
                "flow_margin_short_soft",
                "mf_flow_price",
            ],
            "staged_on_panel": True,
        },
        "markets_short_ratio": {
            "status": "local_only",
            "reason": (
                "COMPLETE short-flow SoT. W93 stages section-0050 "
                "short_ratio_by_date on panels; CF flow confirm eval not-yet."
            ),
            "factory_logics": [
                "flow_margin_short_hard",
                "flow_margin_short_soft",
            ],
            "staged_on_panel": True,
        },
        "fins_summary": {
            "status": "local_only",
            "reason": (
                "COMPLETE fund SoT. W93 stages compact disclosure events "
                "for panel codes; CF fund/value factor eval not-yet "
                "(local fund_* / mf_*)."
            ),
            "factory_logics": [
                "fund_value_only",
                "fund_value_mom_agree",
                "fund_value_mom_agree_slow",
                "mf_value_mom_rate",
            ],
            "staged_on_panel": True,
        },
        "fins_earnings_date": {
            "status": "local_only",
            "reason": (
                "COMPLETE; thickens local event calendar with fins_summary. "
                "Not separately staged on CF panels (fund sidecar uses "
                "fins_summary primary)."
            ),
            "factory_logics": ["event_post_* (local)"],
        },
        "fins_details": {
            "status": "not_yet",
            "reason": (
                "COMPLETE details; current factory fund logics use "
                "fins_summary PIT value scores, not details panels."
            ),
            "factory_logics": [],
        },
        "fins_dividend": {
            "status": "not_yet",
            "reason": (
                "COMPLETE dividend; not required by current CF/factory "
                "bar-native or fund template set."
            ),
            "factory_logics": [],
        },
        "equities_investor_types": {
            "status": "not_yet",
            "reason": (
                "COMPLETE investor-type flow; not in current CF factory "
                "logic templates (distinct from margin/short flow_*)."
            ),
            "factory_logics": [],
        },
        "markets_breakdown": {
            "status": "not_yet",
            "reason": "COMPLETE market breakdown; not wired into CF factory logics.",
            "factory_logics": [],
        },
        "markets_margin_alert": {
            "status": "not_yet",
            "reason": (
                "COMPLETE margin alert; factory flow_* uses "
                "markets_margin_interest levels, not alert flags."
            ),
            "factory_logics": [],
        },
        "markets_short_sale_report": {
            "status": "not_yet",
            "reason": (
                "COMPLETE short-sale report; factory short confirm uses "
                "markets_short_ratio section series."
            ),
            "factory_logics": [],
        },
        "edinet_cross_shareholdings": {
            "status": "not_yet",
            "reason": "COMPLETE EDINET; not in current CF mass-eval factory logics.",
            "factory_logics": [],
        },
        "edinet_large_volume_shareholders": {
            "status": "not_yet",
            "reason": "COMPLETE EDINET; not in current CF mass-eval factory logics.",
            "factory_logics": [],
        },
        "edinet_major_shareholders": {
            "status": "not_yet",
            "reason": "COMPLETE EDINET; not in current CF mass-eval factory logics.",
            "factory_logics": [],
        },
        "jsda_corporate_bond_transactions": {
            "status": "not_yet",
            "reason": (
                "COMPLETE JSDA corporate-bond prints; rate path uses "
                "jsda_tokyo_repo_rates funding SoT."
            ),
            "factory_logics": [],
        },
    }
    # Ensure every COMPLETE-22 id is present (fail closed on drift).
    missing = [d for d in COMPLETE_22_DATASETS if d not in rows]
    extra = [d for d in rows if d not in COMPLETE_22_DATASET_SET]
    if missing or extra:
        raise RuntimeError(
            f"inventory_cf_panel_wiring drift missing={missing} extra={extra}"
        )
    counts = {"wired_on_cf": 0, "local_only": 0, "not_yet": 0}
    for row in rows.values():
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    return {
        "wave": CF_MASS_EVAL_WAVE,
        "version": CF_MASS_EVAL_VERSION,
        "dataset_complete_n": len(COMPLETE_22_DATASETS),
        "status_counts": counts,
        "datasets": rows,
        "thicken_panel_datasets": list(THICKEN_PANEL_DATASETS),
        "cf_bar_native_logic_ids": list(CF_BAR_NATIVE_LOGIC_IDS),
        "freezes": _freeze(),
        "note": (
            "COMPLETE data is never 'missing'. Status describes CF panel "
            "wiring / factory-logic consumption only. W93 thickens calendar "
            "+ rate + flow + fund sidecars onto r2_panels when available."
        ),
    }


def _load_markets_calendar_map(
    *,
    start: str | None,
    end: str | None,
    sqlite_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compact markets_calendar HolDiv map for one period window."""
    import sqlite3

    from research.class_hyp_eval import DEFAULT_SQLITE

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
            # HolDiv 0/1 typically trading-ish; keep raw + trading list for 0.
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
    """Build compact rate/flow/fund/calendar sidecars for denser CF panels.

    Uses COMPLETE-backed local sqlite / mirrors. Gaps disclosed; no invent/ffill.
    """
    from research.class_hyp_eval import (
        DEFAULT_SQLITE,
        build_repo_curve_series,
        load_fins_events_from_sqlite,
        load_margin_from_sqlite,
        load_margin_ndjson,
        load_repo_rows_all_tenors_from_sqlite,
        load_repo_rows_from_sqlite,
        load_short_ratio_series_from_sqlite,
        resolve_margin_path,
    )
    from research.cost_models import load_repo_rate_series_from_rows

    db = Path(sqlite_path) if sqlite_path else DEFAULT_SQLITE
    p_start = str(period.get("period_start") or period.get("start") or "")[:10]
    p_end = str(period.get("period_end") or period.get("end") or "")[:10]
    # Small burn-in for rate/flow change regimes.
    burn_start = p_start
    if p_start:
        try:
            y, m, d = int(p_start[:4]), int(p_start[5:7]), int(p_start[8:10])
            # naive ~90d lookback by month step (good enough for staging window)
            m -= 3
            while m <= 0:
                m += 12
                y -= 1
            burn_start = f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            burn_start = p_start

    out: dict[str, Any] = {
        "thicken_wave": CF_MASS_EVAL_WAVE,
        "thicken_version": CF_MASS_EVAL_VERSION,
    }

    # --- markets_calendar ---
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

    # --- jsda_tokyo_repo_rates ---
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
        # Clip to period with burn kept for change calc.
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

    # --- markets_margin_interest (flow) ---
    try:
        margin_levels: dict[str, list[tuple[str, float]]] = {}
        margin_source = "local_sqlite_jquants_records"
        pid = str(period.get("period_id") or "")
        margin_path = resolve_margin_path(pid) if pid else None
        if margin_path is not None and Path(margin_path).exists():
            margin_levels = load_margin_ndjson(margin_path, codes=codes)
            margin_source = f"complete22_mirror:{Path(margin_path).name}"
        if not margin_levels:
            margin_levels = load_margin_from_sqlite(
                db,
                codes=codes,
                start=burn_start or None,
                end=p_end or None,
            )
            margin_source = "local_sqlite_jquants_records"
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

    # --- markets_short_ratio (attach into flow_regime) ---
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

    # --- fins_summary (fund) ---
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
                        "bps": ev.get("bps"),
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
                "CF fund factor eval remains local_only; staging thickens "
                "panels for future / nets_only paths."
            ),
        }
    except Exception as exc:  # pragma: no cover
        out["fund_regime"] = {
            "dataset": "fins_summary",
            "status": "error",
            "error": str(exc),
        }

    # TOPIX proxy label (index already staged as __NKY_PROXY__ / nky_vol_series).
    out["index_proxy"] = {
        "dataset": "indices_bars_daily_topix",
        "label": "TOPIX",
        "role": "nky_vol_proxy_compare_only",
        "note": (
            "TOPIX closes staged as __NKY_PROXY__ for nky_vol_* only. "
            "Canonical Nikkei vol SoT remains derivatives_bars_daily_options_225."
        ),
    }

    # Compact counts for stage_meta / logs (avoid dumping full maps twice).
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
    from research.class_hyp_eval import (
        DEFAULT_EVAL_CODES,
        bars_rich_to_close_panel,
        load_bars_ndjson_rich,
        resolve_bars_path,
    )

    p = normalize_period_row(period)
    pid = str(p["period_id"])
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    )
    selected = selected[: int(max_codes)]
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
    close = bars_rich_to_close_panel(rich)
    bars_json: dict[str, list[list[Any]]] = {
        code: [[d, float(px)] for d, px in pairs]
        for code, pairs in close.items()
        if pairs
    }
    # W91: stage Nikkei-proxy index closes as reserved code for CF pure-TS
    # index_vol_regime eval (filtered out of CS universe in worker).
    nky_meta: dict[str, Any] = {}
    try:
        from research.class_hyp_eval import load_nky_vol_series_from_sqlite

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
        # include lookback burn-in for long RV window
        if closes_by:
            all_pairs = sorted(closes_by.items())
            # keep last max_days*2 or full lookback around window
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
                    # Stage compact RV maps for CF pure-TS (avoid recompute drift).
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

    # W92: stage options_225 BaseVol / ATM IV / spread regime maps (canonical SoT).
    opt225_meta: dict[str, Any] = {}
    try:
        from research.class_hyp_eval import load_opt225_regime_bundle_for_eval

        opt225 = load_opt225_regime_bundle_for_eval()
        if opt225:
            # Compact maps only (drop bulky level_by_date duplicates when staging).
            compact: dict[str, Any] = {
                "spread_convention": opt225.get("spread_convention"),
                "units": opt225.get("units"),
                "dataset": opt225.get("dataset"),
                "version": opt225.get("version"),
            }
            for kind in ("basevol", "atm_iv", "spread", "spread_change"):
                ser = dict(opt225.get(kind) or {})
                if not ser:
                    continue
                compact[kind] = {
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
            # Explicit by-date series aliases requested by W92 CF wire.
            base_vol_series = dict(
                (compact.get("basevol") or {}).get("rv_abs_by_date") or {}
            )
            atm_iv_series = dict(
                (compact.get("atm_iv") or {}).get("rv_abs_by_date") or {}
            )
            iv_base_spread = dict(
                (compact.get("spread") or {}).get("rv_abs_by_date") or {}
            )
            opt225_meta = {
                "opt225_regime": compact,
                "base_vol_series": base_vol_series,
                "atm_iv_series": atm_iv_series,
                "iv_base_spread": iv_base_spread,
                "opt225_dataset": "derivatives_bars_daily_options_225",
                "opt225_role": "canonical_nky_vol_sot",
                "opt225_spread_convention": compact.get("spread_convention")
                or "atm_iv - base_vol",
                "opt225_n_base_vol": len(base_vol_series),
                "opt225_n_atm_iv": len(atm_iv_series),
                "opt225_n_spread": len(iv_base_spread),
            }
    except Exception as exc:  # pragma: no cover - best-effort
        opt225_meta = {"opt225_error": str(exc)}

    # W93: prefer-wire COMPLETE sidecars into staged panels (compact maps).
    # Worker may ignore unknown keys; local / future CF rate legs consume them.
    thicken_meta = _build_thicken_panel_sidecars(
        period=p,
        codes=selected,
        max_days=int(max_days),
    )

    n_days = max(
        (len(v) for k, v in bars_json.items() if not str(k).startswith("__")),
        default=0,
    )
    n_eq = sum(1 for k in bars_json if not str(k).startswith("__"))
    return {
        **p,
        "status": "ok" if n_eq > 0 else "empty_bars",
        "bars": bars_json,
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


def _build_thicken_panel_sidecars(
    *,
    period: Mapping[str, Any],
    codes: Sequence[str],
    max_days: int,
) -> dict[str, Any]:
    """Attach COMPLETE-backed aux maps for W93 panel thickening.

    Delegates to ``_build_thicken_sidecars`` (sqlite + mirror backed) and adds
    compatibility aliases (`repo_rate_by_date`, `thicken_status`, …).

    DONE when sidecar maps are present in panel JSON. Full CF factor-leg eval
    for flow/fund remains local_only; macro_repo_* consumes repo_rate_regime.
    ``max_days`` reserved for future clip policy (sidecars already windowed).
    """
    _ = max_days  # windowing handled inside _build_thicken_sidecars burn/end
    out = _build_thicken_sidecars(period, codes=codes)
    rates = dict((out.get("repo_rate_regime") or {}).get("rates_by_date") or {})
    out["repo_rate_by_date"] = rates
    # Alias rate_by_date inside regime for older consumers.
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
    # Flat aliases used by early W93 drafts / worker loaders.
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
        "jsda_tokyo_repo_rates": (
            "DONE" if rates else "EMPTY"
        ),
        "markets_margin_interest": (
            "DONE" if margin_compact else "EMPTY"
        ),
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
        "cf_worker_flow_fund_factor_legs_consume_sidecars",
        "rate_abs_level_xs_and_mf_on_cf_pure_ts",
    ]
    out["panel_thicken"] = True
    return out


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
) -> dict[str, Any]:
    """Build real multi-year panels and put under job-scoped R2 prefix.

    Keys: research/mass_eval/job={id}/panels/{period_id}.json
    """
    jid = str(job_id).strip() or "unknown"
    period_list = [
        normalize_period_row(p)
        for p in (periods or DEFAULT_REAL_MULTIYEAR_PERIODS)
    ]
    prefix = f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/panels"
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
        "wave": CF_MASS_EVAL_WAVE,
        "dry_run": bool(dry_run),
    }


def build_cf_mass_eval_job_spec(
    *,
    job_id: str | None = None,
    logic_ids: Sequence[str] | None = None,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    extra_logics: Sequence[Mapping[str, Any]] | None = None,
    mode: str = DEFAULT_W91_MODE,
    panels_prefix: str | None = None,
) -> dict[str, Any]:
    """Declarative job payload for the CF mass-eval Worker."""
    mode_s = str(mode or DEFAULT_W91_MODE).strip()
    if mode_s not in ALLOWED_MODES:
        raise CfMassEvalError(
            f"mode must be one of {sorted(ALLOWED_MODES)}, got {mode_s!r}"
        )
    jid = str(job_id or f"w91-real-{uuid4().hex[:12]}")
    paths = design_mass_factory_paths(jid)
    logics = default_logic_specs(logic_ids)
    if extra_logics:
        for raw in extra_logics:
            logics.append(dict(raw))
    default_periods: Sequence[Mapping[str, Any]] = (
        DEFAULT_REAL_MULTIYEAR_PERIODS
        if mode_s in {"r2_panels", "d1_bars"}
        else DEFAULT_LITE_PERIODS
    )
    period_rows = [
        normalize_period_row(p) for p in (periods or default_periods)
    ]
    pfx = panels_prefix or f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/panels"
    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "job_id": jid,
        "seed": int(seed),
        "mode": mode_s,
        "panels_prefix": pfx,
        "logics": logics,
        "periods": period_rows,
        "max_codes": int(max_codes),
        "max_days": int(max_days),
        "one_way_cost": float(one_way_cost),
        "artifact": paths,
        "datasets": {
            "primary_bars": PRIMARY_BARS_DATASET,
            "complete_22": list(COMPLETE_22_DATASETS),
            "permanent_defer": sorted(PERMANENT_DEFER_DATASETS),
        },
        "shard_policy": {
            "kind": (
                "real_multiyear_r2_panels"
                if mode_s == "r2_panels"
                else (
                    "d1_tip_bars"
                    if mode_s == "d1_bars"
                    else "lite_multi_period"
                )
            ),
            "note": (
                f"mode={mode_s}; ≤{max_codes} codes × ≤{max_days} days × "
                f"{len(period_rows)} periods × {len(logics)} logics. "
                "Heavy multi-year stays local for promising survivors. "
                "W91 default is real staged panels (not synthetic)."
            ),
        },
        "freezes": _freeze(),
        "mass_research": MASS_RESEARCH,
        "ready_declared": False,
        "operational_go": False,
        "continuous_paper": CONTINUOUS_PAPER,
    }


def invoke_cf_mass_eval_worker(
    job_spec: Mapping[str, Any],
    *,
    worker_url: str = DEFAULT_WORKER_URL,
    token: str | None = None,
    timeout: int = 120,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """POST job to CF Worker; return parsed JSON response."""
    url = worker_url.rstrip("/") + "/v1/mass-eval"
    tok = (token if token is not None else resolve_research_run_token()) or ""
    body = json.dumps(dict(job_spec), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "quant-platform-w91-cf-mass-eval/1.0",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Research-Run-Token"] = tok
        headers["X-Mass-Eval-Token"] = tok
        headers["X-Ingestion-Token"] = tok

    t0 = time.perf_counter()
    if http_post is not None:
        raw_resp = http_post(url=url, body=body, headers=headers)
        latency = time.perf_counter() - t0
        if isinstance(raw_resp, Mapping):
            return {
                **dict(raw_resp),
                "invoke_latency_sec": round(latency, 3),
                "worker_url": url,
            }
        text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
        return {
            **json.loads(text),
            "invoke_latency_sec": round(latency, 3),
            "worker_url": url,
        }

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:2000]
        except Exception:
            detail = str(exc)
        raise CfMassEvalError(
            f"CF mass-eval HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CfMassEvalError(f"CF mass-eval network error: {exc}") from exc
    latency = time.perf_counter() - t0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CfMassEvalError(
            f"CF mass-eval non-json (HTTP {status}): {raw[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise CfMassEvalError("CF mass-eval response not an object")
    payload["invoke_latency_sec"] = round(latency, 3)
    payload["worker_url"] = url
    payload["http_status"] = status
    return payload


def deploy_cf_mass_eval_worker(
    *,
    wrangler: str | Path | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Deploy the mass-eval Worker via wrangler (best-effort)."""
    wr = Path(wrangler) if wrangler else _DEFAULT_WRANGLER
    if not wr.is_file():
        # try npx wrangler from worker dir node_modules after install
        alt = _WORKER_DIR / "node_modules" / ".bin" / "wrangler"
        wr = alt if alt.is_file() else wr
    if not wr.is_file():
        raise CfMassEvalError(f"wrangler not found: {wr}")
    if not _WORKER_CONFIG.is_file():
        raise CfMassEvalError(f"worker config missing: {_WORKER_CONFIG}")
    proc = subprocess.run(
        [str(wr), "deploy", f"--config={_WORKER_CONFIG}"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_WORKER_DIR),
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise CfMassEvalError(
            f"wrangler deploy failed rc={proc.returncode}: {combined[-2000:]}"
        )
    # parse workers.dev URL if present
    url = DEFAULT_WORKER_URL
    for line in combined.splitlines():
        if "workers.dev" in line and "https://" in line:
            for part in line.split():
                if part.startswith("https://") and "workers.dev" in part:
                    url = part.strip()
                    break
    return {
        "status": "deployed",
        "worker_url": url,
        "wrangler_rc": 0,
        "log_tail": combined[-1500:],
    }


def put_local_fallback_artifacts(
    job_spec: Mapping[str, Any],
    result_body: Mapping[str, Any],
    *,
    r2_put: Callable[..., Mapping[str, Any]] | None = None,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Write job artifacts to R2 (or stage) from the driver side.

    Used after a successful Worker response (mirror) or when the Worker
    already wrote R2 (driver records the keys).
    """
    paths = design_mass_factory_paths(str(job_spec.get("job_id") or "unknown"))
    put_fn = r2_put or (
        lambda bucket, key, body: default_r2_put(
            bucket,
            key,
            body,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )
    )
    puts: list[dict[str, Any]] = []
    artifacts = {
        paths["manifest_r2_key"]: {
            "job_id": job_spec.get("job_id"),
            "version": CF_MASS_EVAL_VERSION,
            "wave": CF_MASS_EVAL_WAVE,
            "artifact": paths,
            **_freeze(),
        },
        paths["input_plan_r2_key"]: dict(job_spec),
        paths["batch_summary_r2_key"]: dict(result_body),
    }
    if "results" in result_body:
        artifacts[paths["results_r2_key"]] = result_body.get("results")
    if "screens" in result_body:
        artifacts[paths["screens_r2_key"]] = result_body.get("screens")
    if "ranking" in result_body:
        artifacts[paths["ranking_r2_key"]] = result_body.get("ranking")

    for key, obj in artifacts.items():
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        meta = put_fn(RESEARCH_ARTIFACT_BUCKET, key, body)
        puts.append(dict(meta) if isinstance(meta, Mapping) else {"key": key})
    return puts


def run_cf_mass_eval_job(
    *,
    job_id: str | None = None,
    logic_ids: Sequence[str] | None = None,
    extra_logics: Sequence[Mapping[str, Any]] | None = None,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    mode: str = DEFAULT_W91_MODE,
    stage_panels: bool | None = None,
    worker_url: str = DEFAULT_WORKER_URL,
    deploy_if_needed: bool = True,
    mirror_r2_from_driver: bool = True,
    dry_run_r2: bool = False,
    staging_dir: str | Path | None = None,
    http_post: Callable[..., Any] | None = None,
    skip_invoke: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Build → stage real panels (r2_panels) → deploy → invoke CF job.

    W91 default ``mode=r2_panels`` (real COMPLETE-backed multi-year panels).
    Returns a pack with job_id, status, counts, artifact paths, and the
    Worker response body.
    """
    t0 = time.perf_counter()
    mode_s = str(mode or DEFAULT_W91_MODE).strip()
    do_stage = (
        bool(stage_panels)
        if stage_panels is not None
        else mode_s == "r2_panels"
    )
    jid_pre = str(job_id or f"w91-real-{uuid4().hex[:12]}")
    period_rows = [
        normalize_period_row(p)
        for p in (
            periods
            or (
                DEFAULT_REAL_MULTIYEAR_PERIODS
                if mode_s in {"r2_panels", "d1_bars"}
                else DEFAULT_LITE_PERIODS
            )
        )
    ]

    stage_meta: dict[str, Any] | None = None
    if do_stage:
        stage_meta = stage_real_panels_to_r2(
            jid_pre,
            period_rows,
            max_codes=max_codes,
            max_days=max_days,
            dry_run=dry_run_r2,
            staging_dir=staging_dir,
        )
        if int(stage_meta.get("n_ok") or 0) <= 0 and mode_s == "r2_panels":
            raise CfMassEvalError(
                "r2_panels staging produced 0 ok panels; "
                "check COMPLETE-backed mirrors under "
                ".glm-logs/w0815bd_w63_multiyear and w0815be_w64_cost_full"
            )

    panels_prefix = (
        (stage_meta or {}).get("panels_prefix")
        or f"{RESEARCH_ARTIFACT_PREFIX}/job={jid_pre}/panels"
    )
    spec = build_cf_mass_eval_job_spec(
        job_id=jid_pre,
        logic_ids=logic_ids,
        periods=period_rows,
        max_codes=max_codes,
        max_days=max_days,
        one_way_cost=one_way_cost,
        seed=seed,
        extra_logics=extra_logics,
        mode=mode_s,
        panels_prefix=str(panels_prefix),
    )
    jid = str(spec["job_id"])
    paths = design_mass_factory_paths(jid)
    deploy_meta: dict[str, Any] | None = None
    invoke_error: str | None = None
    worker_resp: dict[str, Any] | None = None
    url = worker_url

    if deploy_if_needed and http_post is None and not skip_invoke:
        try:
            deploy_meta = deploy_cf_mass_eval_worker()
            url = str(deploy_meta.get("worker_url") or url)
        except CfMassEvalError as exc:
            deploy_meta = {"status": "deploy_failed", "error": str(exc)}

    if not skip_invoke:
        try:
            worker_resp = invoke_cf_mass_eval_worker(
                spec,
                worker_url=url,
                http_post=http_post,
                timeout=timeout,
            )
        except CfMassEvalError as exc:
            invoke_error = str(exc)

    r2_puts: list[dict[str, Any]] = []
    status = "ok"
    if worker_resp is None:
        status = "invoke_failed"
    elif worker_resp.get("error") and not worker_resp.get("ok"):
        status = "worker_error"
    elif worker_resp.get("ok") is False:
        status = "worker_error"
    elif str(worker_resp.get("status") or "").lower() not in {
        "ok",
        "completed",
        "success",
        "",
    }:
        # accept missing status if results present
        if not worker_resp.get("results") and not worker_resp.get("n_logics"):
            if worker_resp.get("ok") is not True:
                status = "worker_error"

    # Prefer Worker-reported artifact keys; mirror if requested and needed.
    if worker_resp and mirror_r2_from_driver and status == "ok":
        # If worker already wrote R2, still optionally mirror summary from driver
        # only when worker did not claim r2_puts / r2_keys.
        if not worker_resp.get("r2_puts") and not worker_resp.get("r2_keys"):
            try:
                r2_puts = put_local_fallback_artifacts(
                    spec,
                    worker_resp,
                    dry_run=dry_run_r2,
                    staging_dir=staging_dir,
                )
            except Exception as exc:  # pragma: no cover - network
                r2_puts = [{"status": "put_failed", "error": str(exc)}]
        else:
            r2_puts = list(worker_resp.get("r2_puts") or [])

    n_logics = int(
        (worker_resp or {}).get("n_logics")
        or len(spec.get("logics") or [])
    )
    n_periods = int(
        (worker_resp or {}).get("n_periods")
        or len(spec.get("periods") or [])
    )
    n_evaluated = int(
        (worker_resp or {}).get("n_eval_ok")
        or (worker_resp or {}).get("n_evaluated")
        or 0
    )
    n_survivors = int((worker_resp or {}).get("n_survivors") or 0)
    r2_keys = dict((worker_resp or {}).get("r2_keys") or {})
    if not r2_keys:
        r2_keys = {
            "manifest": paths["manifest_r2_key"],
            "summary": paths["batch_summary_r2_key"],
            "results": paths["results_r2_key"],
            "ranking": paths["ranking_r2_key"],
            "panels_prefix": str(panels_prefix),
        }

    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "status": status,
        "job_id": jid,
        "mode": mode_s,
        "worker_url": url,
        "deploy": deploy_meta,
        "stage_panels": stage_meta,
        "invoke_error": invoke_error,
        "n_logics": n_logics,
        "n_periods": n_periods,
        "n_logic_period_cells": n_logics * n_periods,
        "n_evaluated": n_evaluated,
        "n_eval_ok": n_evaluated,
        "n_survivors": n_survivors,
        "artifact_paths": paths,
        "r2_prefix": f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/",
        "r2_keys": r2_keys,
        "r2_puts": r2_puts,
        "panels_prefix": str(panels_prefix),
        "datasets_used": {
            "primary_bars": PRIMARY_BARS_DATASET,
            "complete_22": list(COMPLETE_22_DATASETS),
            "permanent_defer_excluded": sorted(PERMANENT_DEFER_DATASETS),
        },
        "job_spec": {
            k: spec[k]
            for k in (
                "job_id",
                "version",
                "wave",
                "seed",
                "mode",
                "panels_prefix",
                "max_codes",
                "max_days",
                "one_way_cost",
                "shard_policy",
                "datasets",
            )
            if k in spec
        },
        "logic_ids": [L.get("logic_id") for L in (spec.get("logics") or [])],
        "period_ids": [P.get("period_id") for P in (spec.get("periods") or [])],
        "periods": list(spec.get("periods") or []),
        "worker_response": worker_resp,
        "wall_time_sec": round(time.perf_counter() - t0, 3),
        **_freeze(),
    }


def try_cf_mass_eval_status() -> dict[str, Any]:
    """Status helper replacing the old 'blocked' stub for residual docs."""
    return {
        "status": "implemented",
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "worker": DEFAULT_WORKER_NAME,
        "worker_url": DEFAULT_WORKER_URL,
        "entry": "research.cf_mass_eval_job.run_cf_mass_eval_job",
        "artifact_prefix": f"{RESEARCH_ARTIFACT_PREFIX}/job={{id}}/",
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "default_mode": DEFAULT_W91_MODE,
        "modes": sorted(ALLOWED_MODES),
        "shard_policy": "real_multiyear_r2_panels",
        "bar_native_logics": list(CF_BAR_NATIVE_LOGIC_IDS),
        "complete_22": list(COMPLETE_22_DATASETS),
        "real_multiyear_periods": [
            p["period_id"] for p in DEFAULT_REAL_MULTIYEAR_PERIODS
        ],
        "scale_note": (
            "W91: real COMPLETE-backed multi-year panels staged to R2 "
            "(mode=r2_panels). D1 tip-only via mode=d1_bars. "
            "Heavy multi-year promising-only remains local class_hyp_eval."
        ),
        "synthetic_gap": (
            "rate/mf factor legs still not-yet-implemented on pure-TS CF path; "
            "synthetic remains available for smoke only."
        ),
        **_freeze(),
    }


def run_local_wide_eval_pack(
    *,
    llm_accepted: Sequence[Mapping[str, Any]] | None = None,
    seed: int = 870816,
    synthetic: bool = False,
    max_codes: int = 20,
    max_days: int = 80,
    progress: bool = False,
) -> dict[str, Any]:
    """Wide local eval: catalog after_dedup + LLM-accepted (exclude only impossible).

    Used for the broad results table; CF lite is complementary evidence.
    """
    cfg = MassFactoryConfig(
        seed=seed,
        n=100,
        max_codes=max_codes,
        max_days_per_period=max_days,
        use_q4_periods=True,
    )
    gen = generate_strategy_batch(cfg)
    strategies = list(gen.get("strategies_after_dedup") or [])
    # Merge LLM accepted (by logic_id) without collapsing near-groups
    seen = {str(s.get("logic_id")) for s in strategies}
    extra = 0
    for raw in llm_accepted or []:
        lid = str(raw.get("logic_id") or "")
        if not lid or lid in seen:
            # still include ad-hoc under unique key
            if lid in seen and str(raw.get("source") or "").startswith("profit"):
                continue
            if lid in seen:
                lid = f"{lid}__llm_{extra}"
                raw = {**dict(raw), "logic_id": lid}
        strategies.append(dict(raw))
        seen.add(lid)
        extra += 1

    gen_for_eval = {
        **gen,
        "strategies_after_dedup": strategies,
        "n_after_dedup": len(strategies),
    }

    def _cb(i: int, n: int, sid: str) -> None:
        if progress:
            print(f"[wide-eval] {i}/{n} {sid}", flush=True)

    batch = run_batch_eval(
        gen_for_eval,
        config=cfg,
        synthetic=synthetic,
        progress_cb=_cb if progress else None,
    )
    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "kind": "local_wide_eval",
        "n_strategies": len(strategies),
        "n_catalog_after_dedup": int(gen.get("n_after_dedup") or 0),
        "n_llm_merged": extra,
        "batch": {
            k: batch[k]
            for k in batch
            if k not in {"results"}
        },
        "screens": batch.get("screens"),
        "ranking": batch.get("ranking"),
        "results_compact": [
            {
                "strategy_id": r.get("strategy_id"),
                "logic_id": r.get("logic_id"),
                "family_id": r.get("family_id"),
                "survived": (r.get("screen") or {}).get("survived"),
                "mean_net": r.get("mean_net"),
                "t_stat": r.get("t_stat"),
                "sharpe_period": r.get("sharpe_period"),
                "chosen_sign": r.get("chosen_sign"),
                "n_periods_ok": r.get("n_periods_ok"),
                "reject_reasons": (r.get("screen") or {}).get("reject_reasons"),
            }
            for r in (batch.get("results") or [])
        ],
        **_freeze(),
    }


__all__ = [
    "CF_MASS_EVAL_VERSION",
    "CF_MASS_EVAL_WAVE",
    "CF_BAR_NATIVE_LOGIC_IDS",
    "COMPLETE_22_DATASETS",
    "COMPLETE_22_DATASET_SET",
    "PRIMARY_BARS_DATASET",
    "PRIMARY_INDEX_DATASETS",
    "THICKEN_PANEL_DATASETS",
    "DEFAULT_LITE_PERIODS",
    "DEFAULT_REAL_MULTIYEAR_PERIODS",
    "DEFAULT_W91_MODE",
    "ALLOWED_MODES",
    "DEFAULT_WORKER_URL",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "CfMassEvalError",
    "resolve_research_run_token",
    "design_mass_factory_paths",
    "default_logic_specs",
    "normalize_period_row",
    "inventory_complete22",
    "inventory_cf_panel_wiring",
    "build_real_period_panel",
    "stage_real_panels_to_r2",
    "build_cf_mass_eval_job_spec",
    "invoke_cf_mass_eval_worker",
    "deploy_cf_mass_eval_worker",
    "put_local_fallback_artifacts",
    "run_cf_mass_eval_job",
    "try_cf_mass_eval_status",
    "run_local_wide_eval_pack",
]
