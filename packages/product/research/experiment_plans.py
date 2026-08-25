"""Typed ExperimentPlan shortlist. Exactly four plans. Pilot start stays off.

This is a new explicit list of four plan ids. It is not a catalog rewrite
and does not dump active catalog IDs into a pilot. execution_enabled is
false. start() remains capability-off.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from qp_paths import repo_root
from research.artifacts import (
    CORE_RESEARCH_DATA_PROFILE_ID,
    EXPERIMENT_PLAN_VERSION,
    ExperimentPlan,
)
from research.dependency_closure import (
    PlanDependencyClosure,
    build_plan_dependency_closure,
    experiment_plan_digest,
)
from research.eval_flags import CATALOG_AND_PLUS_N_STOPPED, RECONSTITUTION_APPLY
from research.research_data_profile import (
    ResearchDataProfile,
    profile_from_dependency_closure,
)
from selection.budget_ledger import MassResearchDisabledError

SCHEMA_REL = Path("specs") / "experiment_plans" / "schema.json"
PLANS_REL = Path("specs") / "experiment_plans"
SCHEMA_NAME = "schema.json"

# Explicit shortlist. Not catalog_active.pilot_candidates() / n_active.
PILOT_EXPERIMENT_PLAN_IDS: tuple[str, ...] = (
    "exp-mdh-hold10-momentum",
    "exp-xs-hold10-mom5",
    "exp-event-post-hold5",
    "exp-fund-hold10-value-mom",
)
PILOT_PLAN_COUNT: int = 4
PILOT_EXECUTION_ENABLED: bool = False
PILOT_COST_SCENARIO: str = "default_one_way_10bp"
PILOT_EVALUATION_PROTOCOL: str = "standard_research_eval"
PILOT_RISK_POLICY: str = "core_crash_high_vol"
PILOT_PERIOD_START: str = "2023-01-04"
PILOT_PERIOD_END: str = "2023-10-13"


def experiment_plans_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / PLANS_REL


def experiment_plan_schema_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / SCHEMA_REL


def load_experiment_plan_schema(*, root: Path | None = None) -> dict[str, Any]:
    path = experiment_plan_schema_path(root=root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("ExperimentPlan schema must be an object")
    if raw.get("additionalProperties") is not False:
        raise ValueError("ExperimentPlan schema must set additionalProperties false")
    if raw.get("properties", {}).get("execution_enabled", {}).get("const") is not False:
        raise ValueError("ExperimentPlan schema execution_enabled must be const false")
    if (
        raw.get("properties", {}).get("version", {}).get("const")
        != EXPERIMENT_PLAN_VERSION
    ):
        raise ValueError("ExperimentPlan schema version is not in codec lockstep")
    return dict(raw)


def _require_typed_payload(payload: Mapping[str, Any]) -> ExperimentPlan:
    plan = ExperimentPlan.from_dict(payload)
    if not plan.hypothesis:
        raise ValueError(f"{plan.plan_id}: human idea (hypothesis) required")
    if not plan.feature_refs:
        raise ValueError(f"{plan.plan_id}: feature_refs required")
    if plan.research_data_profile_id != CORE_RESEARCH_DATA_PROFILE_ID:
        raise ValueError(
            f"{plan.plan_id}: research_data_profile_id must be "
            f"{CORE_RESEARCH_DATA_PROFILE_ID!r}"
        )
    if plan.execution_enabled is not False or PILOT_EXECUTION_ENABLED is not False:
        raise ValueError(f"{plan.plan_id}: execution_enabled must stay false")
    if payload.get("execution_enabled") is not False:
        raise ValueError(f"{plan.plan_id}: execution_enabled must be false")
    if plan.version != EXPERIMENT_PLAN_VERSION:
        raise ValueError(f"{plan.plan_id}: version must be {EXPERIMENT_PLAN_VERSION}")
    if not plan.period_start or not plan.period_end:
        raise ValueError(f"{plan.plan_id}: period required")
    if not plan.cost_scenario:
        raise ValueError(f"{plan.plan_id}: cost required")
    if not plan.evaluation_protocol:
        raise ValueError(f"{plan.plan_id}: evaluation_protocol required")
    if plan.risk_policy != PILOT_RISK_POLICY:
        raise ValueError(f"{plan.plan_id}: risk_policy must be {PILOT_RISK_POLICY!r}")
    build_plan_dependency_closure(plan)
    return plan


def load_experiment_plans(*, root: Path | None = None) -> tuple[ExperimentPlan, ...]:
    """Load the explicit four-plan shortlist. Does not rewrite the catalog."""
    if PILOT_EXECUTION_ENABLED is not False:
        raise MassResearchDisabledError("pilot execution switch must stay off")
    if len(PILOT_EXPERIMENT_PLAN_IDS) != PILOT_PLAN_COUNT:
        raise ValueError(
            f"PILOT_EXPERIMENT_PLAN_IDS must have length {PILOT_PLAN_COUNT}"
        )
    if len(set(PILOT_EXPERIMENT_PLAN_IDS)) != PILOT_PLAN_COUNT:
        raise ValueError("PILOT_EXPERIMENT_PLAN_IDS cannot contain duplicates")
    directory = experiment_plans_dir(root=root)
    expected_names = {f"{pid}.json" for pid in PILOT_EXPERIMENT_PLAN_IDS} | {SCHEMA_NAME}
    found_names = {p.name for p in directory.glob("*.json")}
    if found_names != expected_names:
        raise ValueError(
            "experiment_plans must be exactly 4 JSON files plus schema.json "
            f"(found {sorted(found_names)})"
        )
    load_experiment_plan_schema(root=root)
    plans: list[ExperimentPlan] = []
    for plan_id in PILOT_EXPERIMENT_PLAN_IDS:
        path = directory / f"{plan_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path.name} must be an object")
        plan = _require_typed_payload(raw)
        if plan.plan_id != plan_id:
            raise ValueError(f"{path.name}: plan_id {plan.plan_id!r} != {plan_id!r}")
        plans.append(plan)
    if len(plans) != PILOT_PLAN_COUNT:
        raise ValueError(f"expected exactly {PILOT_PLAN_COUNT} ExperimentPlans")
    if len({plan.plan_id for plan in plans}) != PILOT_PLAN_COUNT:
        raise ValueError("duplicate ExperimentPlan plan_id")
    if len({plan.idea_id for plan in plans}) != PILOT_PLAN_COUNT:
        raise ValueError("duplicate ExperimentPlan idea_id")
    if len(
        {
            (
                plan.strategy_spec_id,
                plan.strategy_spec_version,
                plan.strategy_spec_hash,
            )
            for plan in plans
        }
    ) != PILOT_PLAN_COUNT:
        raise ValueError("duplicate exact StrategySpec across ExperimentPlans")
    if len({experiment_plan_digest(plan) for plan in plans}) != PILOT_PLAN_COUNT:
        raise ValueError("duplicate ExperimentPlan canonical digest")
    closures = tuple(build_plan_dependency_closure(plan) for plan in plans)
    if len({closure.closure_digest for closure in closures}) != PILOT_PLAN_COUNT:
        raise ValueError("duplicate PlanDependencyClosure digest")
    return tuple(plans)


def load_experiment_plan_closures(
    *, root: Path | None = None
) -> tuple[PlanDependencyClosure, ...]:
    """Compile the exact dependency closure for each of the four plans."""
    return tuple(
        build_plan_dependency_closure(plan)
        for plan in load_experiment_plans(root=root)
    )


def load_experiment_plan_profiles(
    *, root: Path | None = None
) -> tuple[ResearchDataProfile, ...]:
    """Materialize one digest-bound ResearchDataProfile v2 per closure."""
    return tuple(
        profile_from_dependency_closure(closure)
        for closure in load_experiment_plan_closures(root=root)
    )


def start(*_args: object, **_kwargs: object) -> None:
    """Pilot execution stays off. Does not start mass or Phase 7."""
    from research.pilot_loop import start as _pilot_start

    if PILOT_EXECUTION_ENABLED is not False:
        raise MassResearchDisabledError("pilot execution switch must stay off")
    if CATALOG_AND_PLUS_N_STOPPED is not True:
        raise MassResearchDisabledError("AND+N freeze must stay true")
    if RECONSTITUTION_APPLY is not False:
        raise MassResearchDisabledError("reconstitution apply must stay false")
    _pilot_start()


__all__ = [
    "PILOT_COST_SCENARIO",
    "PILOT_EVALUATION_PROTOCOL",
    "PILOT_EXECUTION_ENABLED",
    "PILOT_EXPERIMENT_PLAN_IDS",
    "PILOT_PERIOD_END",
    "PILOT_PERIOD_START",
    "PILOT_PLAN_COUNT",
    "PILOT_RISK_POLICY",
    "PLANS_REL",
    "SCHEMA_REL",
    "experiment_plan_schema_path",
    "experiment_plans_dir",
    "load_experiment_plan_schema",
    "load_experiment_plans",
    "load_experiment_plan_closures",
    "load_experiment_plan_profiles",
    "start",
]
