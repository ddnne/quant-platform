#!/usr/bin/env python3
"""W98 / w0819a Track C — xs_rank_ls_sticky deep-dive (NO GO / NO main promote).

Gates: multi-year + cost + PIT + low-var.
Outputs: subperiod stability / DD proxy / activation tables.
Forbidden this wave:
  * hold/mom micro-grid
  * 3-default pin retune
  * promote_as_main / GO / Mass / READY / live

``relatively better`` may be recorded; promote/GO remain False.
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819a_w98_otc_master_xs"
CF_WORKER_URL = "https://quant-platform-research-mass-eval.taku-haga.workers.dev"

LOGIC_ID = "xs_rank_ls_sticky"

W98_WINDOWS: tuple[dict[str, Any], ...] = (
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


def _all_shards() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in W98_WINDOWS:
        for s in w["shards"]:
            out.append(dict(s))
    return out


def _assert_frozen_pins_untouched() -> dict[str, Any]:
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
        "note": "W98 sticky deep-dive must not mutate 3-default pins",
    }
    if not ok:
        raise RuntimeError(
            "FROZEN_DEFAULT_PATH drift — abort W98 sticky deep: "
            + json.dumps(details, default=str)
        )
    return pack


def _period_dd_proxy(nets: Sequence[float | None]) -> dict[str, Any]:
    """Period-level cumulative-sum max DD proxy (not daily equity curve)."""
    from research.stats_metrics import max_drawdown

    vals = [float(v) for v in nets if v is not None and math.isfinite(float(v))]
    if not vals:
        return {"max_dd": None, "n": 0, "method": "period_net_cumsum_proxy"}
    # Treat each period mean-net as a step return for DD proxy.
    dd = max_drawdown(vals)
    return {
        "max_dd": dd.get("max_dd") if isinstance(dd, Mapping) else dd,
        "n": len(vals),
        "method": "period_net_cumsum_proxy",
        "period_nets": vals,
        "note": (
            "Proxy only — CF mass-eval returns period aggregates, not daily "
            "equity curves. Not a live risk number."
        ),
    }


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
    dd_proxy = _period_dd_proxy(side_nets)
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
        "max_dd_proxy": dd_proxy.get("max_dd"),
        "dd_proxy": dd_proxy,
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


def _sign_int(chosen: Any) -> int | None:
    if chosen in (1, "1", "original", "ORIGINAL", "SIGN_ORIGINAL"):
        return 1
    if chosen in (-1, "-1", "inverted", "INVERTED", "SIGN_INVERTED"):
        return -1
    try:
        from research.sign_selection import SIGN_INVERTED, SIGN_ORIGINAL

        if chosen == SIGN_ORIGINAL:
            return 1
        if chosen == SIGN_INVERTED:
            return -1
    except Exception:
        pass
    return None


def _row_from_pack(pack: Mapping[str, Any], *, window_id: str, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "window": window_id,
        "logic_id": pack.get("logic_id") or LOGIC_ID,
        "family_id": pack.get("family_id"),
        "mean_net": pack.get("mean_net"),
        "t": pack.get("t_stat"),
        "t_stat_reason": pack.get("t_stat_reason"),
        "raw_t_stat": pack.get("raw_t_stat"),
        "low_variance_artifact": bool(pack.get("low_variance_artifact")),
        "act": pack.get("mean_activation"),
        "sharpe": pack.get("sharpe_period"),
        "max_dd_proxy": pack.get("max_dd_proxy"),
        "sign": _sign_int(pack.get("chosen_sign")),
        "survived": bool(pack.get("survived")),
        "reject_reasons": list(pack.get("reject_reasons") or []),
        "n_periods_ok": pack.get("n_periods_ok"),
        "n_periods_total": pack.get("n_periods_total"),
        "params": pack.get("params"),
    }


def _activation_table(period_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in period_rows:
        ar = r.get("activation_rate")
        if ar is None:
            occ = r.get("occurrence") or {}
            ar = occ.get("activation_rate")
        rows.append(
            {
                "period_id": r.get("period_id"),
                "year": r.get("year"),
                "status": r.get("status"),
                "activation_rate": _scalar_f(ar),
                "n_active_positions": r.get("n_active_positions"),
                "net_one_way_mean_active": _scalar_f(r.get("net_one_way_mean_active")),
                "gross_signed_mean_active": _scalar_f(r.get("gross_signed_mean_active")),
                "amortized_one_way_cost": _scalar_f(r.get("amortized_one_way_cost")),
                "hold_days": r.get("hold_days"),
            }
        )
    return rows


def _subperiod_stability(period_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ok = [r for r in period_rows if r.get("status") == "ok"]
    nets = [_scalar_f(r.get("net_one_way_mean_active")) for r in ok]
    nets_ok = [n for n in nets if n is not None]
    signs = [1 if (n is not None and n >= 0) else (-1 if n is not None else None) for n in nets]
    signs_i = [s for s in signs if s is not None]
    act = [_scalar_f(r.get("activation_rate")) for r in ok]
    act_ok = [a for a in act if a is not None]
    dd = _period_dd_proxy(nets_ok)
    return {
        "n_ok": len(ok),
        "period_ids": [r.get("period_id") for r in ok],
        "period_nets": nets_ok,
        "sign_per_period": signs_i,
        "sign_flip_across_subperiods": len(set(signs_i)) > 1 if len(signs_i) >= 2 else False,
        "mean_net": (sum(nets_ok) / len(nets_ok)) if nets_ok else None,
        "min_net": min(nets_ok) if nets_ok else None,
        "max_net": max(nets_ok) if nets_ok else None,
        "mean_activation": (sum(act_ok) / len(act_ok)) if act_ok else None,
        "min_activation": min(act_ok) if act_ok else None,
        "max_activation": max(act_ok) if act_ok else None,
        "dd_proxy": dd,
        "all_positive_net": bool(nets_ok) and all(n > 0 for n in nets_ok),
    }


def _classify(window_rows: Sequence[Mapping[str, Any]], sub: Mapping[str, Any]) -> dict[str, Any]:
    n_win = len(window_rows)
    n_surv = sum(1 for r in window_rows if r.get("survived"))
    signs = [r.get("sign") for r in window_rows if r.get("sign") in (-1, 1)]
    signs_i = [int(s) for s in signs]
    sign_flip = len(set(signs_i)) > 1 if len(signs_i) >= 2 else False
    any_low_var = any(bool(r.get("low_variance_artifact")) for r in window_rows)
    nets = [_scalar_f(r.get("mean_net")) for r in window_rows]
    nets_ok = [n for n in nets if n is not None]
    ts = [_scalar_f(r.get("t")) for r in window_rows]
    ts_ok = [t for t in ts if t is not None]
    acts = [_scalar_f(r.get("act")) for r in window_rows]
    acts_ok = [a for a in acts if a is not None]
    dds = [_scalar_f(r.get("max_dd_proxy")) for r in window_rows]
    dds_ok = [d for d in dds if d is not None]

    relatively_better = bool(
        n_surv == n_win
        and not sign_flip
        and not any_low_var
        and nets_ok
        and all(n > 0 for n in nets_ok)
        and not sub.get("sign_flip_across_subperiods")
    )
    if n_surv == n_win and not sign_flip and not any_low_var:
        stance = "STABLE_RESEARCH_ONLY"
    elif n_surv == 0 or any_low_var:
        stance = "WEAK_OR_UNSTABLE_RESEARCH_ONLY"
    else:
        stance = "UNSTABLE_RESEARCH_ONLY"

    return {
        "logic_id": LOGIC_ID,
        "stance": stance,
        "n_windows": n_win,
        "n_survived_windows": n_surv,
        "sign_flip": sign_flip,
        "signs": signs_i,
        "any_low_var": any_low_var,
        "mean_net_avg": (sum(nets_ok) / len(nets_ok)) if nets_ok else None,
        "t_avg": (sum(ts_ok) / len(ts_ok)) if ts_ok else None,
        "act_avg": (sum(acts_ok) / len(acts_ok)) if acts_ok else None,
        "max_dd_proxy_worst": min(dds_ok) if dds_ok else None,
        "relatively_better": relatively_better,
        "promote_as_main": False,
        "go_eligible": False,
        "research_only": True,
        "hold_mom_microgrid": False,
        "pins_retuned": False,
        "note": (
            "W98 sticky deep-dive: relatively_better may be True but "
            "promote_as_main/GO remain False (policy freeze)."
        ),
    }


def _markdown(
    *,
    window_rows: Sequence[Mapping[str, Any]],
    activation: Sequence[Mapping[str, Any]],
    sub: Mapping[str, Any],
    classification: Mapping[str, Any],
    job_id: str | None,
) -> str:
    lines = [
        "# W98 / w0819a — `xs_rank_ls_sticky` deep-dive",
        "",
        f"**job_id:** `{job_id or 'n/a'}`",
        f"**stance:** `{classification.get('stance')}`",
        f"**relatively_better:** `{classification.get('relatively_better')}`",
        f"**promote_as_main:** `{classification.get('promote_as_main')}`",
        f"**go_eligible:** `{classification.get('go_eligible')}`",
        "",
        "## Window table (cost + PIT + sign + low-var)",
        "",
        "| window | mean_net | t | act | sharpe | max_dd_proxy | sign | survived | low_var |",
        "|--------|---------:|--:|----:|-------:|-------------:|-----:|:--------:|:-------:|",
    ]
    for r in window_rows:
        def fmt(x: Any, nd: int = 4) -> str:
            v = _scalar_f(x)
            return f"{v:.{nd}f}" if v is not None else "—"

        lines.append(
            f"| {r.get('window')} | {fmt(r.get('mean_net'), 6)} | {fmt(r.get('t'), 4)} | "
            f"{fmt(r.get('act'), 4)} | {fmt(r.get('sharpe'), 3)} | {fmt(r.get('max_dd_proxy'), 4)} | "
            f"{r.get('sign')} | {r.get('survived')} | {r.get('low_variance_artifact')} |"
        )
    lines += [
        "",
        "## Subperiod stability",
        "",
        f"- n_ok: **{sub.get('n_ok')}**",
        f"- period_ids: `{sub.get('period_ids')}`",
        f"- sign_flip_across_subperiods: **{sub.get('sign_flip_across_subperiods')}**",
        f"- mean_net / min / max: "
        f"{sub.get('mean_net')} / {sub.get('min_net')} / {sub.get('max_net')}",
        f"- mean_activation / min / max: "
        f"{sub.get('mean_activation')} / {sub.get('min_activation')} / {sub.get('max_activation')}",
        f"- dd_proxy.max_dd: **{(sub.get('dd_proxy') or {}).get('max_dd')}** "
        f"({(sub.get('dd_proxy') or {}).get('method')})",
        f"- all_positive_net: **{sub.get('all_positive_net')}**",
        "",
        "## Activation table",
        "",
        "| period_id | year | act | n_active | net | gross | cost | hold |",
        "|-----------|-----:|----:|---------:|----:|------:|-----:|-----:|",
    ]
    for a in activation:
        def fmt(x: Any, nd: int = 4) -> str:
            v = _scalar_f(x)
            return f"{v:.{nd}f}" if v is not None else "—"

        lines.append(
            f"| {a.get('period_id')} | {a.get('year')} | {fmt(a.get('activation_rate'), 4)} | "
            f"{a.get('n_active_positions')} | {fmt(a.get('net_one_way_mean_active'), 6)} | "
            f"{fmt(a.get('gross_signed_mean_active'), 6)} | "
            f"{fmt(a.get('amortized_one_way_cost'), 6)} | {a.get('hold_days')} |"
        )
    lines += [
        "",
        "## Policy",
        "",
        "- NO hold/mom micro-grid",
        "- NO 3-default pin retune",
        "- promote_as_main = **False** · go_eligible = **False** · research_only = **True**",
        "- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED",
        "",
        "GLM5.3 only. Grok did not implement.",
        "",
    ]
    return "\n".join(lines)


def run_cf(
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
    from research.mass_strategy_factory import MassFactoryConfig

    status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status_sticky_deep.json", status)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"w98-sticky-{ts}"
    shards = _all_shards()
    log(
        f"[w98/C] CF sticky job_id={job_id} mode={mode} "
        f"n_shards={len(shards)} cf={CF_MASS_EVAL_VERSION}"
    )
    try:
        cf_pack = run_cf_mass_eval_job(
            job_id=job_id,
            logic_ids=[LOGIC_ID],
            extra_logics=[],
            periods=shards,
            mode=str(mode),
            max_codes=int(max_codes),
            max_days=min(int(max_days), 120),
            seed=int(seed),
            worker_url=str(worker_url),
            deploy_if_needed=not bool(skip_deploy),
            stage_panels=(mode == "r2_panels"),
            staging_dir=out_dir / "panels_stage_sticky",
        )
    except Exception as exc:
        log(f"[w98/C] CF sticky failed: {exc}")
        cf_pack = {
            "status": "error",
            "error": str(exc),
            "job_id": job_id,
            "mode": mode,
        }
    _dump(out_dir / "cf_sticky_deep_job.json", cf_pack)
    wr = cf_pack.get("worker_response") or {}
    if not wr and isinstance(cf_pack.get("results"), list):
        wr = cf_pack
    if wr:
        _dump(out_dir / "cf_sticky_deep_response.json", wr)

    cfg = MassFactoryConfig()
    raw = None
    for r in wr.get("results") or []:
        if isinstance(r, Mapping) and str(r.get("logic_id") or "") == LOGIC_ID:
            raw = dict(r)
            break

    window_rows: list[dict[str, Any]] = []
    if raw is None:
        for w in W98_WINDOWS:
            window_rows.append(
                {
                    "source": f"cf_{mode}",
                    "window": w["window_id"],
                    "logic_id": LOGIC_ID,
                    "mean_net": None,
                    "t": None,
                    "act": None,
                    "sign": None,
                    "survived": False,
                    "reject_reasons": ["missing_cf_result"],
                    "low_variance_artifact": False,
                    "max_dd_proxy": None,
                }
            )
        activation: list[dict[str, Any]] = []
        sub = _subperiod_stability([])
    else:
        for w in W98_WINDOWS:
            keep = {s["period_id"] for s in w["shards"]}
            pack = _reaggregate_window(
                raw,
                keep_period_ids=keep,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            row = _row_from_pack(
                pack,
                window_id=str(w["window_id"]),
                source="cf_r2_panels" if mode == "r2_panels" else f"cf_{mode}",
            )
            row["job_id"] = cf_pack.get("job_id") or job_id
            window_rows.append(row)
        activation = _activation_table(raw.get("period_rows") or [])
        sub = _subperiod_stability(raw.get("period_rows") or [])

    classification = _classify(window_rows, sub)
    # Hard freeze — never promote / GO even if relatively_better.
    classification["promote_as_main"] = False
    classification["go_eligible"] = False
    classification["research_only"] = True

    out = {
        "wave": "W98 / w0819a",
        "track": "C_xs_rank_ls_sticky_deep",
        "logic_id": LOGIC_ID,
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "status": cf_pack.get("status"),
        "version": CF_MASS_EVAL_VERSION,
        "gates": ["cost", "PIT", "sign", "low_var", "multi_year"],
        "window_rows": window_rows,
        "activation_table": activation,
        "subperiod_stability": sub,
        "classification": classification,
        "promote_as_main": False,
        "go_eligible": False,
        "research_only": True,
        "hold_mom_microgrid": False,
        "pins_retuned": False,
        "relatively_better": classification.get("relatively_better"),
    }
    _dump(out_dir / "sticky_deep.json", out)
    _dump(out_dir / "sticky_window_table.json", window_rows)
    _dump(out_dir / "sticky_activation_table.json", activation)
    _dump(out_dir / "sticky_subperiod_stability.json", sub)
    _dump(out_dir / "sticky_classification.json", classification)
    md = _markdown(
        window_rows=window_rows,
        activation=activation,
        sub=sub,
        classification=classification,
        job_id=out.get("job_id"),
    )
    (out_dir / "sticky_deep_table.md").write_text(md, encoding="utf-8")
    log(
        f"[w98/C] sticky done status={cf_pack.get('status')} "
        f"stance={classification.get('stance')} "
        f"relatively_better={classification.get('relatively_better')} "
        f"promote={classification.get('promote_as_main')} "
        f"GO={classification.get('go_eligible')}"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--seed", type=int, default=880819)
    p.add_argument("--max-codes", type=int, default=12)
    p.add_argument("--max-days", type=int, default=120)
    p.add_argument("--mode", type=str, default="r2_panels")
    p.add_argument("--worker-url", type=str, default=CF_WORKER_URL)
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--skip-cf", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "sticky_deep.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w98/C] pins_untouched={pins['pins_untouched']}")

    if args.skip_cf:
        log("[w98/C] CF skipped")
        sticky = {"status": "skipped", "promote_as_main": False, "go_eligible": False}
    else:
        sticky = run_cf(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            mode=str(args.mode),
            worker_url=str(args.worker_url),
            skip_deploy=bool(args.skip_deploy),
            log=log,
        )

    summary = {
        "wave": "W98 / w0819a",
        "track": "C_xs_rank_ls_sticky_deep",
        "logic_id": LOGIC_ID,
        "pins_untouched": pins.get("pins_untouched"),
        "status": sticky.get("status"),
        "job_id": sticky.get("job_id"),
        "stance": (sticky.get("classification") or {}).get("stance"),
        "relatively_better": sticky.get("relatively_better"),
        "promote_as_main": False,
        "go_eligible": False,
        "research_only": True,
        "hold_mom_microgrid": False,
        "pins_retuned": False,
        "wall_sec": round(time.time() - t0, 1),
        "implementer": "GLM5.3 only. Grok did not implement.",
    }
    _dump(out_dir / "sticky_deep_summary.json", summary)
    log(f"[w98/C] SUMMARY {json.dumps(summary, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
