"""Research control plane (Phase 7 stays OFF): readiness attestation, experiment plans.

This barrel re-exports the fail-closed control plane only. Candidate eval is
``research.cf_daily_path_job`` (POST /v1/daily-path). Smoke codes live in
``research.eval_universe.HARNESS_SMOKE_CODES``. Mass is NO-GO.
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

__all__ = [
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
