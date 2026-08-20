#!/usr/bin/env python3
"""W106 / w0820c Track C — funding/surprise L/S min variants (not a kill).

Do **not** conclude “sign flipped so kill”. From
``event_funding_stress_skip`` and ``surprise_xs_rank_hold`` consider at most
2–3 min variants:

  * sign flip / short side
  * conditional L/S (opposite only under funding stress)
  * occupancy must not collapse

Each needs daily_path_DD. Table which window prefers which side.
NO threshold / hold grid farm. promote_as_main=false · go=false.

Variants (3, not a farm)
------------------------
1. ``event_funding_easy_short`` — same occupancy as skip; take −surprise
   when overnight is easy (sign-flip of the skip book).
2. ``event_funding_stress_ls`` — enter whenever overnight+median exist;
   original surprise sign when easy, opposite under stress. Occupancy
   expands (does not collapse).
3. ``surprise_xs_rank_flip`` — same ranked occupancy; long low-surprise /
   short high-surprise.

Examples
--------
    uv run python scripts/run_w106_funding_surprise_ls.py \\
        --out-dir .glm-logs/w0820c_w106_otc10_ls_hyps/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820c_w106_otc10_ls_hyps"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0820c_w106_funding_surprise_ls_20260820.md"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_event_rate_daily_dd as w102  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

WAVE = "W106 / w0820c"
W106_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT
PARENT_LOGIC_IDS: tuple[str, ...] = (
    "event_funding_stress_skip",
    "surprise_xs_rank_hold",
)

# ---------------------------------------------------------------------------
# 3 min L/S variants (not a threshold/hold grid; occupancy must not collapse)
# ---------------------------------------------------------------------------
NEW_LS_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_easy_short",
        "family_id": "event_funding_combo",
        "kind": "event_funding_easy_short",
        "parent_logic_id": "event_funding_stress_skip",
        "variant_kind": "sign_flip_short_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "SIGN-FLIP / SHORT SIDE of event_funding_stress_skip: same easy-"
            "funding occupancy, take −surprise-sign hold (not a kill of the "
            "parent; window sign-flip is a side table, not a discard)."
        ),
        "thesis": (
            "If post-earnings surprise drift under easy Tokyo overnight repo "
            "is window-unstable in sign, the short side of the same skip book "
            "is the other side of that table — not evidence to kill funding."
        ),
        "signal_definition": (
            "same PIT overnight-lt-median gate as event_funding_stress_skip; "
            "hold −surprise sign; missing overnight → skip (no ffill)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; enter only when "
            "funding is easy; position is opposite of surprise sign"
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
            "mode": "funding_easy_short",
            "gate": "overnight_lt_pit_trailing_median",
            "side": "short_surprise",
        },
    },
    {
        "logic_id": "event_funding_stress_ls",
        "family_id": "event_funding_combo",
        "kind": "event_funding_stress_ls",
        "parent_logic_id": "event_funding_stress_skip",
        "variant_kind": "conditional_ls",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "CONDITIONAL L/S: keep surprise-sign when overnight is easy; take "
            "opposite only under funding stress. Occupancy expands vs skip "
            "(does not collapse). Missing overnight still skip (no ffill)."
        ),
        "thesis": (
            "Funding-stress is a side switch, not a skip-to-empty. Stay in "
            "the event book under both easy and stress overnight regimes; "
            "flip only the surprise sign under stress."
        ),
        "signal_definition": (
            "overnight present and PIT median formed; +surprise if overnight "
            "< median, −surprise if overnight >= median; missing → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; original sign "
            "when easy, opposite only under stress; occupancy = classified "
            "events (easy + stress)"
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
            "mode": "funding_stress_ls",
            "gate": "overnight_present_pit_median",
            "side": "original_easy_opposite_stress",
        },
    },
    {
        "logic_id": "surprise_xs_rank_flip",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_flip",
        "parent_logic_id": "surprise_xs_rank_hold",
        "variant_kind": "sign_flip_short_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "SIGN-FLIP / SHORT SIDE of surprise_xs_rank_hold: same ranked-day "
            "occupancy; long low-surprise / short high-surprise. Not a kill of "
            "the parent; window sign-flip is a side table."
        ),
        "thesis": (
            "Relative-surprise rank is window-unstable in sign. The flipped "
            "CS book is the other side of that table, with occupancy held."
        ),
        "signal_definition": (
            "CS rank of surprise among names whose PIT event entry is inside "
            "the last post_hold_days sessions; flip rank signs; <2 names → "
            "flat (no invent)"
        ),
        "position_rule": (
            "balanced L/S on flipped surprise ranks for currently-in-window "
            "names; names with no recent PIT disclosure stay flat"
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
            "mode": "surprise_xs_rank_flip",
            "sign_flip": True,
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
    pack["note"] = "W106 funding/surprise L/S variants must not mutate 3-default pins"
    return pack


def _event_key(ev: Mapping[str, Any]) -> str:
    return f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"


def classify_funding_entries(
    collected: Mapping[str, Any],
    overnight_by_date: Mapping[str, float],
    *,
    min_hist: int,
) -> dict[str, Any]:
    """PIT overnight vs trailing median. Missing overnight → skip (no ffill)."""
    entry_dates = sorted({e["entry_date"] for e in collected["entries"]})
    med_by = w104.pit_median_on_dates(
        overnight_by_date, entry_dates, min_hist=min_hist
    )
    easy: dict[str, bool] = {}
    classified: dict[str, bool] = {}
    sign_mult: dict[str, float] = {}
    n_skip_missing = 0
    n_skip_no_median = 0
    n_easy = 0
    n_stress = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        d = ev["entry_date"]
        on = overnight_by_date.get(d)
        if on is None:
            n_skip_missing += 1
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_no_median += 1
            continue
        classified[key] = True
        if float(on) >= float(med):
            n_stress += 1
            sign_mult[key] = -1.0
        else:
            n_easy += 1
            easy[key] = True
            sign_mult[key] = 1.0
    return {
        "easy": easy,
        "classified": classified,
        "sign_mult": sign_mult,
        "n_skip_missing": n_skip_missing,
        "n_skip_no_median": n_skip_no_median,
        "n_easy": n_easy,
        "n_stress": n_stress,
    }


def _funding_base_extra(
    spec: Mapping[str, Any], collected: Mapping[str, Any], *, min_hist: int
) -> dict[str, Any]:
    return {
        "kind": spec.get("kind"),
        "variant_kind": spec.get("variant_kind"),
        "parent_logic_id": spec.get("parent_logic_id"),
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "min_hist": min_hist,
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
        "sign_flip_is_not_a_kill": True,
    }


def _blocked_overnight_or_events(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    overnight_by_date: Mapping[str, float],
    extra: Mapping[str, Any],
) -> dict[str, Any] | None:
    dates = list(collected["calendar"])
    if not overnight_by_date:
        return {
            "status": "missing_overnight_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "funding L/S PIT gate. Not approximated."
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
    return None


def _finish_signed_event_book(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    accept: Mapping[str, bool],
    extra: Mapping[str, Any],
    one_way_cost: float,
    sign_mult_by_key: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    dates = list(collected["calendar"])
    held = w104._held_from_event_entries(
        collected, accept=accept, sign_mult_by_key=sign_mult_by_key
    )
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra.get("data_path")
    pack["new_unique_logic"] = True
    pack["catalog"] = False
    pack["promote_as_main"] = False
    pack["go"] = False
    pack["sign_flip_is_not_a_kill"] = True
    return pack


def evaluate_event_funding_easy_short_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Easy-funding occupancy of skip, flipped surprise sign."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = w104._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_funding_base_extra(spec, collected, min_hist=min_hist),
        "gate": "overnight_lt_pit_trailing_median",
        "side": "short_surprise",
    }
    blocked = _blocked_overnight_or_events(
        spec=spec,
        collected=collected,
        overnight_by_date=overnight_by_date,
        extra=extra,
    )
    if blocked:
        return blocked
    gate = classify_funding_entries(
        collected, overnight_by_date, min_hist=min_hist
    )
    accept = dict(gate["easy"])
    sign_mult = {k: -1.0 for k in accept}
    extra.update(
        {
            "n_entered": int(gate["n_easy"]),
            "n_easy_entered": int(gate["n_easy"]),
            "n_stress_entered": 0,
            "n_skip_missing_overnight": int(gate["n_skip_missing"]),
            "n_skip_median_unformed": int(gate["n_skip_no_median"]),
            "n_skip_funding_stress": int(gate["n_stress"]),
            "occupancy_vs_parent": "same_as_skip",
        }
    )
    return _finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=sign_mult,
    )


def evaluate_event_funding_stress_ls_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Conditional L/S: original when easy, opposite only under stress."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = w104._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_funding_base_extra(spec, collected, min_hist=min_hist),
        "gate": "overnight_present_pit_median",
        "side": "original_easy_opposite_stress",
    }
    blocked = _blocked_overnight_or_events(
        spec=spec,
        collected=collected,
        overnight_by_date=overnight_by_date,
        extra=extra,
    )
    if blocked:
        return blocked
    gate = classify_funding_entries(
        collected, overnight_by_date, min_hist=min_hist
    )
    extra.update(
        {
            "n_entered": int(gate["n_easy"]) + int(gate["n_stress"]),
            "n_easy_entered": int(gate["n_easy"]),
            "n_stress_entered": int(gate["n_stress"]),
            "n_skip_missing_overnight": int(gate["n_skip_missing"]),
            "n_skip_median_unformed": int(gate["n_skip_no_median"]),
            "n_skip_funding_stress": 0,
            "occupancy_vs_parent": "expanded_vs_skip",
        }
    )
    return _finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=dict(gate["classified"]),
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=dict(gate["sign_mult"]),
    )


def evaluate_surprise_xs_rank_flip_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Same occupancy as surprise_xs_rank_hold; flipped rank signs."""
    flipped = dict(spec)
    params = dict(spec.get("params") or {})
    params["sign_flip"] = True
    flipped["params"] = params
    flipped["sign_flip"] = True
    pack = w104.evaluate_surprise_xs_rank_hold_daily_mtm(
        bars_by_code,
        events_by_code,
        spec=flipped,
        one_way_cost=one_way_cost,
        period_start=period_start,
        period_end=period_end,
    )
    pack["logic_id"] = spec["logic_id"]
    pack["kind"] = spec.get("kind")
    pack["variant_kind"] = spec.get("variant_kind")
    pack["parent_logic_id"] = spec.get("parent_logic_id")
    pack["sign_flip"] = True
    pack["occupancy_vs_parent"] = "same_as_rank_hold"
    pack["sign_flip_is_not_a_kill"] = True
    pack["promote_as_main"] = False
    pack["go"] = False
    return pack


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
    if lid == "event_funding_easy_short":
        return evaluate_event_funding_easy_short_daily_mtm(
            bars,
            events_by_code,
            overnight_by_date,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "event_funding_stress_ls":
        return evaluate_event_funding_stress_ls_daily_mtm(
            bars,
            events_by_code,
            overnight_by_date,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "surprise_xs_rank_flip":
        return evaluate_surprise_xs_rank_flip_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    return w104._eval_one_shard(
        spec=spec,
        loaded=loaded,
        events_by_code=events_by_code,
        overnight_by_date=overnight_by_date,
        curve_series=curve_series,
        one_way_cost=one_way_cost,
    )


def run_ls_daily_dd(
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
    for w in W106_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w106/{lid}] window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_entered_win = 0
        n_events_win = 0
        n_ranked_win = 0
        n_easy_win = 0
        n_stress_win = 0
        n_act_win = 0
        n_cal_win = 0
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
            summary["n_ranked_days"] = pack.get("n_ranked_days")
            summary["n_easy_entered"] = pack.get("n_easy_entered")
            summary["n_stress_entered"] = pack.get("n_stress_entered")
            summary["n_active_days"] = pack.get("n_active_days")
            shard_summaries.append(summary)
            n_entered_win += int(pack.get("n_entered") or 0)
            n_events_win += int(pack.get("n_events") or 0)
            n_ranked_win += int(pack.get("n_ranked_days") or 0)
            n_easy_win += int(pack.get("n_easy_entered") or 0)
            n_stress_win += int(pack.get("n_stress_entered") or 0)
            n_act_win += int(pack.get("n_active_days") or 0)
            dates_p = list(pack.get("dates") or [])
            n_cal_win += max(0, len(dates_p) - 1)
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
                f"entered={pack.get('n_entered')} events={pack.get('n_events')} "
                f"easy={pack.get('n_easy_entered')} stress={pack.get('n_stress_entered')} "
                f"ranked={pack.get('n_ranked_days')} "
                f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                f"total_net={_fmt(summary.get('total_return_net'))}"
            )
        if not stitch_net:
            gate = evaluate_daily_path_dd_gate(period_net_dd=0.0)
            row = {
                "logic_id": lid,
                "window": wid,
                "daily_path_complete": False,
                "incomplete_reason": (
                    "no ok daily path stitched for this window "
                    f"(n_events={n_events_win} n_entered={n_entered_win})"
                ),
                "n_events": n_events_win,
                "n_entered": n_entered_win,
                "n_ranked_days": n_ranked_win,
                "n_easy_entered": n_easy_win,
                "n_stress_entered": n_stress_win,
                "parent_logic_id": spec.get("parent_logic_id"),
                "variant_kind": spec.get("variant_kind"),
                "new_unique_logic": True,
                "catalog": False,
                "promote_as_main": False,
                "go": False,
                "sign_flip_is_not_a_kill": True,
                "shard_summaries": shard_summaries,
                "gate": {
                    "complete": gate.get("complete"),
                    "fails": gate.get("fails"),
                    "warnings": gate.get("warnings"),
                    "period_net_dd_only_pass_forbidden": True,
                },
            }
        else:
            stitched = w100._stitch_net(stitch_net, stitch_dates)
            net = stitched.get("total_return_net")
            sign = None
            if net is not None:
                try:
                    fv = float(net)
                    if fv > 0:
                        sign = "+"
                    elif fv < 0:
                        sign = "−"
                    else:
                        sign = "0"
                except (TypeError, ValueError):
                    sign = None
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
                    "n_ranked_days": n_ranked_win,
                    "n_easy_entered": n_easy_win,
                    "n_stress_entered": n_stress_win,
                    "n_active_days": n_act_win,
                    "n_calendar_days": n_cal_win,
                    "active_frac": (n_act_win / n_cal_win) if n_cal_win else None,
                    "enter_frac_of_events": (
                        (n_entered_win / n_events_win) if n_events_win else None
                    ),
                    "ranked_frac": (
                        (n_ranked_win / n_cal_win) if n_cal_win else None
                    ),
                    "side_sign": sign,
                    "parent_logic_id": spec.get("parent_logic_id"),
                    "variant_kind": spec.get("variant_kind"),
                    "new_unique_logic": True,
                    "catalog": False,
                    "catalog_map": None,
                    "why_unique": spec.get("why_unique"),
                    "sign_flip_is_not_a_kill": True,
                    "hold_mom_grid": False,
                    "threshold_grid": False,
                    "promote_as_main": False,
                    "go": False,
                },
            )
            row["total_ret_net"] = stitched.get("total_return_net")
            row["side_sign"] = sign
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
        "parent_logic_id": spec.get("parent_logic_id"),
        "variant_kind": spec.get("variant_kind"),
        "new_unique_logic": True,
        "catalog": False,
        "promote_as_main": False,
        "go": False,
        "sign_flip_is_not_a_kill": True,
    }


def _parent_spec(logic_id: str) -> dict[str, Any]:
    for s in w104.NEW_UNIQUE_LOGIC:
        if s["logic_id"] == logic_id:
            return dict(s)
    raise KeyError(logic_id)


def proposals_for_factory() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in NEW_LS_VARIANTS:
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
                "parent_logic_id": spec.get("parent_logic_id"),
                "variant_kind": spec.get("variant_kind"),
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
        f"[w106/C] propose n={len(proposals)} seed={seed} "
        "weak_template_mapping=OFF map_unknown_to_nearest_catalog=false "
        "not_a_count_race=True daily_path_DD_required=True "
        "sign_flip_is_not_a_kill=True"
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
    _dump(out_dir / "ls_hyp_propose_compact.json", compact)
    _dump(out_dir / "ls_hyp_proposals.json", proposals)
    _dump(out_dir / "ls_hyp_accepted.json", eval_out.get("accepted") or [])
    _dump(out_dir / "ls_hyp_rejected.json", eval_out.get("rejected") or [])
    _dump(out_dir / "ls_hyp_eval_screens.json", eval_out.get("eval_screens") or [])

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
        "track": "C_funding_surprise_ls",
        "n_requested": 3,
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_rejected,
        "n_evaluated_factory_synthetic": n_evaluated,
        "n_survivors_period_net": n_survivors_period_net,
        "period_net_is_not_a_pass": True,
        "period_net_dd_only_pass_forbidden": True,
        "sign_flip_is_not_a_kill": True,
        "did_not_kill_funding_surprise": True,
        "weak_template_mapping": "OFF",
        "map_unknown_to_nearest_catalog": False,
        "not_a_count_race": True,
        "hold_mom_grid": False,
        "threshold_grid": False,
        "daily_path_DD_required": True,
        "representative_theses": [
            {
                "logic_id": s["logic_id"],
                "family_id": s["family_id"],
                "parent_logic_id": s.get("parent_logic_id"),
                "variant_kind": s.get("variant_kind"),
                "new_unique_logic": True,
                "catalog": False,
                "why_unique": s.get("why_unique"),
                "thesis": s["thesis"],
            }
            for s in NEW_LS_VARIANTS
        ],
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "promote_as_main": False,
        "go": False,
        "seed": int(seed),
    }
    _dump(out_dir / "ls_hyp_summary.json", summary)
    log(
        f"[w106/C] pack proposed={n_proposed} accepted={n_accepted} "
        f"factory_eval={n_evaluated} period_net_survivors={n_survivors_period_net} "
        "(NOT a pass / NOT a kill)"
    )
    return {"summary": summary, "eval_out": eval_out}


def _side_preference_table(
    daily_packs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Which window prefers which side (parent vs flip vs conditional L/S)."""
    by_lid_win: dict[tuple[str, str], dict[str, Any]] = {}
    for lid, pack in daily_packs.items():
        for row in pack.get("table") or []:
            wid = str(row.get("window") or "")
            by_lid_win[(lid, wid)] = row
    windows = [str(w["window_id"]) for w in W106_WINDOWS]
    out: list[dict[str, Any]] = []
    pairs = (
        (
            "event_funding_stress_skip",
            "event_funding_easy_short",
            "event_funding_stress_ls",
        ),
        (
            "surprise_xs_rank_hold",
            "surprise_xs_rank_flip",
            None,
        ),
    )
    for parent, flip, cond in pairs:
        for wid in windows:
            prow = by_lid_win.get((parent, wid)) or {}
            frow = by_lid_win.get((flip, wid)) or {}
            crow = by_lid_win.get((cond, wid)) if cond else {}
            cands: list[tuple[str, Any, Any]] = []
            for lid, row in (
                (parent, prow),
                (flip, frow),
                (cond, crow),
            ):
                if not lid or not row:
                    continue
                net = row.get("total_ret_net")
                dd = row.get("daily_path_DD")
                if net is None:
                    continue
                cands.append((lid, float(net), dd))
            preferred = None
            if cands:
                preferred = max(cands, key=lambda x: x[1])[0]
            def _occ(row: Mapping[str, Any]) -> dict[str, Any]:
                return {
                    "n_entered": row.get("n_entered"),
                    "n_events": row.get("n_events"),
                    "n_ranked_days": row.get("n_ranked_days"),
                    "n_easy_entered": row.get("n_easy_entered"),
                    "n_stress_entered": row.get("n_stress_entered"),
                    "active_frac": row.get("active_frac"),
                }

            out.append(
                {
                    "window": wid,
                    "parent": parent,
                    "parent_net": prow.get("total_ret_net"),
                    "parent_sign": prow.get("side_sign"),
                    "parent_dd": prow.get("daily_path_DD"),
                    "parent_occ": _occ(prow),
                    "flip": flip,
                    "flip_net": frow.get("total_ret_net"),
                    "flip_sign": frow.get("side_sign"),
                    "flip_dd": frow.get("daily_path_DD"),
                    "flip_occ": _occ(frow),
                    "conditional": cond,
                    "conditional_net": (crow or {}).get("total_ret_net"),
                    "conditional_sign": (crow or {}).get("side_sign"),
                    "conditional_dd": (crow or {}).get("daily_path_DD"),
                    "conditional_occ": _occ(crow or {}),
                    "preferred_side_logic": preferred,
                    "sign_flip_is_not_a_kill": True,
                    "occupancy_collapsed": False,
                    "promote_as_main": False,
                    "go": False,
                }
            )
    return out


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
    p.add_argument("--skip-parents", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w106_funding_surprise_ls.log"

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
        "threshold_grid=false weak_template_mapping=OFF "
        "period_net_dd_only=forbidden complete≠GO "
        "sign_flip_is_not_a_kill=True did_not_kill_funding_surprise=True "
        "GLM implementer only. Grok did not implement."
    )

    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(args.max_codes)]
    sqlite_path = Path(args.sqlite)
    extra = w104.inspect_unique_logic_datasets(
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
        log("[w106/C] propose skipped")

    daily_packs: dict[str, Any] = {}
    if not args.skip_daily:
        events = extra.get("fins_events") or {}
        overnight = extra.get("overnight_by_date") or {}
        curve = extra.get("curve_series")
        specs: list[dict[str, Any]] = []
        if not args.skip_parents:
            for lid in PARENT_LOGIC_IDS:
                specs.append(_parent_spec(lid))
        specs.extend(list(NEW_LS_VARIANTS))
        for spec in specs:
            lid = str(spec["logic_id"])
            daily_packs[lid] = run_ls_daily_dd(
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
        log("[w106/C] daily_path_DD skipped")

    compact: list[dict[str, Any]] = []
    for lid, pack in daily_packs.items():
        for row in pack.get("table") or []:
            compact.append(
                {
                    "logic_id": row.get("logic_id"),
                    "parent_logic_id": row.get("parent_logic_id"),
                    "variant_kind": row.get("variant_kind"),
                    "new_unique_logic": lid in {s["logic_id"] for s in NEW_LS_VARIANTS},
                    "catalog": False,
                    "window": row.get("window"),
                    "n_days": row.get("n_days"),
                    "daily_path_DD": row.get("daily_path_DD"),
                    "dd_duration": row.get("dd_duration"),
                    "recovery_days": row.get("recovery_days"),
                    "recovered": row.get("recovered"),
                    "total_ret_net": row.get("total_ret_net"),
                    "side_sign": row.get("side_sign"),
                    "daily_path_complete": row.get("daily_path_complete"),
                    "n_events": row.get("n_events"),
                    "n_entered": row.get("n_entered"),
                    "n_ranked_days": row.get("n_ranked_days"),
                    "n_easy_entered": row.get("n_easy_entered"),
                    "n_stress_entered": row.get("n_stress_entered"),
                    "active_frac": row.get("active_frac"),
                    "sign_flip_is_not_a_kill": True,
                    "promote_as_main": False,
                    "go": False,
                    "stance": "RESEARCH_ONLY",
                    "data_path": row.get("data_path"),
                }
            )
    _dump(out_dir / "ls_daily_dd_table.json", compact)
    side_table = _side_preference_table(daily_packs)
    _dump(out_dir / "ls_side_preference_table.json", side_table)

    n_impl = sum(1 for s in NEW_LS_VARIANTS if daily_packs.get(s["logic_id"]))
    n_complete = sum(
        1
        for s in NEW_LS_VARIANTS
        if (daily_packs.get(s["logic_id"]) or {}).get("complete")
    )
    pins_after = _assert_frozen_pins_untouched()
    pins_after["note"] = "W106 after L/S variants; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    occupancy_ok = True
    for parent, child, kind in (
        ("event_funding_stress_skip", "event_funding_easy_short", "same"),
        ("event_funding_stress_skip", "event_funding_stress_ls", "expanded"),
        ("surprise_xs_rank_hold", "surprise_xs_rank_flip", "same"),
    ):
        for w in W106_WINDOWS:
            wid = str(w["window_id"])
            prow = next(
                (
                    r
                    for r in (daily_packs.get(parent) or {}).get("table") or []
                    if r.get("window") == wid
                ),
                None,
            )
            crow = next(
                (
                    r
                    for r in (daily_packs.get(child) or {}).get("table") or []
                    if r.get("window") == wid
                ),
                None,
            )
            if not prow or not crow:
                continue
            if parent.startswith("surprise"):
                p_occ = int(prow.get("n_ranked_days") or 0)
                c_occ = int(crow.get("n_ranked_days") or 0)
            else:
                p_occ = int(prow.get("n_entered") or 0)
                c_occ = int(crow.get("n_entered") or 0)
            if kind == "same" and c_occ < p_occ:
                occupancy_ok = False
            if kind == "expanded" and c_occ < p_occ:
                occupancy_ok = False

    summary = {
        "wave": WAVE,
        "track": "C_funding_surprise_ls",
        "n_requested": 3,
        "n_proposed": 3,
        "n_accepted": (hyp_pack or {}).get("summary", {}).get("n_accepted"),
        "n_min_implemented": n_impl,
        "n_daily_path_complete_logics": n_complete,
        "ls_variant_ids": [s["logic_id"] for s in NEW_LS_VARIANTS],
        "parent_logic_ids": list(PARENT_LOGIC_IDS),
        "catalog_map_headline": False,
        "weak_template_mapping": "OFF",
        "hold_mom_microgrid": False,
        "threshold_grid": False,
        "period_net_dd_only_pass_forbidden": True,
        "daily_path_DD_required": True,
        "sign_flip_is_not_a_kill": True,
        "did_not_kill_funding_surprise": True,
        "occupancy_did_not_collapse": occupancy_ok,
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
        "side_preference": side_table,
        "hyps": (hyp_pack or {}).get("summary") if hyp_pack else None,
        "git_sha": _git_sha(),
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w106_c_summary.json", summary)
    log(
        f"[w106] done wall={summary['wall_sec']}s "
        f"impl={n_impl} daily_complete_logics={n_complete} "
        f"occupancy_ok={occupancy_ok} pins={pins_after.get('pins_untouched')} "
        f"worst={summary['worst_daily_path_DD_by_logic']}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
