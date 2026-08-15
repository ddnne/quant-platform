"""Research-only simple daily sign baseline catalog (W65 / w0815bf).

Purpose
-------
Document which COMPLETE-21 simple daily sign hypotheses are fixed as
``research_baseline_rejected`` after multi-period / multi-year / cost-after
evaluation. This is a **research marker only**.

Hard constraints
----------------
* Does **not** mint READY / VerifiedResearchReadiness
* Does **not** arm Mass / Phase7
* Does **not** mass-generate signals or emit order intents
* Does **not** auto-connect gate pass/fail to operational GO
* Catalog is read-only documentation for research agents

See: ``docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md``
"""

from __future__ import annotations

from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Freeze surface (must never arm)
# ---------------------------------------------------------------------------

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False
CONNECTED_TO_READY: bool = False
CONNECTED_TO_MASS: bool = False
EDGE_CLAIMED: bool = False
SIGNIFICANCE_CLAIMED: bool = False
MASS_GENERATE_SIGNALS: bool = False

CATALOG_VERSION: str = "research-baseline-catalog/v1"
CATALOG_WAVE: str = "W65 / w0815bf"
RESEARCH_STATUS_REJECTED: str = "research_baseline_rejected"
HOLDING_PERIOD: str = "1d_nextday_close_to_close"
COST_ASSUMPTION: str = "one_way_10bp (0.001); research-only; 仮定に依存・運用GOではない"

# Signal ids (must match features.minimal_signal)
SIGNAL_ID_S1: str = "c21_topix_relative_sign"
SIGNAL_ID_S2: str = "c21_volume_change_sign"
SIGNAL_ID_S3: str = "c21_topix_rel_disclosure_filter"
SIGNAL_ID_S4: str = "c21_margin_change_sign"
SIGNAL_ID_S5: str = "c21_short_ratio_delta_sign"


def _rejected_entry(
    *,
    hyp_id: str,
    signal_id: str,
    definition: str,
    short_window_note: str,
    multi_year_gross: str,
    cost_after_multi_year: str,
    cost_gate_result: str,
    reasons: list[str],
    proof_refs: list[str],
    holding_period: str = HOLDING_PERIOD,
) -> dict[str, Any]:
    return {
        "hyp_id": hyp_id,
        "signal_id": signal_id,
        "definition": definition,
        "research_status": RESEARCH_STATUS_REJECTED,
        "wave": CATALOG_WAVE,
        "holding_period": holding_period,
        "short_window_note": short_window_note,
        "multi_year_gross": multi_year_gross,
        "cost_after_multi_year": cost_after_multi_year,
        "cost_gate_result": cost_gate_result,
        "reasons": list(reasons),
        "proof_refs": list(proof_refs),
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "edge_claimed": EDGE_CLAIMED,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "mass_generate_signals": MASS_GENERATE_SIGNALS,
        "note": (
            "research_baseline_rejected — simple daily sign fixed as non-candidate. "
            "Not READY. Not Mass. No edge. Catalog is research documentation only."
        ),
    }


# Fixed rejected simple daily sign baselines (S1–S5). Numbers live in proof docs.
REJECTED_SIMPLE_DAILY_SIGN_BASELINES: dict[str, dict[str, Any]] = {
    SIGNAL_ID_S1: _rejected_entry(
        hyp_id="S1",
        signal_id=SIGNAL_ID_S1,
        definition=(
            "sign(topix_relative_1d) if is_trading_day==1 "
            "(volume gate off by default)"
        ),
        short_window_note=(
            "W58 tip-20d gross +0.00528 illusion; W61 multi-period only mild + "
            "on w2023q4 — not stable"
        ),
        multi_year_gross=(
            "W63 Q4 6y gross soft PASS (4+/2−); "
            "y2015+0.002144 y2017−0.000363 y2019+0.001253 "
            "y2021+0.000976 y2023+0.001250 y2025−0.000901"
        ),
        cost_after_multi_year=(
            "W64 Q4 cost FAIL net +3/−3 after 10bp; "
            "full~100d 4y gross FAIL and cost FAIL"
        ),
        cost_gate_result="FAIL",
        reasons=[
            "cost_after_multi_year_destroys_gross_majority",
            "full_span_sign_majority_fails",
            "tip_window_overstated",
            "residual_after_10bp_not_strategy_scale",
        ],
        proof_refs=[
            "docs/proof/w0815bb_w61_multi_period_multisignal_20260815.md",
            "docs/proof/w0815bd_w63_multi_year_eval_20260815.md",
            "docs/proof/w0815be_w64_cost_multi_year_eval_20260815.md",
            "docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md",
        ],
    ),
    SIGNAL_ID_S2: _rejected_entry(
        hyp_id="S2",
        signal_id=SIGNAL_ID_S2,
        definition=(
            "sign(volume_change_1d) if is_trading_day==1 "
            "and |volume_change_1d| >= 0.10"
        ),
        short_window_note=(
            "W58 tip gross −0.00078; W61 fire rate 0% in 2022/2023 Q4 windows "
            "— period-dependent sparsity"
        ),
        multi_year_gross="not multi-year eval'd",
        cost_after_multi_year="not multi-year eval'd",
        cost_gate_result="not_evald",
        reasons=[
            "tip_gross_already_negative",
            "multi_period_fire_rate_unstable",
            "no_multi_year_cost_robust_majority",
            "not_promoted_to_multi_year_cost_campaign",
        ],
        proof_refs=[
            "docs/proof/w0815bb_w61_multi_period_multisignal_20260815.md",
            "docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md",
        ],
    ),
    SIGNAL_ID_S3: _rejected_entry(
        hyp_id="S3",
        signal_id=SIGNAL_ID_S3,
        definition=(
            "sign(topix_relative_1d) if is_trading_day==1 "
            "and disclosure_flag_fins==1"
        ),
        short_window_note=(
            "W58 tip sparse (~29.5% nn) gross +0.00345; W61 tracks S1 pattern; "
            "often fails after 10bp"
        ),
        multi_year_gross="not multi-year eval'd",
        cost_after_multi_year="not multi-year eval'd",
        cost_gate_result="not_evald",
        reasons=[
            "s1_dependent_primary_sign",
            "s1_already_cost_fail_multi_year",
            "multi_period_not_stable_after_cost",
            "no_independent_rescue_path",
        ],
        proof_refs=[
            "docs/proof/w0815bb_w61_multi_period_multisignal_20260815.md",
            "docs/proof/w0815be_w64_cost_multi_year_eval_20260815.md",
            "docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md",
        ],
    ),
    SIGNAL_ID_S4: _rejected_entry(
        hyp_id="S4",
        signal_id=SIGNAL_ID_S4,
        definition="sign(margin_interest_change_1d) if is_trading_day==1",
        short_window_note=(
            "W62 multi-period soft majority − (weak); w2024 empty margin gap held"
        ),
        multi_year_gross=(
            "W63 Q4 6y gross soft PASS all − "
            "(−0.000697 … −0.000104 range)"
        ),
        cost_after_multi_year=(
            "W64 Q4 cost-aware PASS all net − but weak magnitudes "
            "(~1–10bp gross; not strategy candidate)"
        ),
        cost_gate_result="PASS_weak_not_candidate",
        reasons=[
            "consistent_weak_negative_only",
            "magnitude_not_strategy_scale",
            "cost_pass_does_not_imply_go",
            "explicit_non_candidate",
        ],
        proof_refs=[
            "docs/proof/w0815bc_w62_extra_hyp_s4_s5_20260815.md",
            "docs/proof/w0815bd_w63_multi_year_eval_20260815.md",
            "docs/proof/w0815be_w64_cost_multi_year_eval_20260815.md",
            "docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md",
        ],
    ),
    SIGNAL_ID_S5: _rejected_entry(
        hyp_id="S5",
        signal_id=SIGNAL_ID_S5,
        definition=(
            "sign(Δ short_ratio_level[section=0050]) broadcast to codes "
            "if is_trading_day==1"
        ),
        short_window_note=(
            "W62 multi-period FAIL (+/− split); 2024–2025 short JSONL gaps empty"
        ),
        multi_year_gross="not multi-year eval'd",
        cost_after_multi_year="not multi-year eval'd",
        cost_gate_result="not_evald",
        reasons=[
            "multi_period_sign_majority_fail",
            "short_ratio_inventory_gaps",
            "never_multi_year_or_cost_robust",
        ],
        proof_refs=[
            "docs/proof/w0815bc_w62_extra_hyp_s4_s5_20260815.md",
            "docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md",
        ],
    ),
}


def rejected_baseline_catalog() -> dict[str, Any]:
    """Public document for the rejected simple daily sign baseline catalog."""
    return {
        "version": CATALOG_VERSION,
        "wave": CATALOG_WAVE,
        "research_status_value": RESEARCH_STATUS_REJECTED,
        "holding_period": HOLDING_PERIOD,
        "cost_assumption": COST_ASSUMPTION,
        "baselines": dict(REJECTED_SIMPLE_DAILY_SIGN_BASELINES),
        "signal_ids": list(REJECTED_SIMPLE_DAILY_SIGN_BASELINES.keys()),
        "hyp_ids": [
            e["hyp_id"] for e in REJECTED_SIMPLE_DAILY_SIGN_BASELINES.values()
        ],
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "edge_claimed": EDGE_CLAIMED,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "mass_generate_signals": MASS_GENERATE_SIGNALS,
        "note": (
            "Research-only rejected baseline catalog (W65). "
            "Does not mint READY, arm Mass, authorize orders, or claim edge. "
            "Gate pass (including cost-aware soft PASS) does not connect here."
        ),
        "proof": (
            "docs/proof/w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md"
        ),
    }


def get_rejected_baseline(signal_id: str) -> dict[str, Any] | None:
    """Return one rejected baseline entry, or None if not in catalog."""
    return REJECTED_SIMPLE_DAILY_SIGN_BASELINES.get(str(signal_id))


def is_research_baseline_rejected(signal_id: str) -> bool:
    """True iff signal_id is fixed as research_baseline_rejected."""
    entry = get_rejected_baseline(signal_id)
    if entry is None:
        return False
    return entry.get("research_status") == RESEARCH_STATUS_REJECTED


def assert_catalog_closed_to_ready_mass(
    doc: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed if catalog document ever arms READY/Mass (test helper)."""
    body = dict(doc) if doc is not None else rejected_baseline_catalog()
    if body.get("ready_declared") is not False:
        raise AssertionError("baseline catalog must keep ready_declared=False")
    if body.get("operational_go") is not False:
        raise AssertionError("baseline catalog must keep operational_go=False")
    if body.get("connected_to_ready") is not False:
        raise AssertionError("baseline catalog must keep connected_to_ready=False")
    if body.get("connected_to_mass") is not False:
        raise AssertionError("baseline catalog must keep connected_to_mass=False")
    if body.get("mass_research") != MASS_RESEARCH:
        raise AssertionError(f"baseline catalog mass_research must be {MASS_RESEARCH}")
    if body.get("phase7") != PHASE7:
        raise AssertionError(f"baseline catalog phase7 must be {PHASE7}")
    if body.get("mass_generate_signals") is not False:
        raise AssertionError("baseline catalog must not mass-generate signals")
    if body.get("edge_claimed") is not False:
        raise AssertionError("baseline catalog must not claim edge")


__all__ = [
    "CATALOG_VERSION",
    "CATALOG_WAVE",
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "COST_ASSUMPTION",
    "EDGE_CLAIMED",
    "HOLDING_PERIOD",
    "MASS_GENERATE_SIGNALS",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PHASE7",
    "READY_DECLARED",
    "REJECTED_SIMPLE_DAILY_SIGN_BASELINES",
    "RESEARCH_STATUS_REJECTED",
    "SIGNAL_ID_S1",
    "SIGNAL_ID_S2",
    "SIGNAL_ID_S3",
    "SIGNAL_ID_S4",
    "SIGNAL_ID_S5",
    "SIGNIFICANCE_CLAIMED",
    "assert_catalog_closed_to_ready_mass",
    "get_rejected_baseline",
    "is_research_baseline_rejected",
    "rejected_baseline_catalog",
]
