"""The personal CLI stays independent from controlled research authorities."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATHS = (REPO_ROOT,) + tuple(
    REPO_ROOT / "packages" / plane
    for plane in ("edge", "data_plane", "research_runtime", "product")
)


def _isolated_python(program: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            *(str(path) for path in PYTHON_PATHS),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_personal_cli_import_and_input_rejection_do_not_load_authorities() -> None:
    program = r'''
import sys

sys.path[:0] = sys.argv[1:]

from research import personal_cli

code = personal_cli.main([
    "--db",
    "/definitely/missing/personal-research.sqlite",
    "--end",
    "2026-08-27",
])
if code != 2:
    raise AssertionError(f"unexpected missing-input exit code: {code}")

forbidden = {
    "execution.controlled_artifacts",
    "execution.paper_service",
    "execution.trader_authority",
    "ops.range_batch_scheduler",
    "paper_runtime.readiness_attestation",
    "paper_runtime.snapshot",
    "paper_runtime.snapshot_coverage_proof",
    "paper_runtime.snapshot_persist",
    "paper_runtime.snapshot_publish_policy",
    "paper_runtime.snapshot_read",
    "research.readiness",
    "research.ready_manifest",
    "research.scheduler",
}
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise AssertionError(f"personal CLI loaded controlled modules: {loaded}")
'''
    completed = _isolated_python(program)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_lazy_barrels_preserve_existing_package_level_public_imports() -> None:
    program = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:]

expected = {
    "execution": (
        "CONTROLLED_AUTHORITY_UNPROVISIONED",
        "CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED",
        "ControlledArtifactAuthorityPending",
        "ControlledArtifactPublicKeyRegistry",
        "ControlledArtifactVerificationError",
        "ControlledPilotExecutionService",
        "ControlledPilotPending",
        "OfflineFixturePaperService",
        "PaperExecutionRejected",
        "PaperExecutionService",
        "TraderAuthorizationBinding",
        "TraderAuthorizationPublicKeyRegistry",
        "VerifiedTraderAuthorization",
        "VerifiedControlledExecutionArtifacts",
        "load_verified_controlled_execution_artifacts",
        "verify_exact_trader_authorization",
    ),
    "research": (
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
    ),
    "paper_runtime": (
        "DATA_SNAPSHOT_FORMAT",
        "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
        "QUALITY_POLICY_VERSION",
        "READY_MANIFEST_SCHEMA",
        "RESEARCH_SNAPSHOT_MANIFEST_FORMAT",
        "SNAPSHOT_STATES",
        "ReadySnapshot",
        "SnapshotRejected",
        "begin_snapshot_sync",
        "data_snapshot_id",
        "describe_snapshot",
        "fail_snapshot_sync",
        "latest_ready_snapshot",
        "list_ready_snapshots",
        "ExperimentIndex",
        "feature_definition_hashes",
        "git_commit",
        "strategy_definition_hash",
        "CoherenceGateResult",
        "check_ready_coherence",
    ),
    "ops": (
        "BackfillJob",
        "BackfillPlan",
        "BackfillPlanner",
        "RangeBatchScheduler",
        "SchedulerConfig",
        "TRACK_A_DATASETS",
        "plan_and_queue",
    ),
}

for package_name, names in expected.items():
    package = importlib.import_module(package_name)
    if tuple(package.__all__) != names:
        raise AssertionError(
            f"{package_name} public exports changed: {tuple(package.__all__)}"
        )
    for name in names:
        namespace = {}
        exec(f"from {package_name} import {name}", namespace)
        if namespace.get(name) is None:
            raise AssertionError(f"{package_name}.{name} did not resolve")
'''
    completed = _isolated_python(program)
    assert completed.returncode == 0, completed.stdout + completed.stderr
