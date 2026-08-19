#!/usr/bin/env python3
"""W105 / w0820b Track D — research-family registration (NOT promotion).

Register W104 unique_logic (and this-wave new unique_logic if present) as a
research family so factory period-net is not stuck at 0 from unknown family.

registration = recognition, not pass / not promotion.
MUST NOT: auto research_candidate, Mass/READY/GO, main.

Also snapshots Track E (no extra gate grid; sticky/gate stance; no invent)
and Track F (pins frozen, MISDATE wait, projection FRESH).

Examples
--------
    uv run python scripts/run_w105_research_family_register.py \\
        --out-dir .glm-logs/w0820b_w105_otc9_family_hyps/
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

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

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w104_new_hyps_daily_dd as w104  # noqa: E402

WAVE = "W105 / w0820b"
GATE_LOGIC = "xs_cs_dispersion_gate"
STICKY_LOGIC = "xs_rank_ls_sticky"
GATE_STANCE = "RESEARCH_ONLY"
STICKY_STANCE = "STABLE_RESEARCH_ONLY"


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def discover_this_wave_unique_logic() -> list[dict[str, Any]]:
    """W105 Track B new unique_logic if it landed; empty otherwise."""
    extra: list[dict[str, Any]] = []
    for name in (
        "run_w105_new_hyps_daily_dd.py",
        "run_w105_hyps_daily_dd.py",
    ):
        path = ROOT / "scripts" / name
        if not path.is_file():
            continue
        # Import only if present this wave.
        mod_name = path.stem
        if str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
        mod = __import__(mod_name)
        for spec in getattr(mod, "NEW_UNIQUE_LOGIC", ()) or ():
            if isinstance(spec, Mapping) and spec.get("logic_id"):
                extra.append(dict(spec))
    return extra


def run_register(*, out_dir: Path, seed: int, log) -> dict[str, Any]:
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        LOGIC_TEMPLATES,
        MASS_RESEARCH,
        MassFactoryConfig,
        RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE,
        RESEARCH_FAMILY_REGISTER_ID,
        RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS,
        RESEARCH_UNIQUE_FAMILY_IDS,
        RESEARCH_UNIQUE_LOGIC_IDS,
        propose_profit_hypotheses,
        research_family_register_document,
    )

    doc = research_family_register_document()
    _dump(out_dir / "research_family_register.json", doc)
    this_wave = discover_this_wave_unique_logic()
    _dump(out_dir / "research_family_this_wave_new.json", this_wave)

    proposals = w104.proposals_for_factory()
    for spec in this_wave:
        lid = str(spec.get("logic_id") or "")
        if not lid:
            continue
        proposals.append(
            {
                "logic_id": lid,
                "family_id": spec.get("family_id"),
                "thesis": spec.get("thesis"),
                "signal_definition": spec.get("signal_definition"),
                "position_rule": spec.get("position_rule"),
                "datasets": list(spec.get("datasets") or spec.get("datasets_used") or []),
                "datasets_used": list(
                    spec.get("datasets_used") or spec.get("datasets") or []
                ),
                "params": dict(spec.get("params") or {}),
                "new_unique_logic": True,
                "catalog": False,
                "eval_mapped_to_catalog": False,
                "weak_template_mapping": "OFF",
            }
        )

    cfg = MassFactoryConfig(seed=int(seed), n=max(20, len(proposals) + 5))
    log(
        f"[w105/D] register_id={RESEARCH_FAMILY_REGISTER_ID} "
        f"n_proposals={len(proposals)} this_wave_new={len(this_wave)} "
        "registration=recognition not_pass not_promotion "
        "auto_research_candidate=false"
    )
    eval_out = propose_profit_hypotheses(
        proposals,
        evaluate=True,
        synthetic=True,
        config=cfg,
    )
    screens = list(eval_out.get("eval_screens") or [])
    results = list(eval_out.get("eval_results") or [])
    n_unknown_strategies = 0
    n_unknown_period_rows = 0
    n_ok_periods = 0
    compact_screens = []
    for s in screens:
        reasons = [str(x) for x in (s.get("reject_reasons") or [])]
        unknown = any("unknown_family" in r for r in reasons)
        if unknown:
            n_unknown_strategies += 1
        compact_screens.append(
            {
                "logic_id": s.get("logic_id"),
                "family_id": s.get("family_id"),
                "survived": s.get("survived"),
                "reject_reasons": reasons,
                "mean_net": s.get("mean_net"),
                "n_periods_ok": s.get("n_periods_ok"),
                "unknown_family": unknown,
                "promote_as_main": False,
                "go": False,
                "research_candidate": False,
                "registration": "recognition",
                "survived_period_net_is_not_a_pass": True,
            }
        )
    for r in results:
        n_ok_periods += int(r.get("n_periods_ok") or 0)
        for prow in r.get("period_rows") or []:
            skip = str(prow.get("skip_reason") or "")
            if skip.startswith("unknown_family:"):
                n_unknown_period_rows += 1

    n_unknown = n_unknown_strategies
    n_survivors = sum(1 for s in screens if s.get("survived"))
    summary = {
        "wave": WAVE,
        "track": "D_research_family_register",
        "register_id": RESEARCH_FAMILY_REGISTER_ID,
        "registration": "recognition",
        "registration_is_not_a_pass": RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS,
        "registration_is_not_promotion": True,
        "auto_research_candidate": RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE,
        "generation_enabled": False,
        "promote_as_main": False,
        "go": False,
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "n_registered_logic_ids": len(RESEARCH_UNIQUE_LOGIC_IDS),
        "registered_logic_ids": sorted(RESEARCH_UNIQUE_LOGIC_IDS),
        "registered_family_ids": sorted(RESEARCH_UNIQUE_FAMILY_IDS),
        "this_wave_new_unique_logic": [s.get("logic_id") for s in this_wave],
        "n_this_wave_new": len(this_wave),
        "n_proposed": eval_out.get("n_proposals"),
        "n_accepted": eval_out.get("n_accepted"),
        "n_rejected_generation": eval_out.get("n_rejected"),
        "n_evaluated_factory_synthetic": (eval_out.get("eval") or {}).get(
            "n_strategies_evaluated"
        ),
        "n_survivors_period_net": n_survivors,
        "n_unknown_family": n_unknown,
        "n_unknown_family_period_rows": n_unknown_period_rows,
        "n_periods_ok_total": n_ok_periods,
        "factory_period_net_not_stuck_unknown": n_unknown == 0 and n_ok_periods > 0,
        "period_net_is_not_a_pass": True,
        "period_net_dd_only_pass_forbidden": True,
        "catalog_in_LOGIC_TEMPLATES": {
            lid: lid in LOGIC_TEMPLATES for lid in sorted(RESEARCH_UNIQUE_LOGIC_IDS)
        },
        "generation_enabled_by_logic": {
            lid: bool(LOGIC_TEMPLATES[lid].generation_enabled)
            for lid in sorted(RESEARCH_UNIQUE_LOGIC_IDS)
            if lid in LOGIC_TEMPLATES
        },
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "screens": compact_screens,
        "must_not": list(doc.get("must_not") or []),
        "note": (
            "registration = recognition, not pass / not promotion. "
            "Factory synthetic period-net after recognition is still not a pass. "
            "daily_path_DD of the min-impl remains the required eval. "
            "Grok did not implement."
        ),
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "git_sha": _git_sha(),
    }
    _dump(out_dir / "research_family_register_eval.json", compact_screens)
    _dump(out_dir / "research_family_register_summary.json", summary)
    log(
        f"[w105/D] accepted={summary['n_accepted']} "
        f"unknown_family={n_unknown} n_periods_ok={n_ok_periods} "
        f"survivors_period_net={n_survivors} (NOT a pass) "
        f"auto_research_candidate={RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE}"
    )
    return summary


def confirm_e_no_extra_grids(log) -> dict[str, Any]:
    import run_w102_dispersion_quality as w102
    import run_w103_dispersion_deepen as w103d

    pack = {
        "wave": WAVE,
        "track": "E_gate_sticky_repo_confirm",
        "gate_logic": GATE_LOGIC,
        "gate_stance": GATE_STANCE,
        "sticky_logic": STICKY_LOGIC,
        "sticky_stance": STICKY_STANCE,
        "promote_as_main": False,
        "go": False,
        "extra_threshold_grid_this_wave": False,
        "extra_gate_grid_this_wave": False,
        "extra_dispersion_gate_grid": False,
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "repo_invent": False,
        "repo_ffill": False,
        "w103_coarse_thresh_cited_not_rerun": list(w103d.THRESH_MULT_POINTS),
        "gate_spec_hold_days": w102.GATE_SPEC.get("hold_days"),
        "gate_spec_momentum_n": w102.GATE_SPEC.get("momentum_n"),
        "sticky_spec_hold_days": w102.STICKY_SPEC.get("hold_days"),
        "sticky_spec_momentum_n": w102.STICKY_SPEC.get("momentum_n"),
        "note": (
            "W105 E: no extra dispersion_gate grid. sticky stays "
            "STABLE_RESEARCH_ONLY. gate stays RESEARCH_ONLY. "
            "repo no invent / no ffill."
        ),
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
    }
    log(
        f"[w105/E] gate={GATE_STANCE} sticky={STICKY_STANCE} "
        "extra_dispersion_gate_grid=false repo_invent=false repo_ffill=false"
    )
    return pack


def confirm_f_pins_misdate_projection(log) -> dict[str, Any]:
    pins = w99._assert_frozen_pins_untouched()
    pins["note"] = "W105 F: 3-default pins must remain untouched"
    meta_path = ROOT / "data" / "ops" / "projection_meta.json"
    proj: dict[str, Any] = {}
    if meta_path.is_file():
        proj = json.loads(meta_path.read_text(encoding="utf-8"))
    sqlite_path = ROOT / "data" / "structured" / "ingestion.sqlite"
    misdate: dict[str, Any] = {
        "dataset": "equities_master",
        "policy": "KEEP PARTIAL until vendor Date in-window",
        "floor_raise": False,
    }
    if sqlite_path.is_file():
        con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        try:
            cur = con.execute(
                "SELECT status, COUNT(*) FROM coverage_segments "
                "WHERE dataset='equities_master' GROUP BY status"
            )
            counts = {str(r[0]): int(r[1]) for r in cur.fetchall()}
            misdate["counts"] = counts
            misdate["complete"] = int(counts.get("COMPLETE") or 0)
            misdate["partial"] = int(counts.get("PARTIAL") or 0)
        except sqlite3.Error as exc:
            misdate["error"] = str(exc)
        finally:
            con.close()
    pack = {
        "wave": WAVE,
        "track": "F_pins_misdate_projection",
        "pins_untouched": pins.get("pins_untouched"),
        "frozen_defaults_retuned": False,
        "pins": pins,
        "misdate": misdate,
        "projection_status": proj.get("projection_status") or proj.get("status"),
        "projection_generation": proj.get("active_generation"),
        "promote_as_main": False,
        "go": False,
        "mass": "NO-GO",
        "ready": False,
        "live": False,
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
    }
    log(
        f"[w105/F] pins_untouched={pins.get('pins_untouched')} "
        f"projection={pack['projection_status']} "
        f"misdate_complete={misdate.get('complete')} "
        f"misdate_partial={misdate.get('partial')} "
        "go=false mass=NO-GO"
    )
    return pack


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--seed", type=int, default=8908195)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w105_research_family_register.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    log(
        "[w105/D] research-family registration = recognition, not pass / "
        "not promotion. GLM implementer only. Grok did not implement."
    )
    d_sum = run_register(out_dir=out_dir, seed=int(args.seed), log=log)
    e_sum = confirm_e_no_extra_grids(log)
    _dump(out_dir / "e_gate_sticky_confirm.json", e_sum)
    f_sum = confirm_f_pins_misdate_projection(log)
    _dump(out_dir / "f_pins_misdate_projection.json", f_sum)
    wrap = {
        "wave": WAVE,
        "tracks": ["D", "E", "F"],
        "D": {
            "register_id": d_sum.get("register_id"),
            "registration": "recognition",
            "registration_is_not_a_pass": True,
            "factory_period_net_not_stuck_unknown": d_sum.get(
                "factory_period_net_not_stuck_unknown"
            ),
            "n_unknown_family": d_sum.get("n_unknown_family"),
            "n_periods_ok_total": d_sum.get("n_periods_ok_total"),
            "n_survivors_period_net": d_sum.get("n_survivors_period_net"),
            "auto_research_candidate": False,
            "promote_as_main": False,
            "go": False,
        },
        "E": e_sum,
        "F": {
            "pins_untouched": f_sum.get("pins_untouched"),
            "projection_status": f_sum.get("projection_status"),
            "projection_generation": f_sum.get("projection_generation"),
            "misdate_complete": (f_sum.get("misdate") or {}).get("complete"),
            "misdate_partial": (f_sum.get("misdate") or {}).get("partial"),
            "go": False,
        },
        "wall_sec": round(time.time() - t0, 1),
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "git_sha": _git_sha(),
    }
    _dump(out_dir / "w105_def_summary.json", wrap)
    log(f"[w105/DEF] done wall={wrap['wall_sec']}s")
    ok = bool(d_sum.get("factory_period_net_not_stuck_unknown")) and bool(
        f_sum.get("pins_untouched")
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
