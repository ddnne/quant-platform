"""Standard eval mode dispatch (W56 next-day; not candidate SoT).

wiring_only / s1_rejected_baseline / s4_rejected_baseline / class_hyp_offline.
Public imports stay on :mod:`research.eval_harness` /
:mod:`research.eval_harness_standard`. Mass/READY/GO closed.
"""

from __future__ import annotations

from typing import Any, Mapping

from features.minimal_signal import SIGNAL_ID as DEFAULT_SIGNAL_ID
from research.eval_harness import EvalHarnessError, _closed_flags
from research.eval_loaders import load_repo_rows_from_sqlite
from research.eval_universe import DEFAULT_SQLITE
from research.robustness_gate import evaluate_research_robustness_gate

_S4_SIGNAL_ID = "c21_margin_change_sign"
_HISTORY_KEYS = (
    "job_id_prefix",
    "codes",
    "max_days",
    "min_days",
    "feature_row_limit",
    "write_per_day_artifacts",
    "dry_run",
    "d1_execute",
    "r2_put",
    "staging_dir",
    "wrangler",
    "wrangler_config",
    "history_source",
    "r2_get",
    "r2_bucket",
    "apply_robustness_gate",
    "min_periods_gate",
    "min_active_per_period",
    "require_net_sign_majority",
)


def _history_eval_kw(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "years": None,
        "one_way_cost": ctx["cost"],
        **{k: ctx[k] for k in _HISTORY_KEYS},
    }


def _mark_rejected_demo(
    baseline_demo: dict[str, Any],
    signal_id: str,
    hyp_id: str,
    **extra: Any,
) -> None:
    from research.baseline_catalog import is_research_baseline_rejected

    baseline_demo["signal_id"] = signal_id
    baseline_demo["hyp_id"] = hyp_id
    baseline_demo["still_rejected"] = is_research_baseline_rejected(signal_id)
    baseline_demo.update(extra)


def _require_rejected(signal_id: str, mode: str) -> None:
    from research.baseline_catalog import is_research_baseline_rejected

    if not is_research_baseline_rejected(signal_id):
        raise EvalHarnessError(
            f"{mode} requires catalog rejection of {signal_id}"
        )


def _mode_out(ctx: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    out = {
        "steps": [],
        "multi_year": None,
        "class_hyp": None,
        "gate": None,
        "holding_records": ctx.get("holding_records"),
        "scenario_rows": ctx.get("scenario_rows"),
        "rate_data_usable": ctx.get("rate_data_usable", False),
        "repo_series_norm": ctx.get("repo_series_norm"),
    }
    out.update(extra)
    return out


def _mode_class_hyp(ctx: Mapping[str, Any]) -> dict[str, Any]:
    from research.cost_models import load_repo_rate_series_from_rows
    from research.offline.multiyear import run_class_hyp_multi_year_eval

    class_hyp_bundle = run_class_hyp_multi_year_eval(
        ctx["designed"] if ctx["periods_given"] else None,
        codes=ctx.get("codes"),
        one_way_cost=ctx["cost"],
        max_days=ctx["max_days"],
        min_periods_gate=ctx["min_periods_gate"],
        min_active_per_period=ctx["min_active_per_period"],
        apply_robustness_gate=ctx["apply_robustness_gate"],
    )
    md_block = class_hyp_bundle.get("multi_day_hold") or {}
    demo = ctx["baseline_demo"]
    demo["signal_id"] = md_block.get("signal_id")
    demo["hypothesis_class"] = "multi_day_hold"
    demo["class_signals"] = True
    demo["new_signals_registered"] = True
    demo["candidate_summary"] = class_hyp_bundle.get("candidate_summary")
    holding_records = ctx.get("holding_records")
    if ctx.get("include_holding") and md_block.get("holding") is not None:
        holding_records = None
    steps = ["class_hyp_offline_multi_year"]
    if ctx["apply_robustness_gate"]:
        steps.append("robustness_gate_v2")
    scenario_rows = ctx.get("scenario_rows")
    if scenario_rows is None:
        risk_from_md = md_block.get("risk_scenarios")
        risk_from_macro = (class_hyp_bundle.get("macro_conditioned") or {}).get(
            "risk_scenarios"
        )
        if isinstance(risk_from_md, Mapping) and risk_from_md.get("scenario_rows"):
            scenario_rows = list(risk_from_md.get("scenario_rows") or [])
        elif isinstance(risk_from_macro, Mapping) and risk_from_macro.get(
            "scenario_rows"
        ):
            scenario_rows = list(risk_from_macro.get("scenario_rows") or [])
    rate_data_usable = True
    repo_series_norm = ctx.get("repo_series_norm")
    if repo_series_norm is None and class_hyp_bundle.get("repo_load"):
        try:
            _rows = load_repo_rows_from_sqlite(DEFAULT_SQLITE)
            if _rows:
                repo_series_norm = load_repo_rate_series_from_rows(_rows)
        except Exception:  # noqa: BLE001 — non-fatal disclosure path
            pass
    return _mode_out(
        ctx,
        steps=steps,
        multi_year=class_hyp_bundle,
        class_hyp=class_hyp_bundle,
        gate=md_block.get("robustness_gate"),
        holding_records=holding_records,
        scenario_rows=scenario_rows,
        rate_data_usable=rate_data_usable,
        repo_series_norm=repo_series_norm,
    )


def _mode_wiring(ctx: Mapping[str, Any]) -> dict[str, Any]:
    steps = ["wiring_only_no_heavy_r2"]
    mode_s = ctx["mode_s"]
    demo = ctx["baseline_demo"]
    gate_signal_id = DEFAULT_SIGNAL_ID
    if mode_s == "s1_rejected_baseline":
        _mark_rejected_demo(demo, DEFAULT_SIGNAL_ID, "S1")
    elif mode_s == "s4_rejected_baseline":
        gate_signal_id = _S4_SIGNAL_ID
        _mark_rejected_demo(demo, gate_signal_id, "S4")
    gate: dict[str, Any] | None = None
    rows = ctx.get("period_rows_for_gate")
    if rows is not None and ctx["apply_robustness_gate"]:
        gate = evaluate_research_robustness_gate(
            rows,
            signal_id=gate_signal_id,
            min_periods=ctx["min_periods_gate"],
            min_active_per_period=ctx["min_active_per_period"],
            one_way_cost=ctx["cost"],
            require_net_sign_majority=ctx["require_net_sign_majority"],
        )
        steps.append("robustness_gate_v2")
    elif ctx["apply_robustness_gate"]:
        gate = {
            **_closed_flags(),
            "passed": False,
            "reasons": ["wiring_only_no_period_metrics"],
            "signal_id": gate_signal_id,
        }
        steps.append("robustness_gate_v2_surface")
    designed = ctx["designed"]
    return _mode_out(
        ctx,
        steps=steps,
        multi_year={"status": "wiring_only", "n_years_designed": len(designed)},
        gate=gate,
    )


def _mode_s1(ctx: Mapping[str, Any]) -> dict[str, Any]:
    _require_rejected(DEFAULT_SIGNAL_ID, "s1_rejected_baseline")
    from research.eval_harness_s1 import run_multi_year_s1_eval

    multi_year = run_multi_year_s1_eval(
        ctx["designed"],
        volume_change_abs_min=ctx.get("volume_change_abs_min"),
        **_history_eval_kw(ctx),
    )
    _mark_rejected_demo(ctx["baseline_demo"], DEFAULT_SIGNAL_ID, "S1")
    return _mode_out(
        ctx,
        steps=["multi_year_s1_rejected_baseline", "robustness_gate_v2"],
        multi_year=multi_year,
        gate=multi_year.get("robustness_gate"),
    )


def _mode_s4(ctx: Mapping[str, Any]) -> dict[str, Any]:
    _require_rejected(_S4_SIGNAL_ID, "s4_rejected_baseline")
    from research.eval_harness_extra_hyp import run_multi_year_extra_hyp_eval

    want = list(ctx["signal_ids"]) if ctx.get("signal_ids") is not None else [_S4_SIGNAL_ID]
    multi_year = run_multi_year_extra_hyp_eval(
        ctx["designed"],
        signal_ids=want,
        **_history_eval_kw(ctx),
    )
    gates = multi_year.get("robustness_gates") or {}
    if _S4_SIGNAL_ID in gates:
        gate = gates[_S4_SIGNAL_ID]
    elif gates:
        gate = next(iter(gates.values()))
    else:
        gate = None
    _mark_rejected_demo(ctx["baseline_demo"], _S4_SIGNAL_ID, "S4", signal_ids=want)
    return _mode_out(
        ctx,
        steps=["multi_year_s4_rejected_baseline", "robustness_gate_v2"],
        multi_year=multi_year,
        gate=gate,
    )


def run_standard_eval_mode(ctx: dict[str, Any]) -> dict[str, Any]:
    """Run one standard-eval mode. Does not invent signals or auto-promote."""
    mode_s = ctx["mode_s"]
    if mode_s == "class_hyp_offline":
        return _mode_class_hyp(ctx)
    if mode_s == "wiring_only" or (
        ctx["dry_run"]
        and not ctx["executable"]
        and ctx.get("period_rows_for_gate") is None
    ):
        return _mode_wiring(ctx)
    if mode_s == "s1_rejected_baseline":
        return _mode_s1(ctx)
    if mode_s == "s4_rejected_baseline":
        return _mode_s4(ctx)
    return _mode_out(ctx)
