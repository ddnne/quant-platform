#!/usr/bin/env python3
"""W97 / w0818g tracks C+D — deep multi-year survivor eval + constrained hyps.

C. Deep multi-year eval of W96 5 survivors
  logics:
    mf_value_mom_rate · rate_abs_level_xs · event_post_disclosure_hold
    flow_margin_short_hard · xs_rank_ls_sticky
  windows: 2017–19 / 2020–22 / 2023–25 (honest shards)
  gates: cost + PIT + sign + low-var
  CF ``r2_panels`` preferred
  Research-only if unstable — do **not** GO / main-promote

D. Continue constrained hyp gen
  ``llm_hyp_generator`` v1.1+ constraints · xAI preferred · propose→eval
  modest N · do not resurrect demoted/weak as main · no grid

Freezes held: Mass=NO-GO · READY=false · ops GO=false · continuous paper
UNARMED · **3-default pins untouched** · no GO/live.

Examples
--------
    uv run python scripts/run_w97_survivor_deep_eval.py \\
        --out-dir .glm-logs/w0818g_w97_otc_master_hyps/

    uv run python scripts/run_w97_survivor_deep_eval.py --skip-hyps --skip-local
"""

from __future__ import annotations

import argparse
import json
import math
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0818g_w97_otc_master_hyps"
CF_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)

# Honest shards (contiguous 3y bars mirrors absent) — same as W93–W96.
W97_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "w2017_2019",
        "label": "2017–2019",
        "data_note": "2018 mirror absent; y2017_q4 + y2019_full",
        "shards": (
            {
                "period_id": "y2017_q4",
                "year": 2017,
                "period_start": "2017-09-01",
                "period_end": "2017-12-29",
                "window_kind": "q4",
            },
            {
                "period_id": "y2019_full",
                "year": 2019,
                "period_start": "2019-01-04",
                "period_end": "2019-10-18",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2020_2022",
        "label": "2020–2022",
        "data_note": "2020/2022 mirrors absent; y2021_full only",
        "shards": (
            {
                "period_id": "y2021_full",
                "year": 2021,
                "period_start": "2021-01-04",
                "period_end": "2021-10-15",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2023_2025",
        "label": "2023–2025",
        "data_note": "2024 mirror absent; y2023_full + y2025_q4",
        "shards": (
            {
                "period_id": "y2023_full",
                "year": 2023,
                "period_start": "2023-01-04",
                "period_end": "2023-10-13",
                "window_kind": "full_prefer",
            },
            {
                "period_id": "y2025_q4",
                "year": 2025,
                "period_start": "2025-09-01",
                "period_end": "2025-12-29",
                "window_kind": "q4",
            },
        ),
    },
)

# W96 / catalog top survivors for deep multi-year (Track C).
SURVIVOR_LOGIC_IDS: tuple[str, ...] = (
    "mf_value_mom_rate",
    "rate_abs_level_xs",
    "event_post_disclosure_hold",
    "flow_margin_short_hard",
    "xs_rank_ls_sticky",
)

# Prior-wave notes (informational; do not auto-promote).
KNOWN_WEAK_THESIS: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",  # W95 rate weak_thesis / sign flips
        "flow_margin_short_hard",  # W95 flow weak_thesis family
    }
)
KNOWN_LOW_VAR_RISK: frozenset[str] = frozenset(
    {
        "mf_value_mom_rate",  # W96 mapped screen: inflated_t_low_variance
    }
)

# Snapshot of frozen pins — assert untouched (never mutate).
FROZEN_PIN_SNAPSHOT: tuple[tuple[str, int, int | None, str], ...] = (
    ("cross_section_hold_10", 10, 5, "KEEP"),
    ("cross_section_hold_10_mom3", 10, 3, "PROMOTE"),
    ("fundamentals_hold_10", 10, 10, "KEEP"),
)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def _scalar_t(t: Any) -> float | None:
    if t is None:
        return None
    if isinstance(t, Mapping):
        return _scalar_f(t.get("t_stat"))
    return _scalar_f(t)


def _all_shards() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in W97_WINDOWS:
        for s in w["shards"]:
            out.append(dict(s))
    return out


def _assert_frozen_pins_untouched() -> dict[str, Any]:
    """Verify FROZEN_DEFAULT_PATH matches the 3-default pin snapshot."""
    from research.mass_strategy_factory import FROZEN_DEFAULT_PATH

    by_id = {r["representative_id"]: r for r in FROZEN_DEFAULT_PATH}
    ok = True
    details: list[dict[str, Any]] = []
    for rid, hold, mom, stance in FROZEN_PIN_SNAPSHOT:
        r = by_id.get(rid)
        if r is None:
            ok = False
            details.append({"representative_id": rid, "status": "MISSING"})
            continue
        match = (
            int(r.get("hold_days") or -1) == hold
            and int(r.get("momentum_n") or -1) == int(mom or -1)
            and str(r.get("stance") or "") == stance
        )
        if not match:
            ok = False
        details.append(
            {
                "representative_id": rid,
                "expected": {
                    "hold_days": hold,
                    "momentum_n": mom,
                    "stance": stance,
                },
                "actual": {
                    "hold_days": r.get("hold_days"),
                    "momentum_n": r.get("momentum_n"),
                    "stance": r.get("stance"),
                    "mode": r.get("mode"),
                },
                "match": match,
            }
        )
    pack = {
        "pins_untouched": ok,
        "n_pins": len(FROZEN_DEFAULT_PATH),
        "details": details,
        "frozen_defaults_retuned": False,
        "note": "W97 must not mutate 3-default pins",
    }
    if not ok:
        raise RuntimeError(
            "FROZEN_DEFAULT_PATH drift detected — abort before W97 C+D: "
            + json.dumps(details, default=str)
        )
    return pack


def _reaggregate_window(
    result: Mapping[str, Any],
    *,
    keep_period_ids: set[str],
    near_zero_abs: float,
    min_activation: float,
) -> dict[str, Any]:
    from research.mass_strategy_factory import screen_strategy_result
    from research.sign_selection import (
        SIGN_INVERTED,
        SIGN_ORIGINAL,
        choose_sign,
        evaluate_sign_both_sides,
    )
    from research.stats_metrics import period_stats_report, sample_mean, t_stat_vs_zero

    period_rows = [
        dict(r)
        for r in (result.get("period_rows") or [])
        if str(r.get("period_id") or "") in keep_period_ids
    ]
    ok_rows = [r for r in period_rows if r.get("status") == "ok"]
    grosses = [r.get("gross_signed_mean_active") for r in ok_rows]
    nets = [r.get("net_one_way_mean_active") for r in ok_rows]
    costs = [r.get("amortized_one_way_cost") for r in ok_rows]
    pids = [str(r.get("period_id")) for r in ok_rows]
    hold = None
    for r in ok_rows:
        if r.get("hold_days") is not None:
            hold = int(r["hold_days"])
            break
        if r.get("post_hold_days") is not None:
            hold = int(r["post_hold_days"])
            break
    act_rates: list[float] = []
    for r in ok_rows:
        ar = r.get("activation_rate")
        if ar is None:
            occ = r.get("occurrence") or {}
            ar = occ.get("activation_rate")
        if ar is not None:
            try:
                act_rates.append(float(ar))
            except (TypeError, ValueError):
                pass
    mean_activation = sample_mean(act_rates)
    both = evaluate_sign_both_sides(
        period_grosses=grosses,
        period_nets=nets,
        amortized_costs=costs if any(c is not None for c in costs) else None,
        period_ids=pids,
        hold_days=hold,
        near_zero_abs=near_zero_abs,
    )
    choice = choose_sign(both, near_zero_abs=near_zero_abs)
    chosen_sign = choice.get("chosen_sign")
    side_key = (
        "original"
        if chosen_sign == SIGN_ORIGINAL
        else ("inverted" if chosen_sign == SIGN_INVERTED else "original")
    )
    side = dict(both.get(side_key) or {})
    side_nets = list(side.get("nets") or side.get("period_nets") or nets)
    stats = period_stats_report(side_nets)
    mean_net = side.get("mean_net")
    if mean_net is None:
        mean_net = sample_mean(nets)
    mean_gross = sample_mean(grosses)
    t_pack = t_stat_vs_zero(side_nets)
    t_stat = t_pack.get("t_stat")
    sharpe = stats.get("sharpe") if isinstance(stats, Mapping) else None
    if t_pack.get("reason") == "low_variance_artifact":
        sharpe = None
        t_stat = None
    pack = {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id"),
        "params": result.get("params"),
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "t_stat_reason": t_pack.get("reason"),
        "raw_t_stat": t_pack.get("raw_t_stat"),
        "low_variance_artifact": t_pack.get("reason") == "low_variance_artifact",
        "sharpe_period": sharpe,
        "mean_activation": mean_activation,
        "sign_selection": {
            "chosen_sign": chosen_sign,
            "decision": choice.get("decision"),
            "reason": choice.get("reason"),
            "verdict": choice.get("verdict"),
        },
        "chosen_sign": chosen_sign,
        "status": "evaluated" if ok_rows else "no_ok_periods",
    }
    scr = screen_strategy_result(
        pack, near_zero_abs=near_zero_abs, min_activation=min_activation
    )
    pack["screen"] = scr
    pack["survived"] = bool(scr.get("survived"))
    pack["reject_reasons"] = list(scr.get("reject_reasons") or [])
    return pack


def _row_from_pack(
    pack: Mapping[str, Any], *, window_id: str, source: str
) -> dict[str, Any]:
    lid = str(pack.get("logic_id") or "")
    return {
        "source": source,
        "window": window_id,
        "logic_id": lid,
        "family_id": pack.get("family_id"),
        "mean_net": _scalar_f(pack.get("mean_net")),
        "t": _scalar_t(pack.get("t_stat")),
        "t_stat_reason": pack.get("t_stat_reason"),
        "raw_t_stat": pack.get("raw_t_stat"),
        "low_variance_artifact": bool(pack.get("low_variance_artifact")),
        "act": _scalar_f(pack.get("mean_activation")),
        "sharpe": _scalar_f(pack.get("sharpe_period")),
        "sign": pack.get("chosen_sign"),
        "survived": bool(pack.get("survived")),
        "reject_reasons": list(pack.get("reject_reasons") or []),
        "n_periods_ok": pack.get("n_periods_ok"),
        "n_periods_total": pack.get("n_periods_total"),
        "known_weak_thesis": lid in KNOWN_WEAK_THESIS,
        "known_low_var_risk": lid in KNOWN_LOW_VAR_RISK,
    }


def _markdown_window_table(rows: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| window | logic | mean_net | t | act | sharpe | sign | surv | "
        "low_var | rejects |"
    )
    sep = "|---|---|---:|---:|---:|---:|---|:---:|:---:|---|"
    lines = [header, sep]
    for r in rows:
        mn, t, act, sh = (
            r.get("mean_net"),
            r.get("t"),
            r.get("act"),
            r.get("sharpe"),
        )
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sh_s = f"{sh:.3f}" if isinstance(sh, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        rejects = ",".join(str(x) for x in (r.get("reject_reasons") or [])[:3]) or "—"
        lines.append(
            f"| {r.get('window')} | `{r.get('logic_id')}` | {mn_s} | {t_s} | "
            f"{act_s} | {sh_s} | {sign_s} | {r.get('survived')} | "
            f"{r.get('low_variance_artifact')} | {rejects} |"
        )
    return "\n".join(lines)


def _classify_logic(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Cross-window stability classification — never GO/main-promote."""
    if not rows:
        return {
            "stance": "NO_DATA",
            "promote_as_main": False,
            "go_eligible": False,
            "research_only": True,
            "reason": "no_window_rows",
        }
    lid = str(rows[0].get("logic_id") or "")
    n_win = len(rows)
    n_surv = sum(1 for r in rows if r.get("survived"))
    signs = [r.get("sign") for r in rows if r.get("sign") in (-1, 1, "-1", "1")]
    signs_i = [int(s) for s in signs]
    sign_flip = len(set(signs_i)) > 1 if len(signs_i) >= 2 else False
    any_low_var = any(bool(r.get("low_variance_artifact")) for r in rows)
    nets = [_scalar_f(r.get("mean_net")) for r in rows]
    nets_ok = [n for n in nets if n is not None]
    mean_net_avg = (sum(nets_ok) / len(nets_ok)) if nets_ok else None
    ts = [_scalar_t(r.get("t")) for r in rows]
    ts_ok = [t for t in ts if t is not None]
    t_avg = (sum(ts_ok) / len(ts_ok)) if ts_ok else None

    reasons: list[str] = []
    if lid in KNOWN_WEAK_THESIS:
        reasons.append("prior_weak_thesis_family")
    if lid in KNOWN_LOW_VAR_RISK:
        reasons.append("prior_low_var_risk")
    if any_low_var:
        reasons.append("low_variance_artifact_in_window")
    if sign_flip:
        reasons.append("sign_flip_across_windows")
    if n_surv == 0:
        reasons.append("zero_window_survivals")
    elif n_surv < n_win:
        reasons.append("partial_window_survival")

    # Unstable / weak → research-only; never main / GO.
    unstable = bool(
        any_low_var
        or sign_flip
        or n_surv < max(1, n_win - 0)  # require all windows for "stable"
        or (lid in KNOWN_WEAK_THESIS)
        or (lid in KNOWN_LOW_VAR_RISK and any_low_var)
    )
    # Even "stable" survivors stay research-only this wave (no main promote).
    if n_surv == 0 or any_low_var:
        stance = "WEAK_OR_UNSTABLE_RESEARCH_ONLY"
    elif unstable:
        stance = "UNSTABLE_RESEARCH_ONLY"
    else:
        stance = "STABLE_RESEARCH_ONLY"

    return {
        "logic_id": lid,
        "stance": stance,
        "n_windows": n_win,
        "n_survived_windows": n_surv,
        "sign_flip": sign_flip,
        "signs": signs_i,
        "any_low_var": any_low_var,
        "mean_net_avg": mean_net_avg,
        "t_avg": t_avg,
        "known_weak_thesis": lid in KNOWN_WEAK_THESIS,
        "known_low_var_risk": lid in KNOWN_LOW_VAR_RISK,
        "reasons": reasons,
        "promote_as_main": False,
        "go_eligible": False,
        "research_only": True,
        "note": (
            "W97 deep multi-year: research-only if unstable; "
            "never GO/main-promote factory survivors"
        ),
    }


def run_track_c_local(
    *,
    out_dir: Path,
    seed: int,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, Any]:
    from research.mass_strategy_factory import (
        FROZEN_DEFAULT_PATH,
        LOGIC_TEMPLATES,
        MassFactoryConfig,
        evaluate_one_strategy,
        load_batch_data_context,
        screen_strategy_result,
    )

    strategies: list[dict[str, Any]] = []
    for lid in SURVIVOR_LOGIC_IDS:
        tpl = LOGIC_TEMPLATES[lid]
        strategies.append(
            {
                "strategy_id": f"msf_w97_deep_{lid}",
                "logic_id": lid,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "thesis": tpl.thesis,
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "variant": "deep_multi_year",
            }
        )

    cfg = MassFactoryConfig(
        seed=int(seed),
        n=len(strategies),
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    rows_flat: list[dict[str, Any]] = []
    for w in W97_WINDOWS:
        wid = str(w["window_id"])
        periods = [dict(s) for s in w["shards"]]
        log(f"[w97/C] local deep {wid} n={len(strategies)}")
        ctx = load_batch_data_context(cfg, periods=periods, synthetic=False)
        for strat in strategies:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["params"] = dict(strat.get("params") or {})
            res["family_id"] = strat.get("family_id")
            res["t_stat"] = _scalar_t(res.get("t_stat"))
            scr = screen_strategy_result(
                res,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["screen"] = scr
            res["survived"] = bool(scr.get("survived"))
            res["reject_reasons"] = list(scr.get("reject_reasons") or [])
            rows_flat.append(_row_from_pack(res, window_id=wid, source="local"))

    by_logic: dict[str, list[dict[str, Any]]] = {lid: [] for lid in SURVIVOR_LOGIC_IDS}
    for r in rows_flat:
        by_logic.setdefault(str(r["logic_id"]), []).append(r)
    classifications = [_classify_logic(by_logic[lid]) for lid in SURVIVOR_LOGIC_IDS]

    pack = {
        "wave": "W97 / w0818g",
        "track": "C_survivor_deep_eval_local",
        "logics": list(SURVIVOR_LOGIC_IDS),
        "gates": ["cost", "PIT", "sign", "low_var"],
        "rows_flat": rows_flat,
        "classifications": classifications,
        "n_survivors_window_rows": sum(1 for r in rows_flat if r.get("survived")),
        "promote_as_main_candidate": False,
        "go_eligible": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "markdown_table": _markdown_window_table(rows_flat),
    }
    _dump(out_dir / "survivor_deep_local.json", pack)
    (out_dir / "survivor_deep_local_table.md").write_text(
        "# W97 Track C — survivor deep eval (local)\n\n"
        + pack["markdown_table"]
        + "\n",
        encoding="utf-8",
    )
    return pack


def run_track_c_cf(
    *,
    out_dir: Path,
    seed: int,
    max_codes: int,
    max_days: int,
    mode: str,
    worker_url: str,
    skip_deploy: bool,
    log,
) -> dict[str, Any]:
    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.mass_strategy_factory import FROZEN_DEFAULT_PATH, MassFactoryConfig

    status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status_survivor_deep.json", status)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"w97-survivors-{ts}"
    shards = _all_shards()
    log(
        f"[w97/C] CF deep job_id={job_id} mode={mode} "
        f"n_logics={len(SURVIVOR_LOGIC_IDS)} n_shards={len(shards)} "
        f"cf={CF_MASS_EVAL_VERSION}"
    )
    try:
        cf_pack = run_cf_mass_eval_job(
            job_id=job_id,
            logic_ids=list(SURVIVOR_LOGIC_IDS),
            extra_logics=[],
            periods=shards,
            mode=str(mode),
            max_codes=int(max_codes),
            max_days=min(int(max_days), 120),
            seed=int(seed),
            worker_url=str(worker_url),
            deploy_if_needed=not bool(skip_deploy),
            stage_panels=(mode == "r2_panels"),
            staging_dir=out_dir / "panels_stage_survivors",
        )
    except Exception as exc:
        log(f"[w97/C] CF deep failed: {exc}")
        cf_pack = {
            "status": "error",
            "error": str(exc),
            "job_id": job_id,
            "mode": mode,
        }
    _dump(out_dir / "cf_survivor_deep_job.json", cf_pack)
    wr = cf_pack.get("worker_response") or {}
    if not wr and isinstance(cf_pack.get("results"), list):
        wr = cf_pack
    if wr:
        _dump(out_dir / "cf_survivor_deep_response.json", wr)

    cfg = MassFactoryConfig()
    rows_flat: list[dict[str, Any]] = []
    results_by_lid: dict[str, dict[str, Any]] = {}
    for r in wr.get("results") or []:
        if not isinstance(r, Mapping):
            continue
        lid = str(r.get("logic_id") or "")
        if lid in SURVIVOR_LOGIC_IDS:
            results_by_lid[lid] = dict(r)

    for w in W97_WINDOWS:
        wid = str(w["window_id"])
        keep = {s["period_id"] for s in w["shards"]}
        for lid in SURVIVOR_LOGIC_IDS:
            raw = results_by_lid.get(lid)
            if raw is None:
                rows_flat.append(
                    {
                        "source": f"cf_{mode}",
                        "window": wid,
                        "logic_id": lid,
                        "mean_net": None,
                        "t": None,
                        "act": None,
                        "sign": None,
                        "survived": False,
                        "reject_reasons": ["missing_cf_result"],
                        "low_variance_artifact": False,
                        "known_weak_thesis": lid in KNOWN_WEAK_THESIS,
                        "known_low_var_risk": lid in KNOWN_LOW_VAR_RISK,
                    }
                )
                continue
            pack = _reaggregate_window(
                raw,
                keep_period_ids=keep,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            row = _row_from_pack(
                pack,
                window_id=wid,
                source="cf_r2_panels" if mode == "r2_panels" else f"cf_{mode}",
            )
            row["job_id"] = cf_pack.get("job_id") or job_id
            rows_flat.append(row)

    by_logic: dict[str, list[dict[str, Any]]] = {lid: [] for lid in SURVIVOR_LOGIC_IDS}
    for r in rows_flat:
        by_logic.setdefault(str(r["logic_id"]), []).append(r)
    classifications = [_classify_logic(by_logic[lid]) for lid in SURVIVOR_LOGIC_IDS]

    pack_out = {
        "wave": "W97 / w0818g",
        "track": "C_survivor_deep_eval_cf",
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "status": cf_pack.get("status"),
        "version": CF_MASS_EVAL_VERSION,
        "logics": list(SURVIVOR_LOGIC_IDS),
        "gates": ["cost", "PIT", "sign", "low_var"],
        "rows_flat": rows_flat,
        "classifications": classifications,
        "n_survivors_job": cf_pack.get("n_survivors"),
        "n_survivors_window_rows": sum(1 for r in rows_flat if r.get("survived")),
        "promote_as_main_candidate": False,
        "go_eligible": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "markdown_table": _markdown_window_table(rows_flat),
        "promotion_note": (
            "All deep-eval survivors remain research-only. Unstable / "
            "weak_thesis / low-var → explicitly not GO/main-promoted. "
            "3 defaults frozen untouched."
        ),
    }
    _dump(out_dir / "survivor_deep_cf.json", pack_out)
    _dump(out_dir / "survivor_deep_cf_table.json", rows_flat)
    (out_dir / "survivor_deep_cf_table.md").write_text(
        "# W97 Track C — survivor deep eval (CF r2_panels)\n\n"
        + pack_out["markdown_table"]
        + "\n",
        encoding="utf-8",
    )
    log(
        f"[w97/C] CF done status={cf_pack.get('status')} "
        f"job_surv={cf_pack.get('n_survivors')} "
        f"window_surv_rows={pack_out['n_survivors_window_rows']}"
    )
    return pack_out


def _aggregate_preferred(
    *,
    local_pack: Mapping[str, Any] | None,
    cf_pack: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Prefer CF r2_panels; fall back to local."""
    cf_status = str((cf_pack or {}).get("status") or "")
    cf_rows = list((cf_pack or {}).get("rows_flat") or [])
    local_rows = list((local_pack or {}).get("rows_flat") or [])
    if cf_status in {"ok", "partial"} and cf_rows:
        preferred_rows = cf_rows
        preferred_class = list((cf_pack or {}).get("classifications") or [])
        source = "cf_r2_panels"
        job_id = (cf_pack or {}).get("job_id")
    elif local_rows:
        preferred_rows = local_rows
        preferred_class = list((local_pack or {}).get("classifications") or [])
        source = "local"
        job_id = None
    else:
        preferred_rows = []
        preferred_class = []
        source = "none"
        job_id = None

    n_research_only = sum(
        1 for c in preferred_class if c.get("research_only")
    )
    n_unstable = sum(
        1
        for c in preferred_class
        if "UNSTABLE" in str(c.get("stance") or "")
        or "WEAK" in str(c.get("stance") or "")
    )
    headline = (
        f"preferred={source} · window_surv_rows="
        f"{sum(1 for r in preferred_rows if r.get('survived'))}/"
        f"{len(preferred_rows)} · research_only={n_research_only}/"
        f"{len(preferred_class)} · unstable_or_weak={n_unstable} · "
        "promote_as_main=False · go_eligible=False"
    )
    return {
        "wave": "W97 / w0818g",
        "track": "C_survivor_deep_eval",
        "preferred_source": source,
        "cf_job_id": job_id,
        "cf_status": cf_status or None,
        "logics": list(SURVIVOR_LOGIC_IDS),
        "gates": ["cost", "PIT", "sign", "low_var"],
        "rows_flat": preferred_rows,
        "classifications": preferred_class,
        "n_survivors_window_rows": sum(
            1 for r in preferred_rows if r.get("survived")
        ),
        "n_research_only": n_research_only,
        "n_unstable_or_weak": n_unstable,
        "promote_as_main_candidate": False,
        "go_eligible": False,
        "frozen_defaults_retuned": False,
        "headline": headline,
        "markdown_table": _markdown_window_table(preferred_rows),
        "classification_table_md": _markdown_classification(preferred_class),
    }


def _markdown_classification(classes: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| logic | stance | surv_win | sign_flip | low_var | "
        "mean_net_avg | t_avg | main? | GO? |"
    )
    sep = "|---|---|---:|:---:|:---:|---:|---:|:---:|:---:|"
    lines = [header, sep]
    for c in classes:
        mn = c.get("mean_net_avg")
        t = c.get("t_avg")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        lines.append(
            f"| `{c.get('logic_id')}` | {c.get('stance')} | "
            f"{c.get('n_survived_windows')}/{c.get('n_windows')} | "
            f"{c.get('sign_flip')} | {c.get('any_low_var')} | "
            f"{mn_s} | {t_s} | {c.get('promote_as_main')} | "
            f"{c.get('go_eligible')} |"
        )
    return "\n".join(lines)


def _markdown_preferred_table(table: Mapping[str, Any]) -> str:
    lines = [
        "# W97 / w0818g — Track C survivor deep multi-year eval",
        "",
        f"**Preferred source:** `{table.get('preferred_source')}`  ",
        f"**CF job:** `{table.get('cf_job_id')}` · status `{table.get('cf_status')}`  ",
        f"**Headline:** {table.get('headline')}",
        "",
        "## Window × logic (cost + PIT + sign + low-var)",
        "",
        table.get("markdown_table") or "_no rows_",
        "",
        "## Cross-window classification (research-only; no main/GO)",
        "",
        table.get("classification_table_md") or "_no classifications_",
        "",
        "## Freezes held",
        "",
        "- Mass = NO-GO · READY = false · ops GO = false · continuous paper = UNARMED",
        "- 3 default-path pins **untouched / not retuned**",
        "- Unstable / weak_thesis / low-var → research-only (not GO/main-promote)",
        "",
    ]
    return "\n".join(lines)


def run_track_d_hyps(
    *,
    out_dir: Path,
    n_hyps: int,
    provider: str,
    model: str | None,
    seed: int,
    synthetic: bool,
    cf_url: str,
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
    # Prefer xAI explicitly when auto and key present.
    resolved_provider = provider
    if provider == "auto" and key_presence.get("xai"):
        resolved_provider = "xai"
    log(
        f"[w97/D] generating n={n_hyps} provider={resolved_provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION}"
    )

    gen_eval = generate_and_evaluate_hypotheses(
        n=int(n_hyps),
        provider=None if resolved_provider == "auto" else resolved_provider,
        model=model,
        worker_url=cf_url,
        evaluate=True,
        synthetic=bool(synthetic),
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
    _dump(
        out_dir / "llm_hyp_accepted_proposals.json",
        gen_eval.get("accepted_proposals") or [],
    )
    _dump(
        out_dir / "llm_hyp_rejected_proposals.json",
        gen_eval.get("rejected_proposals") or [],
    )

    n_proposed = int(gen_eval.get("n_proposed") or 0)
    n_accepted = int(gen_eval.get("n_accepted") or 0)
    n_gen_rejected = n_proposed - n_accepted
    n_eval_rejected = len(gen_eval.get("rejected_proposals") or [])
    n_survivors = int(gen_eval.get("n_survivors") or 0)
    theses = list(gen_eval.get("representative_theses") or [])

    # Flag any survivor that maps onto demoted/weak families — keep research-only.
    demoted_weak_mapped: list[str] = []
    for s in gen_eval.get("eval_screens") or []:
        if not isinstance(s, Mapping) or not s.get("survived"):
            continue
        lid = str(s.get("logic_id") or "")
        if lid in KNOWN_WEAK_THESIS or lid in KNOWN_LOW_VAR_RISK:
            demoted_weak_mapped.append(lid)
        if lid in {
            "fund_value_mom_agree_slow",
            "opt225_skew_abs_level",
            "opt225_cm_term_abs_level",
            "opt225_basevol_delta_abs",
            "macro_repo_rate_change",
            "macro_repo_rate_level",
            "flow_margin_short_soft",
            "flow_margin_pressure",
        }:
            demoted_weak_mapped.append(lid)

    summary = {
        "wave": "W97 / w0818g",
        "track": "D_constrained_hyp_gen",
        "provider": gen_eval.get("provider"),
        "model": gen_eval.get("model"),
        "llm_hyp_version": LLM_HYP_VERSION,
        "n_requested": int(n_hyps),
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_gen_rejected,
        "n_rejected_evaluator": n_eval_rejected,
        "n_rejected": n_gen_rejected + n_eval_rejected,
        "n_evaluated": gen_eval.get("n_evaluated"),
        "n_survivors": n_survivors,
        "representative_theses": theses,
        "demoted_weak_mapped_survivors": sorted(set(demoted_weak_mapped)),
        "do_not_resurrect_as_main": True,
        "failure_mode_constraints": [
            "no_sign_flip_single_regime_reliance",
            "no_soft_eq_pressure",
            "no_low_var_t_trust",
            "no_window_only",
            "no_dual_options_level",
            "no_repolish_shape_rate_flow_demoted_fund_slow",
            "no_hold_mom_frac_grid",
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var"],
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "promote_as_main_candidate": False,
        "seed": int(seed),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w97/D] n_proposed={n_proposed} n_accepted={n_accepted} "
        f"n_rejected={summary['n_rejected']} "
        f"(gen={n_gen_rejected}+eval={n_eval_rejected}) "
        f"n_survivors={n_survivors} model={gen_eval.get('model')}"
    )
    for th in theses[:8]:
        log(
            f"  · {th.get('logic_id')}: "
            f"{str(th.get('thesis') or '')[:120]}"
        )
    if demoted_weak_mapped:
        log(
            "[w97/D] demoted/weak mapped survivors (research-only, not main): "
            + ", ".join(sorted(set(demoted_weak_mapped)))
        )
    return {"summary": summary, "gen_eval": gen_eval}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--n-hyps", type=int, default=6, help="modest N for Track D")
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument(
        "--provider",
        type=str,
        default="xai",
        help="xai preferred; auto|xai|openai|anthropic|glm|workers_ai|catalog",
    )
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-local", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "synthetic", "nets_only", "d1_bars"],
    )
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--cf-url", type=str, default=CF_WORKER_URL)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_FACTORY_VERSION,
        MASS_RESEARCH,
        PHASE7,
    )

    log(f"[w97] out={out_dir} ts={ts}")
    pin_check = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pin_check)
    log(
        f"[w97] freezes: mass={MASS_RESEARCH} phase7={PHASE7} "
        f"paper={CONTINUOUS_PAPER} READY=False ops_GO=False "
        f"frozen_defaults_retuned=False pins_untouched="
        f"{pin_check['pins_untouched']} factory={MASS_FACTORY_VERSION}"
    )
    log(
        "[w97] 3 defaults frozen (untouched): "
        + ", ".join(
            f"{r['representative_id']}={r['stance']}" for r in FROZEN_DEFAULT_PATH
        )
    )
    log(f"[w97/C] logics={list(SURVIVOR_LOGIC_IDS)}")

    # ------------------------------------------------------------------ C local
    local_pack: dict[str, Any] = {}
    if not args.skip_local:
        local_pack = run_track_c_local(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            log=log,
        )
        log(
            f"[w97/C] local window_surv_rows="
            f"{local_pack.get('n_survivors_window_rows')}"
        )
    else:
        log("[w97/C] local skipped")

    # ------------------------------------------------------------------ C CF
    cf_pack: dict[str, Any] = {}
    if not args.skip_cf:
        cf_pack = run_track_c_cf(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            mode=str(args.mode),
            worker_url=str(args.cf_url),
            skip_deploy=bool(args.skip_deploy),
            log=log,
        )
    else:
        log("[w97/C] CF skipped")

    table = _aggregate_preferred(local_pack=local_pack, cf_pack=cf_pack)
    _dump(out_dir / "survivor_deep_table.json", table)
    md = _markdown_preferred_table(table)
    (out_dir / "survivor_deep_table.md").write_text(md + "\n", encoding="utf-8")
    log(
        f"[w97/C] wrote survivor_deep_table.json/md "
        f"source={table.get('preferred_source')} · {table.get('headline')}"
    )

    # ------------------------------------------------------------------ D hyps
    hyp_pack: dict[str, Any] = {}
    if not args.skip_hyps:
        hyp_pack = run_track_d_hyps(
            out_dir=out_dir,
            n_hyps=int(args.n_hyps),
            provider=str(args.provider),
            model=args.model,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            cf_url=str(args.cf_url),
            log=log,
        )
    else:
        log("[w97/D] hyps skipped")

    hyp_summary = (hyp_pack or {}).get("summary") or {}
    wall = round(time.perf_counter() - t0, 2)
    # Re-assert pins unchanged after run.
    pin_check_after = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert_after.json", pin_check_after)

    run_summary = {
        "wave": "W97 / w0818g",
        "tracks": ["C_survivor_deep_eval", "D_constrained_hyp_gen"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_sec": wall,
        "survivors_deep": {
            "preferred_source": table.get("preferred_source"),
            "cf_job_id": table.get("cf_job_id"),
            "cf_status": table.get("cf_status"),
            "logics": list(SURVIVOR_LOGIC_IDS),
            "n_survivors_window_rows": table.get("n_survivors_window_rows"),
            "n_unstable_or_weak": table.get("n_unstable_or_weak"),
            "classifications": table.get("classifications"),
            "headline": table.get("headline"),
            "promote_as_main_candidate": False,
            "go_eligible": False,
        },
        "hyps": {
            "n_requested": hyp_summary.get("n_requested"),
            "n_proposed": hyp_summary.get("n_proposed"),
            "n_accepted": hyp_summary.get("n_accepted"),
            "n_rejected": hyp_summary.get("n_rejected"),
            "n_evaluated": hyp_summary.get("n_evaluated"),
            "n_survivors": hyp_summary.get("n_survivors"),
            "provider": hyp_summary.get("provider"),
            "model": hyp_summary.get("model"),
            "representative_theses": hyp_summary.get("representative_theses"),
            "demoted_weak_mapped_survivors": hyp_summary.get(
                "demoted_weak_mapped_survivors"
            ),
            "do_not_resurrect_as_main": True,
        },
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "continuous_paper": CONTINUOUS_PAPER,
            "ready_declared": False,
            "operational_go": False,
            "frozen_defaults_retuned": False,
            "pins_untouched": pin_check_after.get("pins_untouched"),
        },
    }
    _dump(out_dir / "w97_cd_summary.json", run_summary)
    log(f"[w97] done wall_sec={wall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
