#!/usr/bin/env python3
"""W105 / w0820b Track B — NEW unique_logic hyps with daily_path_DD required.

Headline is **new unique_logic** (new magnitude filter / new DiscTime timing /
event×own-mom confirm / event×name-margin crowding). Weak-template mapping
OFF. Catalog remaps of sticky / event_post_disclosure_hold /
vol_risk_adjusted_mom are **not** headlined as new strategies.

Do **not** build sticky-approx always-on gates (W104 disclosure_cluster_mom_gate
was ~90% on). These four are event-book filters / combos — occupancy is a
subset of disclosure days, not a CS-mom book that tracks sticky.

Modest N=4 (not a count race). Failure constraints ON. 3-default pins
untouched. Survivors research-only: promote_as_main=false · go=false.

If extra datasets cannot be loaded, the row stays **incomplete** — never
approximated into complete.

Examples
--------
    uv run python scripts/run_w105_new_hyps_daily_dd.py \\
        --out-dir .glm-logs/w0820b_w105_otc9_family_hyps/
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import date, datetime, timezone
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820b_w105_otc9_family_hyps"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0820b_w105_hyps_new_logic_20260820.md"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_event_rate_daily_dd as w102  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

WAVE = "W105 / w0820b"
W105_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT

# ---------------------------------------------------------------------------
# 4 NEW unique_logic proposals (not catalog remaps; not hold/mom grids;
# not sticky-approx always-on CS-mom gates)
# ---------------------------------------------------------------------------
# P1 new SIGNAL FILTER — |surprise| vs PIT trailing median (not own-sign PEAD)
# P2 new ENTRY TIMING — after-close DiscTime only (not event_post both-clock)
# P3 new COMBO — event surprise × own pre-entry mom agree
# P4 new DATASET COMBO — event × name-level margin crowding skip

NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "large_surprise_event_hold",
        "family_id": "large_surprise_filter",
        "kind": "large_surprise_event_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW SIGNAL FILTER: take PIT surprise-sign hold only when "
            "|surprise| ≥ PIT trailing median of |surprise| among prior "
            "universe events (disc_date strictly before). Not event_post "
            "(all signed surprises) and not surprise_xs_rank (CS rank)."
        ),
        "thesis": (
            "Small earnings surprises are noise. Hold the surprise sign only "
            "when |surprise| is at/above its PIT trailing median across prior "
            "universe disclosures — large-surprise PEAD, not all-event PEAD."
        ),
        "signal_definition": (
            "earnings surprise proxy; enter iff abs(surprise) >= PIT median "
            "of abs(surprise) on events with disc_date < this disc_date "
            "(min_hist=20); median unformed → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip entire "
            "event when |surprise| is below the PIT median or median unformed"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
            "mode": "large_surprise_event_hold",
            "gate": "abs_surprise_ge_pit_trailing_median",
        },
    },
    {
        "logic_id": "afterclose_only_event_hold",
        "family_id": "afterclose_event_timing",
        "kind": "afterclose_only_event_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "why_unique": (
            "NEW ENTRY TIMING: surprise hold only when DiscTime is at/after "
            "that day's TSE session close. Missing DiscTime → skip (no invent). "
            "Pre-close disclosures skipped. Not event_post_disclosure_hold "
            "(which takes both pre-close same-day and after-close next-day)."
        ),
        "thesis": (
            "After-hours disclosures avoid same-session leakage. Take the PIT "
            "surprise-sign hold only for DiscTime ≥ session close; skip "
            "intraday prints and time-unknown rows."
        ),
        "signal_definition": (
            "surprise-sign AND parseable DiscTime >= session_close_hhmmss"
            "(disc_date); missing/unparseable DiscTime → skip (no invent)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; flatten/skip "
            "when DiscTime is pre-close or unknown"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "mode": "afterclose_only_event_hold",
            "gate": "disctime_ge_session_close",
        },
    },
    {
        "logic_id": "event_pre_mom_agree_hold",
        "family_id": "event_mom_agree_combo",
        "kind": "event_pre_mom_agree_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW COMBO: event surprise hold only when own-name N-day momentum "
            "ending at the last close strictly before entry agrees in sign "
            "with surprise. Not a sticky CS-mom book and not own-sign PEAD "
            "without confirmation."
        ),
        "thesis": (
            "PEAD is more informative when the name was already drifting in "
            "the surprise direction. Confirm surprise-sign hold with own-name "
            "pre-entry momentum; skip disagreement and missing history."
        ),
        "signal_definition": (
            "surprise-sign AND sign(close[entry-1]/close[entry-1-n]-1) == "
            "surprise-sign; n=5; insufficient bars or zero mom → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip when "
            "pre-entry mom disagrees, is flat, or history is short"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "momentum_n": 5,
            "mode": "event_pre_mom_agree_hold",
            "gate": "own_pre_entry_mom_sign_agrees",
        },
    },
    {
        "logic_id": "event_margin_crowding_skip",
        "family_id": "event_margin_crowd_combo",
        "kind": "event_margin_crowding_skip",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW DATASET COMBO: skip post-disclosure surprise entry when the "
            "name's last PIT margin-interest print (strictly before entry, "
            "max 14 calendar days stale) is at/above that name's PIT trailing "
            "median. Not flow_margin_pressure (not a continuous flow book) "
            "and not a sticky-approx gate."
        ),
        "thesis": (
            "PEAD is weaker when the name is already crowded in margin. Skip "
            "the event when last-known name-level LongVol+ShrtVol is at/above "
            "its PIT trailing median; missing/stale margin → skip (no ffill)."
        ),
        "signal_definition": (
            "surprise-sign; enter only if last margin print with date < "
            "entry_date and age<=14d is strictly below PIT trailing median "
            "of that name's prior prints (min_hist=20); missing/stale → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip entire "
            "event when margin is crowded, unformed, missing, or stale"
        ),
        "datasets": [
            "fins_summary",
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
            "stale_calendar_days": 14,
            "mode": "event_margin_crowding_skip",
            "gate": "name_margin_lt_pit_trailing_median",
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
    pack["note"] = "W105 new unique_logic hyps must not mutate 3-default pins"
    return pack


def pit_median_from_pairs(
    pairs: Sequence[tuple[str, float]],
    query_dates: Sequence[str],
    *,
    min_hist: int,
) -> dict[str, float | None]:
    """PIT trailing median over a multiset of (date, value); date < query only."""
    items: list[tuple[str, float]] = []
    for d, v in pairs:
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


def _ymd(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _event_key(ev: Mapping[str, Any]) -> str:
    return f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"


def _abs_surprise_pairs(
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[tuple[str, float]]:
    from features.class_signals import earnings_surprise_proxy

    pairs: list[tuple[str, float]] = []
    for evs in (events_by_code or {}).values():
        for ev in evs:
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            surprise, _meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            if surprise is None:
                continue
            try:
                av = abs(float(surprise))
            except (TypeError, ValueError):
                continue
            if math.isfinite(av):
                pairs.append((disc, av))
    return pairs


def _attach_disc_time(
    collected: Mapping[str, Any],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Join DiscTime onto collected entries (never invent)."""
    by: dict[tuple[str, str], Any] = {}
    for code, evs in (events_by_code or {}).items():
        for ev in evs:
            disc = str(ev.get("disc_date") or "")[:10]
            if disc:
                by[(str(code), disc)] = ev.get("disc_time")
    out = dict(collected)
    entries = []
    for ev in list(collected.get("entries") or []):
        rec = dict(ev)
        rec["disc_time"] = by.get((str(ev["code"]), str(ev["disc_date"])))
        entries.append(rec)
    out["entries"] = entries
    per_code: dict[str, Any] = {}
    for code, pack in (collected.get("per_code") or {}).items():
        recs = []
        for ev in list(pack.get("entries") or []):
            rec = dict(ev)
            rec["disc_time"] = by.get((str(code), str(ev["disc_date"])))
            recs.append(rec)
        per_code[code] = {**dict(pack), "entries": recs}
    out["per_code"] = per_code
    return out


def _pre_entry_mom(
    *,
    dlist: Sequence[str],
    close_by_code: Mapping[str, float],
    entry_idx: int,
    momentum_n: int,
) -> float | None:
    """Own-name mom ending at last close strictly before entry. No look-ahead."""
    n = int(momentum_n)
    j = int(entry_idx) - 1
    i = j - n
    if i < 0 or j < 0 or j >= len(dlist):
        return None
    c0 = close_by_code.get(dlist[i])
    c1 = close_by_code.get(dlist[j])
    if c0 is None or c1 is None:
        return None
    try:
        f0 = float(c0)
        f1 = float(c1)
    except (TypeError, ValueError):
        return None
    if f0 == 0.0 or not math.isfinite(f0) or not math.isfinite(f1):
        return None
    return (f1 / f0) - 1.0


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


def _collect(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    period_start: str | None,
    period_end: str | None,
) -> dict[str, Any]:
    collected = w104._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    return _attach_disc_time(collected, events_by_code)


def _base_extra(spec: Mapping[str, Any], collected: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "n_events": collected["n_events"],
        "n_eligible_pre_gate": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }


def _empty_extra_or_events(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    extra: Mapping[str, Any],
    empty_dataset: bool,
    empty_reason: str,
) -> dict[str, Any] | None:
    dates = list(collected["calendar"])
    if empty_dataset:
        return {
            "status": "missing_extra_dataset",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": empty_reason,
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


def _finish_event_book(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    accept: Mapping[str, bool],
    extra: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    dates = list(collected["calendar"])
    held = w104._held_from_event_entries(collected, accept=accept)
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
    return pack


def evaluate_large_surprise_event_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only when |surprise| ≥ PIT trailing median."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "min_hist": min_hist,
        "gate": "abs_surprise_ge_pit_trailing_median",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
    }
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=False,
        empty_reason="",
    )
    if blocked:
        return blocked

    pairs = _abs_surprise_pairs(events_by_code)
    query = sorted({e["disc_date"] for e in collected["entries"]})
    med_by = pit_median_from_pairs(pairs, query, min_hist=min_hist)
    accept: dict[str, bool] = {}
    n_skip_unformed = 0
    n_skip_small = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        med = med_by.get(ev["disc_date"])
        if med is None:
            accept[key] = False
            n_skip_unformed += 1
            continue
        if abs(float(ev["surprise"])) < float(med):
            accept[key] = False
            n_skip_small += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_small_surprise": n_skip_small,
            "n_abs_surprise_history": len(pairs),
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


def evaluate_afterclose_only_event_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only for DiscTime ≥ session close (no invent)."""
    from features.class_signals import parse_disc_time_hhmmss, session_close_hhmmss

    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "gate": "disctime_ge_session_close",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
    }
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=False,
        empty_reason="",
    )
    if blocked:
        return blocked

    accept: dict[str, bool] = {}
    n_skip_missing = 0
    n_skip_preclose = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        dt = parse_disc_time_hhmmss(ev.get("disc_time"))
        if dt is None:
            accept[key] = False
            n_skip_missing += 1
            continue
        close_clock = session_close_hhmmss(str(ev["disc_date"]))
        if dt < close_clock:
            accept[key] = False
            n_skip_preclose += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_missing_disctime": n_skip_missing,
            "n_skip_preclose": n_skip_preclose,
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


def evaluate_event_pre_mom_agree_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only when own pre-entry mom sign agrees."""
    from features.class_signals import sign_from_numeric

    params = dict(spec.get("params") or {})
    mom_n = int(spec.get("momentum_n") or params.get("momentum_n") or 5)
    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "momentum_n": mom_n,
        "gate": "own_pre_entry_mom_sign_agrees",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
    }
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=False,
        empty_reason="",
    )
    if blocked:
        return blocked

    accept: dict[str, bool] = {}
    n_skip_hist = 0
    n_skip_disagree = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        code = ev["code"]
        pack = (collected.get("per_code") or {}).get(code) or {}
        dlist = list(pack.get("dlist") or [])
        mom = _pre_entry_mom(
            dlist=dlist,
            close_by_code=collected["close_by"].get(code) or {},
            entry_idx=int(ev["entry_idx"]),
            momentum_n=mom_n,
        )
        mom_sign = sign_from_numeric(mom)
        if mom is None or mom_sign is None or mom_sign == 0.0:
            accept[key] = False
            n_skip_hist += 1
            continue
        if float(mom_sign) != float(ev["sign"]):
            accept[key] = False
            n_skip_disagree += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_mom_history": n_skip_hist,
            "n_skip_mom_disagree": n_skip_disagree,
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


def evaluate_event_margin_crowding_skip_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold skipped when name-level margin is PIT-crowded.

    Last margin print must have date < entry_date and age ≤ stale_calendar_days.
    No ffill across longer gaps. Missing series → incomplete (not approximated).
    """
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    stale_days = int(
        spec.get("stale_calendar_days") or params.get("stale_calendar_days") or 14
    )
    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "min_hist": min_hist,
        "stale_calendar_days": stale_days,
        "gate": "name_margin_lt_pit_trailing_median",
        "extra_dataset": "fins_summary+markets_margin_interest",
        "data_path": "local_real_mirrors+local_sqlite_fins+margin",
    }
    margin_ok = bool(margin_by_code) and any(
        bool(v) for v in (margin_by_code or {}).values()
    )
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=not margin_ok,
        empty_reason=(
            "markets_margin_interest series empty — cannot apply name-level "
            "margin crowding PIT gate. Not approximated."
        ),
    )
    if blocked:
        return blocked

    accept: dict[str, bool] = {}
    n_skip_missing = 0
    n_skip_stale = 0
    n_skip_unformed = 0
    n_skip_crowded = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        series = dict((margin_by_code or {}).get(ev["code"]) or {})
        last = _last_print_before(series, ev["entry_date"])
        if last is None:
            accept[key] = False
            n_skip_missing += 1
            continue
        last_d, last_v = last
        age = (_ymd(ev["entry_date"]) - _ymd(last_d)).days
        if age > int(stale_days):
            accept[key] = False
            n_skip_stale += 1
            continue
        med_by = w104.pit_median_on_dates(
            series, [ev["entry_date"]], min_hist=min_hist
        )
        med = med_by.get(ev["entry_date"])
        if med is None:
            accept[key] = False
            n_skip_unformed += 1
            continue
        if float(last_v) >= float(med):
            accept[key] = False
            n_skip_crowded += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_missing_margin": n_skip_missing,
            "n_skip_stale_margin": n_skip_stale,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_margin_crowded": n_skip_crowded,
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
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
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    one_way_cost: float,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    bars = loaded["bars"]
    p0 = loaded.get("period_start")
    p1 = loaded.get("period_end")
    if lid == "large_surprise_event_hold":
        return evaluate_large_surprise_event_hold_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "afterclose_only_event_hold":
        return evaluate_afterclose_only_event_hold_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "event_pre_mom_agree_hold":
        return evaluate_event_pre_mom_agree_hold_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "event_margin_crowding_skip":
        return evaluate_event_margin_crowding_skip_daily_mtm(
            bars,
            events_by_code,
            margin_by_code,
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
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in W105_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w105/{lid}] window {wid}")
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
                log(f"[w105/{lid}]   {pid}: {loaded.get('status')}")
                continue
            pack = _eval_one_shard(
                spec=spec,
                loaded=loaded,
                events_by_code=events_by_code,
                margin_by_code=margin_by_code,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_events"] = pack.get("n_events")
            summary["n_entered"] = pack.get("n_entered")
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
                f"[w105/{lid}]   {pid}: status={pack.get('status')} "
                f"n={summary.get('n_equity_points')} "
                f"entered={pack.get('n_entered')} events={pack.get('n_events')} "
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
                    "new_unique_logic": True,
                    "catalog": False,
                    "catalog_map": None,
                    "why_unique": spec.get("why_unique"),
                    "headline": spec.get("headline"),
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
        f"[w105/B] propose n={len(proposals)} seed={seed} "
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
        "do_not_repeat_w104_ids": list(W104_UNIQUE_LOGIC_IDS),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w105/B] pack proposed={n_proposed} accepted={n_accepted} "
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
    extra = w104.inspect_unique_logic_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    from research.class_hyp_eval import load_margin_from_sqlite

    raw = load_margin_from_sqlite(
        sqlite_path, codes=list(codes), start="2016-01-01", end="2026-12-31"
    )
    margin_by_code: dict[str, dict[str, float]] = {}
    for code, pairs in (raw or {}).items():
        dmap: dict[str, float] = {}
        for d, v in pairs:
            ds = str(d)[:10]
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if ds and math.isfinite(fv):
                dmap[ds] = fv
        if dmap:
            margin_by_code[str(code)] = dmap
    n_obs = sum(len(v) for v in margin_by_code.values())
    first_d = None
    last_d = None
    for dmap in margin_by_code.values():
        if not dmap:
            continue
        lo = min(dmap)
        hi = max(dmap)
        if first_d is None or lo < first_d:
            first_d = lo
        if last_d is None or hi > last_d:
            last_d = hi
    extra["margin_by_code"] = margin_by_code
    extra["margin"] = {
        "required_dataset": "markets_margin_interest",
        "loader": "load_margin_from_sqlite",
        "status": "ok" if n_obs else "empty",
        "n_codes": len(margin_by_code),
        "n_obs": n_obs,
        "date_min": first_d,
        "date_max": last_d,
        "no_ffill": True,
        "no_invent": True,
        "stale_calendar_days": 14,
    }
    log(
        f"[w105] margin n_codes={len(margin_by_code)} n_obs={n_obs} "
        f"{first_d}..{last_d}"
    )
    return extra


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--seed", type=int, default=8908205)
    p.add_argument("--sqlite", type=str, default=str(SQLITE_DEFAULT))
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-daily", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w105_new_hyps_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w105] pins_untouched={pins['pins_untouched']}")
    log(
        "[w105] promote_as_main=false go=false hold_mom_grid=false "
        "dispersion_thresh_grid=false weak_template_mapping=OFF "
        "period_net_dd_only=forbidden complete≠GO "
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
        }
    }
    _dump(out_dir / "extra_dataset_wiring.json", extra_dump)

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_hyp_pack(out_dir=out_dir, seed=int(args.seed), log=log)
    else:
        log("[w105/B] propose skipped")

    daily_packs: dict[str, Any] = {}
    if not args.skip_daily:
        events = extra.get("fins_events") or {}
        margin = extra.get("margin_by_code") or {}
        for spec in NEW_UNIQUE_LOGIC:
            lid = str(spec["logic_id"])
            daily_packs[lid] = run_unique_logic_daily_dd(
                out_dir=out_dir,
                spec=spec,
                codes=codes,
                events_by_code=events,
                margin_by_code=margin,
                max_days=int(args.max_days),
                one_way_cost=float(args.one_way_cost),
                log=log,
            )
    else:
        log("[w105/B] daily_path_DD skipped")

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
    pins_after["note"] = "W105 after unique_logic hyps; 3-default pins must match"
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
        "sticky_approx_always_on_gate": False,
        "do_not_headline": list(LOGIC_CATALOG_HEADLINE_BAN),
        "do_not_repeat_w104": list(W104_UNIQUE_LOGIC_IDS),
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
    _dump(out_dir / "w105_b_summary.json", summary)
    log(
        f"[w105] done wall={summary['wall_sec']}s "
        f"impl={n_impl} daily_complete_logics={n_complete} "
        f"pins={pins_after.get('pins_untouched')} "
        f"worst={summary['worst_daily_path_DD_by_logic']}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
