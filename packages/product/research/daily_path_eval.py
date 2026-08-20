"""Candidate-grade daily MTM path helpers (extracted from wave scripts).

CF ``research-mass-eval`` returns period aggregates only. Daily equity-curve
drawdown lives here. New code should import this module instead of
``scripts/run_w99_sticky_daily_dd``.

Does not arm Mass / READY / GO. Does not retune frozen default pins.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.eval_windows import FROZEN_PIN_SNAPSHOT, HONEST_3Y_WINDOWS
from research.stats_metrics import (
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
)

W99_WINDOWS = HONEST_3Y_WINDOWS

EVAL_PROTOCOL: str = "daily_path_mtm_after_cost/v1"
R2_EVAL_PREFIX: str = "research/eval"


def dump_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def git_sha(*, cwd: Path | None = None) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd is not None else None,
            text=True,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def fmt(v: Any, nd: int = 6) -> str:
    x = scalar_f(v)
    return f"{x:.{nd}f}" if x is not None else "—"


def assert_frozen_pins_untouched(
    *,
    note: str = "daily_path_eval must not mutate 3-default pins",
) -> dict[str, Any]:
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
                },
                "match": match,
            }
        )
    pack = {
        "pins_untouched": ok,
        "n_pins": len(FROZEN_DEFAULT_PATH),
        "details": details,
        "frozen_defaults_retuned": False,
        "note": note,
    }
    if not ok:
        raise RuntimeError(
            "FROZEN_DEFAULT_PATH drift — abort daily_path_eval: "
            + json.dumps(details, default=str)
        )
    return pack


def load_shard_bars(
    shard: Mapping[str, Any],
    *,
    codes: Sequence[str],
    max_days: int,
) -> dict[str, Any]:
    from research.class_hyp_eval import (
        bars_rich_to_close_panel,
        load_bars_ndjson_rich,
        resolve_bars_path,
    )

    pid = str(shard.get("period_id"))
    p_start = str(shard.get("period_start") or "")[:10] or None
    p_end = str(shard.get("period_end") or "")[:10] or None
    bars_path = resolve_bars_path(pid)
    if bars_path is None or not Path(bars_path).exists():
        return {
            "period_id": pid,
            "status": "missing_bars",
            "bars": {},
            "bars_path": None,
            "period_start": p_start,
            "period_end": p_end,
            "year": shard.get("year"),
        }
    rich = load_bars_ndjson_rich(
        bars_path,
        codes=list(codes),
        max_days=int(max_days),
        period_start=p_start,
        period_end=p_end,
    )
    bars = bars_rich_to_close_panel(rich)
    return {
        "period_id": pid,
        "status": "ok" if bars else "empty_bars",
        "bars": bars,
        "bars_path": str(bars_path),
        "period_start": p_start,
        "period_end": p_end,
        "year": shard.get("year"),
        "n_codes": len(bars),
        "n_days_max": max((len(v) for v in bars.values()), default=0),
    }


def summarize_path(pack: Mapping[str, Any]) -> dict[str, Any]:
    dd = pack.get("drawdown") or {}
    gate = pack.get("daily_path_dd_gate") or {}
    return {
        "status": pack.get("status"),
        "logic_id": pack.get("logic_id"),
        "n_equity_points": pack.get("n_equity_points"),
        "n_active_days": pack.get("n_active_days"),
        "mean_gross_daily": pack.get("mean_gross_daily"),
        "mean_net_daily": pack.get("mean_net_daily"),
        "total_return_gross": pack.get("total_return_gross"),
        "total_return_net": pack.get("total_return_net"),
        "period_ref_net_mean_active": pack.get("period_ref_net_mean_active"),
        "period_ref_gross_mean_active": pack.get("period_ref_gross_mean_active"),
        "daily_path_DD": dd.get("max_dd") if "daily_path_DD" not in pack else pack.get("daily_path_DD"),
        "max_dd": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "dd_duration_days": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "daily_path_measured": gate.get("measured"),
        "daily_path_complete": gate.get("complete"),
        "data_path": pack.get("data_path"),
        "n_gated_off_days": pack.get("n_gated_off_days"),
        "n_gate_on_days": pack.get("n_gate_on_days"),
    }


def stitch_net(nets: Sequence[float], dates: Sequence[str]) -> dict[str, Any]:
    if not nets:
        return {
            "n_equity_points": 0,
            "total_return_net": None,
            "daily_path_DD": None,
        }
    eq = 1.0
    equities: list[float] = []
    for i, net in enumerate(nets):
        if i == 0:
            equities.append(eq)
        else:
            eq = eq * (1.0 + float(net))
            equities.append(eq)
    dd = equity_path_drawdown(equities, list(dates))
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=dd.get("max_dd"),
        dd_duration=dd.get("dd_duration_days"),
        recovered=dd.get("recovered"),
        recovery_days=dd.get("recovery_days"),
        total_ret_net=dd.get("total_return"),
        method="daily_equity_level_peak_to_trough",
    )
    return {
        "n_equity_points": len(equities),
        "total_return_net": dd.get("total_return"),
        "daily_path_DD": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "drawdown": dd,
        "daily_path_dd_gate": {
            "complete": gate.get("complete"),
            "measured": gate.get("measured"),
            "fails": gate.get("fails"),
            "warnings": gate.get("warnings"),
        },
        "equities": equities,
        "dates": list(dates),
    }


# Wave-script aliases (do not add new run_w* files; import these names).
_dump = dump_json
_scalar_f = scalar_f
_fmt = fmt
_assert_frozen_pins_untouched = assert_frozen_pins_untouched
_load_shard_bars = load_shard_bars
_summarize_path = summarize_path
_stitch_net = stitch_net
