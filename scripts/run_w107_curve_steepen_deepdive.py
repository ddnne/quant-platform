#!/usr/bin/env python3
"""W107 / w0820d Track D — light deep-dive of curve_steepen_impulse_cs only.

Measures occupancy, window stability, cost feel.
NO threshold / hold / mom grid farm. promote_as_main=false · go=false.

Examples
--------
    uv run python scripts/run_w107_curve_steepen_deepdive.py \\
        --out-dir .glm-logs/w0820d_w107_otc11_adaptive/
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0820d_w107_otc11_adaptive"
SQLITE_DEFAULT = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_dispersion_quality as w102q  # noqa: E402
import run_w102_event_rate_daily_dd as w102  # noqa: E402
import run_w106_new_hyps_daily_dd as w106  # noqa: E402

WAVE = "W107 / w0820d"
DEEP_LOGIC_ID = "curve_steepen_impulse_cs"
TX_COST_BANDS_BP: tuple[int, ...] = (5, 10, 20)
BASE_TX_BP: int = 10
W107_WINDOWS = w99.W99_WINDOWS


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _spec() -> dict[str, Any]:
    for s in w106.NEW_UNIQUE_LOGIC:
        if s["logic_id"] == DEEP_LOGIC_ID:
            return dict(s)
    raise KeyError(DEEP_LOGIC_ID)


def _eval_window(
    *,
    spec: Mapping[str, Any],
    curve_series: Mapping[str, Any] | None,
    codes: Sequence[str],
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in W107_WINDOWS:
        wid = str(w["window_id"])
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        n_on = 0
        n_off = 0
        n_bar = 0
        n_act = 0
        n_cal = 0
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                continue
            pack = w106.evaluate_curve_steepen_impulse_cs_daily_mtm(
                loaded["bars"],
                curve_series,
                spec=spec,
                one_way_cost=float(one_way_cost),
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["n_gate_on_days"] = pack.get("n_gate_on_days")
            summary["n_gated_off_days"] = pack.get("n_gated_off_days")
            summary["occupancy_frac"] = pack.get("occupancy_frac")
            summary["n_skip_curve_gap"] = pack.get("n_skip_curve_gap")
            summary["n_skip_not_steepen"] = pack.get("n_skip_not_steepen")
            summary["n_skip_small_delta"] = pack.get("n_skip_small_delta")
            shard_summaries.append(summary)
            n_on += int(pack.get("n_gate_on_days") or 0)
            n_off += int(pack.get("n_gated_off_days") or 0)
            n_bar += int(pack.get("n_bar_dates") or 0)
            n_act += int(pack.get("n_active_days") or 0)
            n_cal += max(0, len(list(pack.get("dates") or [])) - 1)
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
                f"[w107/D {lid}] {wid}/{pid} status={pack.get('status')} "
                f"gate_on={pack.get('n_gate_on_days')} "
                f"occ={_fmt(pack.get('occupancy_frac'))} "
                f"DD={_fmt(summary.get('daily_path_DD'))}"
            )
        if not stitch_net:
            rows.append(
                {
                    "logic_id": lid,
                    "window": wid,
                    "daily_path_complete": False,
                    "incomplete_reason": "no ok daily path stitched",
                    "n_gate_on_days": n_on,
                    "promote_as_main": False,
                    "go": False,
                    "shard_summaries": shard_summaries,
                }
            )
            continue
        stitched = w100._stitch_net(stitch_net, stitch_dates)
        char = w102q.dd_interval_character(
            stitched.get("equities") or [], stitch_dates
        )
        occ = (float(n_on) / float(n_bar)) if n_bar else None
        rows.append(
            {
                "logic_id": lid,
                "window": wid,
                "label": w.get("label"),
                "n_days": stitched.get("n_equity_points") or len(stitch_dates),
                "daily_path_DD": stitched.get("daily_path_DD"),
                "dd_duration": stitched.get("dd_duration"),
                "recovery_days": stitched.get("recovery_days"),
                "recovered": stitched.get("recovered"),
                "total_ret_net": stitched.get("total_return_net"),
                "total_return_gross": stitched.get("total_return_gross"),
                "peak_date": stitched.get("peak_date"),
                "trough_date": stitched.get("trough_date"),
                "daily_path_complete": (stitched.get("daily_path_dd_gate") or {}).get(
                    "complete"
                ),
                "n_gate_on_days": n_on,
                "n_gated_off_days": n_off,
                "n_bar_dates": n_bar,
                "occupancy_frac": occ,
                "n_active_days": n_act,
                "n_calendar_days": n_cal,
                "active_frac": (n_act / n_cal) if n_cal else None,
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
                "shard_summaries": shard_summaries,
            }
        )
    return {"logic_id": lid, "table": rows}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--sqlite", type=str, default=str(SQLITE_DEFAULT))
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w107_curve_steepen_deepdive.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(args.max_codes)]
    extra = w106.inspect_unique_logic_datasets(
        codes=codes, sqlite_path=Path(args.sqlite), log=log
    )
    curve = extra.get("curve_series")
    spec = _spec()
    base_ow = BASE_TX_BP / 10_000.0
    log(
        f"[w107/D] logic={DEEP_LOGIC_ID} tx_bands_bp={list(TX_COST_BANDS_BP)} "
        "hold_mom_grid=false threshold_grid=false go=false"
    )
    base = _eval_window(
        spec=spec,
        curve_series=curve,
        codes=codes,
        max_days=int(args.max_days),
        one_way_cost=base_ow,
        log=log,
    )
    slim = [dict(r) for r in base["table"]]
    _dump(out_dir / f"deepdive_{DEEP_LOGIC_ID}_base.json", slim)

    tx_rows: list[dict[str, Any]] = []
    for bp in TX_COST_BANDS_BP:
        ow = float(bp) / 10_000.0
        pack = (
            base
            if bp == BASE_TX_BP
            else _eval_window(
                spec=spec,
                curve_series=curve,
                codes=codes,
                max_days=int(args.max_days),
                one_way_cost=ow,
                log=log,
            )
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
                    "occupancy_frac": r.get("occupancy_frac"),
                    "n_gate_on_days": r.get("n_gate_on_days"),
                    "daily_path_complete": r.get("daily_path_complete"),
                    "promote_as_main": False,
                    "go": False,
                    "note": "tx-band cost feel only; not a strategy grid / not pick-best",
                }
            )
    _dump(out_dir / "deepdive_curve_steepen_tx_cost_feel.json", tx_rows)

    occupancy_rows = []
    stability_rows = []
    worst = None
    signs: list[int] = []
    for r in base["table"]:
        occupancy_rows.append(
            {
                "logic_id": DEEP_LOGIC_ID,
                "window": r.get("window"),
                "n_days": r.get("n_days"),
                "n_gate_on_days": r.get("n_gate_on_days"),
                "n_gated_off_days": r.get("n_gated_off_days"),
                "n_bar_dates": r.get("n_bar_dates"),
                "occupancy_frac": r.get("occupancy_frac"),
                "n_active_days": r.get("n_active_days"),
                "active_frac": r.get("active_frac"),
                "ffill_applied": False,
                "invent_fill": False,
            }
        )
        dd = r.get("daily_path_DD")
        if dd is not None and (worst is None or float(dd) < float(worst)):
            worst = float(dd)
        tr = r.get("total_ret_net")
        if tr is not None:
            signs.append(1 if float(tr) > 0 else (-1 if float(tr) < 0 else 0))
        stability_rows.append(
            {
                "logic_id": DEEP_LOGIC_ID,
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
                "sign_total_ret_net": (
                    1
                    if tr is not None and float(tr) > 0
                    else (-1 if tr is not None and float(tr) < 0 else 0)
                ),
            }
        )
    _dump(out_dir / "deepdive_curve_steepen_occupancy.json", occupancy_rows)
    _dump(out_dir / "deepdive_curve_steepen_window_stability.json", stability_rows)

    summary = {
        "wave": WAVE,
        "track": "D_curve_steepen_light_deepdive",
        "logic_id": DEEP_LOGIC_ID,
        "hold_mom_grid": False,
        "threshold_grid": False,
        "tx_cost_bands_bp": list(TX_COST_BANDS_BP),
        "base_tx_bp": BASE_TX_BP,
        "cost_feel": "tx 5/10/20 bp replay; not pick-best; not a strategy grid",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "stance": "RESEARCH_ONLY",
        "worst_daily_path_DD": worst,
        "window_sign_pattern": signs,
        "occupancy": occupancy_rows,
        "window_stability": stability_rows,
        "tx_cost_feel": tx_rows,
        "mass": "NO-GO",
        "implementer": "Grok",
        "wall_sec": round(time.time() - t0, 1),
        "note": (
            "Light deep-dive only. Occupancy / window stability / cost feel. "
            "No threshold/hold grid farm. Complete measurement ≠ GO."
        ),
    }
    _dump(out_dir / "w107_d_curve_steepen_deepdive.json", summary)
    log(
        f"[w107/D] done wall={summary['wall_sec']}s "
        f"worst={_fmt(worst)} signs={signs}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
