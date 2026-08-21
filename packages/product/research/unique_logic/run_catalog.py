"""Run catalog YAML logics through daily_path_eval (candidate-grade).

Does not add a wave script. Does not promote. Scores go to eval_registry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.class_hyp_eval import (
    DEFAULT_EVAL_CODES,
    build_repo_curve_series,
    load_repo_rows_all_tenors_from_sqlite,
)
from research.daily_path_eval import (
    assert_frozen_pins_untouched,
    dump_json,
    load_shard_bars,
    stitch_net,
    summarize_path,
)
from research.eval_windows import HONEST_3Y_WINDOWS
from research.stats_metrics import evaluate_daily_path_dd_gate
from research.unique_logic.catalog import catalog_spec
from research.unique_logic import cs_overlays


def _log(msg: str) -> None:
    print(msg, flush=True)


def _load_funding(sqlite_path: Path) -> tuple[dict[str, float], dict[str, Any]]:
    rows = load_repo_rows_all_tenors_from_sqlite(
        sqlite_path, start="2016-01-01", end="2026-12-31"
    )
    curve = build_repo_curve_series(rows)
    overnight = dict(curve.get("short_rates_by_date") or curve.get("rates_by_date") or {})
    return overnight, curve


def _eval_shard(
    *,
    spec: Mapping[str, Any],
    loaded: Mapping[str, Any],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    lid = str(spec.get("logic_id") or "")
    bars = loaded.get("bars") or {}
    if lid == "overnight_level_cs_tilt":
        return cs_overlays.evaluate_overnight_level_cs_tilt_daily_mtm(
            bars, overnight, spec=spec, one_way_cost=one_way_cost
        )
    if lid == "xs_low_vol_mom":
        return cs_overlays.evaluate_xs_low_vol_mom_daily_mtm(
            bars, spec=spec, one_way_cost=one_way_cost
        )
    if lid == "repo_3m_level_cs":
        return cs_overlays.evaluate_repo_3m_level_cs_daily_mtm(
            bars, curve, spec=spec, one_way_cost=one_way_cost
        )
    return {
        "status": "unknown_logic",
        "logic_id": lid,
        "daily_path_complete": False,
        "incomplete_reason": f"no catalog dispatch for {lid}",
    }


def eval_logic_windows(
    spec: Mapping[str, Any],
    *,
    codes: Sequence[str],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    max_days: int,
    one_way_cost: float,
) -> list[dict[str, Any]]:
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for window in HONEST_3Y_WINDOWS:
        wid = str(window["window_id"])
        stitch_dates: list[str] = []
        stitch_nets: list[float] = []
        n_gate_on = 0
        n_bar = 0
        shard_summaries: list[dict[str, Any]] = []
        for shard in window["shards"]:
            loaded = load_shard_bars(shard, codes=codes, max_days=max_days)
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": loaded.get("period_id"), "status": loaded.get("status")}
                )
                continue
            pack = _eval_shard(
                spec=spec,
                loaded=loaded,
                overnight=overnight,
                curve=curve,
                one_way_cost=one_way_cost,
            )
            summary = summarize_path(pack)
            summary["period_id"] = loaded.get("period_id")
            summary["window_id"] = wid
            shard_summaries.append(summary)
            n_gate_on += int(pack.get("n_gate_on_days") or 0)
            n_bar += int(pack.get("n_bar_dates") or len(pack.get("dates") or []) or 0)
            dlist = list(pack.get("dates") or [])
            nlist = list(pack.get("net_daily") or [])
            if pack.get("status") == "ok" and dlist and nlist:
                if not stitch_dates:
                    stitch_dates = list(dlist)
                    stitch_nets = list(nlist)
                else:
                    stitch_dates.extend(dlist[1:])
                    stitch_nets.extend(nlist[1:])
        occ = (float(n_gate_on) / float(n_bar)) if n_bar else None
        if not stitch_nets:
            gate = evaluate_daily_path_dd_gate(period_net_dd=0.0)
            row = {
                "logic_id": lid,
                "window": wid,
                "daily_path_DD": None,
                "total_ret_net": None,
                "occupancy_frac": occ,
                "dd_duration": None,
                "recovered": None,
                "n_days": None,
                "daily_path_complete": False,
                "survived": False,
                "promote_as_main": False,
                "go": False,
                "incomplete_reason": "no ok daily path stitched",
                "period_net_dd_only_pass_forbidden": True,
                "gate_complete": gate.get("complete"),
            }
        else:
            stitched = stitch_net(stitch_nets, stitch_dates)
            gate = stitched.get("daily_path_dd_gate") or {}
            row = {
                "logic_id": lid,
                "window": wid,
                "daily_path_DD": stitched.get("daily_path_DD"),
                "total_ret_net": stitched.get("total_return_net"),
                "occupancy_frac": occ,
                "dd_duration": stitched.get("dd_duration"),
                "recovered": stitched.get("recovered"),
                "n_days": stitched.get("n_equity_points"),
                "daily_path_complete": bool(gate.get("complete")),
                "survived": False,
                "promote_as_main": False,
                "go": False,
                "period_net_dd_only_pass_forbidden": True,
            }
        row["headline"] = bool(spec.get("headline"))
        row["axis"] = spec.get("axis")
        row["catalog"] = True
        row["n_gate_on_days"] = n_gate_on
        row["n_bar_dates"] = n_bar
        rows.append(row)
        _log(
            f"[catalog] {lid} {wid} complete={row.get('daily_path_complete')} "
            f"DD={row.get('daily_path_DD')} net={row.get('total_ret_net')} occ={occ}"
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--logic-id", action="append", default=[])
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument(
        "--sqlite",
        type=Path,
        default=repo_root() / "data" / "structured" / "ingestion.sqlite",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=repo_root() / "data" / "ops" / "research_eval" / "catalog_table.json",
    )
    args = p.parse_args(argv)

    pins = assert_frozen_pins_untouched()
    if not pins.get("pins_untouched"):
        raise SystemExit("frozen pins drifted")
    wanted = [str(x) for x in args.logic_id] or [
        "overnight_level_cs_tilt",
        "xs_low_vol_mom",
    ]
    specs = []
    for lid in wanted:
        spec = catalog_spec(lid)
        if spec is None:
            raise SystemExit(f"catalog missing logic_id={lid}")
        specs.append(spec)
    codes = list(DEFAULT_EVAL_CODES)[: int(args.max_codes)]
    overnight, curve = _load_funding(args.sqlite)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        rows.extend(
            eval_logic_windows(
                spec,
                codes=codes,
                overnight=overnight,
                curve=curve,
                max_days=int(args.max_days),
                one_way_cost=float(args.one_way_cost),
            )
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dump_json(args.out, rows)
    _log(json.dumps({"n_cells": len(rows), "out": str(args.out), "promote_as_main": False, "go": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
