"""Run catalog YAML logics through candidate-grade daily_path.

Default backend is Cloudflare isolate fan-out (``--backend cf``).
``--backend local`` is the serial Python HONEST_3Y fallback.

Does not add a wave script. Does not promote. Scores go to eval_registry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.cf_mass_eval_job import DEFAULT_MAX_CODES
from research.eval_loaders import (
    build_repo_curve_series,
    load_fins_events_from_sqlite,
    load_margin_from_sqlite,
    load_repo_rows_all_tenors_from_sqlite,
    load_topix_close_series_from_sqlite,
    repo_history_plane_status,
)
from research.daily_path_eval import (
    assert_frozen_pins_untouched,
    dump_json,
    load_shard_bars,
    stitch_net,
)
from research.eval_windows import HONEST_3Y_WINDOWS
from research.stats_metrics import evaluate_daily_path_dd_gate
from research.unique_logic import all_unique_logic_specs
from research.unique_logic.catalog import catalog_spec
from research.unique_logic.dispatch import evaluate_logic_daily_mtm


def _log(msg: str) -> None:
    print(msg, flush=True)


def _load_extras(
    sqlite_path: Path, *, codes: Sequence[str]
) -> dict[str, Any]:
    rows = load_repo_rows_all_tenors_from_sqlite(
        sqlite_path, start="2016-01-01", end="2026-12-31"
    )
    curve = build_repo_curve_series(rows)
    overnight = dict(curve.get("short_rates_by_date") or curve.get("rates_by_date") or {})
    events = load_fins_events_from_sqlite(
        sqlite_path, codes=list(codes), start="2016-01-01", end="2026-12-31"
    )
    margin_raw = load_margin_from_sqlite(
        sqlite_path, codes=list(codes), start="2016-01-01", end="2026-12-31"
    )
    margin_by_code: dict[str, dict[str, float]] = {}
    for code, pairs in (margin_raw or {}).items():
        margin_by_code[str(code)] = {
            str(d)[:10]: float(v) for d, v in (pairs or []) if v is not None
        }
    topix_pairs = load_topix_close_series_from_sqlite(
        sqlite_path, start="2016-01-01", end="2026-12-31"
    )
    topix_by_date: dict[str, float] = {}
    for d, v in topix_pairs or []:
        try:
            topix_by_date[str(d)[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    return {
        "overnight": overnight,
        "curve": curve,
        "events": events,
        "margin_by_code": margin_by_code,
        "topix_by_date": topix_by_date,
        "n_overnight": len(overnight),
        "n_events": sum(len(v) for v in events.values()) if events else 0,
        "n_margin_codes": len(margin_by_code),
        "n_topix": len(topix_by_date),
        "repo_history_plane": repo_history_plane_status(sqlite_path),
    }


def _eval_shard(
    *,
    spec: Mapping[str, Any],
    loaded: Mapping[str, Any],
    extras: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    return evaluate_logic_daily_mtm(
        spec,
        bars=loaded.get("bars") or {},
        overnight=extras.get("overnight") or {},
        curve=extras.get("curve") or {},
        events=extras.get("events") or {},
        margin_by_code=extras.get("margin_by_code") or {},
        topix_by_date=extras.get("topix_by_date") or {},
        one_way_cost=one_way_cost,
        period_start=loaded.get("period_start"),
        period_end=loaded.get("period_end"),
        adv_by_code=loaded.get("adv_by_code") or extras.get("adv_by_code"),
    )


def eval_logic_windows(
    spec: Mapping[str, Any],
    *,
    codes: Sequence[str],
    extras: Mapping[str, Any],
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
        for shard in window["shards"]:
            loaded = load_shard_bars(shard, codes=codes, max_days=max_days)
            if loaded.get("status") != "ok":
                continue
            pack = _eval_shard(
                spec=spec,
                loaded=loaded,
                extras=extras,
                one_way_cost=one_way_cost,
            )
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
    p.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every unique_logic spec from catalog YAML.",
    )
    p.add_argument(
        "--backend",
        choices=("cf", "local"),
        default="cf",
        help=(
            "cf (default): Cloudflare isolate fan-out POST /v1/daily-path. "
            "local: serial Python daily_path_eval (fallback; HONEST_3Y stitch)."
        ),
    )
    p.add_argument(
        "--job-id",
        default=None,
        help="Optional eval-registry job id for --backend cf.",
    )
    p.add_argument(
        "--panels-prefix",
        default=None,
        help="Reuse staged R2 panels prefix (skip serial stage).",
    )
    p.add_argument(
        "--track",
        choices=("mid_n_explore", "liq_large"),
        default=None,
        help="Eval track. mid_n_explore=80 ADV; liq_large=100 ADV. Never head-N.",
    )
    p.add_argument("--max-codes", type=int, default=DEFAULT_MAX_CODES)
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
    if args.all or not args.logic_id:
        specs = list(all_unique_logic_specs())
    else:
        specs = []
        by_id = {str(s.get("logic_id")): s for s in all_unique_logic_specs()}
        for lid in args.logic_id:
            spec = by_id.get(str(lid)) or catalog_spec(str(lid))
            if spec is None:
                raise SystemExit(f"unknown logic_id={lid}")
            specs.append(spec)

    if args.backend == "cf":
        from research.cf_daily_path_job import run_cf_daily_path_fanout

        ids = [str(s["logic_id"]) for s in specs]
        from research.eval_tracks import eval_track

        max_codes = int(args.max_codes)
        track = args.track
        if track:
            tspec = eval_track(track)
            if args.max_codes == DEFAULT_MAX_CODES:
                max_codes = int(tspec["max_codes"])
        pack = run_cf_daily_path_fanout(
            job_id=args.job_id,
            logic_ids=ids,
            max_codes=max_codes,
            max_days=int(args.max_days),
            one_way_cost=float(args.one_way_cost),
            panels_prefix=args.panels_prefix,
            track=track,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        dump_json(args.out, pack)
        _log(
            json.dumps(
                {
                    "backend": "cf",
                    "job_id": pack.get("job_id"),
                    "n_logics": pack.get("n_logics"),
                    "n_cells": pack.get("n_cells"),
                    "stage_sec": pack.get("stage_sec"),
                    "fanout_sec": pack.get("fanout_sec"),
                    "longest_isolate_sec": pack.get("longest_isolate_sec"),
                    "out": str(args.out),
                    "promote_as_main": False,
                    "go": False,
                    "note": (
                        "CF isolate fan-out is the --all default. "
                        "Use --backend local for Python HONEST_3Y serial fallback."
                    ),
                }
            )
        )
        return 0

    from research.eval_universe import select_eval_universe

    codes = select_eval_universe(max_codes=int(args.max_codes))
    extras = _load_extras(args.sqlite, codes=codes)
    _log(
        json.dumps(
            {
                "backend": "local",
                "n_logics": len(specs),
                "n_overnight": extras.get("n_overnight"),
                "n_events": extras.get("n_events"),
                "n_margin_codes": extras.get("n_margin_codes"),
                "n_topix": extras.get("n_topix"),
                "repo_history_plane": extras.get("repo_history_plane"),
                "note": "serial Python fallback; CF is the default --all path",
            }
        )
    )
    rows: list[dict[str, Any]] = []
    for spec in specs:
        rows.extend(
            eval_logic_windows(
                spec,
                codes=codes,
                extras=extras,
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
