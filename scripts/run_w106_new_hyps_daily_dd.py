#!/usr/bin/env python3
"""W106 / w0820c Track B — NEW unique_logic hyps with daily_path_DD required.

Headline is **new unique_logic** that is **MIXED** (funding / macro /
cross-section), not an event-filter-only pack. W105 was event-hold variants;
this wave does **not** repeat that.

Weak-template mapping OFF. Catalog remaps of sticky / event_post_disclosure_hold
/ vol_risk_adjusted_mom are **not** headlined. Do **not** build sticky-approx
always-on CS-mom gates (W104 disclosure_cluster_mom_gate was ~90% on).

Modest N=4 (not a count race). Failure constraints ON. 3-default pins
untouched. Survivors research-only: promote_as_main=false · go=false.

If extra datasets cannot be loaded, the row stays **incomplete** — never
approximated into complete.

Examples
--------
    uv run python scripts/run_w106_new_hyps_daily_dd.py \\
        --out-dir .glm-logs/w0820c_w106_otc10_ls_hyps/
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import date, datetime, timezone
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820c_w106_otc10_ls_hyps"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0820c_w106_hyps_new_logic_20260820.md"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_event_rate_daily_dd as w102  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402
import run_w105_new_hyps_daily_dd as w105  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

WAVE = "W106 / w0820c"
W106_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT
PACK_BIAS = "mixed"

# ---------------------------------------------------------------------------
# 4 NEW unique_logic proposals (NOT event-filter-only; not catalog remaps;
# not hold/mom grids; not sticky-approx always-on CS-mom gates)
# ---------------------------------------------------------------------------
# P1 FUNDING — overnight repo |Δ| impulse tilts CS mom (not event skip)
# P2 MACRO  — 3M−ON curve steepening impulse gates CS mom (not rate_curve level)
# P3 XS     — CS rank of name-level margin Δ (not price mom, not event skip)
# P4 MACRO×XS — idiosyncratic mom vs TOPIX on large index-move days

NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "funding_impulse_cs_tilt",
        "family_id": "funding_impulse_cs",
        "kind": "funding_impulse_cs_tilt",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "axis": "funding",
        "why_unique": (
            "NEW FUNDING SIGNAL: CS mom L-S sign-tilted by overnight Tokyo "
            "repo CHANGE (not level). Trade only when |Δovernight| ≥ PIT "
            "trailing median of |Δ|; tightening (Δ>0) fades CS mom, easing "
            "(Δ<0) follows. Missing same-date overnight → flatten (no ffill). "
            "Not event_funding_stress_skip (event-book level skip) and not "
            "sticky."
        ),
        "thesis": (
            "Large overnight funding impulses reprice relative-strength. "
            "When Tokyo repo tightens vs the prior print by at least the PIT "
            "median |Δ|, fade CS momentum; when it eases by that much, follow. "
            "Small noise moves and missing prints stay flat."
        ),
        "signal_definition": (
            "Δovernight = overnight[d] − prior overnight print (date < d); "
            "enter iff abs(Δ) >= PIT median of abs(Δ) with delta-date < d "
            "(min_hist=20); tilt = −sign(Δ); missing/unformed/zero → flatten"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank mom L-S × funding-impulse tilt; "
            "flat when |Δ| is below PIT median, median unformed, or overnight "
            "missing same-date (no ffill)"
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
            "mode": "funding_impulse_cs_tilt",
            "gate": "abs_overnight_delta_ge_pit_median",
        },
    },
    {
        "logic_id": "curve_steepen_impulse_cs",
        "family_id": "curve_steepen_impulse_cs",
        "kind": "curve_steepen_impulse_cs",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "axis": "macro",
        "why_unique": (
            "NEW MACRO IMPULSE: CS mom L-S only when the same-date 3M−ON "
            "repo spread STEEPENS vs the prior print AND |Δspread| ≥ PIT "
            "trailing median of |Δspread|. Flatten on flattening, inversion "
            "moves, gaps, or unformed median. Not rate_curve_shape_xs "
            "(level steep/invert transform) and not curve_steep_event_confirm "
            "(event book)."
        ),
        "thesis": (
            "A carry-friendly funding curve is informative when it is actively "
            "steepening, not merely steep. Take CS relative-strength only on "
            "large same-date 3M−ON steepening impulses; otherwise flat."
        ),
        "signal_definition": (
            "Δspread = (3M−ON)[d] − prior same-tenor spread; enter iff "
            "Δspread > 0 AND abs(Δspread) >= PIT median of abs(Δspread) "
            "with date < d (min_hist=20); missing either tenor → flatten "
            "(no ffill)"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank mom L-S on steepening-impulse days; "
            "flat otherwise"
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
            "mode": "curve_steepen_impulse_cs",
            "gate": "spread_delta_gt_0_and_abs_ge_pit_median",
        },
    },
    {
        "logic_id": "xs_margin_delta_rank",
        "family_id": "xs_margin_delta",
        "kind": "xs_margin_delta_rank",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "axis": "cross_section",
        "why_unique": (
            "NEW CROSS-SECTION SIGNAL: rank names by PIT %change in "
            "name-level margin interest (last two prints with date < today, "
            "last print age ≤ 14 calendar days). Long de-crowding / short "
            "crowding. Not price-mom sticky, not flow_margin_pressure "
            "(own-name flow book), not event_margin_crowding_skip."
        ),
        "thesis": (
            "Expanding margin is crowding; shrinking margin is de-crowding. "
            "Among names with two recent PIT margin prints, long the "
            "de-crowding tail and short the crowding tail — a flow CS book, "
            "not a price CS book."
        ),
        "signal_definition": (
            "score = −(last−prev)/|prev| from two prints with last_date < "
            "today and age<=14d; CS rank L-S of scores; <2 names or "
            "missing/stale → flatten that name / day (no ffill, no invent)"
        ),
        "position_rule": (
            "sticky fixed_horizon balanced L/S on margin-delta ranks; names "
            "without two fresh PIT prints stay flat"
        ),
        "datasets": [
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "stale_calendar_days": 14,
            "mode": "xs_margin_delta_rank",
            "gate": "name_margin_delta_cs_rank",
        },
    },
    {
        "logic_id": "idio_mom_macro_impulse",
        "family_id": "idio_mom_macro",
        "kind": "idio_mom_macro_impulse",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "axis": "macro_xs",
        "why_unique": (
            "NEW MACRO×XS: CS rank of idiosyncratic momentum "
            "(name_mom_n − TOPIX_mom_n) only on days when |TOPIX_mom_n| ≥ "
            "PIT trailing median of |TOPIX_mom_n|. Missing same-date TOPIX "
            "→ flatten (no ffill). Not sticky (raw mom CS always-on) and "
            "not vol_risk_adjusted_mom."
        ),
        "thesis": (
            "Idiosyncratic relative strength is more informative on large "
            "index-move days. Rank residual momentum vs TOPIX only when the "
            "index itself has moved by at least its PIT median |mom|; stay "
            "flat on quiet macro days."
        ),
        "signal_definition": (
            "residual = mom_n(name) − mom_n(TOPIX) on the bar calendar; "
            "enter iff abs(TOPIX_mom) >= PIT median of abs(TOPIX_mom) "
            "with date < d (min_hist=20); missing TOPIX print → flatten"
        ),
        "position_rule": (
            "sticky fixed_horizon CS rank of residual mom on macro-impulse "
            "days; flat when |TOPIX mom| is below PIT median or TOPIX missing"
        ),
        "datasets": [
            "indices_bars_daily_topix",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "min_hist": 20,
            "mode": "idio_mom_macro_impulse",
            "gate": "abs_topix_mom_ge_pit_median",
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
W104_UNIQUE_LOGIC_IDS = frozenset(
    {
        "event_funding_stress_skip",
        "curve_steep_event_confirm",
        "disclosure_cluster_mom_gate",
        "surprise_xs_rank_hold",
    }
)
W105_UNIQUE_LOGIC_IDS = frozenset(
    {
        "large_surprise_event_hold",
        "afterclose_only_event_hold",
        "event_pre_mom_agree_hold",
        "event_margin_crowding_skip",
    }
)
ALWAYS_ON_OCCUPANCY_WARN = 0.85


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
    pack["note"] = "W106 new unique_logic hyps must not mutate 3-default pins"
    return pack


def _ymd(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def prior_delta_by_date(series_by_date: Mapping[str, float]) -> dict[str, float]:
    """Same-date minus strictly-prior print. No ffill onto missing dates."""
    items: list[tuple[str, float]] = []
    for d, v in (series_by_date or {}).items():
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
    out: dict[str, float] = {}
    for i in range(1, len(items)):
        out[items[i][0]] = items[i][1] - items[i - 1][1]
    return out


def _last_print_before(
    series_by_date: Mapping[str, float],
    query_date: str,
) -> tuple[str, float] | None:
    prior = [d for d in series_by_date if str(d)[:10] < str(query_date)[:10]]
    if not prior:
        return None
    d = max(prior)
    try:
        return str(d)[:10], float(series_by_date[d])
    except (TypeError, ValueError):
        return None


def _cs_params(spec: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(spec.get("params") or {})
    return {
        "momentum_n": int(spec.get("momentum_n") or params.get("momentum_n") or 5),
        "hold_days": int(spec.get("hold_days") or params.get("hold_days") or 10),
        "long_frac": float(spec.get("long_frac") or params.get("long_frac") or 0.3),
        "short_frac": float(spec.get("short_frac") or params.get("short_frac") or 0.3),
        "min_hist": int(spec.get("min_hist") or params.get("min_hist") or 20),
        "stale_calendar_days": int(
            spec.get("stale_calendar_days") or params.get("stale_calendar_days") or 14
        ),
        "params": params,
    }


def _base_cs_extra(
    spec: Mapping[str, Any],
    *,
    n: int,
    h: int,
    lf: float,
    sf: float,
    min_hist: int,
    gate: str,
    extra_dataset: str,
    data_path: str,
) -> dict[str, Any]:
    return {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "momentum_n": n,
        "hold_days": h,
        "long_frac": lf,
        "short_frac": sf,
        "min_hist": min_hist,
        "gate": gate,
        "axis": spec.get("axis"),
        "extra_dataset": extra_dataset,
        "data_path": data_path,
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
        "sticky_approx_always_on_gate": False,
        "pack_bias": PACK_BIAS,
    }


def _occupancy_note(n_on: int, n_dates: int) -> dict[str, Any]:
    frac = (float(n_on) / float(n_dates)) if n_dates else 0.0
    return {
        "n_gate_on_days": n_on,
        "n_bar_dates": n_dates,
        "occupancy_frac": frac,
        "occupancy_always_on_warning": bool(frac >= ALWAYS_ON_OCCUPANCY_WARN),
        "sticky_approx_always_on_gate": False,
    }


def _cs_held_from_daily(
    *,
    dates_by_code: Mapping[str, Sequence[str]],
    daily_rank: Mapping[str, Mapping[str, float | None]],
    hold_days: int,
) -> dict[str, dict[str, float | None]]:
    from features.class_signals import apply_sticky_hold

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(
            entries, hold_days=int(hold_days), rebalance_mode="fixed_horizon"
        )
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]))
            for i in range(len(dlist))
        }
    return held_by_code_date


def _finish_cs_book(
    *,
    spec: Mapping[str, Any],
    panel: Mapping[str, Any],
    daily_rank: Mapping[str, Mapping[str, float | None]],
    extra: Mapping[str, Any],
    one_way_cost: float,
    hold_days: int,
) -> dict[str, Any]:
    held = _cs_held_from_daily(
        dates_by_code=panel["dates_by_code"],
        daily_rank=daily_rank,
        hold_days=hold_days,
    )
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held,
        close_by=panel["close_by"],
        dates=list(panel["dates"]),
        hold_days=int(hold_days),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra.get("data_path")
    pack["new_unique_logic"] = True
    pack["catalog"] = False
    pack["promote_as_main"] = False
    pack["go"] = False
    pack["pack_bias"] = PACK_BIAS
    return pack


def _empty_extra(
    *,
    spec: Mapping[str, Any],
    extra: Mapping[str, Any],
    reason: str,
    status: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "logic_id": spec["logic_id"],
        "daily_path_complete": False,
        "incomplete_reason": reason,
        **extra,
    }


def evaluate_funding_impulse_cs_tilt_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    overnight_by_date: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom L-S tilted by large overnight repo Δ (funding impulse)."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="abs_overnight_delta_ge_pit_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    overnight = dict(overnight_by_date or {})
    if not overnight:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_overnight_series",
            reason=(
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "funding-impulse CS tilt. Not approximated."
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

    deltas = prior_delta_by_date(overnight)
    abs_deltas = {d: abs(v) for d, v in deltas.items()}
    med_by = w104.pit_median_on_dates(abs_deltas, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_small = 0
    n_tilt_fade = 0
    n_tilt_follow = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        if d not in overnight:
            n_skip_missing += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        dv = deltas.get(d)
        if dv is None:
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
        if abs(float(dv)) < float(med) or float(dv) == 0.0:
            n_skip_small += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        tilt = -1.0 if float(dv) > 0.0 else 1.0
        if tilt < 0:
            n_tilt_fade += 1
        else:
            n_tilt_follow += 1
        n_on += 1
        for code, sign in ranks.items():
            sval = 0.0 if sign is None else float(sign) * tilt
            daily_rank.setdefault(code, {})[d] = sval

    extra.update(
        {
            **_occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_small_delta": n_skip_small,
            "n_tilt_fade_days": n_tilt_fade,
            "n_tilt_follow_days": n_tilt_follow,
            "n_overnight_prints": len(overnight),
            "n_overnight_deltas": len(deltas),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_curve_steepen_impulse_cs_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom L-S only on large 3M−ON steepening impulses (macro)."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="spread_delta_gt_0_and_abs_ge_pit_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    spread_by = dict((curve_series or {}).get("spread_by_date") or {})
    if not spread_by:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_curve_series",
            reason=(
                "jsda_tokyo_repo_rates curve series empty — cannot apply "
                "curve-steepening impulse CS. Not approximated."
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

    deltas = prior_delta_by_date(spread_by)
    abs_deltas = {d: abs(v) for d, v in deltas.items()}
    med_by = w104.pit_median_on_dates(abs_deltas, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_gap = 0
    n_skip_unformed = 0
    n_skip_not_steepen = 0
    n_skip_small = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        if d not in spread_by or d not in deltas:
            n_skip_gap += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        dv = float(deltas[d])
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if dv <= 0.0:
            n_skip_not_steepen += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if abs(dv) < float(med):
            n_skip_small += 1
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
            **_occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_curve_gap": n_skip_gap,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_not_steepen": n_skip_not_steepen,
            "n_skip_small_delta": n_skip_small,
            "n_spread_prints": len(spread_by),
            "n_spread_deltas": len(deltas),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def _margin_delta_score(
    series_by_date: Mapping[str, float],
    query_date: str,
    *,
    stale_days: int,
) -> float | None:
    last = _last_print_before(series_by_date, query_date)
    if last is None:
        return None
    last_d, last_v = last
    age = (_ymd(query_date) - _ymd(last_d)).days
    if age > int(stale_days):
        return None
    prev = _last_print_before(series_by_date, last_d)
    if prev is None:
        return None
    _prev_d, prev_v = prev
    if prev_v == 0.0 or not math.isfinite(prev_v) or not math.isfinite(last_v):
        return None
    # Shrinking margin (de-crowd) → positive score → long.
    return -((last_v - prev_v) / abs(prev_v))


def evaluate_xs_margin_delta_rank_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS rank of PIT name-level margin %change (flow XS, not price mom)."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
    )
    stale_days = int(p["stale_calendar_days"])
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=0,
        gate="name_margin_delta_cs_rank",
        extra_dataset="markets_margin_interest",
        data_path="local_real_mirrors+local_sqlite_margin",
    )
    extra["stale_calendar_days"] = stale_days
    extra["momentum_n"] = None  # signal is margin Δ, not price mom
    margin_ok = bool(margin_by_code) and any(
        bool(v) for v in (margin_by_code or {}).values()
    )
    if not margin_ok:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_extra_dataset",
            reason=(
                "markets_margin_interest series empty — cannot rank name-level "
                "margin delta. Not approximated."
            ),
        )

    # Panel uses mom only to share the bar calendar / close map.
    panel = w100._panel_index(bars_by_code, momentum_n=max(1, int(n)))
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_ranked = 0
    n_flat_sparse = 0
    n_names_ranked = 0
    n_skip_stale_or_missing = 0
    for d in dates:
        scores: dict[str, float] = {}
        for code in dates_by_code:
            series = dict((margin_by_code or {}).get(code) or {})
            sc = _margin_delta_score(series, d, stale_days=stale_days)
            if sc is None:
                n_skip_stale_or_missing += 1
                continue
            scores[code] = float(sc)
        if len(scores) < 2:
            n_flat_sparse += 1
            for code in dates_by_code:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        n_ranked += 1
        n_names_ranked += len(scores)
        for code in dates_by_code:
            sign = ranks.get(code)
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **_occupancy_note(n_ranked, len(dates)),
            "n_ranked_days": n_ranked,
            "n_flat_sparse_days": n_flat_sparse,
            "n_skip_stale_or_missing": n_skip_stale_or_missing,
            "mean_names_on_ranked_days": (
                float(n_names_ranked) / float(n_ranked) if n_ranked else 0.0
            ),
            "occupancy_note": (
                "Ranked occupancy is honest: needs ≥2 names with two PIT "
                "margin prints, last print age ≤ stale cap. Not filled."
            ),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def _index_mom_on_dates(
    close_by_date: Mapping[str, float],
    dates: Sequence[str],
    *,
    momentum_n: int,
) -> dict[str, float | None]:
    n = int(momentum_n)
    out: dict[str, float | None] = {}
    for i, d in enumerate(dates):
        if i < n:
            out[str(d)[:10]] = None
            continue
        d0 = str(dates[i - n])[:10]
        c0 = close_by_date.get(d0)
        c1 = close_by_date.get(str(d)[:10])
        if c0 is None or c1 is None:
            out[str(d)[:10]] = None
            continue
        try:
            f0 = float(c0)
            f1 = float(c1)
        except (TypeError, ValueError):
            out[str(d)[:10]] = None
            continue
        if f0 == 0.0 or not math.isfinite(f0) or not math.isfinite(f1):
            out[str(d)[:10]] = None
            continue
        out[str(d)[:10]] = (f1 / f0) - 1.0
    return out


def evaluate_idio_mom_macro_impulse_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    topix_by_date: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS rank of residual mom vs TOPIX on large |TOPIX mom| days."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="abs_topix_mom_ge_pit_median",
        extra_dataset="indices_bars_daily_topix",
        data_path="local_real_mirrors+local_sqlite_topix",
    )
    topix = dict(topix_by_date or {})
    if not topix:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_topix_series",
            reason=(
                "indices_bars_daily_topix series empty — cannot build "
                "idiosyncratic mom vs TOPIX. Not approximated."
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

    topix_mom = _index_mom_on_dates(topix, dates, momentum_n=n)
    abs_mom = {
        d: abs(v) for d, v in topix_mom.items() if v is not None and math.isfinite(v)
    }
    med_by = w104.pit_median_on_dates(abs_mom, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_quiet = 0
    for d in dates:
        t_mom = topix_mom.get(d)
        name_moms = dict(by_date.get(d) or {})
        if t_mom is None:
            n_skip_missing += 1
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if abs(float(t_mom)) < float(med):
            n_skip_quiet += 1
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        residuals: dict[str, float] = {}
        for code, m in name_moms.items():
            if m is None:
                continue
            try:
                residuals[code] = float(m) - float(t_mom)
            except (TypeError, ValueError):
                continue
        if len(residuals) < 2:
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        ranks = cross_section_rank_signs(residuals, long_frac=lf, short_frac=sf)
        n_on += 1
        for code in name_moms:
            sign = ranks.get(code)
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **_occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_topix": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_quiet_macro": n_skip_quiet,
            "n_topix_prints": len(topix),
            "n_topix_mom": len(abs_mom),
        }
    )
    return _finish_cs_book(
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
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    topix_by_date: Mapping[str, float] | None,
    one_way_cost: float,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    bars = loaded["bars"]
    if lid == "funding_impulse_cs_tilt":
        return evaluate_funding_impulse_cs_tilt_daily_mtm(
            bars,
            overnight_by_date,
            spec=spec,
            one_way_cost=one_way_cost,
        )
    if lid == "curve_steepen_impulse_cs":
        return evaluate_curve_steepen_impulse_cs_daily_mtm(
            bars,
            curve_series,
            spec=spec,
            one_way_cost=one_way_cost,
        )
    if lid == "xs_margin_delta_rank":
        return evaluate_xs_margin_delta_rank_daily_mtm(
            bars,
            margin_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
        )
    if lid == "idio_mom_macro_impulse":
        return evaluate_idio_mom_macro_impulse_daily_mtm(
            bars,
            topix_by_date,
            spec=spec,
            one_way_cost=one_way_cost,
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
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    topix_by_date: Mapping[str, float] | None,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in W106_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w106/{lid}] window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_gate_on_win = 0
        n_ranked_win = 0
        n_bar_win = 0
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                log(f"[w106/{lid}]   {pid}: {loaded.get('status')}")
                continue
            pack = _eval_one_shard(
                spec=spec,
                loaded=loaded,
                overnight_by_date=overnight_by_date,
                curve_series=curve_series,
                margin_by_code=margin_by_code,
                topix_by_date=topix_by_date,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_gate_on_days"] = pack.get("n_gate_on_days")
            summary["n_gated_off_days"] = pack.get("n_gated_off_days")
            summary["n_ranked_days"] = pack.get("n_ranked_days")
            summary["occupancy_frac"] = pack.get("occupancy_frac")
            shard_summaries.append(summary)
            n_gate_on_win += int(pack.get("n_gate_on_days") or 0)
            n_ranked_win += int(pack.get("n_ranked_days") or 0)
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
                f"[w106/{lid}]   {pid}: status={pack.get('status')} "
                f"n={summary.get('n_equity_points')} "
                f"gate_on={pack.get('n_gate_on_days')} "
                f"ranked={pack.get('n_ranked_days')} "
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
                    f"(n_gate_on={n_gate_on_win} n_ranked={n_ranked_win})"
                ),
                extra={
                    "data_path": "local_real_mirrors+local_sqlite",
                    "n_gate_on_days": n_gate_on_win,
                    "n_ranked_days": n_ranked_win,
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
                    "n_ranked_days": n_ranked_win,
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
        f"[w106/B] propose n={len(proposals)} seed={seed} "
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
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w106/B] pack proposed={n_proposed} accepted={n_accepted} "
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
    extra = w105.inspect_unique_logic_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    from research.class_hyp_eval import load_topix_close_series_from_sqlite

    pairs = load_topix_close_series_from_sqlite(
        sqlite_path, start="2016-01-01", end="2026-12-31"
    )
    topix_by_date: dict[str, float] = {}
    for d, v in pairs or []:
        ds = str(d)[:10]
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if ds and math.isfinite(fv):
            topix_by_date[ds] = fv
    extra["topix_by_date"] = topix_by_date
    extra["topix"] = {
        "required_dataset": "indices_bars_daily_topix",
        "loader": "load_topix_close_series_from_sqlite",
        "status": "ok" if topix_by_date else "empty",
        "n_obs": len(topix_by_date),
        "date_min": min(topix_by_date) if topix_by_date else None,
        "date_max": max(topix_by_date) if topix_by_date else None,
        "no_ffill": True,
        "no_invent": True,
    }
    log(
        f"[w106] topix n_obs={len(topix_by_date)} "
        f"{extra['topix']['date_min']}..{extra['topix']['date_max']}"
    )
    return extra


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--seed", type=int, default=8908206)
    p.add_argument("--sqlite", type=str, default=str(SQLITE_DEFAULT))
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-daily", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w106_new_hyps_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w106] pins_untouched={pins['pins_untouched']}")
    log(
        "[w106] promote_as_main=false go=false hold_mom_grid=false "
        "dispersion_thresh_grid=false weak_template_mapping=OFF "
        "period_net_dd_only=forbidden complete≠GO "
        "pack_bias=mixed (funding/macro/xs, NOT event-filter-only) "
        "no sticky-approx always-on gate "
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
        log("[w106/B] propose skipped")

    daily_packs: dict[str, Any] = {}
    if not args.skip_daily:
        overnight = extra.get("overnight_by_date") or {}
        curve = extra.get("curve_series")
        margin = extra.get("margin_by_code") or {}
        topix = extra.get("topix_by_date") or {}
        for spec in NEW_UNIQUE_LOGIC:
            lid = str(spec["logic_id"])
            daily_packs[lid] = run_unique_logic_daily_dd(
                out_dir=out_dir,
                spec=spec,
                codes=codes,
                overnight_by_date=overnight,
                curve_series=curve,
                margin_by_code=margin,
                topix_by_date=topix,
                max_days=int(args.max_days),
                one_way_cost=float(args.one_way_cost),
                log=log,
            )
    else:
        log("[w106/B] daily_path_DD skipped")

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
                    "n_ranked_days": row.get("n_ranked_days"),
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
    pins_after["note"] = "W106 after unique_logic hyps; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": WAVE,
        "track": "B_new_unique_logic_hyps",
        "pack_bias": PACK_BIAS,
        "event_filter_only": False,
        "n_event_filter_logics": 0,
        "n_funding": 1,
        "n_macro": 1,
        "n_cross_section": 1,
        "n_macro_xs": 1,
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
        "git_sha": _git_sha(),
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w106_b_summary.json", summary)
    log(
        f"[w106] done wall={summary['wall_sec']}s "
        f"impl={n_impl} daily_complete_logics={n_complete} "
        f"pins={pins_after.get('pins_untouched')} pack_bias={PACK_BIAS} "
        f"worst={summary['worst_daily_path_DD_by_logic']}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
