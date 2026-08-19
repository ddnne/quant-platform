#!/usr/bin/env python3
"""W101 / w0819d — continue-hyps + missing daily_path_DD + pins/master.

Does NOT rerun the W100 peer catalog / hold-mom grid. Cites the existing
peer daily_path_DD table. Adds a SMALL additional failure-constrained hyp
pack (n=3) and evaluates the one W100 period-net survivor that is bars-only
(vol_risk_adjusted_mom) through the daily_path_DD gate.

Sticky stays STABLE_RESEARCH_ONLY. promote_as_main=false · go=false.
3-default pins untouched. Master MISDATE re-probe only (no fake COMPLETE).
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819d_w101_otc5_dd_close"
W100_LOG = ROOT / ".glm-logs" / "w0819c_w100_daily_path_dd_otc4"
CF_WORKER_URL = "https://quant-platform-research-mass-eval.taku-haga.workers.dev"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402

from research.stats_metrics import evaluate_daily_path_dd_gate  # noqa: E402

W100_SURVIVORS = (
    "event_post_disclosure_hold",
    "rate_curve_shape_xs",
    "vol_risk_adjusted_mom",
)
VOL_SPEC: dict[str, Any] = {
    "logic_id": "vol_risk_adjusted_mom",
    "kind": "vol_mom_gate",
    "hold_days": 10,
    "momentum_n": 10,
    "vol_n": 10,
    "vol_threshold": 1.0,
    "signal_sign": 1,
    "catalog": True,
    "why": "W100 period-net survivor; bars-only mom/vol gate — daily_path_DD this wave",
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def evaluate_vol_risk_adjusted_mom_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """sign(mom) only if |mom|/realized_vol >= threshold else flat (catalog)."""
    from features.class_signals import apply_sticky_hold, sign_from_numeric
    from research.class_hyp_eval import momentum_series

    n = int(spec["momentum_n"])
    h = int(spec["hold_days"])
    vn = int(spec.get("vol_n") or n)
    thresh = float(spec.get("vol_threshold") or 1.0)
    sgn = 1 if int(spec.get("signal_sign") or 1) >= 0 else -1
    dates_by_code: dict[str, list[str]] = {}
    close_by: dict[str, dict[str, float]] = {}
    held_by_code_date: dict[str, dict[str, float | None]] = {}
    calendar: set[str] = set()
    n_flat = 0
    n_on = 0
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < max(n, vn) + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        mom_by_d = {d: m for d, m in moms}
        dlist = [d for d, _ in pairs_l]
        closes = [float(c) for _, c in pairs_l]
        rets: list[float | None] = [None]
        for i in range(1, len(closes)):
            if closes[i - 1] == 0:
                rets.append(None)
            else:
                rets.append(closes[i] / closes[i - 1] - 1.0)
        entries: list[float | None] = []
        for i, d in enumerate(dlist):
            mom = mom_by_d.get(d)
            if mom is None or i < vn:
                entries.append(None)
                continue
            window = [r for r in rets[i - vn + 1 : i + 1] if r is not None]
            if len(window) < max(3, vn // 2):
                entries.append(None)
                continue
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            vol = math.sqrt(var) * math.sqrt(vn)
            if vol <= 0 or not math.isfinite(vol):
                entries.append(None)
                continue
            score = abs(float(mom)) / vol
            if score < thresh:
                entries.append(0.0)
                n_flat += 1
            else:
                entries.append(sign_from_numeric(mom))
                n_on += 1
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]) * sgn)
            for i in range(len(dlist))
        }
        dates_by_code[code] = dlist
        for d, c in pairs_l:
            close_by.setdefault(code, {})[d] = float(c)
            calendar.add(d)
    dates = sorted(calendar)
    return w100._held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=close_by,
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra={
            "momentum_n": n,
            "vol_n": vn,
            "vol_threshold": thresh,
            "signal_sign": sgn,
            "kind": spec.get("kind"),
            "n_codes": len(dates_by_code),
            "n_gate_flat": n_flat,
            "n_gate_on": n_on,
            "catalog": True,
            "promote_as_main": False,
            "go": False,
        },
    )


def run_vol_survivor_daily_dd(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    rows: list[dict[str, Any]] = []
    for w in w100.W100_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w101/C] vol_risk_adjusted_mom window {wid}")
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append({"period_id": pid, "status": loaded.get("status")})
                continue
            pack = evaluate_vol_risk_adjusted_mom_daily_mtm(
                loaded["bars"], spec=VOL_SPEC, one_way_cost=float(one_way_cost)
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            shard_summaries.append(summary)
            dlist = list(pack.get("dates") or [])
            nlist = list(pack.get("net_daily") or [])
            glist = list(pack.get("gross_daily") or [])
            if not stitch_dates:
                stitch_dates = list(dlist)
                stitch_net = list(nlist)
                stitch_gross = list(glist)
            else:
                stitch_dates.extend(dlist[1:])
                stitch_net.extend(nlist[1:])
                stitch_gross.extend(glist[1:])
            log(
                f"[w101/C]   {pid}: n={summary.get('n_equity_points')} "
                f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                f"total_net={_fmt(summary.get('total_return_net'))}"
            )
        stitched = w100._stitch_net(stitch_net, stitch_dates)
        row = {
            "logic_id": "vol_risk_adjusted_mom",
            "window": wid,
            "n_days": stitched.get("n_equity_points"),
            "daily_path_DD": stitched.get("daily_path_DD"),
            "dd_duration": stitched.get("dd_duration"),
            "recovery_days": stitched.get("recovery_days"),
            "recovered": stitched.get("recovered"),
            "total_ret_net": stitched.get("total_return_net"),
            "daily_path_complete": (stitched.get("daily_path_dd_gate") or {}).get(
                "complete"
            ),
            "promote_as_main": False,
            "go": False,
            "stance": "RESEARCH_ONLY",
            "data_path": "local_real_mirrors",
            "data_note": w["data_note"],
            "shard_summaries": shard_summaries,
        }
        rows.append(row)
        _dump(out_dir / f"vol_risk_adjusted_mom_{wid}.json", row)
    _dump(out_dir / "vol_risk_adjusted_mom_daily_dd.json", rows)
    return {"table": rows, "logic_id": "vol_risk_adjusted_mom"}


def run_small_hyp_pack(
    *,
    out_dir: Path,
    n_hyps: int,
    provider: str,
    model: str | None,
    seed: int,
    synthetic: bool,
    vol_table: Sequence[Mapping[str, Any]],
    log,
) -> dict[str, Any]:
    from research.llm_hyp_generator import (
        LLM_HYP_VERSION,
        LLM_HYP_WAVE,
        detect_api_keys,
        generate_and_evaluate_hypotheses,
    )
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_RESEARCH,
    )

    keys = detect_api_keys()
    key_presence = {k: bool(v) for k, v in keys.items()}
    _dump(out_dir / "api_keys_present.json", key_presence)
    resolved_provider = provider
    if provider == "auto" and key_presence.get("xai"):
        resolved_provider = "xai"
    log(
        f"[w101/C] small additional pack n={n_hyps} provider={resolved_provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION} "
        f"reduce_weak_template_mapping=True (not a dump)"
    )
    gen_eval = generate_and_evaluate_hypotheses(
        n=int(n_hyps),
        provider=None if resolved_provider == "auto" else resolved_provider,
        model=model,
        worker_url=CF_WORKER_URL,
        evaluate=True,
        synthetic=bool(synthetic),
        map_unknown_to_nearest_catalog=True,
    )
    gen_compact = {
        k: gen_eval[k]
        for k in gen_eval
        if k
        not in {
            "eval_results",
            "eval_screens",
            "proposals_for_eval",
            "accepted_proposals",
            "rejected_proposals",
        }
    }
    _dump(out_dir / "llm_hyp_generation.json", gen_compact)
    _dump(out_dir / "llm_hyp_proposals.json", gen_eval.get("proposals_for_eval") or [])
    _dump(out_dir / "llm_hyp_eval_ranking.json", gen_eval.get("eval_ranking") or [])
    _dump(out_dir / "llm_hyp_eval_screens.json", gen_eval.get("eval_screens") or [])
    _dump(out_dir / "llm_hyp_accepted_proposals.json", gen_eval.get("accepted_proposals") or [])
    _dump(out_dir / "llm_hyp_rejected_proposals.json", gen_eval.get("rejected_proposals") or [])

    n_proposed = int(gen_eval.get("n_proposed") or 0)
    n_accepted = int(gen_eval.get("n_accepted") or 0)
    n_survivors = int(gen_eval.get("n_survivors") or 0)
    theses = list(gen_eval.get("representative_theses") or [])
    n_skipped_weak = int(gen_eval.get("n_skipped_weak_catalog_map") or 0)

    by_logic: dict[str, list[dict[str, Any]]] = {}
    for row in vol_table:
        by_logic.setdefault(str(row.get("logic_id")), []).append(dict(row))

    survivor_daily: list[dict[str, Any]] = []
    for s in gen_eval.get("eval_screens") or []:
        if not isinstance(s, Mapping) or not s.get("survived"):
            continue
        lid = str(s.get("logic_id") or "")
        peer_rows = by_logic.get(lid) or []
        if peer_rows:
            all_complete = all(bool(r.get("daily_path_complete")) for r in peer_rows)
            survivor_daily.append(
                {
                    "logic_id": lid,
                    "survived_period_net_screen": True,
                    "daily_path_source": "w101_vol_or_peer_same_logic",
                    "windows": peer_rows,
                    "daily_path_DD_required": True,
                    "daily_path_complete": all_complete,
                    "promote_as_main": False,
                    "go": False,
                }
            )
        else:
            gate = evaluate_daily_path_dd_gate(period_net_dd=s.get("mean_net"))
            survivor_daily.append(
                {
                    "logic_id": lid,
                    "survived_period_net_screen": True,
                    "daily_path_source": None,
                    "daily_path_DD_required": True,
                    "daily_path_complete": False,
                    "incomplete_reason": (
                        "period-net eval screen only; daily_path_DD unmeasured "
                        "for this mapped logic. Incomplete — not main / not GO."
                    ),
                    "gate": {
                        "complete": gate.get("complete"),
                        "fails": gate.get("fails"),
                        "warnings": gate.get("warnings"),
                        "period_net_dd_only_pass_forbidden": True,
                    },
                    "promote_as_main": False,
                    "go": False,
                }
            )

    summary = {
        "wave": "W101 / w0819d",
        "track": "C_continue_hyps_small_pack",
        "w100_pack_stands": {
            "proof": "docs/proof/w0819c_w100_hyps_20260819.md",
            "n_proposed": 6,
            "n_accepted": 6,
            "n_period_net_survivors": 3,
            "daily_path_DD_required": True,
            "period_net_survivors_daily_complete_before": "0/3",
            "implemented_thesis": "xs_cs_dispersion_gate",
            "fulfills_continue_hyps_baseline": True,
            "note": (
                "W100 pack is the standing continue-hyps baseline. This wave "
                "adds a SMALL additional pack (n=3, not a dump) and runs "
                "vol_risk_adjusted_mom through daily_path_DD."
            ),
        },
        "provider": gen_eval.get("provider"),
        "model": gen_eval.get("model"),
        "llm_hyp_version": LLM_HYP_VERSION,
        "n_requested": int(n_hyps),
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_proposed - n_accepted,
        "n_evaluated": gen_eval.get("n_evaluated"),
        "n_survivors": n_survivors,
        "n_skipped_weak_catalog_map": n_skipped_weak,
        "representative_theses": theses,
        "reduce_weak_template_mapping": True,
        "failure_mode_constraints": [
            "no_sign_flip_single_regime_reliance",
            "no_soft_eq_pressure",
            "no_low_var_t_trust",
            "no_window_only",
            "no_dual_options_level",
            "no_repolish_shape_rate_flow_demoted_fund_slow",
            "no_hold_mom_frac_grid",
            "reduce_map_onto_known_weak_templates",
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var", "daily_path_DD"],
        "daily_path_DD_required": True,
        "survivor_daily_path": survivor_daily,
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "promote_as_main": False,
        "go": False,
        "seed": int(seed),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w101/C] small pack n_proposed={n_proposed} n_accepted={n_accepted} "
        f"n_survivors={n_survivors} model={gen_eval.get('model')}"
    )
    return {"summary": summary, "gen_eval": gen_eval}


def gate_w100_survivors(
    vol_table: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    vol_complete = bool(vol_table) and all(
        bool(r.get("daily_path_complete")) for r in vol_table
    )
    for lid in W100_SURVIVORS:
        if lid == "vol_risk_adjusted_mom":
            out.append(
                {
                    "logic_id": lid,
                    "survived_period_net_screen": True,
                    "daily_path_source": "w101_local_real_mirrors",
                    "daily_path_DD_required": True,
                    "daily_path_complete": vol_complete,
                    "windows": list(vol_table),
                    "promote_as_main": False,
                    "go": False,
                }
            )
            continue
        gate = evaluate_daily_path_dd_gate(period_net_dd=0.0)
        out.append(
            {
                "logic_id": lid,
                "survived_period_net_screen": True,
                "daily_path_source": None,
                "daily_path_DD_required": True,
                "daily_path_complete": False,
                "incomplete_reason": (
                    "extra-dataset logic (event / rate); not bars-MTM on "
                    "local_real_mirrors. Gate fail: daily_path_DD_unmeasured."
                ),
                "gate": {
                    "complete": gate.get("complete"),
                    "fails": gate.get("fails"),
                    "warnings": gate.get("warnings"),
                    "period_net_dd_only_pass_forbidden": True,
                },
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
    p.add_argument("--n-hyps", type=int, default=3)
    p.add_argument("--seed", type=int, default=8908191)
    p.add_argument("--provider", type=str, default="xai")
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-misdate", action="store_true")
    p.add_argument("--skip-projection", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w101_hyps_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = w100._assert_frozen_pins_untouched()
    pins["note"] = "W101 hyps/DD must not mutate 3-default pins"
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w101] pins_untouched={pins['pins_untouched']}")
    log(
        "[w101] sticky=STABLE_RESEARCH_ONLY promote_as_main=false go=false "
        "hold_mom_grid=false full_grid=false GLM implementer only. "
        "Grok did not implement."
    )

    w100_table_path = W100_LOG / "peer_daily_dd_table.json"
    w100_table = []
    if w100_table_path.is_file():
        w100_table = json.loads(w100_table_path.read_text())
    _dump(
        out_dir / "w100_peer_daily_dd_cite.json",
        {
            "source": str(w100_table_path.relative_to(ROOT)),
            "proof": "docs/proof/w0819c_w100_peer_daily_dd_20260819.md",
            "rerun_grid": False,
            "n_rows": len(w100_table),
            "table": w100_table,
            "note": "W100 peer table reused; no catalog / hold-mom grid this wave.",
        },
    )
    log(f"[w101/B] cited W100 peer table n={len(w100_table)} (no rerun)")

    sticky = {
        "logic_id": "xs_rank_ls_sticky",
        "stance": "STABLE_RESEARCH_ONLY",
        "promote_as_main": False,
        "go": False,
        "hold_mom_microgrid": False,
        "w99_w100_daily_path_DD_reused": True,
        "worst_window": "w2017_2019",
        "worst_daily_path_DD": -0.143741,
    }
    _dump(out_dir / "sticky_stance.json", sticky)

    vol_pack = run_vol_survivor_daily_dd(
        out_dir=out_dir,
        max_codes=int(args.max_codes),
        max_days=int(args.max_days),
        one_way_cost=float(args.one_way_cost),
        log=log,
    )
    w100_survivor_gate = gate_w100_survivors(vol_pack.get("table") or [])
    _dump(out_dir / "w100_survivor_daily_path_gate.json", w100_survivor_gate)

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_small_hyp_pack(
            out_dir=out_dir,
            n_hyps=int(args.n_hyps),
            provider=str(args.provider),
            model=args.model,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            vol_table=vol_pack.get("table") or [],
            log=log,
        )
    else:
        log("[w101/C] hyps skipped")

    misdate: dict[str, Any] | None = None
    if not args.skip_misdate:
        misdate = w100.run_misdate_reprobe(out_dir=out_dir, log=log)
        if isinstance(misdate, dict):
            misdate["wave"] = "W101 / w0819d"
            _dump(out_dir / "master_misdate_probe.json", misdate)
    else:
        log("[w101/E] MISDATE skipped")

    projection: dict[str, Any] | None = None
    if not args.skip_projection:
        projection = w100.refresh_projection(out_dir=out_dir, log=log)
    else:
        log("[w101/E] projection skipped")

    pins_after = w100._assert_frozen_pins_untouched()
    pins_after["note"] = "W101 after hyps/DD; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": "W101 / w0819d",
        "tracks": "B_cite_w100_peer_dd + C_hyps + D_sticky + E_master",
        "w100_pack_stands": True,
        "peer_grid_rerun": False,
        "hold_mom_microgrid": False,
        "sticky": sticky,
        "pins_untouched": pins_after.get("pins_untouched"),
        "vol_risk_adjusted_mom_daily": vol_pack.get("table"),
        "w100_survivor_gate": w100_survivor_gate,
        "hyps": (hyp_pack or {}).get("summary") if hyp_pack else None,
        "misdate": {
            k: misdate.get(k)
            for k in (
                "action",
                "sealed_n",
                "before_after",
                "dataset_complete_claimed",
                "floor_raise_to_2008_05",
            )
        }
        if misdate
        else None,
        "projection": {
            "status": (projection or {}).get("status"),
            "returncode": (projection or {}).get("returncode"),
        }
        if projection
        else None,
        "promote_as_main": False,
        "go": False,
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w101_hyps_dd_summary.json", summary)
    log(f"[w101] done wall={summary['wall_sec']}s pins={pins_after.get('pins_untouched')}")
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
