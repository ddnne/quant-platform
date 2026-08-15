"""Phase 7 research control plane (readiness attestation, experiment plans)."""

from research.readiness import (
    MassResearchDisabledError,
    OperatorOverrideCapability,
    OperatorOverrideService,
    ResearchReadinessService,
    VerifiedResearchReadiness,
    require_mass_research_start,
)
from research.artifacts import (
    ExperimentInsight,
    ExperimentPlan,
    FailureMode,
    FeatureEvidence,
    RegimeObservation,
    ResearchIdea,
    RejectionReason,
    StrategyEvidence,
)
from research.scheduler import ExperimentScheduler, ScheduledExperiment
from research.evaluation import EvaluationHarness, EvaluationProtocol, EvaluationReport
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    MASS_RESEARCH_STATUS,
    PHASE7_STATUS,
    READY_DECLARED,
    SingleShotExecution,
    SingleShotJobSpec,
    assert_mass_and_phase7_off,
    build_single_shot_job_spec,
    execute_single_shot_job,
)
from research.eval_harness import (
    APPROVED_SIGNAL_LEGS,
    MultidaySignalEval,
    assert_harness_closed,
    run_full_pipeline,
    run_multiday_signal_eval,
    run_nextday_return_eval,
)

__all__ = [
    "APPROVED_SIGNAL_LEGS",
    "COMPLETE_21_DATASETS",
    "EvaluationHarness",
    "EvaluationProtocol",
    "EvaluationReport",
    "ExperimentInsight",
    "ExperimentPlan",
    "ExperimentScheduler",
    "FailureMode",
    "FeatureEvidence",
    "MASS_RESEARCH_STATUS",
    "MassResearchDisabledError",
    "MultidaySignalEval",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "PHASE7_STATUS",
    "READY_DECLARED",
    "RegimeObservation",
    "RejectionReason",
    "ResearchIdea",
    "ResearchReadinessService",
    "ScheduledExperiment",
    "SingleShotExecution",
    "SingleShotJobSpec",
    "StrategyEvidence",
    "VerifiedResearchReadiness",
    "assert_harness_closed",
    "assert_mass_and_phase7_off",
    "build_single_shot_job_spec",
    "execute_single_shot_job",
    "require_mass_research_start",
    "run_full_pipeline",
    "run_multiday_signal_eval",
    "run_nextday_return_eval",
]
