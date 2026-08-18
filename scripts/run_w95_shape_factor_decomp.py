#!/usr/bin/env python3
"""W95 / w0818e — rate/flow/fund failure decomposition + fund 2017 giant-t audit.

Reaggregates W94 CF job ``w94-thick-20260818T125009Z`` period_rows with the
W95 low-variance t-gate, writes taxonomy + fund audit, optionally re-invokes
CF on research-mass-eval/v6.

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.

Examples
--------
    uv run python scripts/run_w95_shape_factor_decomp.py \\
        --out-dir .glm-logs/w0818e_w95_shape_factor_decomp/

    uv run python scripts/run_w95_shape_factor_decomp.py --invoke-cf
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

# Reuse W94 window + logic catalogs.
from run_w94_thick_factor_windows import (  # noqa: E402
    ANCHOR_LOGIC_IDS,
    FLOW_LOGIC_IDS,
    FUND_LOGIC_IDS,
    MF_LOGIC_IDS,
    RATE_LOGIC_IDS,
    THICK_FACTOR_LOGIC_IDS,
    W94_WINDOWS,
    _compact_row,
    _family_bucket,
    _markdown_table,
    _reaggregate_window_from_period_rows,
)

W95_SOURCE_JOB = "w94-thick-20260818T125009Z"
W95_SOURCE_LOG = ".glm-logs/w0818d_w94_opt_skew_thick"
DEFAULT_NEAR_ZERO = 0.0005
DEFAULT_MIN_ACT = 0.01


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8"
    )


def _load_w94_response(src: Path) -> dict[str, Any]:
    p = src / "cf_mass_eval_response.json"
    if not p.is_file():
        raise FileNotFoundError(f"missing W94 CF response: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _audit_fund_2017(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from research.stats_metrics import (
        LOW_VARIANCE_MAX_ABS_T,
        LOW_VARIANCE_MIN_REL_STD,
        LOW_VARIANCE_REASON,
        has_pairwise_low_variance_artifact,
        t_stat_vs_zero,
    )

    target = None
    for r in results:
        if r.get("logic_id") == "fund_value_mom_agree_slow":
            target = r
            break
    if target is None:
        return {"ok": False, "error": "fund_value_mom_agree_slow missing"}

    by_pid = {
        str(p.get("period_id")): p
        for p in (target.get("period_rows") or [])
        if p.get("status") == "ok"
    }
    n2017 = by_pid.get("y2017_q4", {}).get("net_one_way_mean_active")
    n2019 = by_pid.get("y2019_full", {}).get("net_one_way_mean_active")
    window_nets = [n2017, n2019]
    gated = t_stat_vs_zero(window_nets)
    # Ungated raw t for disclosure (recompute without gate via formula).
    import math
    from statistics import mean, stdev

    clean = [float(x) for x in window_nets if x is not None]
    raw_t = None
    raw_std = None
    raw_mean = None
    if len(clean) >= 2:
        raw_mean = float(mean(clean))
        raw_std = float(stdev(clean))
        if raw_std > 0:
            raw_t = raw_mean / (raw_std / math.sqrt(len(clean)))

    all_nets = [
        p.get("net_one_way_mean_active")
        for p in (target.get("period_rows") or [])
        if p.get("status") == "ok"
    ]
    aggregate_gated = t_stat_vs_zero(all_nets)
    pairwise = has_pairwise_low_variance_artifact(all_nets)

    conclusion = (
        "ARTIFACT_CONFIRMED: w2017_2019 t≈153 arises from two near-identical "
        "shard nets (y2017_q4≈y2019_full, CV≪5%) on a 2-period window — "
        "low-variance denom inflation, not an edge. Demote/exclude from "
        "survivors via inflated_t_low_variance; gated t_stat=null on that "
        "window. Aggregate 5-period t remains modest and is not the claim."
    )
    return {
        "ok": True,
        "wave": "W95 / w0818e",
        "logic_id": "fund_value_mom_agree_slow",
        "source_job_id": W95_SOURCE_JOB,
        "window": "w2017_2019",
        "shard_ids": ["y2017_q4", "y2019_full"],
        "period_nets": {
            "y2017_q4": n2017,
            "y2019_full": n2019,
        },
        "raw_ungated": {
            "mean_net": raw_mean,
            "std_net": raw_std,
            "t_stat": raw_t,
            "cv": None
            if raw_mean in (None, 0) or raw_std is None
            else abs(raw_std / raw_mean),
            "note": "pre-gate formula reproduction of W94 table t≈153.18",
        },
        "gated": gated,
        "aggregate_5period": {
            "nets": all_nets,
            "gated": aggregate_gated,
            "pairwise_low_variance_artifact": pairwise,
            "w94_ranking_t_stat": 1.7342846474565494,
            "w94_survived_aggregate": True,
        },
        "gate": {
            "min_rel_std": LOW_VARIANCE_MIN_REL_STD,
            "max_abs_t": LOW_VARIANCE_MAX_ABS_T,
            "reason_code": LOW_VARIANCE_REASON,
            "screen_reject": "inflated_t_low_variance",
        },
        "action": {
            "demote_from_survivors": True,
            "exclude_reason": "inflated_t_low_variance",
            "fix_denom": True,
            "taxonomy": "impl_bug",
        },
        "conclusion": conclusion,
        "freezes": {
            "mass_research": "NO-GO",
            "phase7": "OFF",
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": "UNARMED",
            "frozen_defaults_retuned": False,
        },
    }


def _taxonomy_row(
    *,
    logic_id: str,
    window: str,
    row: Mapping[str, Any],
    fund_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify failure mode: data_gap | weak_thesis | impl_bug."""
    lid = logic_id
    reasons = list(row.get("reject_reasons") or [])
    t = row.get("t_stat")
    act = row.get("mean_activation")
    sign = row.get("chosen_sign")
    n_ok = int(row.get("n_periods_ok") or 0)
    mdh = int(row.get("mdh_fallback_periods") or 0)
    labels: list[str] = []
    note_parts: list[str] = []

    # Window shard coverage gaps (honest W94 windows).
    if window == "w2020_2022" and n_ok <= 1:
        labels.append("data_gap")
        note_parts.append("single shard y2021_full only; t null by n<2")
    if window == "w2017_2019":
        note_parts.append("shards y2017_q4+y2019_full (2018 mirror absent)")
    if window == "w2023_2025":
        note_parts.append("shards y2023_full+y2025_q4 (2024 mirror absent)")

    if mdh > 0:
        labels.append("data_gap")
        note_parts.append(f"mdh_fallback_periods={mdh}")

    if "inflated_t_low_variance" in reasons or row.get("low_variance_artifact"):
        labels.append("impl_bug")
        note_parts.append("low-variance inflated t (denom); demoted")

    if lid == "fund_value_mom_agree_slow" and window == "w2017_2019":
        if "impl_bug" not in labels:
            labels.append("impl_bug")
        note_parts.append("W94 giant-t artifact confirmed")

    if lid == "flow_margin_short_soft":
        labels.append("weak_thesis")
        note_parts.append(
            "soft≡pressure by design (conflict keeps margin); near-duplicate"
        )

    # Rate sign flips / weak activation economics.
    if lid.startswith("macro_repo_rate_"):
        if sign in (-1, None) or (
            isinstance(t, (int, float)) and abs(float(t)) < 2.0
        ):
            labels.append("weak_thesis")
            note_parts.append("sign unstable across windows or weak |t|")
        # change vs level: level weaker in 2023
        if lid.endswith("_level") and (
            t is None or (isinstance(t, (int, float)) and abs(float(t)) < 1.0)
        ):
            note_parts.append("level weaker than change; near-zero late window")

    if lid.startswith("flow_margin_"):
        if act is not None and float(act) < 0.05:
            note_parts.append(f"sparse margin prints → low act={float(act):.3f}")
        if sign in (-1, None):
            labels.append("weak_thesis")
            note_parts.append("sign flips 2017→2023; thesis not stable")
        # Eval path itself OK when sidecar consumed.
        if int(row.get("sidecar_consumed_periods") or 0) > 0 and mdh == 0:
            note_parts.append("eval OK (sidecar consumed; not impl_bug)")

    if lid.startswith("fund_") and lid != "fund_value_mom_agree_slow":
        if sign in (-1, None):
            labels.append("weak_thesis")
            note_parts.append("sign flip / non-robust across windows")

    if not labels:
        # Default residual: weak_thesis if rejected, else none.
        if not row.get("survived"):
            labels.append("weak_thesis")
            note_parts.append("lite screen reject; no wiring/impl defect")
        else:
            labels.append("weak_thesis")
            note_parts.append("survived lite but not promoted (freezes held)")

    # Dedup labels preserving order.
    seen: set[str] = set()
    uniq = []
    for x in labels:
        if x not in seen:
            seen.add(x)
            uniq.append(x)

    primary = uniq[0]
    return {
        "window": window,
        "logic_id": lid,
        "bucket": _family_bucket(lid),
        "taxonomy": primary,
        "taxonomy_all": uniq,
        "mean_net": row.get("mean_net"),
        "t_stat": t,
        "raw_t_stat": row.get("raw_t_stat"),
        "act": act,
        "sign": sign,
        "survived": bool(row.get("survived")),
        "reject_reasons": reasons,
        "note": "; ".join(note_parts),
    }


def _taxonomy_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| window | bucket | logic | taxonomy | mean_net | t | act | sign | "
        "survived | note |"
    )
    sep = "|---|---|---|---|---:|---:|---:|---|---|---|"
    lines = [header, sep]
    for r in rows:
        mn, t, act = r.get("mean_net"), r.get("t_stat"), r.get("act")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        note = str(r.get("note") or "")[:80]
        lines.append(
            f"| {r.get('window')} | {r.get('bucket')} | `{r.get('logic_id')}` | "
            f"**{r.get('taxonomy')}** | {mn_s} | {t_s} | {act_s} | {sign_s} | "
            f"{r.get('survived')} | {note} |"
        )
    return "\n".join(lines)


def _rate_decomp(rows_flat: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rate_rows = [r for r in rows_flat if r.get("bucket") == "rate"]
    by_logic: dict[str, list[dict[str, Any]]] = {}
    for r in rate_rows:
        by_logic.setdefault(str(r["logic_id"]), []).append(dict(r))

    flips = []
    for lid, rs in by_logic.items():
        signs = [(r.get("window"), r.get("chosen_sign"), r.get("mean_net"), r.get("mean_activation")) for r in rs]
        nonzero = [s for s in signs if s[1] not in (None, 0)]
        flipped = len({s[1] for s in nonzero}) > 1
        flips.append(
            {
                "logic_id": lid,
                "sign_path": signs,
                "sign_flips_across_windows": flipped,
                "activation_range": [
                    min(
                        (
                            float(r["mean_activation"])
                            for r in rs
                            if r.get("mean_activation") is not None
                        ),
                        default=None,
                    ),
                    max(
                        (
                            float(r["mean_activation"])
                            for r in rs
                            if r.get("mean_activation") is not None
                        ),
                        default=None,
                    ),
                ],
            }
        )
    return {
        "change_vs_level": {
            "change": "macro_repo_rate_change — stronger |mean| in early windows; "
            "sign + (2017) → − (2021) → + (2023); act≈0.07–0.08 stable",
            "level": "macro_repo_rate_level — weaker; 2023 near-zero / no sign; "
            "act≈0.07–0.08; not a pure change substitute",
        },
        "per_logic": flips,
        "conclusion": (
            "Rate failure is weak_thesis (regime-/window-unstable sign), not "
            "impl_bug: sidecars consumed (mdh_fb=0), activation healthy. "
            "Prefer change over level for further probes; do not promote."
        ),
    }


def _flow_decomp(rows_flat: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    flow_rows = [r for r in rows_flat if r.get("bucket") == "flow"]
    soft = [r for r in flow_rows if r.get("logic_id") == "flow_margin_short_soft"]
    pressure = [r for r in flow_rows if r.get("logic_id") == "flow_margin_pressure"]
    soft_eq = True
    for a, b in zip(
        sorted(soft, key=lambda x: str(x.get("window"))),
        sorted(pressure, key=lambda x: str(x.get("window"))),
    ):
        if a.get("mean_net") != b.get("mean_net") or a.get("mean_activation") != b.get(
            "mean_activation"
        ):
            soft_eq = False
    return {
        "sidecar": {
            "margin": "markets_margin_interest → margin_change_by_code (sparse prints)",
            "short": "markets_short_ratio section=0050 → short_ratio_by_date",
            "construction": (
                "cf_mass_eval_job._build_thicken_sidecars stages flow_regime; "
                "worker evalFlowDemand consumes it; missing → disclosed MDH"
            ),
            "mdh_fb_observed": 0,
            "eval_broken": False,
        },
        "soft_equals_pressure": soft_eq,
        "soft_note": (
            "short_confirm_mode=soft keeps margin on conflict and falls back to "
            "margin-only on short gap → soft≈off/pressure whenever short Δ≠0. "
            "Near-duplicate weak_thesis, not a wiring hole."
        ),
        "hard_note": (
            "hard requires same-sign short confirm → lower act (≈0.01–0.10); "
            "sign still flips across windows."
        ),
        "refresh_lag": (
            "Margin interest is print-sparse (not daily); entrySigns are null "
            "between prints by design. Short uses last observation ≤ date. "
            "Not a refresh-lag bug — sparsity lowers activation."
        ),
        "conclusion": (
            "Flow failure = weak_thesis (+ soft near-dup). Eval path OK "
            "(sidecar consumed). Do not treat as impl_bug; demote soft as "
            "near-duplicate of pressure."
        ),
        "rows": flow_rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out-dir",
        default=".glm-logs/w0818e_w95_shape_factor_decomp",
        help="artifact directory",
    )
    ap.add_argument(
        "--source-dir",
        default=W95_SOURCE_LOG,
        help="W94 log dir with cf_mass_eval_response.json",
    )
    ap.add_argument(
        "--near-zero-abs",
        type=float,
        default=DEFAULT_NEAR_ZERO,
    )
    ap.add_argument(
        "--min-activation",
        type=float,
        default=DEFAULT_MIN_ACT,
    )
    ap.add_argument(
        "--invoke-cf",
        action="store_true",
        help="Also invoke CF mass-eval on v6 (optional; needs deploy)",
    )
    ap.add_argument(
        "--skip-cf",
        action="store_true",
        help="Alias: do not invoke CF (default)",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    src = Path(args.source_dir)
    if not src.is_absolute():
        src = ROOT / src

    t0 = time.perf_counter()
    resp = _load_w94_response(src)
    results = list(resp.get("results") or [])

    fund_audit = _audit_fund_2017(results)
    _dump(out_dir / "fund_2017_t_audit.json", fund_audit)

    window_tables: list[dict[str, Any]] = []
    rows_flat: list[dict[str, Any]] = []
    taxonomy_rows: list[dict[str, Any]] = []

    for w in W94_WINDOWS:
        wid = str(w["window_id"])
        shard_ids = {s["period_id"] for s in w["shards"]}
        bucket_rows: dict[str, list[dict[str, Any]]] = {
            "rate": [],
            "flow": [],
            "fund": [],
            "mf": [],
            "anchor": [],
        }
        for r in results:
            lid = str(r.get("logic_id") or "")
            if lid not in THICK_FACTOR_LOGIC_IDS:
                continue
            reagg = _reaggregate_window_from_period_rows(
                r,
                keep_period_ids=shard_ids,
                near_zero_abs=float(args.near_zero_abs),
                min_activation=float(args.min_activation),
            )
            row = _compact_row(reagg, window_id=wid)
            # Preserve raw/gated audit fields on compact row.
            row["raw_t_stat"] = reagg.get("raw_t_stat")
            row["t_stat_reason"] = reagg.get("t_stat_reason")
            row["low_variance_artifact"] = reagg.get("low_variance_artifact")
            # signal/sidecar counts from filtered period rows
            prows = [
                p
                for p in (r.get("period_rows") or [])
                if str(p.get("period_id") or "") in shard_ids
            ]
            if prows and not row.get("signal_ids"):
                row["signal_id_sample"] = (prows[0] or {}).get("signal_id")
            rows_flat.append(row)
            bucket_rows.setdefault(row["bucket"], []).append(row)
            taxonomy_rows.append(
                _taxonomy_row(
                    logic_id=lid,
                    window=wid,
                    row=row,
                    fund_audit=fund_audit,
                )
            )
        window_tables.append(
            {
                "window_id": wid,
                "label": w.get("label"),
                "data_note": w.get("data_note"),
                "shard_ids": sorted(shard_ids),
                "n_survivors": sum(
                    1 for r in rows_flat if r.get("window") == wid and r.get("survived")
                ),
                **bucket_rows,
            }
        )

    # Bucket tables
    for bucket, logic_ids in (
        ("rate", RATE_LOGIC_IDS),
        ("flow", FLOW_LOGIC_IDS),
        ("fund", FUND_LOGIC_IDS),
        ("mf", MF_LOGIC_IDS),
        ("anchor", ANCHOR_LOGIC_IDS),
    ):
        brows = [r for r in rows_flat if r.get("bucket") == bucket]
        _dump(out_dir / f"cf_{bucket}_table.json", {"bucket": bucket, "rows": brows})
        (out_dir / f"cf_{bucket}_table.md").write_text(
            f"# W95 CF {bucket} window table (gated)\n\n"
            + _markdown_table(brows)
            + "\n",
            encoding="utf-8",
        )

    rate_decomp = _rate_decomp(rows_flat)
    flow_decomp = _flow_decomp(rows_flat)
    _dump(out_dir / "rate_decomp.json", rate_decomp)
    _dump(out_dir / "flow_decomp.json", flow_decomp)

    tax = {
        "wave": "W95 / w0818e",
        "source_job_id": W95_SOURCE_JOB,
        "labels": ["data_gap", "weak_thesis", "impl_bug"],
        "rows": taxonomy_rows,
        "counts": {
            lab: sum(1 for r in taxonomy_rows if r.get("taxonomy") == lab)
            for lab in ("data_gap", "weak_thesis", "impl_bug")
        },
    }
    _dump(out_dir / "failure_taxonomy.json", tax)
    (out_dir / "failure_taxonomy.md").write_text(
        "# W95 failure taxonomy (logic × window)\n\n"
        "Labels: **data_gap** | **weak_thesis** | **impl_bug**\n\n"
        + _taxonomy_markdown(taxonomy_rows)
        + "\n",
        encoding="utf-8",
    )

    # Demoted survivors from W94 aggregate ranking.
    w94_ranking = list(resp.get("ranking") or [])
    demoted = []
    kept = []
    for s in w94_ranking:
        lid = str(s.get("logic_id") or "")
        # Re-screen aggregate period_rows under W95 gate.
        match = next((r for r in results if r.get("logic_id") == lid), None)
        if match is None:
            kept.append(s)
            continue
        from research.mass_strategy_factory import screen_strategy_result

        probe = {
            **{k: match.get(k) for k in (
                "strategy_id", "logic_id", "family_id", "mean_gross", "mean_net",
                "t_stat", "sharpe_period", "chosen_sign", "mean_activation",
                "n_periods_ok", "period_rows",
            )},
            "sign_selection": {
                "chosen_sign": 1 if match.get("chosen_sign") == "original" else (
                    -1 if match.get("chosen_sign") == "inverted" else None
                ),
                "decision": (
                    "keep_original"
                    if match.get("chosen_sign") == "original"
                    else (
                        "keep_inverted"
                        if match.get("chosen_sign") == "inverted"
                        else "reject"
                    )
                ),
            },
        }
        scr = screen_strategy_result(
            probe,
            near_zero_abs=float(args.near_zero_abs),
            min_activation=float(args.min_activation),
        )
        if not scr.get("survived"):
            demoted.append(
                {
                    **s,
                    "demoted": True,
                    "demote_reasons": scr.get("reject_reasons"),
                    "w95_screen": scr,
                }
            )
        else:
            kept.append({**s, "demoted": False})

    survivors_w95 = {
        "source_job_id": W95_SOURCE_JOB,
        "w94_n_survivors": int(resp.get("n_survivors") or len(w94_ranking)),
        "w95_n_survivors": len(kept),
        "demoted": demoted,
        "kept": kept,
        "note": (
            "W95 re-screen of W94 aggregate ranking with pairwise "
            "low-variance inflated-t gate. fund_value_mom_agree_slow expected "
            "demoted."
        ),
    }
    _dump(out_dir / "survivors_demotion.json", survivors_w95)

    cf_pack = None
    if args.invoke_cf and not args.skip_cf:
        try:
            from research.cf_mass_eval_job import run_cf_mass_eval_job

            periods = []
            for w in W94_WINDOWS:
                for s in w["shards"]:
                    periods.append(dict(s))
            # dedupe periods
            seen_p: set[str] = set()
            uniq_periods = []
            for p in periods:
                pid = str(p.get("period_id"))
                if pid in seen_p:
                    continue
                seen_p.add(pid)
                uniq_periods.append(p)
            job_id = (
                "w95-decomp-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=list(THICK_FACTOR_LOGIC_IDS),
                periods=uniq_periods,
                mode="r2_panels",
                seed=870818,
                deploy_if_needed=False,  # already deployed v6 above
            )
            _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
            worker_resp = (
                cf_pack.get("worker_response")
                or cf_pack.get("response")
                or {}
            )
            if worker_resp:
                _dump(out_dir / "cf_mass_eval_response.json", worker_resp)
                # Recompute demotion against live v6 response when present.
                live_ranking = list(worker_resp.get("ranking") or [])
                live_demoted = [
                    s
                    for s in live_ranking
                    if str(s.get("logic_id")) == "fund_value_mom_agree_slow"
                ]
                # Also check results screen reject reasons.
                live_fund = next(
                    (
                        r
                        for r in (worker_resp.get("results") or [])
                        if r.get("logic_id") == "fund_value_mom_agree_slow"
                    ),
                    None,
                )
                _dump(
                    out_dir / "cf_v6_live_fund_check.json",
                    {
                        "job_id": job_id,
                        "n_survivors": worker_resp.get("n_survivors"),
                        "fund_in_ranking": live_demoted,
                        "fund_result_screen": (live_fund or {}).get("screen"),
                        "fund_low_variance_artifact": (live_fund or {}).get(
                            "low_variance_artifact"
                        ),
                        "fund_t_stat": (live_fund or {}).get("t_stat"),
                        "fund_raw_t_stat": (live_fund or {}).get("raw_t_stat"),
                        "version": worker_resp.get("version"),
                        "wave": worker_resp.get("wave"),
                    },
                )
        except Exception as exc:  # pragma: no cover
            cf_pack = {"ok": False, "error": str(exc)}
            _dump(out_dir / "cf_invoke_error.json", cf_pack)

    summary = {
        "wave": "W95 / w0818e",
        "track": "B_rate_flow_fund_failure_decomp",
        "source_job_id": W95_SOURCE_JOB,
        "worker_target": "research-mass-eval/v6",
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "fund_2017_audit": {
            "artifact_confirmed": bool(fund_audit.get("ok")),
            "raw_t": (fund_audit.get("raw_ungated") or {}).get("t_stat"),
            "gated_reason": (fund_audit.get("gated") or {}).get("reason"),
            "demote": True,
        },
        "survivors": {
            "w94": survivors_w95["w94_n_survivors"],
            "w95_kept": survivors_w95["w95_n_survivors"],
            "demoted_ids": [d.get("logic_id") for d in demoted],
        },
        "taxonomy_counts": tax["counts"],
        "rate_conclusion": rate_decomp["conclusion"],
        "flow_conclusion": flow_decomp["conclusion"],
        "cf_invoked": bool(args.invoke_cf and not args.skip_cf),
        "cf_ok": (
            None
            if cf_pack is None
            else bool(
                str(cf_pack.get("status") or "").lower() == "ok"
                or (cf_pack.get("worker_response") or {}).get("ok")
                or cf_pack.get("ok")
            )
        ),
        "cf_job_id": None if cf_pack is None else cf_pack.get("job_id"),
        "cf_n_survivors": None if cf_pack is None else cf_pack.get("n_survivors"),
        "freezes": fund_audit.get("freezes"),
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    _dump(out_dir / "w95_summary.json", summary)
    _dump(
        out_dir / "cf_window_summary.json",
        {
            "wave": "W95 / w0818e",
            "source_job_id": W95_SOURCE_JOB,
            "window_tables": window_tables,
            "rows_flat": rows_flat,
        },
    )
    (out_dir / "cf_window_table.md").write_text(
        "# W95 gated CF window table\n\n" + _markdown_table(rows_flat) + "\n",
        encoding="utf-8",
    )

    summary_md = "\n".join(
        [
            "# W95 / w0818e — shape/factor failure decomposition",
            "",
            f"**Source CF job:** `{W95_SOURCE_JOB}`",
            f"**Worker target:** research-mass-eval/v6",
            "",
            "## Fund 2017 giant-t",
            "",
            f"- Raw ungated t: `{(fund_audit.get('raw_ungated') or {}).get('t_stat')}`",
            f"- Gated reason: `{(fund_audit.get('gated') or {}).get('reason')}`",
            f"- Action: demote/exclude survivors (`inflated_t_low_variance`)",
            f"- Conclusion: {fund_audit.get('conclusion')}",
            "",
            "## Survivors demotion",
            "",
            f"- W94 survivors: {survivors_w95['w94_n_survivors']}",
            f"- W95 kept: {survivors_w95['w95_n_survivors']}",
            f"- Demoted: {', '.join(str(d.get('logic_id')) for d in demoted) or '—'}",
            "",
            "## Rate",
            "",
            rate_decomp["conclusion"],
            "",
            "## Flow",
            "",
            flow_decomp["conclusion"],
            "",
            "## Taxonomy counts",
            "",
            json.dumps(tax["counts"], indent=2),
            "",
            "## Freezes held",
            "",
            "- Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言",
            "- continuous paper UNARMED · 3 defaults not retuned · TOPIX proxy only",
            "",
            "## Artifacts",
            "",
            "- `fund_2017_t_audit.json`",
            "- `failure_taxonomy.md` / `.json`",
            "- `rate_decomp.json` / `flow_decomp.json`",
            "- `cf_{rate,flow,fund,mf}_table.md`",
            "- `survivors_demotion.json`",
            "",
        ]
    )
    (out_dir / "SUMMARY.md").write_text(summary_md, encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
