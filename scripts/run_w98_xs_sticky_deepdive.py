#!/usr/bin/env python3
"""W98 / w0819a tracks C+D — xs_rank_ls_sticky deep-dive + constrained hyps.

C. xs_rank_ls_sticky deep-dive (NO GO / NO main)
  windows: 2017–19 / 2020–22 / 2023–25 (honest shards)
  gates: cost + PIT + sign + low-var
  CF ``r2_panels`` preferred
  tables: window stability · subperiod · drawdown · activation
  **no** hold/mom micro-grid · **3-default pins untouched**
  Explicit ``promote_as_main=False`` · ``go=False``

D. Continue constrained hyp gen
  ``llm_hyp_generator`` v1.1+ failure constraints · xAI preferred
  reduce mapping onto known weak catalog templates · modest N
  evaluate through propose_profit_hypotheses gate

Freezes held: Mass=NO-GO · READY=false · ops GO=false · continuous paper
UNARMED · **3-default pins untouched** · no GO/live.

Examples
--------
    uv run python scripts/run_w98_xs_sticky_deepdive.py \\
        --out-dir .glm-logs/w0819a_w98_otc_master_xs/

    uv run python scripts/run_w98_xs_sticky_deepdive.py --skip-hyps --skip-local
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
CF_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)

# Honest shards (contiguous 3y bars mirrors absent) — same as W93–W97.
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

STICKY_LOGIC_ID = "xs_rank_ls_sticky"
LOGIC_IDS: tuple[str, ...] = (STICKY_LOGIC_ID,)

# Known weak / demoted families — Track D flags + reduce catalog remap.
KNOWN_WEAK_THESIS: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",
        "flow_margin_short_hard",
    }
)
KNOWN_DEMOTED_OR_WEAK: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",
        "flow_margin_short_hard",
        "flow_margin_short_soft",
        "flow_margin_pressure",
        "fund_value_mom_agree_slow",
        "opt225_skew_abs_level",
        "opt225_cm_term_abs_level",
        "opt225_basevol_delta_abs",
        "macro_repo_rate_level",
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
    for w in W98_WINDOWS:
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
        "hold_mom_micro_grid": False,
        "note": "W98 must not mutate 3-default pins; no hold/mom micro-grid",
    }
    if not ok:
        raise RuntimeError(
            "FROZEN_DEFAULT_PATH drift detected — abort before W98 C+D: "
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
        "max_dd": stats.get("max_dd") if isinstance(stats, Mapping) else None,
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
        "max_dd": _scalar_f(pack.get("max_dd")),
        "sign": pack.get("chosen_sign"),
        "survived": bool(pack.get("survived")),
        "reject_reasons": list(pack.get("reject_reasons") or []),
        "n_periods_ok": pack.get("n_periods_ok"),
        "n_periods_total": pack.get("n_periods_total"),
        "params": pack.get("params"),
        "period_rows": list(pack.get("period_rows") or []),
    }


def _markdown_window_table(rows: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| window | logic | mean_net | t | act | sharpe | max_dd | sign | surv | "
        "low_var | rejects |"
    )
    sep = "|---|---|---:|---:|---:|---:|---:|---|:---:|:---:|---|"
    lines = [header, sep]
    for r in rows:
        mn, t, act, sh, dd = (
            r.get("mean_net"),
            r.get("t"),
            r.get("act"),
            r.get("sharpe"),
            r.get("max_dd"),
        )
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sh_s = f"{sh:.3f}" if isinstance(sh, float) else "—"
        dd_s = f"{dd:.6f}" if isinstance(dd, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        rejects = ",".join(str(x) for x in (r.get("reject_reasons") or [])[:3]) or "—"
        lines.append(
            f"| {r.get('window')} | `{r.get('logic_id')}` | {mn_s} | {t_s} | "
            f"{act_s} | {sh_s} | {dd_s} | {sign_s} | {r.get('survived')} | "
            f"{r.get('low_variance_artifact')} | {rejects} |"
        )
    return "\n".join(lines)


def _build_subperiod_table(
    raw: Mapping[str, Any] | None, *, source: str
) -> dict[str, Any]:
    """Per-shard (subperiod) stability rows for sticky."""
    from research.stats_metrics import max_drawdown

    rows: list[dict[str, Any]] = []
    period_rows = list((raw or {}).get("period_rows") or [])
    chosen = (raw or {}).get("chosen_sign")
    sign_mult = -1.0 if str(chosen) in {"-1", "inverted"} else 1.0
    for pr in period_rows:
        pid = str(pr.get("period_id") or "")
        wid = None
        for w in W98_WINDOWS:
            if any(s["period_id"] == pid for s in w["shards"]):
                wid = w["window_id"]
                break
        gross = _scalar_f(pr.get("gross_signed_mean_active"))
        net = _scalar_f(pr.get("net_one_way_mean_active"))
        cost = _scalar_f(pr.get("amortized_one_way_cost"))
        act = _scalar_f(pr.get("activation_rate"))
        if act is None:
            occ = pr.get("occurrence") or {}
            act = _scalar_f(occ.get("activation_rate"))
        signed_net = (net * sign_mult) if net is not None else None
        rows.append(
            {
                "source": source,
                "window": wid,
                "period_id": pid,
                "year": pr.get("year"),
                "status": pr.get("status"),
                "gross": gross,
                "net": net,
                "signed_net": signed_net,
                "cost": cost,
                "act": act,
                "hold_days": pr.get("hold_days"),
                "n_active_positions": pr.get("n_active_positions"),
            }
        )
    signed_series = [r["signed_net"] for r in rows if r.get("status") == "ok"]
    dd = max_drawdown(signed_series)
    n_pos = sum(1 for v in signed_series if isinstance(v, float) and v > 0)
    n_neg = sum(1 for v in signed_series if isinstance(v, float) and v < 0)
    return {
        "logic_id": STICKY_LOGIC_ID,
        "source": source,
        "chosen_sign": chosen,
        "rows": rows,
        "n_ok": sum(1 for r in rows if r.get("status") == "ok"),
        "n_pos_signed": n_pos,
        "n_neg_signed": n_neg,
        "max_dd_across_subperiods": dd.get("max_dd"),
        "abs_max_dd_across_subperiods": dd.get("abs_max_dd"),
        "markdown": _markdown_subperiod(rows, chosen_sign=chosen),
    }


def _markdown_subperiod(
    rows: Sequence[Mapping[str, Any]], *, chosen_sign: Any
) -> str:
    header = (
        "| window | period | status | gross | net | signed_net | cost | act | "
        "hold | n_pos |"
    )
    sep = "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"
    lines = [
        f"chosen_sign={chosen_sign}",
        "",
        header,
        sep,
    ]
    for r in rows:
        def fmt(k: str) -> str:
            v = r.get(k)
            return f"{v:.6f}" if isinstance(v, float) else ("—" if v is None else str(v))

        lines.append(
            f"| {r.get('window')} | `{r.get('period_id')}` | {r.get('status')} | "
            f"{fmt('gross')} | {fmt('net')} | {fmt('signed_net')} | {fmt('cost')} | "
            f"{fmt('act')} | {r.get('hold_days') if r.get('hold_days') is not None else '—'} | "
            f"{r.get('n_active_positions') if r.get('n_active_positions') is not None else '—'} |"
        )
    return "\n".join(lines)


def _build_activation_table(
    raw: Mapping[str, Any] | None, *, source: str, min_activation: float
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for pr in (raw or {}).get("period_rows") or []:
        pid = str(pr.get("period_id") or "")
        wid = None
        for w in W98_WINDOWS:
            if any(s["period_id"] == pid for s in w["shards"]):
                wid = w["window_id"]
                break
        act = _scalar_f(pr.get("activation_rate"))
        if act is None:
            occ = pr.get("occurrence") or {}
            act = _scalar_f(occ.get("activation_rate"))
        below = act is not None and act < float(min_activation)
        rows.append(
            {
                "source": source,
                "window": wid,
                "period_id": pid,
                "activation_rate": act,
                "min_activation": float(min_activation),
                "below_min": below,
                "n_active_positions": pr.get("n_active_positions"),
                "status": pr.get("status"),
            }
        )
    acts = [r["activation_rate"] for r in rows if isinstance(r.get("activation_rate"), float)]
    mean_act = (sum(acts) / len(acts)) if acts else None
    header = (
        "| window | period | act | min_act | below_min | n_active_pos | status |"
    )
    sep = "|---|---|---:|---:|:---:|---:|---|"
    lines = [header, sep]
    for r in rows:
        act = r.get("activation_rate")
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        lines.append(
            f"| {r.get('window')} | `{r.get('period_id')}` | {act_s} | "
            f"{r.get('min_activation'):.4f} | {r.get('below_min')} | "
            f"{r.get('n_active_positions') if r.get('n_active_positions') is not None else '—'} | "
            f"{r.get('status')} |"
        )
    return {
        "logic_id": STICKY_LOGIC_ID,
        "source": source,
        "mean_activation": mean_act,
        "min_activation_gate": float(min_activation),
        "n_below_min": sum(1 for r in rows if r.get("below_min")),
        "rows": rows,
        "markdown": "\n".join(lines),
    }


def _build_drawdown_table(
    window_rows: Sequence[Mapping[str, Any]],
    subperiod: Mapping[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Window-level + cross-subperiod drawdown (period-net cumulative)."""
    from research.stats_metrics import max_drawdown

    win_rows: list[dict[str, Any]] = []
    for r in window_rows:
        win_rows.append(
            {
                "window": r.get("window"),
                "mean_net": r.get("mean_net"),
                "max_dd": r.get("max_dd"),
                "survived": r.get("survived"),
                "sign": r.get("sign"),
                "n_periods_ok": r.get("n_periods_ok"),
            }
        )
    # Ordered subperiod signed nets → cumulative DD path
    signed = [
        r.get("signed_net")
        for r in (subperiod.get("rows") or [])
        if r.get("status") == "ok"
    ]
    dd_all = max_drawdown(signed)
    # Per-window DD from that window's shards
    per_win_dd: list[dict[str, Any]] = []
    for w in W98_WINDOWS:
        wid = w["window_id"]
        series = [
            r.get("signed_net")
            for r in (subperiod.get("rows") or [])
            if r.get("window") == wid and r.get("status") == "ok"
        ]
        d = max_drawdown(series)
        per_win_dd.append(
            {
                "window": wid,
                "n": d.get("n"),
                "max_dd": d.get("max_dd"),
                "abs_max_dd": d.get("abs_max_dd"),
                "period_nets": series,
            }
        )
    header = "| scope | n | max_dd | abs_max_dd | note |"
    sep = "|---|---:|---:|---:|---|"
    lines = [header, sep]
    lines.append(
        f"| all_subperiods | {dd_all.get('n')} | "
        f"{dd_all.get('max_dd') if dd_all.get('max_dd') is not None else '—'} | "
        f"{dd_all.get('abs_max_dd') if dd_all.get('abs_max_dd') is not None else '—'} | "
        f"cumulative signed period-nets |"
    )
    for d in per_win_dd:
        md = d.get("max_dd")
        ad = d.get("abs_max_dd")
        lines.append(
            f"| `{d.get('window')}` | {d.get('n')} | "
            f"{md if isinstance(md, float) else '—'} | "
            f"{ad if isinstance(ad, float) else '—'} | window shards |"
        )
    return {
        "logic_id": STICKY_LOGIC_ID,
        "source": source,
        "kind": "period_nets_cumulative",
        "window_rows": win_rows,
        "across_all_subperiods": dd_all,
        "per_window": per_win_dd,
        "markdown": "\n".join(lines),
        "note": (
            "DD on cumulative sum of signed period nets (research period-level; "
            "not intraday equity curve). No hold/mom micro-grid."
        ),
    }


def _classify_sticky(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Cross-window stability — never GO/main-promote."""
    if not rows:
        return {
            "logic_id": STICKY_LOGIC_ID,
            "stance": "NO_DATA",
            "promote_as_main": False,
            "go": False,
            "go_eligible": False,
            "research_only": True,
            "reason": "no_window_rows",
        }
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
    acts = [_scalar_f(r.get("act")) for r in rows]
    acts_ok = [a for a in acts if a is not None]
    act_avg = (sum(acts_ok) / len(acts_ok)) if acts_ok else None

    reasons: list[str] = []
    if any_low_var:
        reasons.append("low_variance_artifact_in_window")
    if sign_flip:
        reasons.append("sign_flip_across_windows")
    if n_surv == 0:
        reasons.append("zero_window_survivals")
    elif n_surv < n_win:
        reasons.append("partial_window_survival")

    unstable = bool(any_low_var or sign_flip or n_surv < n_win)
    if n_surv == 0 or any_low_var:
        stance = "WEAK_OR_UNSTABLE_RESEARCH_ONLY"
    elif unstable:
        stance = "UNSTABLE_RESEARCH_ONLY"
    else:
        stance = "STABLE_RESEARCH_ONLY"

    return {
        "logic_id": STICKY_LOGIC_ID,
        "stance": stance,
        "n_windows": n_win,
        "n_survived_windows": n_surv,
        "sign_flip": sign_flip,
        "signs": signs_i,
        "any_low_var": any_low_var,
        "mean_net_avg": mean_net_avg,
        "t_avg": t_avg,
        "act_avg": act_avg,
        "reasons": reasons,
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "research_only": True,
        "note": (
            "W98 sticky deep-dive: research-only; explicit "
            "promote_as_main=false · go=false; no hold/mom micro-grid"
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

    tpl = LOGIC_TEMPLATES[STICKY_LOGIC_ID]
    strat = {
        "strategy_id": f"msf_w98_deep_{STICKY_LOGIC_ID}",
        "logic_id": STICKY_LOGIC_ID,
        "family_id": tpl.family_id,
        "params": dict(tpl.base_params),
        "thesis": tpl.thesis,
        "signal_definition": tpl.signal_definition,
        "position_rule": tpl.position_rule,
        "datasets_used": list(tpl.datasets_used),
        "variant": "sticky_deep_multi_year",
    }
    # Pin check: base params are catalog defaults — NOT a hold/mom retune.
    assert int(strat["params"]["hold_days"]) == 10
    assert int(strat["params"]["momentum_n"]) == 5

    cfg = MassFactoryConfig(
        seed=int(seed),
        n=1,
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    rows_flat: list[dict[str, Any]] = []
    raw_by_window: dict[str, dict[str, Any]] = {}
    for w in W98_WINDOWS:
        wid = str(w["window_id"])
        periods = [dict(s) for s in w["shards"]]
        log(f"[w98/C] local sticky deep {wid}")
        ctx = load_batch_data_context(cfg, periods=periods, synthetic=False)
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
        raw_by_window[wid] = res
        rows_flat.append(_row_from_pack(res, window_id=wid, source="local"))

    # Merge period rows across windows for subperiod/activation/DD tables
    merged_periods: list[dict[str, Any]] = []
    for w in W98_WINDOWS:
        wid = str(w["window_id"])
        for pr in (raw_by_window.get(wid) or {}).get("period_rows") or []:
            merged_periods.append(dict(pr))
    # Prefer first non-null chosen_sign (should be stable)
    chosen = None
    for r in rows_flat:
        if r.get("sign") is not None:
            chosen = r.get("sign")
            break
    merged_raw = {
        "logic_id": STICKY_LOGIC_ID,
        "period_rows": merged_periods,
        "chosen_sign": chosen,
        "params": dict(tpl.base_params),
    }
    subperiod = _build_subperiod_table(merged_raw, source="local")
    activation = _build_activation_table(
        merged_raw, source="local", min_activation=cfg.min_activation
    )
    drawdown = _build_drawdown_table(rows_flat, subperiod, source="local")
    classification = _classify_sticky(rows_flat)

    pack = {
        "wave": "W98 / w0819a",
        "track": "C_xs_rank_ls_sticky_deep_local",
        "logic_id": STICKY_LOGIC_ID,
        "gates": ["cost", "PIT", "sign", "low_var"],
        "params": dict(tpl.base_params),
        "hold_mom_micro_grid": False,
        "rows_flat": rows_flat,
        "classification": classification,
        "subperiod": subperiod,
        "activation": activation,
        "drawdown": drawdown,
        "n_survivors_window_rows": sum(1 for r in rows_flat if r.get("survived")),
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "markdown_table": _markdown_window_table(rows_flat),
    }
    _dump(out_dir / "sticky_deep_local.json", pack)
    (out_dir / "sticky_deep_local_table.md").write_text(
        "# W98 Track C — xs_rank_ls_sticky deep eval (local)\n\n"
        + pack["markdown_table"]
        + "\n\n## Subperiod\n\n"
        + subperiod["markdown"]
        + "\n\n## Activation\n\n"
        + activation["markdown"]
        + "\n\n## Drawdown\n\n"
        + drawdown["markdown"]
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
    _dump(out_dir / "cf_status_sticky_deep.json", status)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"w98-sticky-{ts}"
    shards = _all_shards()
    log(
        f"[w98/C] CF sticky job_id={job_id} mode={mode} "
        f"logic={STICKY_LOGIC_ID} n_shards={len(shards)} "
        f"cf={CF_MASS_EVAL_VERSION}"
    )
    try:
        cf_pack = run_cf_mass_eval_job(
            job_id=job_id,
            logic_ids=list(LOGIC_IDS),
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
    rows_flat: list[dict[str, Any]] = []
    raw_sticky: dict[str, Any] | None = None
    for r in wr.get("results") or []:
        if not isinstance(r, Mapping):
            continue
        if str(r.get("logic_id") or "") == STICKY_LOGIC_ID:
            raw_sticky = dict(r)
            break

    for w in W98_WINDOWS:
        wid = str(w["window_id"])
        keep = {s["period_id"] for s in w["shards"]}
        if raw_sticky is None:
            rows_flat.append(
                {
                    "source": f"cf_{mode}",
                    "window": wid,
                    "logic_id": STICKY_LOGIC_ID,
                    "mean_net": None,
                    "t": None,
                    "act": None,
                    "sign": None,
                    "survived": False,
                    "reject_reasons": ["missing_cf_result"],
                    "low_variance_artifact": False,
                    "max_dd": None,
                }
            )
            continue
        pack = _reaggregate_window(
            raw_sticky,
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

    subperiod = _build_subperiod_table(
        raw_sticky,
        source="cf_r2_panels" if mode == "r2_panels" else f"cf_{mode}",
    )
    activation = _build_activation_table(
        raw_sticky,
        source="cf_r2_panels" if mode == "r2_panels" else f"cf_{mode}",
        min_activation=cfg.min_activation,
    )
    drawdown = _build_drawdown_table(
        rows_flat,
        subperiod,
        source="cf_r2_panels" if mode == "r2_panels" else f"cf_{mode}",
    )
    classification = _classify_sticky(rows_flat)

    pack_out = {
        "wave": "W98 / w0819a",
        "track": "C_xs_rank_ls_sticky_deep_cf",
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "status": cf_pack.get("status"),
        "version": CF_MASS_EVAL_VERSION,
        "logic_id": STICKY_LOGIC_ID,
        "gates": ["cost", "PIT", "sign", "low_var"],
        "params": (raw_sticky or {}).get("params"),
        "hold_mom_micro_grid": False,
        "rows_flat": rows_flat,
        "classification": classification,
        "subperiod": subperiod,
        "activation": activation,
        "drawdown": drawdown,
        "raw_sticky_screen": (raw_sticky or {}).get("screen"),
        "n_survivors_job": cf_pack.get("n_survivors"),
        "n_survivors_window_rows": sum(1 for r in rows_flat if r.get("survived")),
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "markdown_table": _markdown_window_table(rows_flat),
        "promotion_note": (
            "xs_rank_ls_sticky remains research-only. Explicit "
            "promote_as_main=false · go=false. No hold/mom micro-grid. "
            "3 defaults frozen untouched."
        ),
    }
    _dump(out_dir / "sticky_deep_cf.json", pack_out)
    _dump(out_dir / "sticky_deep_cf_table.json", rows_flat)
    _dump(out_dir / "sticky_subperiod_table.json", subperiod)
    _dump(out_dir / "sticky_activation_table.json", activation)
    _dump(out_dir / "sticky_drawdown_table.json", drawdown)
    (out_dir / "sticky_deep_cf_table.md").write_text(
        "# W98 Track C — xs_rank_ls_sticky deep eval (CF r2_panels)\n\n"
        + pack_out["markdown_table"]
        + "\n\n## Subperiod stability\n\n"
        + subperiod["markdown"]
        + "\n\n## Activation\n\n"
        + activation["markdown"]
        + "\n\n## Drawdown (period-net cumulative)\n\n"
        + drawdown["markdown"]
        + "\n",
        encoding="utf-8",
    )
    log(
        f"[w98/C] CF done status={cf_pack.get('status')} "
        f"job_surv={cf_pack.get('n_survivors')} "
        f"window_surv_rows={pack_out['n_survivors_window_rows']} "
        f"stance={classification.get('stance')} "
        f"promote_as_main=False go=False"
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
        preferred = cf_pack or {}
        source = "cf_r2_panels"
    elif local_rows:
        preferred = local_pack or {}
        source = "local"
    else:
        preferred = {}
        source = "none"

    rows = list(preferred.get("rows_flat") or [])
    classification = preferred.get("classification") or _classify_sticky(rows)
    headline = (
        f"preferred={source} · logic={STICKY_LOGIC_ID} · window_surv="
        f"{sum(1 for r in rows if r.get('survived'))}/{len(rows)} · "
        f"stance={classification.get('stance')} · "
        f"sign_flip={classification.get('sign_flip')} · "
        f"low_var={classification.get('any_low_var')} · "
        "promote_as_main=false · go=false"
    )
    return {
        "wave": "W98 / w0819a",
        "track": "C_xs_rank_ls_sticky_deep",
        "preferred_source": source,
        "cf_job_id": (cf_pack or {}).get("job_id"),
        "cf_status": cf_status or None,
        "logic_id": STICKY_LOGIC_ID,
        "gates": ["cost", "PIT", "sign", "low_var"],
        "params": preferred.get("params"),
        "hold_mom_micro_grid": False,
        "rows_flat": rows,
        "classification": classification,
        "subperiod": preferred.get("subperiod"),
        "activation": preferred.get("activation"),
        "drawdown": preferred.get("drawdown"),
        "n_survivors_window_rows": sum(1 for r in rows if r.get("survived")),
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "frozen_defaults_retuned": False,
        "headline": headline,
        "markdown_table": _markdown_window_table(rows),
        "classification_md": (
            f"| logic | stance | surv_win | sign_flip | low_var | "
            f"mean_net_avg | t_avg | act_avg | main? | GO? |\n"
            f"|---|---|---:|:---:|:---:|---:|---:|---:|:---:|:---:|\n"
            f"| `{STICKY_LOGIC_ID}` | {classification.get('stance')} | "
            f"{classification.get('n_survived_windows')}/"
            f"{classification.get('n_windows')} | "
            f"{classification.get('sign_flip')} | "
            f"{classification.get('any_low_var')} | "
            f"{_fmt(classification.get('mean_net_avg'))} | "
            f"{_fmt(classification.get('t_avg'), 4)} | "
            f"{_fmt(classification.get('act_avg'), 4)} | "
            f"{classification.get('promote_as_main')} | "
            f"{classification.get('go')} |"
        ),
    }


def _fmt(v: Any, nd: int = 6) -> str:
    return f"{v:.{nd}f}" if isinstance(v, float) else "—"


def _markdown_preferred_table(table: Mapping[str, Any]) -> str:
    sub = table.get("subperiod") or {}
    act = table.get("activation") or {}
    dd = table.get("drawdown") or {}
    lines = [
        "# W98 / w0819a — Track C xs_rank_ls_sticky deep multi-year eval",
        "",
        f"**Preferred source:** `{table.get('preferred_source')}`  ",
        f"**CF job:** `{table.get('cf_job_id')}` · status `{table.get('cf_status')}`  ",
        f"**Headline:** {table.get('headline')}",
        "",
        "## Explicit stance",
        "",
        "- `promote_as_main` = **false**",
        "- `go` = **false**",
        "- hold/mom micro-grid = **not run**",
        "- 3-default pins = **untouched**",
        "",
        "## Window × logic (cost + PIT + sign + low-var)",
        "",
        table.get("markdown_table") or "_no rows_",
        "",
        "## Cross-window classification (research-only; no main/GO)",
        "",
        table.get("classification_md") or "_no classification_",
        "",
        "## Subperiod stability",
        "",
        sub.get("markdown") or "_no subperiod_",
        "",
        "## Activation table",
        "",
        act.get("markdown") or "_no activation_",
        "",
        "## Drawdown table (period-net cumulative)",
        "",
        dd.get("markdown") or "_no drawdown_",
        "",
        "## Freezes held",
        "",
        "- Mass = NO-GO · READY = false · ops GO = false · continuous paper = UNARMED",
        "- 3 default-path pins **untouched / not retuned**",
        "- No hold/mom micro-grid on sticky or defaults",
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
    resolved_provider = provider
    if provider == "auto" and key_presence.get("xai"):
        resolved_provider = "xai"
    log(
        f"[w98/D] generating n={n_hyps} provider={resolved_provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION} "
        f"reduce_weak_template_mapping=True"
    )

    gen_eval = generate_and_evaluate_hypotheses(
        n=int(n_hyps),
        provider=None if resolved_provider == "auto" else resolved_provider,
        model=model,
        worker_url=cf_url,
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
    n_skipped_weak = int(gen_eval.get("n_skipped_weak_catalog_map") or 0)

    demoted_weak_mapped: list[str] = []
    for s in gen_eval.get("eval_screens") or []:
        if not isinstance(s, Mapping) or not s.get("survived"):
            continue
        lid = str(s.get("logic_id") or "")
        if lid in KNOWN_DEMOTED_OR_WEAK or lid in KNOWN_WEAK_THESIS:
            demoted_weak_mapped.append(lid)

    # Also scan proposals for skipped weak maps / remaining weak maps
    skipped_ids = []
    mapped_ids = []
    for p in gen_eval.get("proposals_for_eval") or []:
        if not isinstance(p, Mapping):
            continue
        if p.get("skipped_weak_catalog_map"):
            skipped_ids.append(str(p.get("skipped_weak_catalog_map")))
        if p.get("eval_mapped_to_catalog") and p.get("logic_id") in KNOWN_DEMOTED_OR_WEAK:
            mapped_ids.append(str(p.get("logic_id")))

    summary = {
        "wave": "W98 / w0819a",
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
        "n_skipped_weak_catalog_map": n_skipped_weak or len(skipped_ids),
        "skipped_weak_catalog_targets": sorted(set(skipped_ids)),
        "weak_mapped_despite_reduce": sorted(set(mapped_ids)),
        "representative_theses": theses,
        "demoted_weak_mapped_survivors": sorted(set(demoted_weak_mapped)),
        "do_not_resurrect_as_main": True,
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
        "gates": ["cost", "PIT", "low_var"],
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
        f"[w98/D] n_proposed={n_proposed} n_accepted={n_accepted} "
        f"n_rejected={summary['n_rejected']} "
        f"(gen={n_gen_rejected}+eval={n_eval_rejected}) "
        f"n_survivors={n_survivors} n_skipped_weak_map="
        f"{summary['n_skipped_weak_catalog_map']} model={gen_eval.get('model')}"
    )
    for th in theses[:8]:
        log(
            f"  · {th.get('logic_id')}: "
            f"{str(th.get('thesis') or '')[:120]}"
        )
    if demoted_weak_mapped:
        log(
            "[w98/D] demoted/weak mapped survivors (research-only, not main): "
            + ", ".join(sorted(set(demoted_weak_mapped)))
        )
    return {"summary": summary, "gen_eval": gen_eval}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--n-hyps", type=int, default=6, help="modest N for Track D")
    p.add_argument("--seed", type=int, default=870819)
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

    log(f"[w98] out={out_dir} ts={ts}")
    pin_check = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pin_check)
    log(
        f"[w98] freezes: mass={MASS_RESEARCH} phase7={PHASE7} "
        f"paper={CONTINUOUS_PAPER} READY=False ops_GO=False "
        f"frozen_defaults_retuned=False pins_untouched="
        f"{pin_check['pins_untouched']} factory={MASS_FACTORY_VERSION} "
        f"hold_mom_micro_grid=False"
    )
    log(
        "[w98] 3 defaults frozen (untouched): "
        + ", ".join(
            f"{r['representative_id']}={r['stance']}" for r in FROZEN_DEFAULT_PATH
        )
    )
    log(f"[w98/C] logic={STICKY_LOGIC_ID} promote_as_main=false go=false")

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
            f"[w98/C] local window_surv_rows="
            f"{local_pack.get('n_survivors_window_rows')}"
        )
    else:
        log("[w98/C] local skipped")

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
        log("[w98/C] CF skipped")

    table = _aggregate_preferred(local_pack=local_pack, cf_pack=cf_pack)
    _dump(out_dir / "sticky_deep_table.json", table)
    md = _markdown_preferred_table(table)
    (out_dir / "sticky_deep_table.md").write_text(md + "\n", encoding="utf-8")
    # Convenience aliases for the four required tables
    if table.get("subperiod"):
        _dump(out_dir / "sticky_subperiod_preferred.json", table["subperiod"])
    if table.get("activation"):
        _dump(out_dir / "sticky_activation_preferred.json", table["activation"])
    if table.get("drawdown"):
        _dump(out_dir / "sticky_drawdown_preferred.json", table["drawdown"])
    log(
        f"[w98/C] wrote sticky_deep_table.json/md "
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
        log("[w98/D] hyps skipped")

    hyp_summary = (hyp_pack or {}).get("summary") or {}
    wall = round(time.perf_counter() - t0, 2)
    pin_check_after = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert_after.json", pin_check_after)

    run_summary = {
        "wave": "W98 / w0819a",
        "tracks": ["C_xs_rank_ls_sticky_deep", "D_constrained_hyp_gen"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_sec": wall,
        "sticky_deep": {
            "preferred_source": table.get("preferred_source"),
            "cf_job_id": table.get("cf_job_id"),
            "cf_status": table.get("cf_status"),
            "logic_id": STICKY_LOGIC_ID,
            "n_survivors_window_rows": table.get("n_survivors_window_rows"),
            "classification": table.get("classification"),
            "headline": table.get("headline"),
            "promote_as_main": False,
            "go": False,
            "hold_mom_micro_grid": False,
        },
        "hyps": {
            "n_requested": hyp_summary.get("n_requested"),
            "n_proposed": hyp_summary.get("n_proposed"),
            "n_accepted": hyp_summary.get("n_accepted"),
            "n_rejected": hyp_summary.get("n_rejected"),
            "n_evaluated": hyp_summary.get("n_evaluated"),
            "n_survivors": hyp_summary.get("n_survivors"),
            "n_skipped_weak_catalog_map": hyp_summary.get(
                "n_skipped_weak_catalog_map"
            ),
            "provider": hyp_summary.get("provider"),
            "model": hyp_summary.get("model"),
            "representative_theses": hyp_summary.get("representative_theses"),
            "demoted_weak_mapped_survivors": hyp_summary.get(
                "demoted_weak_mapped_survivors"
            ),
            "reduce_weak_template_mapping": True,
            "do_not_resurrect_as_main": True,
            "promote_as_main": False,
            "go": False,
        },
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "continuous_paper": CONTINUOUS_PAPER,
            "ready_declared": False,
            "operational_go": False,
            "frozen_defaults_retuned": False,
            "pins_untouched": pin_check_after.get("pins_untouched"),
            "hold_mom_micro_grid": False,
        },
    }
    _dump(out_dir / "w98_cd_summary.json", run_summary)
    log(f"[w98] done wall_sec={wall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
