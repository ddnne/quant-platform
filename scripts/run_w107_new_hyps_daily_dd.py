#!/usr/bin/env python3
"""W107 / w0820d Track B — NEW mixed unique_logic hyps with daily_path_DD.

Headline is **new unique_logic** that is **MIXED** (funding / calendar /
cross-section / macro), not an event-filter-only pack and not a W106 repeat.

Weak-template mapping OFF. Catalog remaps of sticky / event_post_disclosure_hold
/ vol_risk_adjusted_mom are **not** headlined. Do **not** build sticky-approx
always-on CS-mom gates.

Modest N=4 (not a count race). Failure constraints ON. 3-default pins
untouched. Survivors research-only: promote_as_main=false · go=false.

If extra datasets cannot be loaded, the row stays **incomplete** — never
approximated into complete.

Examples
--------
    uv run python scripts/run_w107_new_hyps_daily_dd.py \\
        --out-dir .glm-logs/w0820d_w107_otc11_adaptive/
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from statistics import median
from typing import Any, Mapping, Sequence

from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820d_w107_otc11_adaptive"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0820d_w107_hyps_new_logic_20260820.md"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_event_rate_daily_dd as w102  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402
import run_w105_new_hyps_daily_dd as w105  # noqa: E402
import run_w106_new_hyps_daily_dd as w106  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

WAVE = "W107 / w0820d"
W107_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT
PACK_BIAS = "mixed"
ALWAYS_ON_OCCUPANCY_WARN = w106.ALWAYS_ON_OCCUPANCY_WARN

# ---------------------------------------------------------------------------
# 4 NEW unique_logic proposals (NOT event-filter-only; not catalog remaps;
# not hold/mom grids; not sticky-approx always-on CS-mom gates)
# ---------------------------------------------------------------------------
# P1 FUNDING  — overnight LEVEL (tight) fades CS mom (not Δimpulse)
# P2 CALENDAR — month-end invert CS mom (not always-on)
# P3 XS       — high-vol regime, mom among low-vol names (not vol-scaled mom)
# P4 MACRO    — 3M repo LEVEL tight follows CS mom (not 3M−ON Δspread)

NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "overnight_level_cs_tilt",
        "family_id": "overnight_level_cs",
        "kind": "overnight_level_cs_tilt",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "axis": "funding",
        "why_unique": (
            "NEW FUNDING LEVEL: CS mom L-S faded only when same-date overnight "
            "Tokyo repo LEVEL is >= PIT trailing median. Flatten when easy, "
            "median unformed, or overnight missing (no ffill). Not "
            "funding_impulse_cs_tilt (that uses |Δovernight|) and not "
            "event_funding_stress_skip (event book)."
        ),
        "thesis": (
            "Tight overnight *level* (not a large Δ) is when relative-strength "
            "crowds and should be faded. Easy overnight and missing prints "
            "stay flat — occupancy is the tight half, not sticky-always-on."
        ),
        "signal_definition": (
            "enter iff overnight[d] >= PIT median of overnight with date < d "
            "(min_hist=20); tilt = −1 (fade CS mom); missing/unformed → flatten"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank mom L-S × fade tilt on tight-overnight "
            "days; flat when overnight is easy, unformed, or missing same-date"
        ),
        "datasets": [
            "jsda_tokyo_repo_rates",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "min_hist": 20,
            "mode": "overnight_level_cs_tilt",
            "gate": "overnight_ge_pit_trailing_median",
        },
    },
    {
        "logic_id": "month_end_cs_fade",
        "family_id": "month_end_cs",
        "kind": "month_end_cs_fade",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "axis": "calendar",
        "why_unique": (
            "NEW CALENDAR SIGNAL: invert CS mom only on the last 3 bar-calendar "
            "sessions of each calendar month. Flatten all other days. Not sticky "
            "always-on, not a hold/mom grid, not an event filter."
        ),
        "thesis": (
            "Month-end rebalance / window-dressing fades relative-strength. "
            "Take the inverted CS book only on the last three sessions of the "
            "month; stay flat otherwise so occupancy stays sparse."
        ),
        "signal_definition": (
            "month-end days = last 3 dates of YYYY-MM on the bar calendar; "
            "tilt = −1 on those days; else flatten (no invent, no ffill)"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank mom L-S inverted on month-end days; "
            "flat otherwise"
        ),
        "datasets": [
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "month_end_sessions": 3,
            "mode": "month_end_cs_fade",
            "gate": "last_n_sessions_of_calendar_month",
        },
    },
    {
        "logic_id": "xs_low_vol_mom",
        "family_id": "xs_low_vol_mom",
        "kind": "xs_low_vol_mom",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "axis": "cross_section",
        "why_unique": (
            "NEW XS UNIVERSE: in a high CS-vol regime (CS median trailing vol "
            ">= PIT median of that median), rank mom among names whose own "
            "trailing vol is below that day's CS median. Not vol_risk_adjusted_mom "
            "(which scales mom by vol for ranking) and not sticky always-on."
        ),
        "thesis": (
            "When the cross-section is noisy, momentum among the quieter half "
            "is cleaner. Stay flat in low-vol regimes so this is not a sticky "
            "clone with a vol haircut."
        ),
        "signal_definition": (
            "vol = trailing stdev of daily returns (lookback=20, PIT on bars); "
            "cs_med = median vol of names with vol that day; enter iff "
            "cs_med >= PIT median of cs_med (min_hist=20); rank mom among "
            "names with vol < cs_med; <2 names → flatten"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank mom L-S inside the low-vol half on "
            "high CS-vol days; flat otherwise"
        ),
        "datasets": [
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_lookback": 20,
            "min_hist": 20,
            "mode": "xs_low_vol_mom",
            "gate": "cs_median_vol_ge_pit_median_then_low_vol_universe",
        },
    },
    {
        "logic_id": "repo_3m_level_cs",
        "family_id": "repo_3m_level_cs",
        "kind": "repo_3m_level_cs",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "axis": "macro",
        "why_unique": (
            "NEW MACRO LEVEL: CS mom L-S only when same-date 3M Tokyo repo "
            "LEVEL is >= PIT trailing median. Flatten when easy, unformed, or "
            "3M missing (no ffill). Not curve_steepen_impulse_cs (Δ of 3M−ON "
            "spread) and not overnight_level_cs_tilt (ON tenor)."
        ),
        "thesis": (
            "Tight term funding (3M level) is when carry-friendly relative "
            "strength can be followed. Easy 3M and missing prints stay flat."
        ),
        "signal_definition": (
            "enter iff 3M[d] >= PIT median of 3M with date < d (min_hist=20); "
            "tilt = +1 (follow CS mom); missing/unformed → flatten"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank mom L-S on tight-3M days; flat when "
            "3M is easy, unformed, or missing same-date"
        ),
        "datasets": [
            "jsda_tokyo_repo_rates",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "min_hist": 20,
            "mode": "repo_3m_level_cs",
            "gate": "term_3m_ge_pit_trailing_median",
        },
    },
)

KNOWN_WEAK_THESIS = w100.KNOWN_WEAK_THESIS
KNOWN_DEMOTED_OR_WEAK = w100.KNOWN_DEMOTED_OR_WEAK
LOGIC_CATALOG_HEADLINE_BAN = frozenset(
    {
        "xs_rank_ls_sticky",
        "event_post_disclosure_hold",
        "vol_risk_adjusted_mom",
    }
)
W104_UNIQUE_LOGIC_IDS = w106.W104_UNIQUE_LOGIC_IDS
W105_UNIQUE_LOGIC_IDS = w106.W105_UNIQUE_LOGIC_IDS
W106_UNIQUE_LOGIC_IDS = frozenset(
    {
        "funding_impulse_cs_tilt",
        "curve_steepen_impulse_cs",
        "xs_margin_delta_rank",
        "idio_mom_macro_impulse",
        "event_funding_easy_short",
        "event_funding_stress_ls",
        "surprise_xs_rank_flip",
    }
)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _assert_frozen_pins_untouched() -> dict[str, Any]:
    pack = w99._assert_frozen_pins_untouched()
    pack["note"] = "W107 new unique_logic hyps must not mutate 3-default pins"
    return pack


def _month_end_days(dates: Sequence[str], n_last: int) -> set[str]:
    by_ym: dict[str, list[str]] = {}
    for d in dates:
        ds = str(d)[:10]
        if len(ds) < 7:
            continue
        by_ym.setdefault(ds[:7], []).append(ds)
    out: set[str] = set()
    n = max(1, int(n_last))
    for _ym, ds in by_ym.items():
        ds_s = sorted(ds)
        out.update(ds_s[-n:])
    return out


def _trailing_vol_by_date(
    close_by: Mapping[str, float],
    dates: Sequence[str],
    *,
    lookback: int,
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    rets: list[float | None] = []
    prev: float | None = None
    min_n = max(5, int(lookback) // 2)
    for d in dates:
        ds = str(d)[:10]
        c = close_by.get(ds)
        r: float | None = None
        if prev is not None and c is not None and prev != 0.0:
            try:
                fv = (float(c) / float(prev)) - 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                fv = None
            if fv is not None and math.isfinite(fv):
                r = fv
        rets.append(r)
        window = [x for x in rets[-int(lookback) :] if x is not None]
        if len(window) >= min_n:
            m = sum(window) / float(len(window))
            var = sum((x - m) ** 2 for x in window) / float(len(window) - 1)
            out[ds] = math.sqrt(var) if var > 0.0 else 0.0
        else:
            out[ds] = None
        prev = float(c) if c is not None else None
    return out


def evaluate_overnight_level_cs_tilt_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    overnight_by_date: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom faded when overnight LEVEL is tight vs PIT median."""
    from features.class_signals import cross_section_rank_signs

    p = w106._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = w106._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="overnight_ge_pit_trailing_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    extra["pack_bias"] = PACK_BIAS
    overnight = dict(overnight_by_date or {})
    if not overnight:
        return w106._empty_extra(
            spec=spec,
            extra=extra,
            status="missing_overnight_series",
            reason=(
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "overnight-level CS tilt. Not approximated."
            ),
        )

    panel = w100._panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    med_by = w104.pit_median_on_dates(overnight, dates, min_hist=min_hist)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_easy = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        on = overnight.get(d)
        if on is None:
            n_skip_missing += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if float(on) < float(med):
            n_skip_easy += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        n_on += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else -float(sign)
            )

    extra.update(
        {
            **w106._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_easy_overnight": n_skip_easy,
            "n_overnight_prints": len(overnight),
        }
    )
    return w106._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_month_end_cs_fade_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """Invert CS mom on last N bar sessions of each calendar month."""
    from features.class_signals import cross_section_rank_signs

    p = w106._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    n_last = int(
        spec.get("month_end_sessions")
        or p["params"].get("month_end_sessions")
        or 3
    )
    extra = w106._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="last_n_sessions_of_calendar_month",
        extra_dataset="equities_bars_daily",
        data_path="local_real_mirrors+local_sqlite_bars",
    )
    extra["pack_bias"] = PACK_BIAS
    extra["month_end_sessions"] = n_last

    panel = w100._panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    me = _month_end_days(dates, n_last)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        if d not in me:
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        n_on += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else -float(sign)
            )

    extra.update(
        {
            **w106._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_month_end_days": len(me),
        }
    )
    return w106._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_xs_low_vol_mom_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """High CS-vol regime: rank mom among the low-vol half."""
    from features.class_signals import cross_section_rank_signs

    p = w106._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    lookback = int(
        spec.get("vol_lookback") or p["params"].get("vol_lookback") or 20
    )
    extra = w106._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="cs_median_vol_ge_pit_median_then_low_vol_universe",
        extra_dataset="equities_bars_daily",
        data_path="local_real_mirrors+local_sqlite_bars",
    )
    extra["pack_bias"] = PACK_BIAS
    extra["vol_lookback"] = lookback
    extra["not_vol_risk_adjusted_mom"] = True

    panel = w100._panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    close_by = panel["close_by"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    vol_by_code: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        vol_by_code[code] = _trailing_vol_by_date(
            close_by.get(code) or {}, dlist, lookback=lookback
        )

    cs_med_vol: dict[str, float] = {}
    for d in dates:
        vals = []
        for code in dates_by_code:
            v = (vol_by_code.get(code) or {}).get(d)
            if v is not None and math.isfinite(float(v)):
                vals.append(float(v))
        if len(vals) >= 2:
            cs_med_vol[d] = float(median(vals))

    med_by = w104.pit_median_on_dates(cs_med_vol, dates, min_hist=min_hist)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_unformed = 0
    n_skip_quiet = 0
    n_skip_sparse = 0
    n_names_ranked = 0
    for d in dates:
        cs_med = cs_med_vol.get(d)
        pit_med = med_by.get(d)
        if cs_med is None or pit_med is None:
            n_skip_unformed += 1
            n_off += 1
            moms = by_date.get(d) or {}
            for code in moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if float(cs_med) < float(pit_med):
            n_skip_quiet += 1
            n_off += 1
            moms = by_date.get(d) or {}
            for code in moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        scores: dict[str, float] = {}
        moms = by_date.get(d) or {}
        for code, mom in moms.items():
            if mom is None or not math.isfinite(float(mom)):
                continue
            v = (vol_by_code.get(code) or {}).get(d)
            if v is None or not math.isfinite(float(v)):
                continue
            if float(v) < float(cs_med):
                scores[code] = float(mom)
        if len(scores) < 2:
            n_skip_sparse += 1
            n_off += 1
            for code in moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        n_on += 1
        n_names_ranked += len(scores)
        for code in moms:
            sign = ranks.get(code)
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **w106._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_quiet_vol_regime": n_skip_quiet,
            "n_skip_sparse_low_vol": n_skip_sparse,
            "mean_names_on_ranked_days": (
                float(n_names_ranked) / float(n_on) if n_on else 0.0
            ),
        }
    )
    return w106._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_repo_3m_level_cs_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom followed when 3M repo LEVEL is tight vs PIT median."""
    from features.class_signals import cross_section_rank_signs

    p = w106._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = w106._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="term_3m_ge_pit_trailing_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    extra["pack_bias"] = PACK_BIAS
    long_by = dict((curve_series or {}).get("long_rates_by_date") or {})
    if not long_by:
        return w106._empty_extra(
            spec=spec,
            extra=extra,
            status="missing_3m_series",
            reason=(
                "jsda_tokyo_repo_rates 3M series empty — cannot apply "
                "repo-3M-level CS. Not approximated."
            ),
        )

    panel = w100._panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    med_by = w104.pit_median_on_dates(long_by, dates, min_hist=min_hist)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_easy = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        lv = long_by.get(d)
        if lv is None:
            n_skip_missing += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if float(lv) < float(med):
            n_skip_easy += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        n_on += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **w106._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_3m": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_easy_3m": n_skip_easy,
            "n_3m_prints": len(long_by),
        }
    )
    return w106._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def _incomplete_row(
    *,
    logic_id: str,
    window_id: str,
    reason: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gate = evaluate_daily_path_dd_gate(period_net_dd=0.0)
    row = {
        "logic_id": logic_id,
        "window": window_id,
        "n_days": None,
        "daily_path_DD": None,
        "dd_duration": None,
        "recovery_days": None,
        "recovered": None,
        "total_ret_net": None,
        "daily_path_complete": False,
        "daily_path_measured": False,
        "incomplete_reason": reason,
        "promote_as_main": False,
        "go": False,
        "stance": "RESEARCH_ONLY",
        "new_unique_logic": True,
        "catalog": False,
        "pack_bias": PACK_BIAS,
        "gate": {
            "complete": gate.get("complete"),
            "fails": gate.get("fails"),
            "warnings": gate.get("warnings"),
            "period_net_dd_only_pass_forbidden": True,
        },
    }
    if extra:
        row.update(dict(extra))
    return row


def _eval_one_shard(
    *,
    spec: Mapping[str, Any],
    loaded: Mapping[str, Any],
    overnight_by_date: Mapping[str, float],
    curve_series: Mapping[str, Any] | None,
    one_way_cost: float,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    bars = loaded["bars"]
    if lid == "overnight_level_cs_tilt":
        return evaluate_overnight_level_cs_tilt_daily_mtm(
            bars, overnight_by_date, spec=spec, one_way_cost=one_way_cost
        )
    if lid == "month_end_cs_fade":
        return evaluate_month_end_cs_fade_daily_mtm(
            bars, spec=spec, one_way_cost=one_way_cost
        )
    if lid == "xs_low_vol_mom":
        return evaluate_xs_low_vol_mom_daily_mtm(
            bars, spec=spec, one_way_cost=one_way_cost
        )
    if lid == "repo_3m_level_cs":
        return evaluate_repo_3m_level_cs_daily_mtm(
            bars, curve_series, spec=spec, one_way_cost=one_way_cost
        )
    return {
        "status": "unknown_logic",
        "logic_id": lid,
        "daily_path_complete": False,
        "incomplete_reason": f"no min-impl evaluator for {lid}",
    }


def run_unique_logic_daily_dd(
    *,
    out_dir: Path,
    spec: Mapping[str, Any],
    codes: Sequence[str],
    overnight_by_date: Mapping[str, float],
    curve_series: Mapping[str, Any] | None,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in W107_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w107/{lid}] window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_gate_on_win = 0
        n_bar_win = 0
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                log(f"[w107/{lid}]   {pid}: {loaded.get('status')}")
                continue
            pack = _eval_one_shard(
                spec=spec,
                loaded=loaded,
                overnight_by_date=overnight_by_date,
                curve_series=curve_series,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_gate_on_days"] = pack.get("n_gate_on_days")
            summary["n_gated_off_days"] = pack.get("n_gated_off_days")
            summary["occupancy_frac"] = pack.get("occupancy_frac")
            shard_summaries.append(summary)
            n_gate_on_win += int(pack.get("n_gate_on_days") or 0)
            n_bar_win += int(pack.get("n_bar_dates") or 0)
            dlist = list(pack.get("dates") or [])
            nlist = list(pack.get("net_daily") or [])
            glist = list(pack.get("gross_daily") or [])
            if pack.get("status") == "ok" and dlist:
                if not stitch_dates:
                    stitch_dates = list(dlist)
                    stitch_net = list(nlist)
                    stitch_gross = list(glist)
                else:
                    stitch_dates.extend(dlist[1:])
                    stitch_net.extend(nlist[1:])
                    stitch_gross.extend(glist[1:])
            log(
                f"[w107/{lid}]   {pid}: status={pack.get('status')} "
                f"n={summary.get('n_equity_points')} "
                f"gate_on={pack.get('n_gate_on_days')} "
                f"occ={_fmt(pack.get('occupancy_frac'))} "
                f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                f"total_net={_fmt(summary.get('total_return_net'))}"
            )
        occ = (float(n_gate_on_win) / float(n_bar_win)) if n_bar_win else None
        if not stitch_net:
            row = _incomplete_row(
                logic_id=lid,
                window_id=wid,
                reason=(
                    "no ok daily path stitched for this window "
                    f"(n_gate_on={n_gate_on_win})"
                ),
                extra={
                    "data_path": "local_real_mirrors+local_sqlite",
                    "n_gate_on_days": n_gate_on_win,
                    "n_bar_dates": n_bar_win,
                    "occupancy_frac": occ,
                    "shard_summaries": shard_summaries,
                    "new_unique_logic": True,
                    "catalog": False,
                    "axis": spec.get("axis"),
                },
            )
        else:
            stitched = w100._stitch_net(stitch_net, stitch_dates)
            row = w102._window_row_from_stitch(
                logic_id=lid,
                window=w,
                stitched=stitched,
                stitch_net=stitch_net,
                stitch_gross=stitch_gross,
                shard_summaries=shard_summaries,
                extra={
                    "data_path": "local_real_mirrors+local_sqlite",
                    "n_gate_on_days": n_gate_on_win,
                    "n_bar_dates": n_bar_win,
                    "occupancy_frac": occ,
                    "occupancy_always_on_warning": bool(
                        occ is not None and float(occ) >= ALWAYS_ON_OCCUPANCY_WARN
                    ),
                    "new_unique_logic": True,
                    "catalog": False,
                    "catalog_map": None,
                    "why_unique": spec.get("why_unique"),
                    "headline": spec.get("headline"),
                    "axis": spec.get("axis"),
                    "pack_bias": PACK_BIAS,
                },
            )
        rows.append(row)
        _dump(out_dir / f"{lid}_{wid}.json", row)

    _dump(out_dir / f"{lid}_daily_dd.json", rows)
    complete = bool(rows) and all(bool(r.get("daily_path_complete")) for r in rows)
    worst = None
    for r in rows:
        dd = r.get("daily_path_DD")
        if dd is None:
            continue
        if worst is None or float(dd) < float(worst):
            worst = float(dd)
    return {
        "table": rows,
        "logic_id": lid,
        "complete": complete,
        "worst_daily_path_DD": worst,
        "new_unique_logic": True,
        "catalog": False,
        "promote_as_main": False,
        "go": False,
        "pack_bias": PACK_BIAS,
        "axis": spec.get("axis"),
    }


def proposals_for_factory() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in NEW_UNIQUE_LOGIC:
        out.append(
            {
                "logic_id": spec["logic_id"],
                "family_id": spec["family_id"],
                "thesis": spec["thesis"],
                "signal_definition": spec["signal_definition"],
                "position_rule": spec["position_rule"],
                "datasets": list(spec["datasets"]),
                "datasets_used": list(spec["datasets"]),
                "params": dict(spec["params"]),
                "new_unique_logic": True,
                "catalog": False,
                "eval_mapped_to_catalog": False,
                "weak_template_mapping": "OFF",
            }
        )
    return out


def run_hyp_pack(*, out_dir: Path, seed: int, log) -> dict[str, Any]:
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_RESEARCH,
        MassFactoryConfig,
        propose_profit_hypotheses,
    )

    proposals = proposals_for_factory()
    cfg = MassFactoryConfig(seed=int(seed), n=max(20, len(proposals) + 5))
    log(
        f"[w107/B] propose n={len(proposals)} seed={seed} "
        "weak_template_mapping=OFF map_unknown_to_nearest_catalog=false "
        "not_a_count_race=True daily_path_DD_required=True pack_bias=mixed"
    )
    eval_out = propose_profit_hypotheses(
        proposals,
        evaluate=True,
        synthetic=True,
        config=cfg,
    )
    compact = {
        k: eval_out[k]
        for k in eval_out
        if k
        not in {
            "accepted",
            "rejected",
            "eval_results",
            "eval_screens",
            "eval_ranking",
        }
    }
    _dump(out_dir / "hyp_propose_compact.json", compact)
    _dump(out_dir / "hyp_proposals.json", proposals)
    _dump(out_dir / "hyp_accepted.json", eval_out.get("accepted") or [])
    _dump(out_dir / "hyp_rejected.json", eval_out.get("rejected") or [])
    _dump(out_dir / "hyp_eval_screens.json", eval_out.get("eval_screens") or [])
    _dump(out_dir / "hyp_eval_ranking.json", eval_out.get("eval_ranking") or [])

    mapped = []
    skipped_weak = []
    for p in eval_out.get("accepted") or []:
        lid = str(p.get("logic_id") or "")
        if p.get("eval_mapped_to_catalog"):
            mapped.append(lid)
        if lid in LOGIC_CATALOG_HEADLINE_BAN:
            mapped.append(lid)
        if lid in KNOWN_DEMOTED_OR_WEAK or lid in KNOWN_WEAK_THESIS:
            skipped_weak.append(lid)

    n_proposed = int(eval_out.get("n_proposals") or len(proposals))
    n_accepted = int(eval_out.get("n_accepted") or 0)
    n_rejected = int(eval_out.get("n_rejected") or 0)
    n_evaluated = int((eval_out.get("eval") or {}).get("n_strategies_evaluated") or 0)
    n_survivors_period_net = sum(
        1
        for s in (eval_out.get("eval_screens") or [])
        if isinstance(s, Mapping) and s.get("survived")
    )
    summary = {
        "wave": WAVE,
        "track": "B_new_unique_logic_hyps",
        "pack_bias": PACK_BIAS,
        "event_filter_only": False,
        "n_requested": 4,
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_rejected,
        "n_evaluated_factory_synthetic": n_evaluated,
        "n_survivors_period_net": n_survivors_period_net,
        "period_net_is_not_a_pass": True,
        "period_net_dd_only_pass_forbidden": True,
        "factory_note": (
            "Ad-hoc unique family_ids are unknown to catalog dispatch until "
            "family append. Factory synthetic period-net is NOT the unique_logic "
            "eval and cannot pass. daily_path_DD of min-impl is required."
        ),
        "n_skipped_weak_catalog_map": 0,
        "skipped_weak_catalog_targets": skipped_weak,
        "weak_mapped_despite_off": mapped,
        "weak_template_mapping": "OFF",
        "map_unknown_to_nearest_catalog": False,
        "not_a_count_race": True,
        "failure_mode_constraints": [
            "no_sign_flip_single_regime_reliance",
            "no_soft_eq_pressure",
            "no_low_var_t_trust",
            "no_window_only",
            "no_dual_options_level",
            "no_repolish_shape_rate_flow_demoted_fund_slow",
            "no_hold_mom_frac_grid",
            "weak_template_mapping_off",
            "daily_path_DD_required",
            "no_event_filter_only_pack",
            "no_sticky_approx_always_on_gate",
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var", "daily_path_DD"],
        "daily_path_DD_required": True,
        "representative_theses": [
            {
                "logic_id": s["logic_id"],
                "family_id": s["family_id"],
                "axis": s.get("axis"),
                "new_unique_logic": True,
                "catalog": False,
                "catalog_map": None,
                "headline": s.get("headline"),
                "why_unique": s.get("why_unique"),
                "thesis": s["thesis"],
            }
            for s in NEW_UNIQUE_LOGIC
        ],
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "promote_as_main": False,
        "go": False,
        "seed": int(seed),
        "do_not_headline_catalog_remap": list(LOGIC_CATALOG_HEADLINE_BAN),
        "do_not_repeat_w104_ids": list(W104_UNIQUE_LOGIC_IDS),
        "do_not_repeat_w105_ids": list(W105_UNIQUE_LOGIC_IDS),
        "do_not_repeat_w106_ids": list(W106_UNIQUE_LOGIC_IDS),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w107/B] pack proposed={n_proposed} accepted={n_accepted} "
        f"factory_eval={n_evaluated} period_net_survivors={n_survivors_period_net} "
        f"weak_map_off mapped={mapped or '[]'} pack_bias={PACK_BIAS}"
    )
    return {"summary": summary, "eval_out": eval_out}


def inspect_unique_logic_datasets(
    *,
    codes: Sequence[str],
    sqlite_path: Path,
    log,
) -> dict[str, Any]:
    extra = w106.inspect_unique_logic_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    curve = extra.get("curve_series") or {}
    long_by = dict(curve.get("long_rates_by_date") or {}) if isinstance(curve, Mapping) else {}
    extra["n_3m"] = len(long_by)
    extra["term_3m_date_min"] = min(long_by) if long_by else None
    extra["term_3m_date_max"] = max(long_by) if long_by else None
    log(
        f"[w107] 3m n={len(long_by)} "
        f"{extra['term_3m_date_min']}..{extra['term_3m_date_max']}"
    )
    return extra


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--seed", type=int, default=8908207)
    p.add_argument("--sqlite", type=str, default=str(SQLITE_DEFAULT))
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-daily", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w107_new_hyps_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w107] pins_untouched={pins['pins_untouched']}")
    log(
        "[w107] promote_as_main=false go=false hold_mom_grid=false "
        "dispersion_thresh_grid=false weak_template_mapping=OFF "
        "period_net_dd_only=forbidden complete≠GO "
        "pack_bias=mixed (funding/calendar/xs/macro, NOT event-filter-only) "
        "no sticky-approx always-on gate "
        "Grok implementer (this wave)."
    )

    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(args.max_codes)]
    sqlite_path = Path(args.sqlite)
    extra = inspect_unique_logic_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    extra_dump = {
        k: v
        for k, v in extra.items()
        if k
        not in {
            "fins_events",
            "curve_series",
            "overnight_by_date",
            "margin_by_code",
            "topix_by_date",
        }
    }
    extra_dump["pack_bias"] = PACK_BIAS
    extra_dump["event_filter_only"] = False
    _dump(out_dir / "extra_dataset_wiring.json", extra_dump)

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_hyp_pack(out_dir=out_dir, seed=int(args.seed), log=log)
    else:
        log("[w107/B] propose skipped")

    daily_packs: dict[str, Any] = {}
    if not args.skip_daily:
        overnight = extra.get("overnight_by_date") or {}
        curve = extra.get("curve_series")
        for spec in NEW_UNIQUE_LOGIC:
            lid = str(spec["logic_id"])
            daily_packs[lid] = run_unique_logic_daily_dd(
                out_dir=out_dir,
                spec=spec,
                codes=codes,
                overnight_by_date=overnight,
                curve_series=curve,
                max_days=int(args.max_days),
                one_way_cost=float(args.one_way_cost),
                log=log,
            )
    else:
        log("[w107/B] daily_path_DD skipped")

    compact: list[dict[str, Any]] = []
    for spec in NEW_UNIQUE_LOGIC:
        lid = str(spec["logic_id"])
        pack = daily_packs.get(lid) or {}
        for row in pack.get("table") or []:
            compact.append(
                {
                    "logic_id": row.get("logic_id"),
                    "new_unique_logic": True,
                    "catalog": False,
                    "catalog_map": None,
                    "headline": spec.get("headline"),
                    "axis": spec.get("axis"),
                    "pack_bias": PACK_BIAS,
                    "window": row.get("window"),
                    "n_days": row.get("n_days"),
                    "daily_path_DD": row.get("daily_path_DD"),
                    "dd_duration": row.get("dd_duration"),
                    "recovery_days": row.get("recovery_days"),
                    "recovered": row.get("recovered"),
                    "total_ret_net": row.get("total_ret_net"),
                    "daily_path_complete": row.get("daily_path_complete"),
                    "incomplete_reason": row.get("incomplete_reason"),
                    "n_gate_on_days": row.get("n_gate_on_days"),
                    "n_bar_dates": row.get("n_bar_dates"),
                    "occupancy_frac": row.get("occupancy_frac"),
                    "occupancy_always_on_warning": row.get(
                        "occupancy_always_on_warning"
                    ),
                    "promote_as_main": False,
                    "go": False,
                    "stance": "RESEARCH_ONLY",
                    "data_path": row.get("data_path"),
                }
            )
    _dump(out_dir / "new_unique_logic_daily_dd_table.json", compact)

    n_impl = sum(1 for s in NEW_UNIQUE_LOGIC if daily_packs.get(s["logic_id"]))
    n_complete = sum(1 for p in daily_packs.values() if p.get("complete"))
    pins_after = _assert_frozen_pins_untouched()
    pins_after["note"] = "W107 after unique_logic hyps; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": WAVE,
        "track": "B_new_unique_logic_hyps",
        "pack_bias": PACK_BIAS,
        "event_filter_only": False,
        "n_event_filter_logics": 0,
        "n_funding": 1,
        "n_calendar": 1,
        "n_cross_section": 1,
        "n_macro": 1,
        "n_requested": 4,
        "n_proposed": 4,
        "n_accepted": (hyp_pack or {}).get("summary", {}).get("n_accepted"),
        "n_min_implemented": n_impl,
        "n_daily_path_complete_logics": n_complete,
        "new_unique_logic_ids": [s["logic_id"] for s in NEW_UNIQUE_LOGIC],
        "headline_unique_logic": [
            s["logic_id"] for s in NEW_UNIQUE_LOGIC if s.get("headline")
        ],
        "axes": {s["logic_id"]: s.get("axis") for s in NEW_UNIQUE_LOGIC},
        "catalog_map_headline": False,
        "sticky_approx_always_on_gate": False,
        "do_not_headline": list(LOGIC_CATALOG_HEADLINE_BAN),
        "do_not_repeat_w104": list(W104_UNIQUE_LOGIC_IDS),
        "do_not_repeat_w105": list(W105_UNIQUE_LOGIC_IDS),
        "do_not_repeat_w106": list(W106_UNIQUE_LOGIC_IDS),
        "weak_template_mapping": "OFF",
        "hold_mom_microgrid": False,
        "dispersion_thresh_grid": False,
        "period_net_dd_only_pass_forbidden": True,
        "daily_path_DD_required": True,
        "pins_untouched": pins_after.get("pins_untouched"),
        "promote_as_main": False,
        "go": False,
        "mass": "NO-GO",
        "ready": False,
        "continuous_paper": "UNARMED",
        "implementer": "Grok",
        "orchestrator_implemented": True,
        "worst_daily_path_DD_by_logic": {
            lid: p.get("worst_daily_path_DD") for lid, p in daily_packs.items()
        },
        "complete_by_logic": {
            lid: p.get("complete") for lid, p in daily_packs.items()
        },
        "hyps": (hyp_pack or {}).get("summary") if hyp_pack else None,
        "git_sha": _git_sha(),
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w107_b_summary.json", summary)
    log(
        f"[w107] done wall={summary['wall_sec']}s "
        f"impl={n_impl} daily_complete_logics={n_complete} "
        f"pins={pins_after.get('pins_untouched')} pack_bias={PACK_BIAS} "
        f"worst={summary['worst_daily_path_DD_by_logic']}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
