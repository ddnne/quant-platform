"""Phase 7 research control plane (readiness attestation, experiment plans).

Heavy modules (eval_harness, unique_logic, factory, paper adapter) are imported
from their own packages — this barrel only re-exports the fail-closed control
plane. Mass / READY / GO remain closed.
"""

from research.readiness import (
    MassResearchDisabledError,
    OperatorOverrideCapability,
    OperatorOverrideService,
    ResearchReadinessService,
    VerifiedResearchReadiness,
    require_mass_research_start,
)
from research.artifacts import (
    ExperimentPlan,
    ResearchIdea,
)
from research.scheduler import (
    ExperimentScheduler,
    HypothesisClassScheduleSelection,
    ScheduledExperiment,
    select_schedule_hypothesis_classes,
)
from research.evaluation import EvaluationHarness, EvaluationProtocol, EvaluationReport

__all__ = [
    "EvaluationHarness",
    "EvaluationProtocol",
    "EvaluationReport",
    "ExperimentPlan",
    "ExperimentScheduler",
    "HypothesisClassScheduleSelection",
    "MassResearchDisabledError",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "ResearchIdea",
    "ResearchReadinessService",
    "ScheduledExperiment",
    "VerifiedResearchReadiness",
    "require_mass_research_start",
    "select_schedule_hypothesis_classes",
]
