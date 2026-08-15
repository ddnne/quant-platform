"""Single-shot research job skeleton (Mass OFF / Phase7 OFF / READY not declared).

W49 / w0815ap_g3 T8 — minimal declaration only:

* **Inputs:** COMPLETE 21 dataset ids only (permanent DEFER excluded via
  ``data_contracts.permanent_defer``).
* **Output path:** R2/CF artifact key design (``quant-structured``). Local FS
  is **not** Source of Truth.
* **Not** connected to ``agents.mass_research`` / mass research loop.
* Does **not** set READY / mint readiness / arm Phase7.

This module does not run experiments, open market HTTP, or publish READY
snapshots. It only validates inputs and designs CF artifact keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import uuid4

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
    reject_permanent_defer_for_history,
)

# ---------------------------------------------------------------------------
# Freeze constants (T9: tests assert these remain closed — do not arm)
# ---------------------------------------------------------------------------

MASS_RESEARCH_STATUS: str = "NO-GO"
PHASE7_STATUS: str = "OFF"
READY_PUBLICATION_STATUS: str = "OFF"
READY_DECLARED: bool = False

# No env/flag arming switches exist for Phase7 / mass research.
# Keep empty frozensets as the explicit contract tests freeze against.
PHASE7_ENV_ARMING_SWITCHES: frozenset[str] = frozenset()
MASS_RESEARCH_ENV_ARMING_SWITCHES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# COMPLETE 21 dataset ids (residual SoT held; do not invent 22)
# Source list: docs/proof/coverage_baseline_21_usage_notes_20260815.md
# Relation: governed 26 − permanent DEFER 5 == these 21.
# ---------------------------------------------------------------------------

COMPLETE_21_DATASETS: tuple[str, ...] = (
    "derivatives_bars_daily_futures",
    "derivatives_bars_daily_options",
    "derivatives_bars_daily_options_225",
    "edinet_cross_shareholdings",
    "edinet_large_volume_shareholders",
    "edinet_major_shareholders",
    "equities_bars_daily",
    "equities_investor_types",
    "fins_details",
    "fins_dividend",
    "fins_summary",
    "indices_bars_daily",
    "indices_bars_daily_topix",
    "jsda_corporate_bond_transactions",
    "jsda_tokyo_repo_rates",
    "markets_breakdown",
    "markets_calendar",
    "markets_margin_alert",
    "markets_margin_interest",
    "markets_short_ratio",
    "markets_short_sale_report",
)

COMPLETE_21_DATASET_SET: frozenset[str] = frozenset(COMPLETE_21_DATASETS)

if len(COMPLETE_21_DATASETS) != 21:
    raise RuntimeError(
        f"COMPLETE_21_DATASETS must have exactly 21 ids, got {len(COMPLETE_21_DATASETS)}"
    )
if COMPLETE_21_DATASET_SET & PERMANENT_DEFER_DATASETS:
    raise RuntimeError(
        "COMPLETE_21_DATASETS must not intersect permanent DEFER: "
        f"{sorted(COMPLETE_21_DATASET_SET & PERMANENT_DEFER_DATASETS)}"
    )

# ---------------------------------------------------------------------------
# R2 / CF artifact path design (local is not SoT)
# ---------------------------------------------------------------------------

RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/single_shot"
# History inputs remain on the CF history plane (not local SQLite SoT):
#   structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl
#   archive/jquants_records/{dataset}/batch/...
# Job outputs land under RESEARCH_ARTIFACT_PREFIX (same bucket).


class SingleShotJobError(ValueError):
    """Invalid single-shot job input or path design."""


@dataclass(frozen=True)
class SingleShotJobSpec:
    """Declarative single-shot job (not a runnable mass research session)."""

    job_id: str
    dataset_ids: tuple[str, ...]
    period_start: str
    period_end: str
    artifact_bucket: str
    artifact_prefix: str
    manifest_r2_key: str
    input_plan_r2_key: str
    result_r2_key_template: str
    mass_research: str = MASS_RESEARCH_STATUS
    phase7: str = PHASE7_STATUS
    ready_declared: bool = READY_DECLARED
    local_sot: bool = False
    version: str = "single-shot-job/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "dataset_ids": list(self.dataset_ids),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "artifact": {
                "bucket": self.artifact_bucket,
                "prefix": self.artifact_prefix,
                "manifest_r2_key": self.manifest_r2_key,
                "input_plan_r2_key": self.input_plan_r2_key,
                "result_r2_key_template": self.result_r2_key_template,
                "local_sot": self.local_sot,
            },
            "mass_research": self.mass_research,
            "phase7": self.phase7,
            "ready_declared": self.ready_declared,
            "ready_publication": READY_PUBLICATION_STATUS,
        }


def design_artifact_paths(job_id: str) -> dict[str, Any]:
    """Return R2 key layout for a single-shot job.

    Local filesystem paths are intentionally **not** returned as SoT.
    Operators may stage drafts locally, but the designed authority keys are R2.
    """
    jid = str(job_id).strip()
    if not jid:
        raise SingleShotJobError("job_id must be non-empty")
    if "/" in jid or "\\" in jid or ".." in jid:
        raise SingleShotJobError("job_id must not contain path separators")
    prefix = f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}"
    return {
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "prefix": prefix,
        "manifest_r2_key": f"{prefix}/manifest.json",
        "input_plan_r2_key": f"{prefix}/input_plan.json",
        "result_r2_key_template": f"{prefix}/result/{{content_hash}}.json",
        "local_sot": False,
        "history_input_patterns": {
            "structured_jsonl": "structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl",
            "archive_ndjson": "archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}.ndjson",
            "note": "History SoT is R2 quant-structured; D1 is hot tip only; local SQLite is mirror only.",
        },
    }


def require_complete_21_only(
    datasets: Sequence[str] | str,
    *,
    context: str = "single-shot research job",
) -> tuple[str, ...]:
    """Return ordered unique dataset ids if all are COMPLETE-21 eligible.

    Fail-closed when:

    * any permanent DEFER id is present (imports permanent_defer guards)
    * any id is outside the residual COMPLETE 21 set
    * the list is empty
    """
    if isinstance(datasets, str):
        requested = (datasets,)
    else:
        requested = tuple(datasets)

    # Permanent DEFER hard reject first (shared contract with history loaders).
    reject_permanent_defer_for_history(requested, context=context)

    out: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for item in requested:
        value = str(item).strip()
        if not value or value in seen:
            continue
        if value not in COMPLETE_21_DATASET_SET:
            unknown.append(value)
            continue
        seen.add(value)
        out.append(value)

    if unknown:
        raise SingleShotJobError(
            f"{context}: dataset(s) not in COMPLETE 21 allowlist: "
            f"{sorted(set(unknown))}. Prefer residual COMPLETE 21; "
            "do not invent Dataset COMPLETE 22."
        )
    if not out:
        raise SingleShotJobError(
            f"{context}: at least one COMPLETE 21 dataset id is required"
        )
    return tuple(out)


def build_single_shot_job_spec(
    *,
    dataset_ids: Sequence[str],
    period_start: str,
    period_end: str,
    job_id: str | None = None,
) -> SingleShotJobSpec:
    """Build a single-shot job declaration.

    Does **not**:

    * call ``start_mass_research`` / mass research loop
    * set READY / mint ``VerifiedResearchReadiness``
    * arm Phase7 env switches
    * write local SoT artifacts as authority
    """
    start = str(period_start).strip()
    end = str(period_end).strip()
    if not start or not end:
        raise SingleShotJobError("period_start and period_end are required")

    ids = require_complete_21_only(dataset_ids)
    jid = str(job_id).strip() if job_id else str(uuid4())
    paths = design_artifact_paths(jid)

    return SingleShotJobSpec(
        job_id=jid,
        dataset_ids=ids,
        period_start=start,
        period_end=end,
        artifact_bucket=str(paths["bucket"]),
        artifact_prefix=str(paths["prefix"]),
        manifest_r2_key=str(paths["manifest_r2_key"]),
        input_plan_r2_key=str(paths["input_plan_r2_key"]),
        result_r2_key_template=str(paths["result_r2_key_template"]),
        mass_research=MASS_RESEARCH_STATUS,
        phase7=PHASE7_STATUS,
        ready_declared=READY_DECLARED,
        local_sot=False,
    )


def freeze_status() -> dict[str, Any]:
    """Return Phase7 / Mass / READY freeze surface (never arms switches)."""
    return {
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_publication": READY_PUBLICATION_STATUS,
        "ready_declared": READY_DECLARED,
        "phase7_env_arming_switches": sorted(PHASE7_ENV_ARMING_SWITCHES),
        "mass_research_env_arming_switches": sorted(MASS_RESEARCH_ENV_ARMING_SWITCHES),
        "complete_21_count": len(COMPLETE_21_DATASETS),
        "permanent_defer_count": len(PERMANENT_DEFER_DATASETS),
        "connected_to_mass_research_loop": False,
        "sets_ready": False,
        "local_sot": False,
        "artifact_bucket": RESEARCH_ARTIFACT_BUCKET,
        "artifact_prefix": RESEARCH_ARTIFACT_PREFIX,
    }


def assert_mass_and_phase7_off() -> Mapping[str, Any]:
    """Hard-check freeze constants; raise if any switch is not closed.

    Tests and operators may call this as a guard. It never enables anything.
    """
    status = freeze_status()
    if status["mass_research"] != "NO-GO":
        raise RuntimeError(f"mass_research must be NO-GO, got {status['mass_research']!r}")
    if status["phase7"] != "OFF":
        raise RuntimeError(f"phase7 must be OFF, got {status['phase7']!r}")
    if status["ready_publication"] != "OFF":
        raise RuntimeError(
            f"ready_publication must be OFF, got {status['ready_publication']!r}"
        )
    if status["ready_declared"] is not False:
        raise RuntimeError("ready_declared must be False")
    if status["phase7_env_arming_switches"]:
        raise RuntimeError("PHASE7 env arming switches must remain empty")
    if status["mass_research_env_arming_switches"]:
        raise RuntimeError("MASS_RESEARCH env arming switches must remain empty")
    if status["connected_to_mass_research_loop"] is not False:
        raise RuntimeError("single-shot skeleton must not connect to mass loop")
    if status["sets_ready"] is not False:
        raise RuntimeError("single-shot skeleton must not set READY")
    return status


__all__ = [
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "MASS_RESEARCH_ENV_ARMING_SWITCHES",
    "MASS_RESEARCH_STATUS",
    "PHASE7_ENV_ARMING_SWITCHES",
    "PHASE7_STATUS",
    "READY_DECLARED",
    "READY_PUBLICATION_STATUS",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "SingleShotJobError",
    "SingleShotJobSpec",
    "assert_mass_and_phase7_off",
    "build_single_shot_job_spec",
    "design_artifact_paths",
    "freeze_status",
    "require_complete_21_only",
    "PermanentDeferHistoryError",
]
