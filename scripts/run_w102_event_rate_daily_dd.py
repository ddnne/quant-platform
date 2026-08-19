#!/usr/bin/env python3
"""W102 / w0819e Track B — event / rate extra-dataset daily_path_DD.

Wires the two W100 period-net survivors that were left incomplete:

  * ``event_post_disclosure_hold``  ← fins_summary (DiscDate/DiscTime + surprise)
  * ``rate_curve_shape_xs``         ← jsda_tokyo_repo_rates (3M−ON curve) + bars

Same daily MTM-after-cost method as W99/W100. period_net_DD-only is
forbidden. Complete measurement ≠ GO / main. 3-default pins untouched.

If an extra dataset cannot be loaded, the row stays **incomplete** with the
exact missing path — never approximated into complete.

Examples
--------
    uv run python scripts/run_w102_event_rate_daily_dd.py \\
        --out-dir .glm-logs/w0819e_w102_otc6_event_rate_dd/
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819e_w102_otc6_event_rate_dd"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0819e_w102_event_rate_daily_dd_20260819.md"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

W102_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT

EVENT_SPEC: dict[str, Any] = {
    "logic_id": "event_post_disclosure_hold",
    "family": "event_post",
    "kind": "event_post_hold",
    "post_hold_days": 5,
    "entry_mode": "same_day_close_if_pre_close",
    "catalog": True,
    "extra_dataset": "fins_summary",
    "why": "W100 period-net survivor; extra-dataset event book — daily_path_DD this wave",
}

RATE_SPEC: dict[str, Any] = {
    "logic_id": "rate_curve_shape_xs",
    "family": "rate_factor",
    "kind": "rate_curve_xs",
    "hold_days": 10,
    "momentum_n": 5,
    "long_frac": 0.3,
    "short_frac": 0.3,
    "steep_threshold": 0.0,
    "invert_threshold": 0.0,
    "curve_short_tenor": "overnight/翌日物/T+0",
    "curve_long_tenor": "3M/T+1",
    "catalog": True,
    "extra_dataset": "jsda_tokyo_repo_rates",
    "why": "W100 period-net survivor; extra-dataset curve CS — daily_path_DD this wave",
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _assert_frozen_pins_untouched() -> dict[str, Any]:
    pack = w99._assert_frozen_pins_untouched()
    pack["note"] = "W102 event/rate daily DD must not mutate 3-default pins"
    return pack


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def inspect_extra_datasets(
    *,
    codes: Sequence[str],
    sqlite_path: Path,
    log,
) -> dict[str, Any]:
    """Identify + load extra datasets required for a daily equity curve."""
    from research.class_hyp_eval import (
        build_repo_curve_series,
        load_fins_events_from_sqlite,
        load_repo_rows_all_tenors_from_sqlite,
    )

    pack: dict[str, Any] = {
        "sqlite_path": str(sqlite_path),
        "sqlite_exists": sqlite_path.is_file(),
        "codes": list(codes),
        "event": {
            "logic_id": EVENT_SPEC["logic_id"],
            "required_dataset": "fins_summary",
            "required_fields": [
                "DiscDate",
                "DiscTime",
                "EPS",
                "FEPS",
                "prior_eps (chronological)",
            ],
            "loader": "load_fins_events_from_sqlite",
            "local_table": "jquants_records WHERE dataset='fins_summary'",
        },
        "rate": {
            "logic_id": RATE_SPEC["logic_id"],
            "required_dataset": "jsda_tokyo_repo_rates",
            "required_tenors": [
                RATE_SPEC["curve_short_tenor"],
                RATE_SPEC["curve_long_tenor"],
            ],
            "curve_definition": "spread = rate(3M/T+1) - rate(overnight/翌日物/T+0)",
            "loader": "load_repo_rows_all_tenors_from_sqlite + build_repo_curve_series",
            "local_table": "jsda_repo_rates",
            "no_ffill": True,
            "no_invent": True,
        },
    }

    if not sqlite_path.is_file():
        pack["status"] = "missing_sqlite"
        pack["blocked"] = True
        pack["missing"] = [str(sqlite_path)]
        log(f"[w102] BLOCKED missing sqlite {sqlite_path}")
        return pack

    # Event: lookback so prior_eps exists for 2017 shards.
    events = load_fins_events_from_sqlite(
        sqlite_path, codes=list(codes), start="2016-01-01", end="2026-12-31"
    )
    n_events = sum(len(v) for v in events.values())
    n_disc_time = 0
    n_surprise_fields = 0
    first_d: str | None = None
    last_d: str | None = None
    per_code: dict[str, int] = {}
    for code, evs in events.items():
        per_code[code] = len(evs)
        for ev in evs:
            d = str(ev.get("disc_date") or "")[:10]
            if d:
                if first_d is None or d < first_d:
                    first_d = d
                if last_d is None or d > last_d:
                    last_d = d
            if ev.get("disc_time"):
                n_disc_time += 1
            if ev.get("eps") is not None and (
                ev.get("feps") is not None or ev.get("prior_eps") is not None
            ):
                n_surprise_fields += 1
    event_ok = n_events > 0 and len(events) > 0
    pack["event"].update(
        {
            "status": "ok" if event_ok else "empty",
            "n_codes_with_events": len(events),
            "n_events": n_events,
            "n_disc_time_present": n_disc_time,
            "n_surprise_fields": n_surprise_fields,
            "disc_date_min": first_d,
            "disc_date_max": last_d,
            "per_code": per_code,
            "invent_disctime": False,
        }
    )
    pack["fins_events"] = events if event_ok else {}

    repo_rows = load_repo_rows_all_tenors_from_sqlite(
        sqlite_path, start="2016-01-01", end="2026-12-31"
    )
    curve = build_repo_curve_series(
        repo_rows,
        short_tenor=str(RATE_SPEC["curve_short_tenor"]),
        long_tenor=str(RATE_SPEC["curve_long_tenor"]),
    )
    n_spread = int(curve.get("n_obs_spread") or 0)
    rate_ok = n_spread > 0
    pack["rate"].update(
        {
            "status": "ok" if rate_ok else "empty",
            "n_repo_rows": len(repo_rows),
            "n_obs_short": curve.get("n_obs_short"),
            "n_obs_long": curve.get("n_obs_long"),
            "n_obs_spread": n_spread,
            "n_gap_either_leg": curve.get("n_gap_either_leg"),
            "tenors_observed": curve.get("tenors_observed"),
            "spread_date_min": min(curve.get("spread_by_date") or {"": None})
            if curve.get("spread_by_date")
            else None,
            "spread_date_max": max(curve.get("spread_by_date") or {"": None})
            if curve.get("spread_by_date")
            else None,
            "ffill_applied": bool(curve.get("ffill_applied")),
            "invent_fill": bool(curve.get("invent_fill")),
        }
    )
    pack["curve_series"] = curve if rate_ok else None

    missing: list[str] = []
    if not event_ok:
        missing.append(
            "fins_summary events empty for DEFAULT_EVAL_CODES "
            "(need DiscDate/DiscTime + EPS/FEPS|prior_eps in jquants_records)"
        )
    if not rate_ok:
        missing.append(
            "jsda_tokyo_repo_rates curve empty "
            "(need same-date overnight/翌日物/T+0 and 3M/T+1 in jsda_repo_rates)"
        )
    pack["missing"] = missing
    pack["blocked"] = bool(missing)
    pack["status"] = "ok" if not missing else "partial_or_blocked"
    log(
        f"[w102] extra datasets event={pack['event']['status']} "
        f"n_events={n_events} n_codes={len(events)} "
        f"rate={pack['rate']['status']} n_spread={n_spread} "
        f"missing={missing or 'none'}"
    )
    return pack


def evaluate_event_post_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Daily MTM of PIT post-disclosure holds (not period-net).

    Book construction (single book; last-event-wins if overlapping):
      * PIT entry via ``event_post_entry_bar_index`` (no DiscTime invent).
      * Position = sign(surprise_proxy) on [entry, entry+hold) session dates.
      * Flatten after hold. Non-event / no-surprise → no trade.
    Daily mark + amortized cost uses the W99/W100 held-book path.
    """
    from features.class_signals import (
        earnings_surprise_proxy,
        event_post_entry_bar_index,
        sign_from_numeric,
    )

    h = int(spec.get("post_hold_days") or 5)
    entry_mode = str(spec.get("entry_mode") or "same_day_close_if_pre_close")
    p0 = str(period_start)[:10] if period_start else None
    p1 = str(period_end)[:10] if period_end else None

    close_by: dict[str, dict[str, float]] = {}
    held_by_code_date: dict[str, dict[str, float | None]] = {}
    calendar: set[str] = set()
    n_events = 0
    n_entered = 0
    n_no_surprise = 0
    n_no_bar = 0
    n_same_day = 0
    n_next_session = 0
    n_overlap_replace = 0

    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        dlist = [str(d)[:10] for d, _ in pairs_l]
        date_to_idx = {d: i for i, d in enumerate(dlist)}
        for d, c in pairs_l:
            close_by.setdefault(code, {})[str(d)[:10]] = float(c)
            calendar.add(str(d)[:10])
        held: list[float | None] = [None] * len(dlist)
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
            if sgn is None or sgn == 0.0:
                n_no_surprise += 1
                continue
            if entry_date == disc:
                n_same_day += 1
            else:
                n_next_session += 1
            n_entered += 1
            end = min(idx + h, len(dlist))
            for j in range(idx, end):
                if held[j] is not None and held[j] != float(sgn):
                    n_overlap_replace += 1
                held[j] = float(sgn)
        held_by_code_date[code] = {dlist[i]: held[i] for i in range(len(dlist))}

    dates = sorted(calendar)
    extra = {
        "kind": spec.get("kind"),
        "post_hold_days": h,
        "entry_mode": entry_mode,
        "n_events": n_events,
        "n_entered": n_entered,
        "n_no_surprise": n_no_surprise,
        "n_no_bar_match": n_no_bar,
        "n_same_day_entry": n_same_day,
        "n_next_session_entry": n_next_session,
        "n_overlap_replace": n_overlap_replace,
        "hold_construction": "explicit_event_window_last_event_wins",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
        "catalog": True,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if not dates:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": 0,
            **extra,
        }
    if n_events == 0:
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

    pack = w100._held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=close_by,
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_rate_curve_xs_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """Daily MTM of repo-curve × CS L-S sticky book (not period-net).

    Same daily rank + curve transform + sticky hold as
    ``evaluate_rate_curve_xs_on_bars``; marked every session. Missing either
    tenor on a bar date → gap (no ffill / no invent).
    """
    from features.class_signals import apply_sticky_hold, compute_rate_curve_xs_signal

    n = int(spec.get("momentum_n") or 5)
    h = int(spec.get("hold_days") or 10)
    lf = float(spec.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or 0.3)
    steep = float(spec.get("steep_threshold") or 0.0)
    invert = float(spec.get("invert_threshold") or 0.0)

    extra_base = {
        "kind": spec.get("kind"),
        "momentum_n": n,
        "hold_days": h,
        "long_frac": lf,
        "short_frac": sf,
        "steep_threshold": steep,
        "invert_threshold": invert,
        "curve_short_tenor": (curve_series or {}).get("short_tenor")
        or spec.get("curve_short_tenor"),
        "curve_long_tenor": (curve_series or {}).get("long_tenor")
        or spec.get("curve_long_tenor"),
        "extra_dataset": "jsda_tokyo_repo_rates",
        "data_path": "local_real_mirrors+local_sqlite_jsda_repo_rates",
        "ffill_applied": False,
        "invent_fill": False,
        "catalog": True,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if not curve_series or not (curve_series.get("spread_by_date") or {}):
        return {
            "status": "missing_curve_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates curve series empty — cannot build "
                "daily book. Not approximated."
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

    from features.class_signals import cross_section_rank_signs

    short_by = dict(curve_series.get("short_rates_by_date") or {})
    long_by = dict(curve_series.get("long_rates_by_date") or {})
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        s_rate = short_by.get(str(d)[:10])
        l_rate = long_by.get(str(d)[:10])
        if s_rate is None or l_rate is None:
            n_regime_gap += 1
            for code in ranks:
                daily_adj.setdefault(code, {})[d] = None
            continue
        for code, cs_sign in ranks.items():
            rec = compute_rate_curve_xs_signal(
                cs_sign=cs_sign,
                short_rate=s_rate,
                long_rate=l_rate,
                steep_threshold=steep,
                invert_threshold=invert,
                code=code,
                date=d,
            )
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]))
            for i in range(len(dlist))
        }

    extra = {
        **extra_base,
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_bar_dates": len(dates),
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
    pack["n_regime_gap"] = n_regime_gap
    pack["regime_counts"] = regime_counts
    return pack


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


def _window_row_from_stitch(
    *,
    logic_id: str,
    window: Mapping[str, Any],
    stitched: Mapping[str, Any],
    stitch_net: Sequence[float],
    stitch_gross: Sequence[float],
    shard_summaries: Sequence[Mapping[str, Any]],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    g_eq = 1.0
    for i, g in enumerate(stitch_gross):
        if i == 0:
            continue
        g_eq *= 1.0 + float(g)
    gate = stitched.get("daily_path_dd_gate") or {}
    row = {
        "logic_id": logic_id,
        "window": window["window_id"],
        "label": window["label"],
        "data_note": window["data_note"],
        "n_days": stitched.get("n_equity_points"),
        "daily_path_DD": stitched.get("daily_path_DD"),
        "abs_max_dd": stitched.get("abs_max_dd"),
        "dd_duration": stitched.get("dd_duration"),
        "recovery_days": stitched.get("recovery_days"),
        "recovered": stitched.get("recovered"),
        "peak_date": stitched.get("peak_date"),
        "trough_date": stitched.get("trough_date"),
        "recovery_date": stitched.get("recovery_date"),
        "total_ret_net": stitched.get("total_return_net"),
        "total_return_gross": g_eq - 1.0 if stitch_gross else None,
        "mean_net_daily": (
            sum(stitch_net[1:]) / max(1, len(stitch_net) - 1)
            if len(stitch_net) > 1
            else None
        ),
        "daily_path_complete": bool(gate.get("complete")),
        "daily_path_measured": bool(gate.get("measured")),
        "promote_as_main": False,
        "go": False,
        "stance": "RESEARCH_ONLY",
        "research_only": True,
        "shard_summaries": list(shard_summaries),
        "warning": (
            "period_net_DD=0 is an aggregation artifact — NOT riskless. "
            "Use daily_path_DD."
        ),
    }
    if extra:
        row.update(dict(extra))
    return row


def run_event_daily_dd(
    *,
    out_dir: Path,
    codes: Sequence[str],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if not events_by_code:
        reason = (
            "fins_summary not wired: no DiscDate events for eval codes in "
            "local ingestion.sqlite jquants_records. Daily book cannot be built."
        )
        for w in W102_WINDOWS:
            row = _incomplete_row(
                logic_id=EVENT_SPEC["logic_id"],
                window_id=str(w["window_id"]),
                reason=reason,
                extra={"data_path": None, "extra_dataset": "fins_summary"},
            )
            rows.append(row)
        _dump(out_dir / "event_post_disclosure_hold_daily_dd.json", rows)
        return {"table": rows, "logic_id": EVENT_SPEC["logic_id"], "complete": False}

    for w in W102_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w102/event] window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_entered_win = 0
        n_events_win = 0
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                log(f"[w102/event]   {pid}: {loaded.get('status')}")
                continue
            pack = evaluate_event_post_daily_mtm(
                loaded["bars"],
                events_by_code,
                spec=EVENT_SPEC,
                one_way_cost=float(one_way_cost),
                period_start=loaded.get("period_start"),
                period_end=loaded.get("period_end"),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_events"] = pack.get("n_events")
            summary["n_entered"] = pack.get("n_entered")
            summary["n_no_surprise"] = pack.get("n_no_surprise")
            summary["n_same_day_entry"] = pack.get("n_same_day_entry")
            summary["n_next_session_entry"] = pack.get("n_next_session_entry")
            shard_summaries.append(summary)
            n_entered_win += int(pack.get("n_entered") or 0)
            n_events_win += int(pack.get("n_events") or 0)
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
                f"[w102/event]   {pid}: status={pack.get('status')} "
                f"n={summary.get('n_equity_points')} entered={pack.get('n_entered')} "
                f"events={pack.get('n_events')} "
                f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                f"total_net={_fmt(summary.get('total_return_net'))}"
            )
        if not stitch_net:
            row = _incomplete_row(
                logic_id=EVENT_SPEC["logic_id"],
                window_id=wid,
                reason=(
                    "no ok daily path stitched for this window "
                    f"(n_events={n_events_win} n_entered={n_entered_win})"
                ),
                extra={
                    "data_path": "local_real_mirrors+local_sqlite_fins_summary",
                    "extra_dataset": "fins_summary",
                    "n_events": n_events_win,
                    "n_entered": n_entered_win,
                    "shard_summaries": shard_summaries,
                },
            )
        else:
            stitched = w100._stitch_net(stitch_net, stitch_dates)
            row = _window_row_from_stitch(
                logic_id=EVENT_SPEC["logic_id"],
                window=w,
                stitched=stitched,
                stitch_net=stitch_net,
                stitch_gross=stitch_gross,
                shard_summaries=shard_summaries,
                extra={
                    "data_path": "local_real_mirrors+local_sqlite_fins_summary",
                    "extra_dataset": "fins_summary",
                    "hold_days": EVENT_SPEC["post_hold_days"],
                    "entry_mode": EVENT_SPEC["entry_mode"],
                    "n_events": n_events_win,
                    "n_entered": n_entered_win,
                    "catalog": True,
                },
            )
        rows.append(row)
        _dump(out_dir / f"event_post_disclosure_hold_{wid}.json", row)

    _dump(out_dir / "event_post_disclosure_hold_daily_dd.json", rows)
    complete = bool(rows) and all(bool(r.get("daily_path_complete")) for r in rows)
    return {
        "table": rows,
        "logic_id": EVENT_SPEC["logic_id"],
        "complete": complete,
    }


def run_rate_daily_dd(
    *,
    out_dir: Path,
    codes: Sequence[str],
    curve_series: Mapping[str, Any] | None,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if not curve_series or not (curve_series.get("spread_by_date") or {}):
        reason = (
            "jsda_tokyo_repo_rates curve not wired: need same-date "
            "overnight/翌日物/T+0 and 3M/T+1 in local jsda_repo_rates. "
            "No ffill / no invent."
        )
        for w in W102_WINDOWS:
            row = _incomplete_row(
                logic_id=RATE_SPEC["logic_id"],
                window_id=str(w["window_id"]),
                reason=reason,
                extra={
                    "data_path": None,
                    "extra_dataset": "jsda_tokyo_repo_rates",
                },
            )
            rows.append(row)
        _dump(out_dir / "rate_curve_shape_xs_daily_dd.json", rows)
        return {"table": rows, "logic_id": RATE_SPEC["logic_id"], "complete": False}

    for w in W102_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w102/rate] window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_gap_win = 0
        regime_win: dict[str, int] = {}
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                log(f"[w102/rate]   {pid}: {loaded.get('status')}")
                continue
            pack = evaluate_rate_curve_xs_daily_mtm(
                loaded["bars"],
                curve_series,
                spec=RATE_SPEC,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_regime_gap"] = pack.get("n_regime_gap")
            summary["regime_counts"] = pack.get("regime_counts")
            shard_summaries.append(summary)
            n_gap_win += int(pack.get("n_regime_gap") or 0)
            for k, v in (pack.get("regime_counts") or {}).items():
                regime_win[str(k)] = regime_win.get(str(k), 0) + int(v)
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
                f"[w102/rate]   {pid}: status={pack.get('status')} "
                f"n={summary.get('n_equity_points')} "
                f"gap={pack.get('n_regime_gap')} "
                f"regimes={pack.get('regime_counts')} "
                f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                f"total_net={_fmt(summary.get('total_return_net'))}"
            )
        if not stitch_net:
            row = _incomplete_row(
                logic_id=RATE_SPEC["logic_id"],
                window_id=wid,
                reason="no ok daily path stitched for this window",
                extra={
                    "data_path": "local_real_mirrors+local_sqlite_jsda_repo_rates",
                    "extra_dataset": "jsda_tokyo_repo_rates",
                    "n_regime_gap": n_gap_win,
                    "regime_counts": regime_win,
                    "shard_summaries": shard_summaries,
                },
            )
        else:
            stitched = w100._stitch_net(stitch_net, stitch_dates)
            row = _window_row_from_stitch(
                logic_id=RATE_SPEC["logic_id"],
                window=w,
                stitched=stitched,
                stitch_net=stitch_net,
                stitch_gross=stitch_gross,
                shard_summaries=shard_summaries,
                extra={
                    "data_path": "local_real_mirrors+local_sqlite_jsda_repo_rates",
                    "extra_dataset": "jsda_tokyo_repo_rates",
                    "hold_days": RATE_SPEC["hold_days"],
                    "momentum_n": RATE_SPEC["momentum_n"],
                    "n_regime_gap": n_gap_win,
                    "regime_counts": regime_win,
                    "catalog": True,
                },
            )
        rows.append(row)
        _dump(out_dir / f"rate_curve_shape_xs_{wid}.json", row)

    _dump(out_dir / "rate_curve_shape_xs_daily_dd.json", rows)
    complete = bool(rows) and all(bool(r.get("daily_path_complete")) for r in rows)
    return {
        "table": rows,
        "logic_id": RATE_SPEC["logic_id"],
        "complete": complete,
    }


def _md_row(r: Mapping[str, Any]) -> str:
    if not r.get("daily_path_complete"):
        return (
            f"| `{r.get('logic_id')}` | {r.get('window')} | — | — | — | — | — | — | "
            f"**incomplete** | `{r.get('incomplete_reason') or 'unmeasured'}` |"
        )
    recov = r.get("recovery_days")
    recov_s = "—" if recov is None else str(recov)
    return (
        f"| `{r.get('logic_id')}` | {r.get('window')} | {r.get('n_days')} | "
        f"{_fmt(r.get('daily_path_DD'))} | {r.get('dd_duration')} | {recov_s} | "
        f"{r.get('recovered')} | {_fmt(r.get('total_ret_net'))} | "
        f"{'yes' if r.get('daily_path_complete') else 'no'} | — |"
    )


def write_proof(
    *,
    proof_path: Path,
    out_dir: Path,
    extra: Mapping[str, Any],
    event_pack: Mapping[str, Any],
    rate_pack: Mapping[str, Any],
    pins: Mapping[str, Any],
    git_sha: str | None,
    codes: Sequence[str],
    max_days: int,
    one_way_cost: float,
) -> str:
    ev_rows = list(event_pack.get("table") or [])
    rt_rows = list(rate_pack.get("table") or [])
    all_rows = ev_rows + rt_rows
    ev_ok = bool(event_pack.get("complete"))
    rt_ok = bool(rate_pack.get("complete"))
    ev_meta = extra.get("event") or {}
    rt_meta = extra.get("rate") or {}
    try:
        rel_logs = str(out_dir.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        rel_logs = str(out_dir)

    lines = [
        "# W102 / w0819e Track B — event / rate extra-dataset daily_path_DD",
        "",
        "**Wave:** W102 / `w0819e` · Track B  ",
        "**Targets:** `event_post_disclosure_hold` · `rate_curve_shape_xs`  ",
        "**Method:** daily MTM after cost — same as W99/W100 "
        "(`scripts/run_w99_sticky_daily_dd.py`, `scripts/run_w100_peer_daily_dd.py`)  ",
        f"**Recipe:** `scripts/run_w102_event_rate_daily_dd.py`  ",
        f"**Logs:** [`{rel_logs}`](../../{rel_logs}/)  ",
        f"**HEAD (pre-commit):** `{git_sha or 'n/a'}`  ",
        "**Implementer:** GLM5.3 only. Grok did **not** implement.",
        "",
        "---",
        "",
        "## Verdict",
        "",
        "| field | value |",
        "|-------|-------|",
        f"| `event_post_disclosure_hold` daily_path_DD | "
        f"{'**complete**' if ev_ok else '**incomplete**'} |",
        f"| `rate_curve_shape_xs` daily_path_DD | "
        f"{'**complete**' if rt_ok else '**incomplete**'} |",
        "| period_net_DD-only pass | **forbidden / not used** |",
        "| promote_as_main | **False** |",
        "| go / go_eligible | **False** |",
        "| Complete measurement = GO/main | **no** |",
        f"| 3-default pins untouched | **{pins.get('pins_untouched')}** |",
        "| hold/mom micro-grid | **not run** |",
        "| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |",
        "",
        "W100/W101 left these two as **unmeasured → incomplete** because the "
        "peer bars-MTM path did not wire extra datasets. This wave **identifies "
        "the exact files**, **wires what is local**, and emits the required "
        "scorecard. Complete measurement is **not** a GO.",
        "",
        "## 1. Extra datasets required for a daily equity curve",
        "",
        "### `event_post_disclosure_hold`",
        "",
        "| need | path |",
        "|------|------|",
        "| bars (close panel) | local `real_mirrors` shards (same W99/W100 windows) |",
        "| disclosure events | `fins_summary` via "
        "`data/structured/ingestion.sqlite` → `jquants_records` |",
        "| PIT fields | `DiscDate` + `DiscTime` (never invented) |",
        "| surprise proxy | `FEPS−EPS` else `EPS−prior_eps` (else skip) |",
        "| loader | `load_fins_events_from_sqlite` |",
        "",
        f"Local status: **{ev_meta.get('status')}** · "
        f"n_events={ev_meta.get('n_events')} · "
        f"n_codes={ev_meta.get('n_codes_with_events')} · "
        f"DiscTime present={ev_meta.get('n_disc_time_present')} · "
        f"surprise fields={ev_meta.get('n_surprise_fields')} · "
        f"span {ev_meta.get('disc_date_min')}→{ev_meta.get('disc_date_max')}.",
        "",
        "### `rate_curve_shape_xs`",
        "",
        "| need | path |",
        "|------|------|",
        "| bars (close panel) | local `real_mirrors` shards (same W99/W100 windows) |",
        "| funding curve | `jsda_tokyo_repo_rates` via "
        "`data/structured/ingestion.sqlite` → `jsda_repo_rates` |",
        "| tenors (observed only) | `overnight/翌日物/T+0` and `3M/T+1` |",
        "| curve | `spread = 3M − overnight` same `as_of_date` (no ffill) |",
        "| loader | `load_repo_rows_all_tenors_from_sqlite` + `build_repo_curve_series` |",
        "",
        f"Local status: **{rt_meta.get('status')}** · "
        f"n_repo_rows={rt_meta.get('n_repo_rows')} · "
        f"n_spread={rt_meta.get('n_obs_spread')} · "
        f"n_gap_either_leg={rt_meta.get('n_gap_either_leg')} · "
        f"span {rt_meta.get('spread_date_min')}→{rt_meta.get('spread_date_max')} · "
        f"ffill={rt_meta.get('ffill_applied')} invent={rt_meta.get('invent_fill')}.",
        "",
        "## 2. Wiring result",
        "",
        "| logic | extra dataset | wired | daily_path_complete | missing |",
        "|-------|---------------|:-----:|:-------------------:|---------|",
        f"| `event_post_disclosure_hold` | `fins_summary` | "
        f"{'yes' if ev_meta.get('status') == 'ok' else 'no'} | "
        f"{'yes' if ev_ok else 'no'} | "
        f"{(extra.get('missing') and [m for m in extra.get('missing') or [] if 'fins' in m]) or '—'} |",
        f"| `rate_curve_shape_xs` | `jsda_tokyo_repo_rates` | "
        f"{'yes' if rt_meta.get('status') == 'ok' else 'no'} | "
        f"{'yes' if rt_ok else 'no'} | "
        f"{(extra.get('missing') and [m for m in extra.get('missing') or [] if 'repo' in m or 'curve' in m]) or '—'} |",
        "",
        "## 3. Daily path table (after cost)",
        "",
        "Required columns: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**.",
        "",
        "| logic | window | n_days | daily_path_DD | dd_duration | recovery | recovered | total_ret_net | complete | missing |",
        "|-------|--------|-------:|--------------:|------------:|---------:|:---------:|--------------:|:--------:|---------|",
    ]
    for r in all_rows:
        lines.append(_md_row(r))

    # Per-shard
    lines += [
        "",
        "### Per-shard",
        "",
        "| logic | window | period_id | n_days | daily_path_DD | total_ret_net | extra |",
        "|-------|--------|-----------|-------:|--------------:|--------------:|-------|",
    ]
    for r in all_rows:
        for s in r.get("shard_summaries") or []:
            extra_s = ""
            if r.get("logic_id") == EVENT_SPEC["logic_id"]:
                extra_s = (
                    f"entered={s.get('n_entered')} events={s.get('n_events')}"
                )
            else:
                extra_s = (
                    f"gap={s.get('n_regime_gap')} regimes={s.get('regime_counts')}"
                )
            lines.append(
                f"| `{r.get('logic_id')}` | {r.get('window')} | {s.get('period_id')} | "
                f"{s.get('n_equity_points')} | {_fmt(s.get('daily_path_DD'))} | "
                f"{_fmt(s.get('total_return_net'))} | {extra_s} |"
            )

    ev_worst = None
    rt_worst = None
    for r in ev_rows:
        dd = r.get("daily_path_DD")
        if isinstance(dd, (int, float)) and math.isfinite(float(dd)):
            if ev_worst is None or float(dd) < ev_worst:
                ev_worst = float(dd)
    for r in rt_rows:
        dd = r.get("daily_path_DD")
        if isinstance(dd, (int, float)) and math.isfinite(float(dd)):
            if rt_worst is None or float(dd) < rt_worst:
                rt_worst = float(dd)

    lines += [
        "",
        "## Headline (research-only · not GO)",
        "",
    ]
    if ev_ok:
        lines.append(
            f"- `event_post_disclosure_hold`: daily_path_DD **complete** on all "
            f"three windows. Worst path DD **{_fmt(ev_worst)}**. Sparse event "
            "book (hold=5 PIT post-disclosure). **Research-only. Not main. Not GO.**"
        )
    else:
        lines.append(
            "- `event_post_disclosure_hold`: daily_path_DD **incomplete**. "
            "See missing-data column — not approximated into complete."
        )
    if rt_ok:
        lines.append(
            f"- `rate_curve_shape_xs`: daily_path_DD **complete** on all three "
            f"windows. Worst path DD **{_fmt(rt_worst)}**. Curve = JSDA 3M−ON "
            "(funding term-structure proxy, **not** JGB/OIS). "
            "**Research-only. Not main. Not GO.**"
        )
    else:
        lines.append(
            "- `rate_curve_shape_xs`: daily_path_DD **incomplete**. "
            "See missing-data column — not approximated into complete."
        )
    lines += [
        "",
        "> **Warning:** period-net DD = 0 when all period nets are positive is an",
        "> **aggregation artifact**. It does **not** mean the strategy is riskless.",
        "> Use **daily_path_DD** (duration / recovery / total_ret_net).",
        ">",
        "> **Complete measurement ≠ GO / main.** These rows remain research-only.",
        "",
        "## Method",
        "",
        "1. Identify extra datasets: `fins_summary` (events) and "
        "`jsda_tokyo_repo_rates` (curve). Load from local `ingestion.sqlite`.",
        "2. Load local `real_mirrors` bars for W98/W99 honest shards "
        "(2018/2020/2022/2024 absent — omitted, no synthetic fill).",
        "3. **Event book:** PIT entry (`same_day_close_if_pre_close`); "
        "explicit hold window of `post_hold_days=5`; last-event-wins if overlap.",
        "4. **Rate book:** CS mom ranks × curve-shape transform "
        "(steep keep / inverted reverse / flat no-trade) + sticky hold=10 mom=5.",
        "5. Mark the held book to market **daily** (equal-weight active names).",
        "6. Subtract Python amortized daily cost drag while active "
        f"(one_way={one_way_cost}).",
        "7. Equity-curve peak-to-trough → max DD, duration, recovery, after-cost total return.",
        "8. `evaluate_daily_path_dd_gate` must **complete**; period-net-only is **forbidden**.",
        "",
        f"Codes: first {len(codes)} of `DEFAULT_EVAL_CODES`; "
        f"max_days/shard={max_days}. Catalog base params — **not** a retune.",
        "",
        "## Freezes held",
        "",
        "- promote_as_main = **false** · go = **false**",
        "- no hold/mom micro-grid · no 3-default pin retune",
        "- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED",
        "- period_net_DD-only **cannot pass**",
        "- no invent DiscTime · no repo ffill",
        "",
        "## Non-claims",
        "",
        "- No READY / Mass / GO / live / pin retune / hold-mom grid / full catalog grid.",
        "- Neither logic promoted as main. Sticky not re-promoted.",
        "- Local mirrors + local sqlite ≠ CF SoT.",
        "- Period-net DD=0 **must not** be read as riskless.",
        "- Complete daily_path_DD is **not** a production candidate / GO.",
        "",
        "GLM implementer only. Grok did not implement.",
        "",
    ]
    body = "\n".join(lines)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(body, encoding="utf-8")
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--proof", type=str, default=str(PROOF_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument(
        "--sqlite",
        type=str,
        default=str(ROOT / "data" / "structured" / "ingestion.sqlite"),
    )
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w102_event_rate_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w102] pins_untouched={pins['pins_untouched']}")
    log(
        "[w102] promote_as_main=false go=false hold_mom_grid=false "
        "period_net_dd_only=forbidden complete≠GO "
        "GLM implementer only. Grok did not implement."
    )

    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(args.max_codes)]
    sqlite_path = Path(args.sqlite)
    extra = inspect_extra_datasets(codes=codes, sqlite_path=sqlite_path, log=log)
    extra_dump = {
        k: v
        for k, v in extra.items()
        if k not in {"fins_events", "curve_series"}
    }
    _dump(out_dir / "extra_dataset_wiring.json", extra_dump)

    event_pack = run_event_daily_dd(
        out_dir=out_dir,
        codes=codes,
        events_by_code=extra.get("fins_events") or {},
        max_days=int(args.max_days),
        one_way_cost=float(args.one_way_cost),
        log=log,
    )
    rate_pack = run_rate_daily_dd(
        out_dir=out_dir,
        codes=codes,
        curve_series=extra.get("curve_series"),
        max_days=int(args.max_days),
        one_way_cost=float(args.one_way_cost),
        log=log,
    )

    compact = []
    for row in list(event_pack.get("table") or []) + list(rate_pack.get("table") or []):
        compact.append(
            {
                "logic_id": row.get("logic_id"),
                "window": row.get("window"),
                "n_days": row.get("n_days"),
                "daily_path_DD": row.get("daily_path_DD"),
                "dd_duration": row.get("dd_duration"),
                "recovery_days": row.get("recovery_days"),
                "recovered": row.get("recovered"),
                "total_ret_net": row.get("total_ret_net"),
                "daily_path_complete": row.get("daily_path_complete"),
                "incomplete_reason": row.get("incomplete_reason"),
                "promote_as_main": False,
                "go": False,
                "stance": "RESEARCH_ONLY",
                "data_path": row.get("data_path"),
                "extra_dataset": row.get("extra_dataset"),
            }
        )
    _dump(out_dir / "event_rate_daily_dd_table.json", compact)

    pins_after = _assert_frozen_pins_untouched()
    pins_after["note"] = "W102 after event/rate daily DD; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    sha = _git_sha()
    write_proof(
        proof_path=Path(args.proof),
        out_dir=out_dir,
        extra=extra,
        event_pack=event_pack,
        rate_pack=rate_pack,
        pins=pins_after,
        git_sha=sha,
        codes=codes,
        max_days=int(args.max_days),
        one_way_cost=float(args.one_way_cost),
    )

    summary = {
        "wave": "W102 / w0819e",
        "track": "B_event_rate_daily_path_dd",
        "event_post_disclosure_hold": {
            "daily_path_complete": bool(event_pack.get("complete")),
            "table": event_pack.get("table"),
        },
        "rate_curve_shape_xs": {
            "daily_path_complete": bool(rate_pack.get("complete")),
            "table": rate_pack.get("table"),
        },
        "extra_dataset_wiring": extra_dump,
        "pins_untouched": pins_after.get("pins_untouched"),
        "promote_as_main": False,
        "go": False,
        "period_net_dd_only_pass_forbidden": True,
        "complete_measurement_is_not_go": True,
        "hold_mom_microgrid": False,
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "head_pre_commit": sha,
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w102_event_rate_daily_dd_summary.json", summary)
    log(
        f"[w102] done wall={summary['wall_sec']}s "
        f"event_complete={event_pack.get('complete')} "
        f"rate_complete={rate_pack.get('complete')} "
        f"pins={pins_after.get('pins_untouched')}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
