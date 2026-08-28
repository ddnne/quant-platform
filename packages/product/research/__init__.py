"""Research control plane (Phase 7 stays OFF): readiness attestation, experiment plans.

This barrel re-exports the fail-closed control plane only. Candidate eval is
``research.cf_daily_path_job`` (POST /v1/daily-path). Smoke codes live in
Offline fixtures choose their own explicit codes. Mass is NO-GO.
"""

from __future__ import annotations

from importlib import import_module


_EXPORT_MODULES = {
    "MassResearchDisabledError": ".readiness",
    "OperatorOverrideCapability": ".readiness",
    "OperatorOverrideService": ".readiness",
    "ReadinessPublicKeyRegistry": ".readiness",
    "ResearchReadinessService": ".readiness",
    "VerifiedMassReadiness": ".readiness",
    "VerifiedPilotReadiness": ".readiness",
    "VerifiedResearchReadiness": ".readiness",
    "load_verified_pilot_readiness": ".readiness",
    "require_mass_research_start": ".readiness",
    "ExactFourPilotReadyBinding": ".ready_manifest",
    "ReadyManifest": ".ready_manifest",
    "VerifiedPilotReadyPublication": ".ready_manifest",
    "load_exact_four_pilot_ready_binding": ".ready_manifest",
    "ExperimentPlan": ".artifacts",
    "ResearchIdea": ".artifacts",
    "ExperimentScheduler": ".scheduler",
    "HypothesisClassScheduleSelection": ".scheduler",
    "ScheduledExperiment": ".scheduler",
    "select_schedule_hypothesis_classes": ".scheduler",
}


def __getattr__(name: str):
    """Load control-plane authorities only when their public export is used."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

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
