#!/usr/bin/env python3
"""W104 / w0820a Track B — NEW unique_logic hyps with daily_path_DD required.

Headline is **new unique_logic** (new PIT gate / new signal / new entry /
funding×disclosure×macro combo). Weak-template mapping OFF. Catalog remaps
of sticky / event_post_disclosure_hold / vol_risk_adjusted_mom are **not**
headlined as new strategies.

Modest N=4 (not a count race). Failure constraints ON. 3-default pins
untouched. Survivors research-only: promote_as_main=false · go=false.

If extra datasets cannot be loaded, the row stays **incomplete** — never
approximated into complete.

Examples
--------
    uv run python scripts/run_w104_new_hyps_daily_dd.py \\
        --out-dir .glm-logs/w0820a_w104_otc8_new_hyps/
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820a_w104_otc8_new_hyps"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0820a_w104_hyps_new_logic_20260820.md"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_event_rate_daily_dd as w102  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

WAVE = "W104 / w0820a"
W104_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT

# ---------------------------------------------------------------------------
# 4 NEW unique_logic proposals (not catalog remaps; not hold/mom grids)
# ---------------------------------------------------------------------------
# P1 new PIT gate + funding × disclosure
# P2 funding × disclosure × macro (curve shape)
# P3 new PIT gate (disclosure-cluster, not mom-std)
# P4 new SIGNAL (CS surprise rank, not own-sign event hold)

NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_stress_skip",
        "family_id": "event_funding_combo",
        "kind": "event_funding_stress_skip",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW PIT GATE + funding×disclosure: skip post-disclosure surprise "
            "entry when overnight Tokyo repo is at/above its PIT trailing "
            "median (funding stress). Not event_post_disclosure_hold remap."
        ),
        "thesis": (
            "Post-earnings surprise drift is financing-sensitive. When overnight "
            "Tokyo repo is at/above its PIT trailing median, skip the event "
            "entry; take surprise-sign hold only when funding is easy."
        ),
        "signal_definition": (
            "earnings surprise proxy; enter only if overnight repo on entry "
            "date is strictly below PIT trailing median of prior overnight "
            "prints; missing same-date overnight → skip (no ffill)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip entire "
            "event when funding-stress gate is on or overnight is missing"
        ),
        "datasets": [
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
            "mode": "funding_stress_skip",
            "gate": "overnight_lt_pit_trailing_median",
        },
    },
    {
        "logic_id": "curve_steep_event_confirm",
        "family_id": "event_macro_curve_combo",
        "kind": "curve_steep_event_confirm",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW combo funding×disclosure×macro: event surprise hold only "
            "when 3M−ON repo curve is steep (spread>0, both tenors same date, "
            "no ffill). Distinct from overnight-level gate and from "
            "rate_curve_shape_xs (not a CS-mom book)."
        ),
        "thesis": (
            "Event surprise drift is confirmed only in a carry-friendly term-"
            "funding regime: take PIT surprise-sign hold iff the JSDA Tokyo "
            "repo curve (3M−overnight) is steep on the entry date."
        ),
        "signal_definition": (
            "surprise-sign AND same-date repo spread (3M/T+1 − overnight/T+0) "
            "> 0; missing either tenor → skip (no ffill / no invent)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; flatten/skip "
            "when curve is flat, inverted, or gapped"
        ),
        "datasets": [
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "steep_threshold": 0.0,
            "mode": "curve_steep_event_confirm",
            "gate": "repo_curve_spread_gt_0",
        },
    },
    {
        "logic_id": "disclosure_cluster_mom_gate",
        "family_id": "disclosure_cluster_gate",
        "kind": "disclosure_cluster_mom_gate",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "why_unique": (
            "NEW PIT GATE: CS mom L-S sticky only when PIT count of recent "
            "universe disclosures ≥ trailing median. Distinct from "
            "xs_cs_dispersion_gate (disclosure count, not mom std) and not a "
            "sticky remap."
        ),
        "thesis": (
            "Relative-strength L-S is more informative during earnings-season "
            "information flow. Gate the CS mom book ON only when the PIT "
            "count of disclosures in the last N sessions is at/above its "
            "trailing median."
        ),
        "signal_definition": (
            "CS rank mom L-S × PIT disclosure-cluster count vs trailing "
            "median (strict: DiscDate < today; no same-day look-ahead)"
        ),
        "position_rule": (
            "sticky fixed_horizon hold of gated rank signs; flat when "
            "disclosure cluster is below PIT trailing median"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "cluster_lookback": 5,
            "min_hist": 10,
            "mode": "disclosure_cluster_gate",
            "gate": "n_recent_disclosures_ge_pit_median",
        },
    },
    {
        "logic_id": "surprise_xs_rank_hold",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "why_unique": (
            "NEW SIGNAL: cross-section rank of earnings surprise among names "
            "currently in a PIT event window — relative surprise, not "
            "own-sign time-series event_post hold."
        ),
        "thesis": (
            "Among names that have a PIT-available disclosure in the last H "
            "sessions, long high-surprise / short low-surprise. Relative "
            "surprise, not own-sign PEAD hold."
        ),
        "signal_definition": (
            "CS rank of surprise among names whose PIT event entry is inside "
            "the last post_hold_days sessions; <2 names → flat (no invent)"
        ),
        "position_rule": (
            "balanced L/S on surprise ranks for currently-in-window names; "
            "names with no recent PIT disclosure stay flat"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "long_frac": 0.3,
            "short_frac": 0.3,
            "mode": "surprise_xs_rank",
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
    pack["note"] = "W104 new unique_logic hyps must not mutate 3-default pins"
    return pack


def pit_median_on_dates(
    series_by_date: Mapping[str, float],
    query_dates: Sequence[str],
    *,
    min_hist: int,
) -> dict[str, float | None]:
    """PIT trailing median: values with series_date < query_date only."""
    items: list[tuple[str, float]] = []
    for d, v in series_by_date.items():
        ds = str(d)[:10]
        if not ds:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            items.append((ds, fv))
    items.sort(key=lambda x: x[0])
    hist: list[float] = []
    j = 0
    out: dict[str, float | None] = {}
    for d in query_dates:
        ds = str(d)[:10]
        while j < len(items) and items[j][0] < ds:
            hist.append(items[j][1])
            j += 1
        out[ds] = float(median(hist)) if len(hist) >= int(min_hist) else None
    return out


def _collect_event_entries(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """PIT event entries (no DiscTime invent). Shared by event-gated logics."""
    from features.class_signals import (
        earnings_surprise_proxy,
        event_post_entry_bar_index,
        sign_from_numeric,
    )

    h = int(spec.get("post_hold_days") or spec.get("params", {}).get("post_hold_days") or 5)
    entry_mode = str(
        spec.get("entry_mode")
        or (spec.get("params") or {}).get("entry_mode")
        or "same_day_close_if_pre_close"
    )
    p0 = str(period_start)[:10] if period_start else None
    p1 = str(period_end)[:10] if period_end else None

    close_by: dict[str, dict[str, float]] = {}
    calendar: set[str] = set()
    per_code: dict[str, dict[str, Any]] = {}
    n_events = 0
    n_no_surprise = 0
    n_no_bar = 0
    entries: list[dict[str, Any]] = []

    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        dlist = [str(d)[:10] for d, _ in pairs_l]
        date_to_idx = {d: i for i, d in enumerate(dlist)}
        for d, c in pairs_l:
            close_by.setdefault(code, {})[str(d)[:10]] = float(c)
            calendar.add(str(d)[:10])
        code_entries: list[dict[str, Any]] = []
        for ev in list(events_by_code.get(code) or []):
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            if p0 and disc < p0:
                continue
            if p1 and disc > p1:
                continue
            n_events += 1
            surprise, _s_meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            disc_time = ev.get("disc_time")
            event_time = ev.get("event_time") or ev.get("available_at")
            idx, entry_date, _meta = event_post_entry_bar_index(
                date_to_idx,
                disc_date=disc,
                disc_time=disc_time,
                event_time=str(event_time) if event_time else None,
                entry_mode=entry_mode,
            )
            if idx is None or entry_date is None:
                n_no_bar += 1
                continue
            sgn = sign_from_numeric(surprise)
            if sgn is None or sgn == 0.0 or surprise is None:
                n_no_surprise += 1
                continue
            rec = {
                "code": code,
                "disc_date": disc,
                "entry_idx": int(idx),
                "entry_date": str(entry_date)[:10],
                "surprise": float(surprise),
                "sign": float(sgn),
            }
            code_entries.append(rec)
            entries.append(rec)
        per_code[code] = {"dlist": dlist, "entries": code_entries}

    return {
        "hold_days": h,
        "entry_mode": entry_mode,
        "close_by": close_by,
        "calendar": sorted(calendar),
        "per_code": per_code,
        "entries": entries,
        "n_events": n_events,
        "n_no_surprise": n_no_surprise,
        "n_no_bar": n_no_bar,
        "n_eligible": len(entries),
    }


def _held_from_event_entries(
    collected: Mapping[str, Any],
    *,
    accept: Mapping[str, bool] | None = None,
) -> dict[str, dict[str, float | None]]:
    """Build last-event-wins held book; accept[entry_key] gates entries."""
    h = int(collected["hold_days"])
    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, pack in (collected.get("per_code") or {}).items():
        dlist = list(pack.get("dlist") or [])
        held: list[float | None] = [None] * len(dlist)
        for ev in pack.get("entries") or []:
            key = f"{code}|{ev['entry_date']}|{ev['disc_date']}"
            if accept is not None and not accept.get(key, False):
                continue
            idx = int(ev["entry_idx"])
            sgn = float(ev["sign"])
            end = min(idx + h, len(dlist))
            for j in range(idx, end):
                held[j] = sgn
        held_by_code_date[code] = {dlist[i]: held[i] for i in range(len(dlist))}
    return held_by_code_date


def evaluate_event_funding_stress_skip_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold skipped under PIT overnight funding stress.

    Gate (PIT): overnight[entry_date] < trailing median of overnight prints
    with date < entry_date. Missing same-date overnight → skip (no ffill).
    """
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = _collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    dates = list(collected["calendar"])
    extra = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "min_hist": min_hist,
        "gate": "overnight_lt_pit_trailing_median",
        "n_events": collected["n_events"],
        "n_eligible_pre_gate": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "extra_dataset": "fins_summary+jsda_tokyo_repo_rates",
        "data_path": "local_real_mirrors+local_sqlite_fins+repo",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if not overnight_by_date:
        return {
            "status": "missing_overnight_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "funding-stress PIT gate. Not approximated."
            ),
            **extra,
        }
    if collected["n_events"] == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary loaded but no DiscDate events in this shard "
                "for eval codes — daily book empty. Not approximated."
            ),
            **extra,
        }

    entry_dates = sorted({e["entry_date"] for e in collected["entries"]})
    med_by = pit_median_on_dates(overnight_by_date, entry_dates, min_hist=min_hist)
    accept: dict[str, bool] = {}
    n_skip_missing = 0
    n_skip_no_median = 0
    n_skip_stress = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"
        d = ev["entry_date"]
        on = overnight_by_date.get(d)
        if on is None:
            accept[key] = False
            n_skip_missing += 1
            continue
        med = med_by.get(d)
        if med is None:
            accept[key] = False
            n_skip_no_median += 1
            continue
        if float(on) >= float(med):
            accept[key] = False
            n_skip_stress += 1
            continue
        accept[key] = True
        n_entered += 1

    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_no_median,
            "n_skip_funding_stress": n_skip_stress,
        }
    )
    held = _held_from_event_entries(collected, accept=accept)
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_curve_steep_event_confirm_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only when same-date repo curve is steep (no ffill)."""
    params = dict(spec.get("params") or {})
    steep = float(spec.get("steep_threshold") or params.get("steep_threshold") or 0.0)
    collected = _collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    dates = list(collected["calendar"])
    spread_by = dict((curve_series or {}).get("spread_by_date") or {})
    extra = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "steep_threshold": steep,
        "gate": "repo_curve_spread_gt_steep_threshold",
        "n_events": collected["n_events"],
        "n_eligible_pre_gate": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "extra_dataset": "fins_summary+jsda_tokyo_repo_rates",
        "data_path": "local_real_mirrors+local_sqlite_fins+repo",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if not spread_by:
        return {
            "status": "missing_curve_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates curve series empty — cannot apply "
                "steep-curve event confirm. Not approximated."
            ),
            **extra,
        }
    if collected["n_events"] == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary loaded but no DiscDate events in this shard "
                "for eval codes — daily book empty. Not approximated."
            ),
            **extra,
        }

    accept: dict[str, bool] = {}
    n_skip_gap = 0
    n_skip_not_steep = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"
        sp = spread_by.get(ev["entry_date"])
        if sp is None:
            accept[key] = False
            n_skip_gap += 1
            continue
        if float(sp) <= float(steep):
            accept[key] = False
            n_skip_not_steep += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_curve_gap": n_skip_gap,
            "n_skip_not_steep": n_skip_not_steep,
        }
    )
    held = _held_from_event_entries(collected, accept=accept)
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_disclosure_cluster_mom_gate_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom L-S sticky gated by PIT universe disclosure-cluster count.

    Distinct from xs_cs_dispersion_gate (mom std). DiscDate < today only.
    """
    from features.class_signals import apply_sticky_hold, cross_section_rank_signs

    params = dict(spec.get("params") or {})
    n = int(spec.get("momentum_n") or params.get("momentum_n") or 5)
    h = int(spec.get("hold_days") or params.get("hold_days") or 10)
    lf = float(spec.get("long_frac") or params.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or params.get("short_frac") or 0.3)
    lookback = int(spec.get("cluster_lookback") or params.get("cluster_lookback") or 5)
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 10)

    extra_base = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "momentum_n": n,
        "hold_days": h,
        "long_frac": lf,
        "short_frac": sf,
        "cluster_lookback": lookback,
        "min_hist": min_hist,
        "gate": "n_recent_disclosures_ge_pit_median",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    n_disc = sum(len(v) for v in (events_by_code or {}).values())
    if n_disc == 0:
        return {
            "status": "no_events",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary events empty — disclosure-cluster gate cannot "
                "be built. Not approximated."
            ),
            **extra_base,
        }

    panel = w100._panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra_base,
        }

    disc_dates: list[str] = []
    for evs in (events_by_code or {}).values():
        for ev in evs:
            d = str(ev.get("disc_date") or "")[:10]
            if d:
                disc_dates.append(d)
    disc_dates.sort()

    # Per bar date: count DiscDate in the previous `lookback` bar dates (strict).
    date_set_index = {d: i for i, d in enumerate(dates)}
    cluster_by: dict[str, float] = {}
    for i, d in enumerate(dates):
        lo = max(0, i - lookback)
        window = set(dates[lo:i])  # excludes today
        c = sum(1 for dd in disc_dates if dd in window)
        cluster_by[d] = float(c)
    med_by = pit_median_on_dates(cluster_by, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_gated_off = 0
    n_gate_on = 0
    n_median_unformed = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        med = med_by.get(d)
        cl = cluster_by.get(d, 0.0)
        if med is None:
            on = False
            n_median_unformed += 1
        else:
            on = float(cl) >= float(med)
        if on:
            n_gate_on += 1
        else:
            n_gated_off += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = sign if on else 0.0

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]))
            for i in range(len(dlist))
        }
    extra = {
        **extra_base,
        "n_gated_off_days": n_gated_off,
        "n_gate_on_days": n_gate_on,
        "n_median_unformed_days": n_median_unformed,
        "n_disclosure_prints": n_disc,
        "n_bar_dates": len(dates),
        "n_date_index": len(date_set_index),
    }
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=panel["close_by"],
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_surprise_xs_rank_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """CS rank of surprise among names in a PIT event window (new signal)."""
    from features.class_signals import cross_section_rank_signs

    params = dict(spec.get("params") or {})
    lf = float(spec.get("long_frac") or params.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or params.get("short_frac") or 0.3)
    collected = _collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    h = int(collected["hold_days"])
    dates = list(collected["calendar"])
    extra = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "post_hold_days": h,
        "entry_mode": collected["entry_mode"],
        "long_frac": lf,
        "short_frac": sf,
        "n_events": collected["n_events"],
        "n_eligible": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if collected["n_events"] == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary loaded but no DiscDate events in this shard "
                "for eval codes — daily book empty. Not approximated."
            ),
            **extra,
        }
    if not dates:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": 0,
            **extra,
        }

    # Active surprise by date: names whose PIT entry is in [d-h+1, d] wait —
    # position lives on [entry, entry+h). Rank those currently held-in-window.
    date_to_idx = {d: i for i, d in enumerate(dates)}
    surprise_by_date: dict[str, dict[str, float]] = {d: {} for d in dates}
    for ev in collected["entries"]:
        ed = ev["entry_date"]
        if ed not in date_to_idx:
            continue
        i0 = date_to_idx[ed]
        for j in range(i0, min(i0 + h, len(dates))):
            surprise_by_date[dates[j]][ev["code"]] = float(ev["surprise"])

    held_by_code_date: dict[str, dict[str, float | None]] = {
        code: {d: None for d in dates} for code in collected["per_code"]
    }
    n_ranked_days = 0
    n_flat_sparse = 0
    n_names_ranked = 0
    for d in dates:
        scores = surprise_by_date.get(d) or {}
        if len(scores) < 2:
            n_flat_sparse += 1
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        n_ranked_days += 1
        n_names_ranked += len(scores)
        for code, sign in ranks.items():
            held_by_code_date.setdefault(code, {})[d] = (
                None if sign is None else float(sign)
            )

    extra.update(
        {
            "n_ranked_days": n_ranked_days,
            "n_flat_sparse_days": n_flat_sparse,
            "mean_names_on_ranked_days": (
                float(n_names_ranked) / float(n_ranked_days) if n_ranked_days else 0.0
            ),
            "occupancy_note": (
                "Sparse occupancy is honest: CS surprise rank needs ≥2 names "
                "in-window. Not filled."
            ),
        }
    )
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


EVALUATORS = {
    "event_funding_stress_skip": "event_funding",
    "curve_steep_event_confirm": "curve_event",
    "disclosure_cluster_mom_gate": "cluster",
    "surprise_xs_rank_hold": "surprise_xs",
}


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
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    curve_series: Mapping[str, Any] | None,
    one_way_cost: float,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    bars = loaded["bars"]
    p0 = loaded.get("period_start")
    p1 = loaded.get("period_end")
    if lid == "event_funding_stress_skip":
        return evaluate_event_funding_stress_skip_daily_mtm(
            bars,
            events_by_code,
            overnight_by_date,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "curve_steep_event_confirm":
        return evaluate_curve_steep_event_confirm_daily_mtm(
            bars,
            events_by_code,
            curve_series,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "disclosure_cluster_mom_gate":
        return evaluate_disclosure_cluster_mom_gate_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
        )
    if lid == "surprise_xs_rank_hold":
        return evaluate_surprise_xs_rank_hold_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
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
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    curve_series: Mapping[str, Any] | None,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in W104_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w104/{lid}] window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_entered_win = 0
        n_events_win = 0
        n_gate_on_win = 0
        n_ranked_win = 0
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                log(f"[w104/{lid}]   {pid}: {loaded.get('status')}")
                continue
            pack = _eval_one_shard(
                spec=spec,
                loaded=loaded,
                events_by_code=events_by_code,
                overnight_by_date=overnight_by_date,
                curve_series=curve_series,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_events"] = pack.get("n_events")
            summary["n_entered"] = pack.get("n_entered")
            summary["n_gate_on_days"] = pack.get("n_gate_on_days")
            summary["n_gated_off_days"] = pack.get("n_gated_off_days")
            summary["n_ranked_days"] = pack.get("n_ranked_days")
            shard_summaries.append(summary)
            n_entered_win += int(pack.get("n_entered") or 0)
            n_events_win += int(pack.get("n_events") or 0)
            n_gate_on_win += int(pack.get("n_gate_on_days") or 0)
            n_ranked_win += int(pack.get("n_ranked_days") or 0)
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
                f"[w104/{lid}]   {pid}: status={pack.get('status')} "
                f"n={summary.get('n_equity_points')} "
                f"entered={pack.get('n_entered')} events={pack.get('n_events')} "
                f"gate_on={pack.get('n_gate_on_days')} "
                f"ranked={pack.get('n_ranked_days')} "
                f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                f"total_net={_fmt(summary.get('total_return_net'))}"
            )
        if not stitch_net:
            row = _incomplete_row(
                logic_id=lid,
                window_id=wid,
                reason=(
                    "no ok daily path stitched for this window "
                    f"(n_events={n_events_win} n_entered={n_entered_win})"
                ),
                extra={
                    "data_path": "local_real_mirrors+local_sqlite",
                    "n_events": n_events_win,
                    "n_entered": n_entered_win,
                    "n_gate_on_days": n_gate_on_win,
                    "n_ranked_days": n_ranked_win,
                    "shard_summaries": shard_summaries,
                    "new_unique_logic": True,
                    "catalog": False,
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
                    "n_events": n_events_win,
                    "n_entered": n_entered_win,
                    "n_gate_on_days": n_gate_on_win,
                    "n_ranked_days": n_ranked_win,
                    "new_unique_logic": True,
                    "catalog": False,
                    "catalog_map": None,
                    "why_unique": spec.get("why_unique"),
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
    """Route 4 NEW unique_logic through propose_profit_hypotheses.

    Weak-template mapping OFF: ad-hoc family_ids do **not** remap onto
    sticky / event_post_disclosure_hold / vol_risk_adjusted_mom.
    Factory period-net of unknown families is **not** a pass; daily_path_DD
    of the min-impl is the required eval.
    """
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
        f"[w104/B] propose n={len(proposals)} seed={seed} "
        "weak_template_mapping=OFF map_unknown_to_nearest_catalog=false "
        "not_a_count_race=True daily_path_DD_required=True"
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
        "n_requested": 4,
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_rejected,
        "n_evaluated_factory_synthetic": n_evaluated,
        "n_survivors_period_net": n_survivors_period_net,
        "period_net_is_not_a_pass": True,
        "period_net_dd_only_pass_forbidden": True,
        "factory_note": (
            "Ad-hoc unique family_ids are unknown to catalog dispatch. "
            "Factory synthetic period-net is NOT the unique_logic eval and "
            "cannot pass. daily_path_DD of min-impl is required."
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
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var", "daily_path_DD"],
        "daily_path_DD_required": True,
        "representative_theses": [
            {
                "logic_id": s["logic_id"],
                "family_id": s["family_id"],
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
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w104/B] pack proposed={n_proposed} accepted={n_accepted} "
        f"factory_eval={n_evaluated} period_net_survivors={n_survivors_period_net} "
        f"weak_map_off mapped={mapped or '[]'}"
    )
    return {"summary": summary, "eval_out": eval_out}


def inspect_unique_logic_datasets(
    *,
    codes: Sequence[str],
    sqlite_path: Path,
    log,
) -> dict[str, Any]:
    extra = w102.inspect_extra_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    overnight = {}
    curve = extra.get("curve_series") or {}
    if isinstance(curve, Mapping):
        overnight = dict(curve.get("short_rates_by_date") or {})
        if not overnight:
            overnight = dict(curve.get("rates_by_date") or {})
    extra["overnight_by_date"] = overnight
    extra["n_overnight"] = len(overnight)
    extra["overnight_date_min"] = min(overnight) if overnight else None
    extra["overnight_date_max"] = max(overnight) if overnight else None
    log(
        f"[w104] overnight n={len(overnight)} "
        f"{extra['overnight_date_min']}..{extra['overnight_date_max']}"
    )
    return extra


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--seed", type=int, default=8908194)
    p.add_argument(
        "--sqlite",
        type=str,
        default=str(SQLITE_DEFAULT),
    )
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-daily", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w104_new_hyps_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w104] pins_untouched={pins['pins_untouched']}")
    log(
        "[w104] promote_as_main=false go=false hold_mom_grid=false "
        "dispersion_thresh_grid=false weak_template_mapping=OFF "
        "period_net_dd_only=forbidden complete≠GO "
        "GLM implementer only. Grok did not implement."
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
        if k not in {"fins_events", "curve_series", "overnight_by_date"}
    }
    _dump(out_dir / "extra_dataset_wiring.json", extra_dump)

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_hyp_pack(out_dir=out_dir, seed=int(args.seed), log=log)
    else:
        log("[w104/B] propose skipped")

    daily_packs: dict[str, Any] = {}
    if not args.skip_daily:
        events = extra.get("fins_events") or {}
        overnight = extra.get("overnight_by_date") or {}
        curve = extra.get("curve_series")
        for spec in NEW_UNIQUE_LOGIC:
            lid = str(spec["logic_id"])
            daily_packs[lid] = run_unique_logic_daily_dd(
                out_dir=out_dir,
                spec=spec,
                codes=codes,
                events_by_code=events,
                overnight_by_date=overnight,
                curve_series=curve,
                max_days=int(args.max_days),
                one_way_cost=float(args.one_way_cost),
                log=log,
            )
    else:
        log("[w104/B] daily_path_DD skipped")

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
                    "window": row.get("window"),
                    "n_days": row.get("n_days"),
                    "daily_path_DD": row.get("daily_path_DD"),
                    "dd_duration": row.get("dd_duration"),
                    "recovery_days": row.get("recovery_days"),
                    "recovered": row.get("recovered"),
                    "total_ret_net": row.get("total_ret_net"),
                    "daily_path_complete": row.get("daily_path_complete"),
                    "incomplete_reason": row.get("incomplete_reason"),
                    "n_events": row.get("n_events"),
                    "n_entered": row.get("n_entered"),
                    "n_gate_on_days": row.get("n_gate_on_days"),
                    "n_ranked_days": row.get("n_ranked_days"),
                    "promote_as_main": False,
                    "go": False,
                    "stance": "RESEARCH_ONLY",
                    "data_path": row.get("data_path"),
                }
            )
    _dump(out_dir / "new_unique_logic_daily_dd_table.json", compact)

    n_impl = sum(1 for s in NEW_UNIQUE_LOGIC if daily_packs.get(s["logic_id"]))
    n_complete = sum(
        1 for p in daily_packs.values() if p.get("complete")
    )
    pins_after = _assert_frozen_pins_untouched()
    pins_after["note"] = "W104 after unique_logic hyps; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": WAVE,
        "track": "B_new_unique_logic_hyps",
        "n_requested": 4,
        "n_proposed": 4,
        "n_accepted": (hyp_pack or {}).get("summary", {}).get("n_accepted"),
        "n_min_implemented": n_impl,
        "n_daily_path_complete_logics": n_complete,
        "new_unique_logic_ids": [s["logic_id"] for s in NEW_UNIQUE_LOGIC],
        "headline_unique_logic": [
            s["logic_id"] for s in NEW_UNIQUE_LOGIC if s.get("headline")
        ],
        "catalog_map_headline": False,
        "do_not_headline": list(LOGIC_CATALOG_HEADLINE_BAN),
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
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "worst_daily_path_DD_by_logic": {
            lid: p.get("worst_daily_path_DD") for lid, p in daily_packs.items()
        },
        "complete_by_logic": {
            lid: p.get("complete") for lid, p in daily_packs.items()
        },
        "hyps": (hyp_pack or {}).get("summary") if hyp_pack else None,
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w104_b_summary.json", summary)
    log(
        f"[w104] done wall={summary['wall_sec']}s "
        f"impl={n_impl} daily_complete_logics={n_complete} "
        f"pins={pins_after.get('pins_untouched')} "
        f"worst={summary['worst_daily_path_DD_by_logic']}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
