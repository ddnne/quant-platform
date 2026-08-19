#!/usr/bin/env python3
"""W105 / w0820b Track C — light deep-dive of two unique_logics only.

Logics (only these two):
  * event_funding_stress_skip
  * surprise_xs_rank_hold

Measures occupancy, window stability, cost feel.
NO threshold / hold grid farm. promote_as_main=false · go=false.

Examples
--------
    uv run python scripts/run_w105_funding_surprise_deepdive.py \\
        --out-dir .glm-logs/w0820b_w105_otc9_family_hyps/
"""
from __future__ import annotations

import argparse
import json
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820b_w105_otc9_family_hyps"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_dispersion_quality as w102  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402

WAVE = "W105 / w0820b"
DEEP_LOGIC_IDS: tuple[str, ...] = (
    "event_funding_stress_skip",
    "surprise_xs_rank_hold",
)
TX_COST_BANDS_BP: tuple[int, ...] = (5, 10, 20)
BASE_TX_BP: int = 10


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _pct(v: Any, nd: int = 1) -> str:
    x = w100._scalar_f(v)
    if x is None:
        return "—"
    return f"{x * 100:.{nd}f}%"


def _spec_by_id(logic_id: str) -> dict[str, Any]:
    for s in w104.NEW_UNIQUE_LOGIC:
        if s["logic_id"] == logic_id:
            return dict(s)
    raise KeyError(logic_id)


def _occupancy_from_pack(pack: Mapping[str, Any]) -> dict[str, Any]:
    dates = list(pack.get("dates") or [])
    n_cal = max(0, len(dates) - 1)
    n_act = int(pack.get("n_active_days") or 0)
    n_events = pack.get("n_events")
    n_entered = pack.get("n_entered")
    n_eligible = pack.get("n_eligible") or pack.get("n_eligible_pre_gate")
    return {
        "n_calendar_days": n_cal,
        "n_active_days": n_act,
        "active_frac": (n_act / n_cal) if n_cal else None,
        "n_events": n_events,
        "n_eligible_pre_gate": n_eligible,
        "n_entered": n_entered,
        "enter_frac_of_events": (
            (float(n_entered) / float(n_events))
            if n_entered is not None and n_events
            else None
        ),
        "n_skip_missing_overnight": pack.get("n_skip_missing_overnight"),
        "n_skip_median_unformed": pack.get("n_skip_median_unformed"),
        "n_skip_funding_stress": pack.get("n_skip_funding_stress"),
        "n_ranked_days": pack.get("n_ranked_days"),
        "n_flat_sparse_days": pack.get("n_flat_sparse_days"),
        "mean_names_on_ranked_days": pack.get("mean_names_on_ranked_days"),
        "ranked_frac": (
            (float(pack.get("n_ranked_days") or 0) / float(n_cal)) if n_cal else None
        ),
        "ffill_applied": pack.get("ffill_applied"),
        "invent_fill": pack.get("invent_fill"),
    }


def _eval_window(
    *,
    spec: Mapping[str, Any],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    curve_series: Mapping[str, Any] | None,
    codes: Sequence[str],
    max_days: int,
    one_way_cost: float,
    log,
    keep_path: bool,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in w104.W104_WINDOWS:
        wid = str(w["window_id"])
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        shard_packs: list[dict[str, Any]] = []
        n_events_win = 0
        n_entered_win = 0
        n_ranked_win = 0
        n_flat_win = 0
        n_skip_missing = 0
        n_skip_med = 0
        n_skip_stress = 0
        n_act_win = 0
        n_cal_win = 0
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                continue
            pack = w104._eval_one_shard(
                spec=spec,
                loaded=loaded,
                events_by_code=events_by_code,
                overnight_by_date=overnight_by_date,
                curve_series=curve_series,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            occ = _occupancy_from_pack(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary.update(
                {
                    k: occ[k]
                    for k in occ
                    if k
                    in {
                        "n_events",
                        "n_entered",
                        "n_ranked_days",
                        "n_flat_sparse_days",
                        "n_skip_missing_overnight",
                        "n_skip_median_unformed",
                        "n_skip_funding_stress",
                        "n_active_days",
                        "active_frac",
                        "mean_names_on_ranked_days",
                    }
                }
            )
            shard_summaries.append(summary)
            n_events_win += int(pack.get("n_events") or 0)
            n_entered_win += int(pack.get("n_entered") or 0)
            n_ranked_win += int(pack.get("n_ranked_days") or 0)
            n_flat_win += int(pack.get("n_flat_sparse_days") or 0)
            n_skip_missing += int(pack.get("n_skip_missing_overnight") or 0)
            n_skip_med += int(pack.get("n_skip_median_unformed") or 0)
            n_skip_stress += int(pack.get("n_skip_funding_stress") or 0)
            n_act_win += int(occ.get("n_active_days") or 0)
            n_cal_win += int(occ.get("n_calendar_days") or 0)
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
            if keep_path:
                shard_packs.append(
                    {
                        "period_id": pid,
                        "dates": dlist,
                        "equities": list(pack.get("equities") or []),
                        "gross_daily": glist,
                        "net_daily": nlist,
                        "daily_cost_drag": pack.get("daily_cost_drag"),
                    }
                )
            log(
                f"[w105/C {lid}] {wid}/{pid} status={pack.get('status')} "
                f"entered={pack.get('n_entered')} events={pack.get('n_events')} "
                f"ranked={pack.get('n_ranked_days')} "
                f"skip_stress={pack.get('n_skip_funding_stress')} "
                f"skip_missing={pack.get('n_skip_missing_overnight')} "
                f"DD={_fmt(summary.get('daily_path_DD'))}"
            )
        if not stitch_net:
            rows.append(
                {
                    "logic_id": lid,
                    "window": wid,
                    "daily_path_complete": False,
                    "incomplete_reason": "no ok daily path stitched",
                    "n_events": n_events_win,
                    "n_entered": n_entered_win,
                    "promote_as_main": False,
                    "go": False,
                    "shard_summaries": shard_summaries,
                }
            )
            continue
        stitched = w100._stitch_net(stitch_net, stitch_dates)
        char = w102.dd_interval_character(
            stitched.get("equities") or [], stitch_dates
        )
        n_cal = max(0, len(stitch_dates) - 1)
        row = {
            "logic_id": lid,
            "window": wid,
            "label": w.get("label"),
            "data_note": w.get("data_note"),
            "n_days": stitched.get("n_equity_points") or len(stitch_dates),
            "daily_path_DD": stitched.get("daily_path_DD"),
            "dd_duration": stitched.get("dd_duration"),
            "recovery_days": stitched.get("recovery_days"),
            "recovered": stitched.get("recovered"),
            "total_ret_net": stitched.get("total_return_net"),
            "total_return_gross": stitched.get("total_return_gross"),
            "peak_date": stitched.get("peak_date"),
            "trough_date": stitched.get("trough_date"),
            "recovery_date": stitched.get("recovery_date"),
            "daily_path_complete": (stitched.get("daily_path_dd_gate") or {}).get(
                "complete"
            ),
            "n_calendar_days": n_cal_win or n_cal,
            "n_active_days": n_act_win,
            "active_frac": (n_act_win / n_cal_win) if n_cal_win else None,
            "n_events": n_events_win,
            "n_entered": n_entered_win,
            "enter_frac_of_events": (
                (n_entered_win / n_events_win) if n_events_win else None
            ),
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_med,
            "n_skip_funding_stress": n_skip_stress,
            "n_ranked_days": n_ranked_win,
            "n_flat_sparse_days": n_flat_win,
            "ranked_frac": (n_ranked_win / n_cal_win) if n_cal_win else None,
            "n_dd_episodes": char.get("n_episodes"),
            "time_underwater_frac": char.get("time_underwater_frac"),
            "max_episode_duration": char.get("max_episode_duration"),
            "median_episode_duration": char.get("median_episode_duration"),
            "n_unrecovered": char.get("n_unrecovered"),
            "one_way_cost": float(one_way_cost),
            "ffill_applied": False,
            "invent_fill": False,
            "hold_mom_grid": False,
            "threshold_grid": False,
            "promote_as_main": False,
            "go": False,
            "stance": "RESEARCH_ONLY",
            "data_path": "local_real_mirrors+local_sqlite",
            "shard_summaries": shard_summaries,
        }
        if keep_path:
            row["_path"] = {
                "dates": stitch_dates,
                "equities": stitched.get("equities") or [],
                "net_daily": stitch_net,
                "gross_daily": stitch_gross,
                "shard_packs": shard_packs,
            }
        rows.append(row)
    return {"logic_id": lid, "table": rows}


def run_deepdive(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    sqlite_path: Path,
    log,
) -> dict[str, Any]:
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    extra = w104.inspect_unique_logic_datasets(
        codes=codes, sqlite_path=sqlite_path, log=log
    )
    events = extra.get("fins_events") or {}
    overnight = extra.get("overnight_by_date") or {}
    curve = extra.get("curve_series")
    base_one_way = BASE_TX_BP / 10_000.0
    log(
        f"[w105/C] logics={list(DEEP_LOGIC_IDS)} tx_bands_bp={list(TX_COST_BANDS_BP)} "
        "hold_mom_grid=false threshold_grid=false go=false"
    )

    base_by: dict[str, dict[str, Any]] = {}
    for lid in DEEP_LOGIC_IDS:
        spec = _spec_by_id(lid)
        pack = _eval_window(
            spec=spec,
            events_by_code=events,
            overnight_by_date=overnight,
            curve_series=curve,
            codes=codes,
            max_days=max_days,
            one_way_cost=base_one_way,
            log=log,
            keep_path=True,
        )
        base_by[lid] = pack
        slim = [
            {k: v for k, v in r.items() if not str(k).startswith("_")}
            for r in pack["table"]
        ]
        _dump(out_dir / f"deepdive_{lid}_base.json", slim)

    tx_rows: list[dict[str, Any]] = []
    for bp in TX_COST_BANDS_BP:
        ow = float(bp) / 10_000.0
        for lid in DEEP_LOGIC_IDS:
            spec = _spec_by_id(lid)
            if bp == BASE_TX_BP:
                pack = base_by[lid]
            else:
                pack = _eval_window(
                    spec=spec,
                    events_by_code=events,
                    overnight_by_date=overnight,
                    curve_series=curve,
                    codes=codes,
                    max_days=max_days,
                    one_way_cost=ow,
                    log=log,
                    keep_path=False,
                )
            for r in pack["table"]:
                tx_rows.append(
                    {
                        "logic_id": r["logic_id"],
                        "window": r["window"],
                        "one_way_bp": bp,
                        "daily_path_DD": r.get("daily_path_DD"),
                        "dd_duration": r.get("dd_duration"),
                        "recovery_days": r.get("recovery_days"),
                        "recovered": r.get("recovered"),
                        "total_ret_net": r.get("total_ret_net"),
                        "n_days": r.get("n_days"),
                        "n_active_days": r.get("n_active_days"),
                        "n_entered": r.get("n_entered"),
                        "n_ranked_days": r.get("n_ranked_days"),
                        "daily_path_complete": r.get("daily_path_complete"),
                        "promote_as_main": False,
                        "go": False,
                        "note": "tx-band cost feel only; not a strategy grid / not pick-best",
                    }
                )
    _dump(out_dir / "deepdive_tx_cost_feel.json", tx_rows)

    occupancy_rows: list[dict[str, Any]] = []
    stability_rows: list[dict[str, Any]] = []
    worst_by: dict[str, float | None] = {}
    for lid, pack in base_by.items():
        worst = None
        signs: list[int] = []
        for r in pack["table"]:
            occupancy_rows.append(
                {
                    "logic_id": lid,
                    "window": r.get("window"),
                    "n_days": r.get("n_days"),
                    "n_calendar_days": r.get("n_calendar_days"),
                    "n_active_days": r.get("n_active_days"),
                    "active_frac": r.get("active_frac"),
                    "n_events": r.get("n_events"),
                    "n_entered": r.get("n_entered"),
                    "enter_frac_of_events": r.get("enter_frac_of_events"),
                    "n_skip_missing_overnight": r.get("n_skip_missing_overnight"),
                    "n_skip_median_unformed": r.get("n_skip_median_unformed"),
                    "n_skip_funding_stress": r.get("n_skip_funding_stress"),
                    "n_ranked_days": r.get("n_ranked_days"),
                    "n_flat_sparse_days": r.get("n_flat_sparse_days"),
                    "ranked_frac": r.get("ranked_frac"),
                    "ffill_applied": False,
                    "invent_fill": False,
                }
            )
            dd = r.get("daily_path_DD")
            if dd is not None:
                if worst is None or float(dd) < float(worst):
                    worst = float(dd)
            tr = r.get("total_ret_net")
            if tr is not None:
                signs.append(1 if float(tr) > 0 else (-1 if float(tr) < 0 else 0))
            stability_rows.append(
                {
                    "logic_id": lid,
                    "window": r.get("window"),
                    "daily_path_DD": r.get("daily_path_DD"),
                    "dd_duration": r.get("dd_duration"),
                    "recovery_days": r.get("recovery_days"),
                    "recovered": r.get("recovered"),
                    "total_ret_net": r.get("total_ret_net"),
                    "n_dd_episodes": r.get("n_dd_episodes"),
                    "time_underwater_frac": r.get("time_underwater_frac"),
                    "max_episode_duration": r.get("max_episode_duration"),
                    "median_episode_duration": r.get("median_episode_duration"),
                    "peak_date": r.get("peak_date"),
                    "trough_date": r.get("trough_date"),
                    "sign_total_ret_net": (
                        1
                        if tr is not None and float(tr) > 0
                        else (-1 if tr is not None and float(tr) < 0 else 0)
                    ),
                }
            )
        worst_by[lid] = worst
        log(
            f"[w105/C] {lid} worst_daily_path_DD={_fmt(worst)} "
            f"window_sign_pattern={signs} (not a pass)"
        )

    _dump(out_dir / "deepdive_occupancy.json", occupancy_rows)
    _dump(out_dir / "deepdive_window_stability.json", stability_rows)

    extra_dump = {
        k: v
        for k, v in extra.items()
        if k not in {"fins_events", "curve_series", "overnight_by_date"}
    }
    _dump(out_dir / "deepdive_extra_dataset_wiring.json", extra_dump)

    summary = {
        "wave": WAVE,
        "track": "C_funding_surprise_light_deepdive",
        "logics": list(DEEP_LOGIC_IDS),
        "n_logics": 2,
        "hold_mom_grid": False,
        "threshold_grid": False,
        "dispersion_gate_grid": False,
        "tx_cost_bands_bp": list(TX_COST_BANDS_BP),
        "base_tx_bp": BASE_TX_BP,
        "cost_feel": "tx 5/10/20 bp replay; not pick-best; not a strategy grid",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "stance": "RESEARCH_ONLY",
        "worst_daily_path_DD_by_logic": worst_by,
        "occupancy": occupancy_rows,
        "window_stability": stability_rows,
        "tx_cost_feel": tx_rows,
        "mass_research": "NO-GO",
        "ready": False,
        "continuous_paper": "UNARMED",
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "note": (
            "Light deep-dive only. Occupancy / window stability / cost feel. "
            "No threshold/hold grid farm. Complete measurement ≠ GO."
        ),
    }
    _dump(out_dir / "deepdive_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--sqlite", type=str, default=str(SQLITE_DEFAULT))
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w105_funding_surprise_deepdive.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = w104._assert_frozen_pins_untouched()
    pins["note"] = "W105 C deep-dive must not mutate 3-default pins"
    _dump(out_dir / "deepdive_frozen_pins_assert.json", pins)
    log(f"[w105/C] pins_untouched={pins['pins_untouched']}")
    log(
        "[w105/C] promote_as_main=false go=false hold_mom_grid=false "
        "threshold_grid=false GLM implementer only. Grok did not implement."
    )
    summary = run_deepdive(
        out_dir=out_dir,
        max_codes=int(args.max_codes),
        max_days=int(args.max_days),
        sqlite_path=Path(args.sqlite),
        log=log,
    )
    pins_after = w104._assert_frozen_pins_untouched()
    _dump(out_dir / "deepdive_frozen_pins_assert_after.json", pins_after)
    summary["pins_untouched"] = pins_after.get("pins_untouched")
    summary["wall_sec"] = round(time.time() - t0, 1)
    _dump(out_dir / "deepdive_summary.json", summary)
    log(
        f"[w105/C] done wall={summary['wall_sec']}s "
        f"pins={pins_after.get('pins_untouched')} "
        f"worst={summary.get('worst_daily_path_DD_by_logic')}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
