#!/usr/bin/env python3
"""W107 / w0820d Track C — funding/surprise adaptive side + fixed L/S table.

Do **not** conclude “sign flipped so kill”. Keep the W106 fixed L/S side
table and add a trail-K PIT adaptive overlay:

  * at each easy-funding event, last K completed-hold mean orig vs flip
    (hold_end < entry_date); pick the better side
  * on each surprise ranked day, last K completed ranked-day orig nets
    (date < d); orig if mean>=0 else flip

Occupancy must match the parent (not collapse). No threshold / hold grid.
promote_as_main=false · go=false.

Examples
--------
    uv run python scripts/run_w107_funding_surprise_adaptive.py \\
        --out-dir .glm-logs/w0820d_w107_otc11_adaptive/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
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
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402
import run_w106_funding_surprise_ls as w106  # noqa: E402

WAVE = "W107 / w0820d"
W107_WINDOWS = w99.W99_WINDOWS
TRAIL_K = 10
TRAIL_MIN = 5

ADAPTIVE_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_adaptive_side",
        "family_id": "event_funding_combo",
        "kind": "event_funding_adaptive_side",
        "parent_logic_id": "event_funding_stress_skip",
        "variant_kind": "trail_k_adaptive_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "ADAPTIVE SIDE of event_funding_stress_skip: same easy-funding "
            "occupancy; at each PIT entry pick orig vs flip from last K "
            "completed holds with hold_end < entry_date. Not a kill of the "
            "fixed L/S table."
        ),
        "thesis": (
            "Window sign-flip of easy-funding surprise is a side table. "
            "A PIT trail-K overlay can pick the recently-working side without "
            "discarding either parent."
        ),
        "signal_definition": (
            "same PIT overnight-lt-median gate as skip; sign = orig if mean "
            f"orig hold of last {TRAIL_K} completed (min {TRAIL_MIN}) >= mean "
            "flip, else flip; insufficient history → orig (no invent)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; enter only when "
            "funding is easy; side chosen from completed holds only"
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
            "trail_k": TRAIL_K,
            "trail_min": TRAIL_MIN,
            "mode": "funding_easy_adaptive_side",
            "gate": "overnight_lt_pit_trailing_median",
            "side": "trail_k_orig_vs_flip",
        },
    },
    {
        "logic_id": "surprise_xs_rank_adaptive",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_adaptive",
        "parent_logic_id": "surprise_xs_rank_hold",
        "variant_kind": "trail_k_adaptive_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "ADAPTIVE SIDE of surprise_xs_rank_hold: same ranked occupancy; "
            "each day pick orig vs flip from last K completed ranked-day orig "
            "nets with date < d. Not a kill of the parent or the flip."
        ),
        "thesis": (
            "Relative-surprise rank is window-unstable in sign. A PIT trail-K "
            "overlay sits beside orig and flip rather than killing either."
        ),
        "signal_definition": (
            "same CS surprise rank occupancy as parent; tilt = +1 if mean of "
            f"last {TRAIL_K} completed orig daily nets (min {TRAIL_MIN}) >= 0 "
            "else −1; insufficient history → orig"
        ),
        "position_rule": (
            "balanced L/S on (possibly flipped) surprise ranks for currently-"
            "in-window names; occupancy held vs parent"
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
            "trail_k": TRAIL_K,
            "trail_min": TRAIL_MIN,
            "mode": "surprise_xs_rank_adaptive",
        },
    },
)

PARENT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_stress_skip",
        "family_id": "event_funding_combo",
        "kind": "event_funding_stress_skip",
        "variant_kind": "parent_orig",
        "parent_logic_id": None,
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
        },
        "why_unique": "W104 parent orig (fixed table, not a kill).",
    },
    {
        "logic_id": "surprise_xs_rank_hold",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_hold",
        "variant_kind": "parent_orig",
        "parent_logic_id": None,
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "long_frac": 0.3,
            "short_frac": 0.3,
        },
        "why_unique": "W104 parent orig (fixed table, not a kill).",
    },
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
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _assert_frozen_pins_untouched() -> dict[str, Any]:
    pack = w99._assert_frozen_pins_untouched()
    pack["note"] = "W107 adaptive side must not mutate 3-default pins"
    return pack


def proposals_for_factory() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in ADAPTIVE_VARIANTS:
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


def _event_hold_end_and_raw(
    ev: Mapping[str, Any],
    collected: Mapping[str, Any],
) -> tuple[str, float] | None:
    code = str(ev["code"])
    pack = (collected.get("per_code") or {}).get(code) or {}
    dlist = list(pack.get("dlist") or [])
    idx = int(ev["entry_idx"])
    h = int(collected["hold_days"])
    if idx < 0 or idx >= len(dlist):
        return None
    end = min(idx + h, len(dlist)) - 1
    if end <= idx:
        return None
    close_by = (collected.get("close_by") or {}).get(code) or {}
    c0 = close_by.get(dlist[idx])
    c1 = close_by.get(dlist[end])
    if c0 is None or c1 is None:
        return None
    try:
        f0 = float(c0)
        f1 = float(c1)
    except (TypeError, ValueError):
        return None
    if f0 == 0.0:
        return None
    return str(dlist[end]), (f1 / f0) - 1.0


def evaluate_event_funding_adaptive_side_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Easy-funding occupancy; PIT trail-K orig vs flip side."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    trail_k = int(spec.get("trail_k") or params.get("trail_k") or TRAIL_K)
    trail_min = int(spec.get("trail_min") or params.get("trail_min") or TRAIL_MIN)
    collected = w104._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **w106._funding_base_extra(spec, collected, min_hist=min_hist),
        "gate": "overnight_lt_pit_trailing_median",
        "side": "trail_k_orig_vs_flip",
        "trail_k": trail_k,
        "trail_min": trail_min,
        "occupancy_vs_parent": "same_as_skip",
    }
    blocked = w106._blocked_overnight_or_events(
        spec=spec,
        collected=collected,
        overnight_by_date=overnight_by_date,
        extra=extra,
    )
    if blocked:
        return blocked
    gate = w106.classify_funding_entries(
        collected, overnight_by_date, min_hist=min_hist
    )
    easy_keys = dict(gate["easy"])
    cost = 2.0 * float(one_way_cost)
    ordered = sorted(
        [e for e in collected["entries"] if easy_keys.get(w106._event_key(e))],
        key=lambda e: (e["entry_date"], e["code"], e["disc_date"]),
    )
    history: list[dict[str, Any]] = []
    sign_mult: dict[str, float] = {}
    n_orig = 0
    n_flip = 0
    n_default_orig = 0
    for ev in ordered:
        key = w106._event_key(ev)
        entry_d = str(ev["entry_date"])
        completed = [h for h in history if str(h["hold_end"]) < entry_d]
        lastk = completed[-trail_k:]
        if len(lastk) < trail_min:
            mult = 1.0
            n_default_orig += 1
        else:
            m_orig = sum(float(h["orig"]) for h in lastk) / float(len(lastk))
            m_flip = sum(float(h["flip"]) for h in lastk) / float(len(lastk))
            if m_orig >= m_flip:
                mult = 1.0
                n_orig += 1
            else:
                mult = -1.0
                n_flip += 1
        sign_mult[key] = mult
        hr = _event_hold_end_and_raw(ev, collected)
        if hr is None:
            continue
        hold_end, raw = hr
        sgn = float(ev["sign"])
        history.append(
            {
                "hold_end": hold_end,
                "orig": sgn * raw - cost,
                "flip": -sgn * raw - cost,
            }
        )
    extra.update(
        {
            "n_entered": int(gate["n_easy"]),
            "n_easy_entered": int(gate["n_easy"]),
            "n_stress_entered": 0,
            "n_skip_missing_overnight": int(gate["n_skip_missing"]),
            "n_skip_median_unformed": int(gate["n_skip_no_median"]),
            "n_skip_funding_stress": int(gate["n_stress"]),
            "n_adaptive_orig": n_orig + n_default_orig,
            "n_adaptive_flip": n_flip,
            "n_adaptive_default_orig": n_default_orig,
        }
    )
    return w106._finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=easy_keys,
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=sign_mult,
    )


def evaluate_surprise_xs_rank_adaptive_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Same occupancy as surprise_xs_rank_hold; PIT trail-K orig vs flip."""
    params = dict(spec.get("params") or {})
    trail_k = int(spec.get("trail_k") or params.get("trail_k") or TRAIL_K)
    trail_min = int(spec.get("trail_min") or params.get("trail_min") or TRAIL_MIN)
    orig_spec = dict(spec)
    orig_params = dict(params)
    orig_params["sign_flip"] = False
    orig_spec["params"] = orig_params
    orig_spec["sign_flip"] = False
    orig = w104.evaluate_surprise_xs_rank_hold_daily_mtm(
        bars_by_code,
        events_by_code,
        spec=orig_spec,
        one_way_cost=one_way_cost,
        period_start=period_start,
        period_end=period_end,
    )
    orig["logic_id"] = spec["logic_id"]
    orig["kind"] = spec.get("kind")
    orig["variant_kind"] = spec.get("variant_kind")
    orig["parent_logic_id"] = spec.get("parent_logic_id")
    orig["occupancy_vs_parent"] = "same_as_rank_hold"
    orig["sign_flip_is_not_a_kill"] = True
    orig["promote_as_main"] = False
    orig["go"] = False
    orig["adaptive_side"] = True
    orig["trail_k"] = trail_k
    orig["trail_min"] = trail_min
    if orig.get("status") != "ok":
        return orig

    dates = list(orig.get("dates") or [])
    net = list(orig.get("net_daily") or [])
    gross = list(orig.get("gross_daily") or [])
    if not dates or not net or len(gross) != len(net):
        orig["status"] = "adaptive_path_incomplete"
        orig["daily_path_complete"] = False
        orig["incomplete_reason"] = (
            "orig surprise path missing gross/net series — adaptive overlay "
            "not approximated"
        )
        return orig

    hist: list[float] = []
    n_orig = n_flip = n_def = 0
    adapt_net: list[float] = []
    adapt_gross: list[float] = []
    for i, _d in enumerate(dates):
        lastk = hist[-trail_k:]
        if len(lastk) < trail_min:
            t = 1.0
            n_def += 1
        elif sum(lastk) / float(len(lastk)) >= 0.0:
            t = 1.0
            n_orig += 1
        else:
            t = -1.0
            n_flip += 1
        g = float(gross[i])
        n = float(net[i])
        cost = g - n
        adapt_g = t * g
        adapt_n = adapt_g - cost
        adapt_gross.append(adapt_g)
        adapt_net.append(adapt_n)
        hist.append(n)
    stitched = w100._stitch_net(adapt_net, dates)
    orig["net_daily"] = adapt_net
    orig["gross_daily"] = adapt_gross
    orig["n_adaptive_orig"] = n_orig + n_def
    orig["n_adaptive_flip"] = n_flip
    orig["n_adaptive_default_orig"] = n_def
    orig.update(
        {
            k: stitched.get(k)
            for k in (
                "daily_path_DD",
                "dd_duration",
                "recovery_days",
                "recovered",
                "total_return_net",
                "equities",
            )
            if k in stitched
        }
    )
    orig["total_ret_net"] = stitched.get("total_return_net")
    orig["mean_net_daily"] = (
        (sum(adapt_net) / float(len(adapt_net))) if adapt_net else None
    )
    orig["status"] = "ok"
    orig["daily_path_complete"] = True
    return orig


_W106_EVAL_ONE_SHARD = w106._eval_one_shard


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
    if lid == "event_funding_adaptive_side":
        return evaluate_event_funding_adaptive_side_daily_mtm(
            bars,
            events_by_code,
            overnight_by_date,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    if lid == "surprise_xs_rank_adaptive":
        return evaluate_surprise_xs_rank_adaptive_daily_mtm(
            bars,
            events_by_code,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=p0,
            period_end=p1,
        )
    return _W106_EVAL_ONE_SHARD(
        spec=spec,
        loaded=loaded,
        events_by_code=events_by_code,
        overnight_by_date=overnight_by_date,
        curve_series=curve_series,
        one_way_cost=one_way_cost,
    )


def run_adaptive_daily_dd(
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
    # Reuse W106 stitch/window machinery with this-wave evaluator.
    orig_windows = w106.W106_WINDOWS
    w106._eval_one_shard = _eval_one_shard  # type: ignore[assignment]
    w106.W106_WINDOWS = W107_WINDOWS  # type: ignore[misc]
    try:
        return w106.run_ls_daily_dd(
            out_dir=out_dir,
            spec=spec,
            codes=codes,
            events_by_code=events_by_code,
            overnight_by_date=overnight_by_date,
            curve_series=curve_series,
            max_days=max_days,
            one_way_cost=one_way_cost,
            log=log,
        )
    finally:
        w106._eval_one_shard = _W106_EVAL_ONE_SHARD  # type: ignore[assignment]
        w106.W106_WINDOWS = orig_windows  # type: ignore[misc]


def _side_preference_table(daily_packs: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_lid_win: dict[tuple[str, str], dict[str, Any]] = {}
    for lid, pack in daily_packs.items():
        for row in pack.get("table") or []:
            wid = str(row.get("window") or "")
            by_lid_win[(lid, wid)] = row
    windows = [str(w["window_id"]) for w in W107_WINDOWS]
    out: list[dict[str, Any]] = []
    groups = (
        (
            "event_funding_stress_skip",
            "event_funding_easy_short",
            "event_funding_stress_ls",
            "event_funding_adaptive_side",
        ),
        (
            "surprise_xs_rank_hold",
            "surprise_xs_rank_flip",
            None,
            "surprise_xs_rank_adaptive",
        ),
    )
    for parent, flip, cond, adaptive in groups:
        for wid in windows:
            rows = {
                parent: by_lid_win.get((parent, wid)) or {},
                flip: by_lid_win.get((flip, wid)) or {},
                adaptive: by_lid_win.get((adaptive, wid)) or {},
            }
            if cond:
                rows[cond] = by_lid_win.get((cond, wid)) or {}
            cands: list[tuple[str, float, Any]] = []
            for lid, row in rows.items():
                net = row.get("total_ret_net")
                if net is None:
                    continue
                cands.append((lid, float(net), row.get("daily_path_DD")))
            preferred = max(cands, key=lambda x: x[1])[0] if cands else None

            def _occ(row: Mapping[str, Any]) -> dict[str, Any]:
                return {
                    "n_entered": row.get("n_entered"),
                    "n_events": row.get("n_events"),
                    "n_ranked_days": row.get("n_ranked_days"),
                    "n_easy_entered": row.get("n_easy_entered"),
                    "n_stress_entered": row.get("n_stress_entered"),
                    "n_adaptive_orig": row.get("n_adaptive_orig"),
                    "n_adaptive_flip": row.get("n_adaptive_flip"),
                    "active_frac": row.get("active_frac"),
                }

            out.append(
                {
                    "window": wid,
                    "parent": parent,
                    "parent_net": rows[parent].get("total_ret_net"),
                    "parent_dd": rows[parent].get("daily_path_DD"),
                    "parent_occ": _occ(rows[parent]),
                    "flip": flip,
                    "flip_net": rows[flip].get("total_ret_net"),
                    "flip_dd": rows[flip].get("daily_path_DD"),
                    "flip_occ": _occ(rows[flip]),
                    "conditional": cond,
                    "conditional_net": (rows.get(cond) or {}).get("total_ret_net")
                    if cond
                    else None,
                    "conditional_dd": (rows.get(cond) or {}).get("daily_path_DD")
                    if cond
                    else None,
                    "adaptive": adaptive,
                    "adaptive_net": rows[adaptive].get("total_ret_net"),
                    "adaptive_dd": rows[adaptive].get("daily_path_DD"),
                    "adaptive_occ": _occ(rows[adaptive]),
                    "preferred_side_logic": preferred,
                    "sign_flip_is_not_a_kill": True,
                    "did_not_kill_funding_surprise": True,
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
    p.add_argument("--seed", type=int, default=8908207)
    p.add_argument("--sqlite", type=str, default=str(SQLITE_DEFAULT))
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-fixed", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w107_funding_surprise_adaptive.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert_adaptive.json", pins)
    log(f"[w107/C] pins_untouched={pins['pins_untouched']}")
    log(
        "[w107/C] adaptive side + fixed L/S table. "
        "sign_flip_is_not_a_kill=True did_not_kill_funding_surprise=True "
        "hold_mom_grid=false threshold_grid=false go=false "
        "Grok implementer (this wave)."
    )

    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(args.max_codes)]
    sqlite_path = Path(args.sqlite)
    extra = w104.inspect_unique_logic_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    events = extra.get("fins_events") or {}
    overnight = extra.get("overnight_by_date") or {}
    curve = extra.get("curve_series")

    specs: list[dict[str, Any]] = []
    if not args.skip_fixed:
        specs.extend(dict(s) for s in PARENT_SPECS)
        specs.extend(dict(s) for s in w106.NEW_LS_VARIANTS)
    specs.extend(dict(s) for s in ADAPTIVE_VARIANTS)

    daily_packs: dict[str, Any] = {}
    for spec in specs:
        lid = str(spec["logic_id"])
        daily_packs[lid] = run_adaptive_daily_dd(
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

    side = _side_preference_table(daily_packs)
    _dump(out_dir / "funding_surprise_side_table.json", side)

    compact = []
    for spec in specs:
        lid = str(spec["logic_id"])
        pack = daily_packs.get(lid) or {}
        for row in pack.get("table") or []:
            compact.append(
                {
                    "logic_id": row.get("logic_id"),
                    "parent_logic_id": spec.get("parent_logic_id"),
                    "variant_kind": spec.get("variant_kind"),
                    "window": row.get("window"),
                    "n_days": row.get("n_days"),
                    "daily_path_DD": row.get("daily_path_DD"),
                    "dd_duration": row.get("dd_duration"),
                    "recovery_days": row.get("recovery_days"),
                    "recovered": row.get("recovered"),
                    "total_ret_net": row.get("total_ret_net"),
                    "daily_path_complete": row.get("daily_path_complete"),
                    "n_entered": row.get("n_entered"),
                    "n_events": row.get("n_events"),
                    "n_ranked_days": row.get("n_ranked_days"),
                    "n_adaptive_orig": row.get("n_adaptive_orig"),
                    "n_adaptive_flip": row.get("n_adaptive_flip"),
                    "side_sign": row.get("side_sign"),
                    "sign_flip_is_not_a_kill": True,
                    "promote_as_main": False,
                    "go": False,
                    "stance": "RESEARCH_ONLY",
                }
            )
    _dump(out_dir / "funding_surprise_adaptive_daily_dd_table.json", compact)

    if not args.skip_hyps:
        from research.mass_strategy_factory import (
            CONTINUOUS_PAPER,
            FROZEN_DEFAULT_PATH,
            MASS_RESEARCH,
            MassFactoryConfig,
            propose_profit_hypotheses,
        )

        proposals = proposals_for_factory()
        cfg = MassFactoryConfig(seed=int(args.seed), n=max(20, len(proposals) + 5))
        eval_out = propose_profit_hypotheses(
            proposals, evaluate=True, synthetic=True, config=cfg
        )
        _dump(out_dir / "adaptive_hyp_proposals.json", proposals)
        _dump(out_dir / "adaptive_hyp_eval_screens.json", eval_out.get("eval_screens") or [])
        hyp_summary = {
            "n_proposed": eval_out.get("n_proposals"),
            "n_accepted": eval_out.get("n_accepted"),
            "n_survivors_period_net": sum(
                1
                for s in (eval_out.get("eval_screens") or [])
                if isinstance(s, Mapping) and s.get("survived")
            ),
            "period_net_is_not_a_pass": True,
            "sign_flip_is_not_a_kill": True,
            "mass_research": MASS_RESEARCH,
            "continuous_paper": CONTINUOUS_PAPER,
            "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
            "promote_as_main": False,
            "go": False,
        }
        _dump(out_dir / "adaptive_hyp_summary.json", hyp_summary)
    else:
        hyp_summary = None

    pins_after = _assert_frozen_pins_untouched()
    n_complete = sum(1 for p in daily_packs.values() if p.get("complete"))
    summary = {
        "wave": WAVE,
        "track": "C_funding_surprise_adaptive",
        "n_adaptive": len(ADAPTIVE_VARIANTS),
        "adaptive_logic_ids": [s["logic_id"] for s in ADAPTIVE_VARIANTS],
        "fixed_ls_table_kept": not args.skip_fixed,
        "sign_flip_is_not_a_kill": True,
        "did_not_kill_funding_surprise": True,
        "trail_k": TRAIL_K,
        "trail_min": TRAIL_MIN,
        "n_daily_path_complete_logics": n_complete,
        "worst_daily_path_DD_by_logic": {
            lid: p.get("worst_daily_path_DD") for lid, p in daily_packs.items()
        },
        "complete_by_logic": {
            lid: p.get("complete") for lid, p in daily_packs.items()
        },
        "side_table": side,
        "hyps": hyp_summary,
        "hold_mom_grid": False,
        "threshold_grid": False,
        "pins_untouched": pins_after.get("pins_untouched"),
        "promote_as_main": False,
        "go": False,
        "mass": "NO-GO",
        "implementer": "Grok",
        "git_sha": _git_sha(),
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w107_c_summary.json", summary)
    log(
        f"[w107/C] done wall={summary['wall_sec']}s complete={n_complete} "
        f"pins={pins_after.get('pins_untouched')} not_a_kill=true"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
