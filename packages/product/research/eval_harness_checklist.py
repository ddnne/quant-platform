"""Standard research eval checklist v2 (W56 next-day; not candidate SoT).

``evaluate_checklist_v2_completeness`` + checklist document.
Runner: :mod:`research.eval_harness_standard`. Mass/READY/GO closed.
"""

from __future__ import annotations

from typing import Any

from research.eval_harness import _closed_flags


CHECKLIST_VERSION: str = "standard-research-eval-checklist/v2"
CHECKLIST_VERSION_V1: str = "standard-research-eval-checklist/v1"
STANDARD_EVAL_DAILY_PATH_DD_PROOF: str = (
    "docs/proof/w0819c_w100_daily_path_dd_gate_20260819.md"
)
COST_MODEL_PREFER_REPO_LINKED: bool = True
COST_MODEL_REQUIRE_REPO_LINKED: bool = False
COST_MODEL_PREFER_LIQUIDITY_LINKED: bool = True
COST_MODEL_REQUIRE_LIQUIDITY_LINKED: bool = False
STANDARD_EVAL_MODES: tuple[str, ...] = (
    "wiring_only",
    "s1_rejected_baseline",
    "s4_rejected_baseline",
    "class_hyp_offline",
)

# Checklist v2 required item ids (order is documentation-stable).
CHECKLIST_V2_REQUIRED: tuple[str, ...] = (
    "multi_year_or_non_overlapping_long_periods",
    "cost_assumption_default_10bp_one_way",
    "leverage_short_cost_assumptions",
    "robustness_gate_v2_with_cost",
    "explicit_data_gap_disclosure",
    "risk_scenario_evaluation",
    "daily_path_dd",
    "pass_does_not_connect_ready_mass_go",
)
CHECKLIST_V2_NEAR_REQUIRED: tuple[str, ...] = (
    "holding_turnover_metrics",  # near-required for high-frequency hyps
)
CHECKLIST_V2_INSUFFICIENT: tuple[str, ...] = (
    "short_window_only",
    "gross_only_without_cost_gate",
    "skipped_checklist",
    "incomplete_leverage_short_costs",
    "incomplete_risk_scenarios",
    "scenario_sign_break_undisclosed",
    "period_net_dd_only_pass",
    "period_net_dd_zero_daily_unmeasured",
)


def standard_research_eval_checklist_document() -> dict[str, Any]:
    """Public document for the standard research evaluation checklist (v2)."""
    from research.cost_models import COST_MODELS_VERSION, COST_MODELS_WAVE

    return {
        "version": CHECKLIST_VERSION,
        "prior_version": CHECKLIST_VERSION_V1,
        "daily_path_dd_proof": STANDARD_EVAL_DAILY_PATH_DD_PROOF,
        "required": list(CHECKLIST_V2_REQUIRED),
        "near_required": list(CHECKLIST_V2_NEAR_REQUIRED),
        "recommended": [
            "holding_turnover_metrics",
            "repo_linked_cost_model",
            "liquidity_linked_cost_model",
        ],
        "insufficient": list(CHECKLIST_V2_INSUFFICIENT),
        "cost_models_surface": {
            "version": COST_MODELS_VERSION,
            "wave": COST_MODELS_WAVE,
        },
        "cost_model_defaults": {
            "prefer_repo_linked": COST_MODEL_PREFER_REPO_LINKED,
            "require_repo_linked": COST_MODEL_REQUIRE_REPO_LINKED,
            "prefer_liquidity_linked": COST_MODEL_PREFER_LIQUIDITY_LINKED,
            "require_liquidity_linked": COST_MODEL_REQUIRE_LIQUIDITY_LINKED,
        },
        "daily_path_dd_surface": {"period_net_dd_only_pass_forbidden": True},
        "default_entry": "run_standard_research_eval",
        "research_candidate": False,
        "incomplete_checklist_blocks_research_candidate": True,
        **_closed_flags(),
    }


def evaluate_checklist_v2_completeness(
    *,
    multi_year_present: bool,
    cost_assumption_present: bool,
    leverage_short_complete: bool,
    robustness_gate_present: bool,
    data_gap_disclosed: bool,
    risk_scenarios_passed: bool,
    risk_scenarios_candidate_allowed: bool,
    freeze_closed: bool,
    holding_present: bool = False,
    high_frequency_hyp: bool = False,
    require_holding_for_hf: bool = True,
    checklist_skipped: bool = False,
    daily_path_dd_complete: bool = False,
    period_net_dd_only: bool = False,
    period_net_dd_zero_daily_unmeasured: bool = False,
) -> dict[str, Any]:
    """Incomplete → not candidate. Complete still does not auto-promote."""
    hf_req = bool(high_frequency_hyp and require_holding_for_hf)
    flags: list[tuple[str, bool, bool]] = [
        ("multi_year_or_non_overlapping_long_periods", bool(multi_year_present), bool(multi_year_present)),
        ("cost_assumption_default_10bp_one_way", bool(cost_assumption_present), bool(cost_assumption_present)),
        ("leverage_short_cost_assumptions", bool(leverage_short_complete), bool(leverage_short_complete)),
        ("robustness_gate_v2_with_cost", bool(robustness_gate_present), bool(robustness_gate_present)),
        ("explicit_data_gap_disclosure", bool(data_gap_disclosed), bool(data_gap_disclosed)),
        (
            "risk_scenario_evaluation",
            bool(risk_scenarios_passed),
            bool(risk_scenarios_passed) and bool(risk_scenarios_candidate_allowed),
        ),
        (
            "daily_path_dd",
            bool(daily_path_dd_complete),
            bool(daily_path_dd_complete) and not bool(period_net_dd_only),
        ),
        ("pass_does_not_connect_ready_mass_go", bool(freeze_closed), bool(freeze_closed)),
    ]
    items: dict[str, Any] = {
        k: {"required": True, "present": present, "passed": passed}
        for k, present, passed in flags
    }
    items["risk_scenario_evaluation"].update(
        scenario_passed=bool(risk_scenarios_passed),
        scenario_candidate_allowed=bool(risk_scenarios_candidate_allowed),
    )
    items["daily_path_dd"].update(
        period_net_dd_only_pass_forbidden=True,
        period_net_dd_only=bool(period_net_dd_only),
        period_net_dd_zero_daily_unmeasured=bool(period_net_dd_zero_daily_unmeasured),
    )
    items["holding_turnover_metrics"] = {
        "required": hf_req,
        "near_required": True,
        "present": bool(holding_present),
        "passed": bool(holding_present) if hf_req else True,
        "high_frequency_hyp": bool(high_frequency_hyp),
    }
    missing = [k for k, v in items.items() if v.get("required") and not v.get("passed")]
    if checklist_skipped:
        missing = list(dict.fromkeys([*missing, "checklist_skipped"]))
    complete = not missing and not checklist_skipped
    return {
        "version": CHECKLIST_VERSION,
        "complete": bool(complete),
        "research_candidate_allowed": bool(complete),
        "missing_required": missing,
        "items": items,
        "period_net_dd_only": bool(period_net_dd_only),
        "period_net_dd_zero_daily_unmeasured": bool(
            period_net_dd_zero_daily_unmeasured
        ),
        **_closed_flags(),
    }


__all__ = [
    "CHECKLIST_VERSION",
    "CHECKLIST_VERSION_V1",
    "CHECKLIST_V2_INSUFFICIENT",
    "CHECKLIST_V2_NEAR_REQUIRED",
    "CHECKLIST_V2_REQUIRED",
    "COST_MODEL_PREFER_LIQUIDITY_LINKED",
    "COST_MODEL_PREFER_REPO_LINKED",
    "COST_MODEL_REQUIRE_LIQUIDITY_LINKED",
    "COST_MODEL_REQUIRE_REPO_LINKED",
    "STANDARD_EVAL_DAILY_PATH_DD_PROOF",
    "STANDARD_EVAL_MODES",
    "evaluate_checklist_v2_completeness",
    "standard_research_eval_checklist_document",
]
