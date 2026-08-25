"""Research control plane (Phase 7 stays OFF): readiness attestation, experiment plans.

This barrel re-exports the fail-closed control plane only. Candidate eval is
``research.cf_daily_path_job`` (POST /v1/daily-path). Smoke codes live in
``research.eval_universe.HARNESS_SMOKE_CODES``. Mass is NO-GO.
"""

from research.readiness import (
    MassResearchDisabledError,
    OperatorOverrideCapability,
    OperatorOverrideService,
    ReadinessPublicKeyRegistry,
    ResearchReadinessService,
    VerifiedMassReadiness,
    VerifiedPilotReadiness,
    VerifiedResearchReadiness,
    load_verified_pilot_readiness,
    require_mass_research_start,
)
from research.ready_manifest import (
    ExactFourPilotReadyBinding,
    ReadyManifest,
    VerifiedPilotReadyPublication,
    load_exact_four_pilot_ready_binding,
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
    "ExactFourPilotReadyBinding",
    "HypothesisClassScheduleSelection",
    "MassResearchDisabledError",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "ResearchIdea",
    "ReadyManifest",
    "ReadinessPublicKeyRegistry",
    "ResearchReadinessService",
    "ScheduledExperiment",
    "VerifiedMassReadiness",
    "VerifiedPilotReadiness",
    "VerifiedPilotReadyPublication",
    "VerifiedResearchReadiness",
    "load_exact_four_pilot_ready_binding",
    "load_verified_pilot_readiness",
    "require_mass_research_start",
    "select_schedule_hypothesis_classes",
]
