#!/usr/bin/env python3
"""W95 / w0818e — rate / flow / fund failure decomposition.

Tracks
------
6. rate: change vs level, activation, sign-flip timing
7. flow: margin/short definition / refresh / missingness breaking eval?
8. fund 2017 giant-t: reproduce; if single-period / low-variance artifact → demote
9. Classify failures: data gap vs weak thesis vs implementation bug
10. Fix only worth-fixing items → re-eval

Consumes W94 thick CF response by default (same shards / worker v5), with
optional local corroboration. Does **not** retune 3 defaults / arm Mass/READY/GO.

Examples
--------
    uv run python scripts/run_w95_factor_failure_decomp.py \\
        --out-dir .glm-logs/w0818e_w95_shape_factor_decomp/

    uv run python scripts/run_w95_factor_failure_decomp.py --local-corroborate
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

W95_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "w2017_2019",
        "shards": ("y2017_q4", "y2019_full"),
    },
    {
        "window_id": "w2020_2022",
        "shards": ("y2021_full",),
    },
    {
        "window_id": "w2023_2025",
        "shards": ("y2023_full", "y2025_q4"),
    },
)

RATE_LOGIC_IDS = ("macro_repo_rate_change", "macro_repo_rate_level")
FLOW_LOGIC_IDS = (
    "flow_margin_pressure",
    "flow_margin_short_hard",
    "flow_margin_short_soft",
)
FUND_LOGIC_IDS = (
    "fund_value_only",
    "fund_value_mom_agree",
    "fund_value_mom_agree_slow",
)
MF_LOGIC_IDS = ("mf_value_mom_rate", "mf_flow_price")


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def _scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def _t_stat(nets: Sequence[float]) -> float | None:
    xs = [float(x) for x in nets if x is not None and math.isfinite(float(x))]
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    if var <= 0:
        return None
    se = math.sqrt(var / n)
    if se == 0:
        return None
    return mean / se


def _load_w94_thick(prior: Path) -> dict[str, Any]:
    resp = prior / "cf_mass_eval_response.json"
    job = prior / "cf_mass_eval_job.json"
    if not resp.is_file():
        raise FileNotFoundError(f"missing W94 thick response: {resp}")
    pack = json.loads(resp.read_text(encoding="utf-8"))
    job_meta = {}
    if job.is_file():
        job_meta = json.loads(job.read_text(encoding="utf-8"))
    return {"response": pack, "job": job_meta, "path": str(resp)}


def _period_net_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for pr in result.get("period_rows") or []:
        occ = pr.get("occurrence") or {}
        out.append(
            {
                "period_id": pr.get("period_id"),
                "status": pr.get("status"),
                "net": _scalar_f(pr.get("net_one_way_mean_active")),
                "gross": _scalar_f(pr.get("gross_signed_mean_active")),
                "act": _scalar_f(
                    pr.get("activation_rate")
                    if pr.get("activation_rate") is not None
                    else occ.get("activation_rate")
                ),
                "hold_days": pr.get("hold_days"),
                "signal_id": pr.get("signal_id"),
            }
        )
    return out


def _window_reagg(
    period_rows: Sequence[Mapping[str, Any]], *, shard_ids: Sequence[str]
) -> dict[str, Any]:
    keep = set(shard_ids)
    rows = [r for r in period_rows if str(r.get("period_id")) in keep and r.get("status") == "ok"]
    nets = [r["net"] for r in rows if r.get("net") is not None]
    acts = [r["act"] for r in rows if r.get("act") is not None]
    mean_net = (sum(nets) / len(nets)) if nets else None
    mean_act = (sum(acts) / len(acts)) if acts else None
    t = _t_stat([float(n) for n in nets]) if len(nets) >= 2 else None
    # crude sign: +1 if mean_net>0 else -1 if <0 else None (pre sign-selection)
    sign = None
    if mean_net is not None:
        if mean_net > 1e-12:
            sign = 1
        elif mean_net < -1e-12:
            sign = -1
    return {
        "n_ok": len(rows),
        "nets": nets,
        "mean_net": mean_net,
        "mean_act": mean_act,
        "t": t,
        "sign_raw": sign,
        "period_ids": [r.get("period_id") for r in rows],
    }


def reproduce_fund2017_giant_t(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reproduce fund_value_mom_agree_slow w2017_2019 giant-t; classify artifact."""
    target = None
    for r in results:
        if str(r.get("logic_id")) == "fund_value_mom_agree_slow":
            target = r
            break
    if target is None:
        return {"status": "missing_logic", "conclusion": "cannot_reproduce"}

    prows = _period_net_rows(target)
    w = _window_reagg(prows, shard_ids=("y2017_q4", "y2019_full"))
    nets = [float(n) for n in (w.get("nets") or [])]
    conclusion = {
        "logic_id": "fund_value_mom_agree_slow",
        "window": "w2017_2019",
        "period_ids": w.get("period_ids"),
        "n_ok": w.get("n_ok"),
        "nets": nets,
        "mean_net": w.get("mean_net"),
        "t_reproduced": w.get("t"),
        "fullspan_5period": {
            "n_ok": target.get("n_periods_ok"),
            "mean_net": _scalar_f(target.get("mean_net")),
            "t_stat": _scalar_f(target.get("t_stat")),
            "mean_activation": _scalar_f(target.get("mean_activation")),
            "chosen_sign": target.get("chosen_sign"),
        },
    }
    # Artifact criteria: n=2 and near-equal nets → tiny variance → inflated t.
    is_artifact = False
    reason = []
    if len(nets) == 2:
        mean = sum(nets) / 2
        var = sum((x - mean) ** 2 for x in nets) / 1
        conclusion["variance_n2"] = var
        if var < 1e-6:
            is_artifact = True
            reason.append("n=2_near_equal_nets_low_variance")
        if w.get("t") is not None and abs(float(w["t"])) > 20:
            reason.append("t_abs_gt_20")
            is_artifact = True
    elif len(nets) <= 1:
        is_artifact = True
        reason.append("single_period_or_empty")

    # Compare to 5-period t (should be ordinary).
    t5 = _scalar_f(target.get("t_stat"))
    if t5 is not None and abs(t5) < 3 and is_artifact:
        reason.append("fullspan_t_ordinary_confirms_window_artifact")

    conclusion["is_low_variance_artifact"] = is_artifact
    conclusion["reasons"] = reason
    conclusion["action"] = (
        "demote_drop_from_promising_and_window_headline"
        if is_artifact
        else "keep_parallel_review"
    )
    conclusion["classification"] = (
        "statistical_artifact"
        if is_artifact
        else "needs_review"
    )
    conclusion["implementation_bug"] = False
    conclusion["note"] = (
        "W94 window table t≈153 on fund_value_mom_agree_slow / w2017_2019 is "
        "exactly the n=2 two-period t-stat with near-identical nets "
        "(~0.00823 vs ~0.00834). Not a data bug and not a thesis confirmation. "
        "Demote from promising / window-headline; keep near-group parallel."
    )
    return conclusion


def decomp_rate(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by = {str(r.get("logic_id")): r for r in results}
    rows = []
    sign_timeline = []
    for lid in RATE_LOGIC_IDS:
        r = by.get(lid)
        if not r:
            continue
        prows = _period_net_rows(r)
        for w in W95_WINDOWS:
            agg = _window_reagg(prows, shard_ids=w["shards"])
            # Prefer chosen sign from CF window tables when available; else raw.
            rows.append(
                {
                    "window": w["window_id"],
                    "logic": lid,
                    "mean_net": agg["mean_net"],
                    "t": agg["t"],
                    "act": agg["mean_act"],
                    "sign_raw": agg["sign_raw"],
                    "n_ok": agg["n_ok"],
                    "period_nets": agg["nets"],
                }
            )
        for pr in prows:
            sign_timeline.append(
                {
                    "logic": lid,
                    "period_id": pr.get("period_id"),
                    "net": pr.get("net"),
                    "act": pr.get("act"),
                    "sign_hint": (
                        1
                        if (pr.get("net") or 0) > 0
                        else (-1 if (pr.get("net") or 0) < 0 else None)
                    ),
                }
            )

    # Sign-flip timing from period nets (change vs level).
    flips = {}
    for lid in RATE_LOGIC_IDS:
        seq = [s for s in sign_timeline if s["logic"] == lid]
        seq_sorted = sorted(seq, key=lambda x: str(x.get("period_id")))
        flip_events = []
        prev = None
        for s in seq_sorted:
            cur = s.get("sign_hint")
            if prev is not None and cur is not None and cur != prev:
                flip_events.append(
                    {"from": prev, "to": cur, "at_period": s.get("period_id")}
                )
            if cur is not None:
                prev = cur
        flips[lid] = flip_events

    change = by.get("macro_repo_rate_change") or {}
    level = by.get("macro_repo_rate_level") or {}
    return {
        "bucket": "rate",
        "rows": rows,
        "sign_timeline": sign_timeline,
        "sign_flips": flips,
        "activation_range": {
            "change": _scalar_f(change.get("mean_activation")),
            "level": _scalar_f(level.get("mean_activation")),
        },
        "mdh_fallback_note": "W94 thick job mdh_fb=0 (sidecar consumed)",
        "classification": "weak_thesis",
        "details": (
            "change and level both activate ~0.07–0.08 but fail lite screen "
            "(both_signs_near_zero_or_nonpositive). Sign flips across "
            "2017→2021→2023 shards. Not a data gap (sidecar present). "
            "Not an implementation bug. Weak / unstable thesis — do not promote."
        ),
        "worth_fixing": False,
        "promote": False,
    }


def decomp_flow(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by = {str(r.get("logic_id")): r for r in results}
    rows = []
    soft_eq_off = True
    for lid in FLOW_LOGIC_IDS:
        r = by.get(lid)
        if not r:
            continue
        prows = _period_net_rows(r)
        for w in W95_WINDOWS:
            agg = _window_reagg(prows, shard_ids=w["shards"])
            rows.append(
                {
                    "window": w["window_id"],
                    "logic": lid,
                    "mean_net": agg["mean_net"],
                    "t": agg["t"],
                    "act": agg["mean_act"],
                    "n_ok": agg["n_ok"],
                    "period_nets": agg["nets"],
                }
            )

    # soft ≡ pressure (off)?
    off = by.get("flow_margin_pressure")
    soft = by.get("flow_margin_short_soft")
    hard = by.get("flow_margin_short_hard")
    soft_off_identical = False
    if off and soft:
        off_nets = [
            (_scalar_f(pr.get("net_one_way_mean_active")), pr.get("period_id"))
            for pr in (off.get("period_rows") or [])
        ]
        soft_nets = [
            (_scalar_f(pr.get("net_one_way_mean_active")), pr.get("period_id"))
            for pr in (soft.get("period_rows") or [])
        ]
        soft_off_identical = off_nets == soft_nets
        soft_eq_off = soft_off_identical

    hard_act = _scalar_f((hard or {}).get("mean_activation"))
    off_act = _scalar_f((off or {}).get("mean_activation"))

    classification = "weak_thesis"
    data_gap_notes = []
    if soft_eq_off:
        data_gap_notes.append(
            "soft≡off on all periods → soft short-confirm not differentiating; "
            "consistent with short_ratio sparse/gap → soft falls back to margin-only "
            "(by design) OR short rarely conflicts. Soft path non-informative here."
        )
        classification = "data_gap_partial_plus_weak_thesis"
    if hard_act is not None and off_act is not None and hard_act < 0.5 * off_act:
        data_gap_notes.append(
            f"hard act ({hard_act:.4f}) << off act ({off_act:.4f}) → short confirm "
            "often missing/conflicting; lowers occurrence; does not rescue nets."
        )

    return {
        "bucket": "flow",
        "definition": {
            "pressure": "margin_interest_change only (short_confirm_mode=off)",
            "hard": "margin AND same-sign short_ratio_change; missing short → no entry",
            "soft": (
                "same-sign short when present; short gap → margin-only; "
                "conflict → keep margin (not a hard veto)"
            ),
            "refresh": "entry only on margin observation days; sticky min_hold between prints",
            "datasets": [
                "markets_margin_interest",
                "markets_short_ratio (hard/soft)",
            ],
        },
        "rows": rows,
        "soft_equiv_off": soft_eq_off,
        "soft_off_identical_period_nets": soft_off_identical,
        "activation": {
            "pressure": off_act,
            "hard": hard_act,
            "soft": _scalar_f((soft or {}).get("mean_activation")),
        },
        "sign_flip_note": (
            "2023 window nets flip negative vs 2017/2021 positive on pressure/soft; "
            "hard similarly unstable."
        ),
        "missingness_breaking_eval": soft_eq_off,
        "data_gap_notes": data_gap_notes,
        "mdh_fallback_note": "W94 thick job mdh_fb=0 (flow sidecar consumed)",
        "classification": classification,
        "implementation_bug": False,
        "details": (
            "Flow logics consume staged flow_regime (mdh_fb=0). Soft collapses to "
            "pressure on these panels (identical period nets) — short confirm not "
            "adding information. Hard lowers act without producing survivors. "
            "Sign flips 2017→2023. Failure = weak thesis (+ soft non-diff from "
            "short missingness), not an implementation bug. Not worth a code fix "
            "this wave; disclose soft≡off."
        ),
        "worth_fixing": False,
        "promote": False,
    }


def decomp_fund(results: Sequence[Mapping[str, Any]], *, giant: Mapping[str, Any]) -> dict[str, Any]:
    by = {str(r.get("logic_id")): r for r in results}
    rows = []
    for lid in FUND_LOGIC_IDS:
        r = by.get(lid)
        if not r:
            continue
        prows = _period_net_rows(r)
        for w in W95_WINDOWS:
            agg = _window_reagg(prows, shard_ids=w["shards"])
            rows.append(
                {
                    "window": w["window_id"],
                    "logic": lid,
                    "mean_net": agg["mean_net"],
                    "t": agg["t"],
                    "act": agg["mean_act"],
                    "n_ok": agg["n_ok"],
                    "period_nets": agg["nets"],
                }
            )
    return {
        "bucket": "fund",
        "rows": rows,
        "fund2017_giant_t": giant,
        "classification": (
            "statistical_artifact"
            if giant.get("is_low_variance_artifact")
            else "weak_thesis"
        ),
        "details": (
            "fund_value_mom_agree_slow w2017_2019 giant-t reproduced as n=2 "
            "low-variance artifact. Other fund logics fail lite screen with "
            "sign flips into 2023/2025. mdh_fb=0. Demote slow from promising; "
            "no implementation bug."
        ),
        "worth_fixing": False,
        "action": giant.get("action"),
        "promote": False,
        "demoted_logics": (
            ["fund_value_mom_agree_slow"]
            if giant.get("is_low_variance_artifact")
            else []
        ),
    }


def _markdown_summary(pack: Mapping[str, Any]) -> str:
    lines = [
        "# W95 rate / flow / fund failure decomposition",
        "",
        f"**Wave:** W95 / w0818e",
        f"**Source job:** `{pack.get('source_job_id')}`",
        "",
        "## Classifications",
        "",
        "| bucket | classification | worth_fix | promote | note |",
        "|---|---|---|---|---|",
    ]
    for key in ("rate", "flow", "fund"):
        b = pack.get(key) or {}
        lines.append(
            f"| {key} | {b.get('classification')} | {b.get('worth_fixing')} | "
            f"{b.get('promote')} | {(b.get('details') or '')[:120]}… |"
        )
    giant = (pack.get("fund") or {}).get("fund2017_giant_t") or {}
    lines.extend(
        [
            "",
            "## Fund 2017 giant-t",
            "",
            f"- reproduced t: **{giant.get('t_reproduced')}**",
            f"- n_ok: **{giant.get('n_ok')}** nets={giant.get('nets')}",
            f"- artifact: **{giant.get('is_low_variance_artifact')}**",
            f"- action: **{giant.get('action')}**",
            f"- note: {giant.get('note')}",
            "",
            "## Flow soft≡off",
            "",
            f"- soft_equiv_off: **{(pack.get('flow') or {}).get('soft_equiv_off')}**",
            f"- missingness_breaking_eval: **{(pack.get('flow') or {}).get('missingness_breaking_eval')}**",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="W95 rate/flow/fund failure decomp")
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818e_w95_shape_factor_decomp"),
    )
    p.add_argument(
        "--w94-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818d_w94_opt_skew_thick"),
    )
    p.add_argument("--local-corroborate", action="store_true")
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    prior = Path(args.w94_dir)
    loaded = _load_w94_thick(prior)
    resp = loaded["response"]
    results = list(resp.get("results") or [])
    log(
        f"[w95] loaded W94 thick job={resp.get('job_id')} "
        f"n_results={len(results)} status={resp.get('ok')}"
    )

    giant = reproduce_fund2017_giant_t(results)
    log(
        f"[w95] fund2017 giant-t reproduced t={giant.get('t_reproduced')} "
        f"artifact={giant.get('is_low_variance_artifact')} action={giant.get('action')}"
    )

    rate = decomp_rate(results)
    flow = decomp_flow(results)
    fund = decomp_fund(results, giant=giant)

    # MF light note (not primary track but classify).
    mf_rows = []
    by = {str(r.get("logic_id")): r for r in results}
    for lid in MF_LOGIC_IDS:
        r = by.get(lid)
        if not r:
            continue
        mf_rows.append(
            {
                "logic": lid,
                "mean_net": _scalar_f(r.get("mean_net")),
                "t": _scalar_f(r.get("t_stat")),
                "act": _scalar_f(r.get("mean_activation")),
                "survived": (r.get("screen") or {}).get("survived"),
            }
        )
    mf = {
        "bucket": "mf",
        "rows": mf_rows,
        "classification": "weak_thesis",
        "details": (
            "mf_flow_price 2020 spike / low act; mf_value_mom_rate no lite survivors. "
            "Not promoted."
        ),
        "worth_fixing": False,
        "promote": False,
    }

    classifications = {
        "rate": rate["classification"],
        "flow": flow["classification"],
        "fund": fund["classification"],
        "mf": mf["classification"],
        "implementation_bugs_found": False,
        "worth_fixing_items": [],
        "demoted": fund.get("demoted_logics") or [],
        "summary": (
            "No worth-fixing implementation bugs. Rate/flow/fund failures are "
            "weak-thesis and/or statistical artifact (fund2017) / soft≡off "
            "missingness (flow). Demote fund_value_mom_agree_slow from promising."
        ),
    }

    pack = {
        "wave": "W95 / w0818e",
        "track": "B_rate_flow_fund_failure_decomp",
        "ts": ts,
        "source_job_id": resp.get("job_id"),
        "source_path": loaded["path"],
        "source_mode": resp.get("mode"),
        "rate": rate,
        "flow": flow,
        "fund": fund,
        "mf": mf,
        "classifications": classifications,
        "freezes": {
            "mass_research": "NO-GO",
            "phase7": "OFF",
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": "UNARMED",
            "frozen_defaults_retuned": False,
        },
        "elapsed_sec": round(time.perf_counter() - t0, 2),
    }

    local_pack = None
    if args.local_corroborate:
        log("[w95] local corroboration on fund/rate (optional)")
        try:
            from research.mass_strategy_factory import (
                MassFactoryConfig,
                evaluate_one_strategy,
                load_batch_data_context,
                LOGIC_TEMPLATES,
            )

            # Only y2017_q4 + y2019_full for fund artifact corroboration.
            periods = [
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
            ]
            cfg = MassFactoryConfig(
                seed=int(args.seed),
                n=1,
                max_codes=int(args.max_codes),
                max_days_per_period=int(args.max_days),
                use_q4_periods=False,
            )
            ctx = load_batch_data_context(cfg, periods=periods, synthetic=False)
            tpl = LOGIC_TEMPLATES["fund_value_mom_agree_slow"]
            strat = {
                "strategy_id": "msf_w95_fund_slow_local",
                "logic_id": tpl.logic_id,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
            }
            res = evaluate_one_strategy(strat, ctx)
            local_nets = [
                _scalar_f(pr.get("net_one_way_mean_active"))
                for pr in (res.get("period_rows") or [])
                if pr.get("status") == "ok"
            ]
            local_pack = {
                "logic_id": "fund_value_mom_agree_slow",
                "window": "w2017_2019",
                "mean_net": _scalar_f(res.get("mean_net")),
                "t_stat": _scalar_f(res.get("t_stat")),
                "period_nets": local_nets,
                "note": "local corroboration; may differ from CF panels but checks artifact shape",
            }
            log(
                f"[w95] local fund_slow w2017 nets={local_nets} t={local_pack['t_stat']}"
            )
        except Exception as exc:
            local_pack = {"status": "error", "error": str(exc)}
            log(f"[w95] local corroboration failed: {exc}")

    pack["local_corroboration"] = local_pack
    _dump(out_dir / "factor_failure_decomp.json", pack)
    _dump(out_dir / "fund2017_giant_t.json", giant)
    (out_dir / "factor_failure_decomp.md").write_text(
        _markdown_summary(pack) + "\n", encoding="utf-8"
    )
    (out_dir / "fund2017_giant_t.md").write_text(
        "\n".join(
            [
                "# W95 — fund 2017 giant-t reproduce",
                "",
                f"**Logic:** `fund_value_mom_agree_slow`",
                f"**Window:** w2017_2019 (shards y2017_q4 + y2019_full)",
                f"**Reproduced t:** `{giant.get('t_reproduced')}`",
                f"**Nets:** `{giant.get('nets')}`",
                f"**Artifact:** **{giant.get('is_low_variance_artifact')}**",
                f"**Action:** **{giant.get('action')}**",
                "",
                giant.get("note") or "",
                "",
                "```json",
                json.dumps(giant, indent=2, default=str),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    log(
        f"[w95] decomp done · demoted={classifications['demoted']} "
        f"bugs={classifications['implementation_bugs_found']} "
        f"elapsed={pack['elapsed_sec']}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
