"""Single ReadyManifest type — publisher, coherence, ReadinessService.

SoT: ``specs/ready/ready_manifest.schema.json``. Missing proofs are
UNKNOWN/MISSING, never default PASS. Does not publish live READY.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from selection.budget_ledger import MassResearchDisabledError

READY_MANIFEST_FORMAT: str = "ready-manifest/v1"
SCHEMA_REL: Path = Path("specs") / "ready" / "ready_manifest.schema.json"
CORE_PROFILE_REL: Path = Path("specs") / "research_profiles" / "core_v1.json"
SOURCE_CAPABILITY_REL: Path = Path("specs") / "source_capability"
MISSING: str = "MISSING"
UNKNOWN: str = "UNKNOWN"
ABSENT_PROOFS: frozenset[str] = frozenset({MISSING, UNKNOWN, ""})
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROOF_RE = re.compile(r"(?:sha256:[0-9a-f]{64}|UNKNOWN|MISSING)\Z")

PROOF_DIGEST_FIELDS: tuple[str, ...] = (
    "profile_digest",
    "plan_set_digest",
    "dependency_closure_digest",
    "dataset_membership_digest",
    "coverage_policy_digest",
    "coverage_proof_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "validation_proof_digest",
    "b0_proof_digest",
    "b4_proof_digest",
)
TIMESTAMP_FIELDS: tuple[str, ...] = ("created_at", "published_at")
GENERATION_PIN_FIELDS: tuple[str, ...] = (
    "source_generation",
    "applied_sync_generation",
    "export_cursor",
    "applied_cursor",
    "feature_generation",
    "catalog_generation",
)

_SCHEMA: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_digest(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def is_sha256_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def proof_or_missing(value: Any) -> str:
    """Return a schema proof token. None/blank/invalid → MISSING, not PASS."""
    if value is None:
        return MISSING
    text = str(value).strip()
    if not text or text in ABSENT_PROOFS:
        return text if text in {MISSING, UNKNOWN} else MISSING
    if _PROOF_RE.fullmatch(text):
        return text
    return MISSING


def pin_or_missing(value: Any) -> str:
    if value is None:
        return MISSING
    text = str(value).strip()
    return text if text else MISSING


def schema_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / SCHEMA_REL


def load_ready_manifest_schema(*, root: Path | None = None) -> dict[str, Any]:
    """Load the ReadyManifest JSON Schema. Cached for the repo root."""
    global _SCHEMA
    if _SCHEMA is not None and root is None:
        return _SCHEMA
    path = schema_path(root=root)
    if not path.is_file():
        raise MassResearchDisabledError(f"ReadyManifest schema missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MassResearchDisabledError("ReadyManifest schema must be an object")
    if raw.get("$id") != READY_MANIFEST_FORMAT:
        raise MassResearchDisabledError(
            f"ReadyManifest schema $id must be {READY_MANIFEST_FORMAT!r}"
        )
    if raw.get("additionalProperties") is not False:
        raise MassResearchDisabledError(
            "ReadyManifest schema must set additionalProperties false"
        )
    if root is None:
        _SCHEMA = raw
    return raw


def validate_ready_manifest_document(payload: Any) -> None:
    schema = load_ready_manifest_schema()
    if not isinstance(payload, Mapping):
        raise MassResearchDisabledError("ReadyManifest must be an object")
    try:
        import jsonschema
    except ImportError as exc:
        raise MassResearchDisabledError("jsonschema is required to validate ReadyManifest") from exc
    try:
        jsonschema.validate(instance=dict(payload), schema=schema)
    except jsonschema.ValidationError as exc:
        raise MassResearchDisabledError(f"ReadyManifest schema invalid: {exc.message}") from exc


def compute_dataset_membership_digest(dataset_ids: Sequence[str] | None) -> str:
    if dataset_ids is None:
        return MISSING
    return canonical_digest(sorted({str(item) for item in dataset_ids}))


@dataclass(frozen=True)
class ReadyManifest:
    """Closed ReadyManifest. Not a live READY publish."""

    snapshot_id: str
    publication_scope: str
    profile_id: str
    profile_version: str
    profile_digest: str
    plan_ids: tuple[str, ...]
    plan_set_digest: str
    dependency_closure_digest: str
    dataset_ids: tuple[str, ...]
    dataset_membership_digest: str
    coverage_policy_version: str
    coverage_policy_digest: str
    coverage_proof_digest: str
    raw_proof_digest: str
    receipt_proof_digest: str
    validation_proof_digest: str
    b0_proof_digest: str
    b4_proof_digest: str
    source_generation: str
    applied_sync_generation: str
    export_cursor: str
    applied_cursor: str
    pit_contract_digests: Mapping[str, str]
    feature_generation: str
    catalog_generation: str
    created_at: str
    published_at: str
    format: str = READY_MANIFEST_FORMAT
    manifest_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        body = {
            "format": self.format,
            "snapshot_id": self.snapshot_id,
            "publication_scope": self.publication_scope,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "plan_ids": list(self.plan_ids),
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_digest": self.dependency_closure_digest,
            "dataset_ids": list(self.dataset_ids),
            "dataset_membership_digest": self.dataset_membership_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_policy_digest": self.coverage_policy_digest,
            "coverage_proof_digest": self.coverage_proof_digest,
            "raw_proof_digest": self.raw_proof_digest,
            "receipt_proof_digest": self.receipt_proof_digest,
            "validation_proof_digest": self.validation_proof_digest,
            "b0_proof_digest": self.b0_proof_digest,
            "b4_proof_digest": self.b4_proof_digest,
            "source_generation": self.source_generation,
            "applied_sync_generation": self.applied_sync_generation,
            "export_cursor": self.export_cursor,
            "applied_cursor": self.applied_cursor,
            "pit_contract_digests": dict(self.pit_contract_digests),
            "feature_generation": self.feature_generation,
            "catalog_generation": self.catalog_generation,
            "created_at": self.created_at,
            "published_at": self.published_at,
        }
        digest = self.manifest_digest or _manifest_digest_for(body)
        return {**body, "manifest_digest": digest}

    def to_canonical_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("manifest_digest", None)
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReadyManifest":
        if not isinstance(payload, Mapping):
            raise MassResearchDisabledError("ReadyManifest must be an object")
        document = dict(payload)
        declared = document.pop("manifest_digest", None)
        validate_ready_manifest_document({**document, **(
            {"manifest_digest": declared} if declared is not None else {}
        )})
        pit_raw = document.get("pit_contract_digests")
        if not isinstance(pit_raw, Mapping) or not pit_raw:
            raise MassResearchDisabledError("ReadyManifest pit_contract_digests missing")
        pit = {str(key): proof_or_missing(value) for key, value in pit_raw.items()}
        dataset_ids_raw = document.get("dataset_ids")
        if not isinstance(dataset_ids_raw, Sequence) or isinstance(
            dataset_ids_raw, (str, bytes)
        ):
            raise MassResearchDisabledError("ReadyManifest dataset_ids must be an array")
        dataset_ids = tuple(str(item) for item in dataset_ids_raw)
        plan_ids_raw = document.get("plan_ids")
        if not isinstance(plan_ids_raw, Sequence) or isinstance(
            plan_ids_raw, (str, bytes)
        ):
            raise MassResearchDisabledError("ReadyManifest plan_ids must be an array")
        plan_ids = tuple(str(item) for item in plan_ids_raw)
        body = {
            "format": str(document.get("format") or ""),
            "snapshot_id": str(document.get("snapshot_id") or ""),
            "publication_scope": str(document.get("publication_scope") or ""),
            "profile_id": str(document.get("profile_id") or ""),
            "profile_version": pin_or_missing(document.get("profile_version")),
            "profile_digest": proof_or_missing(document.get("profile_digest")),
            "plan_ids": plan_ids,
            "plan_set_digest": proof_or_missing(document.get("plan_set_digest")),
            "dependency_closure_digest": proof_or_missing(
                document.get("dependency_closure_digest")
            ),
            "dataset_ids": dataset_ids,
            "dataset_membership_digest": proof_or_missing(
                document.get("dataset_membership_digest")
            ),
            "coverage_policy_version": pin_or_missing(
                document.get("coverage_policy_version")
            ),
            "coverage_policy_digest": proof_or_missing(
                document.get("coverage_policy_digest")
            ),
            "coverage_proof_digest": proof_or_missing(
                document.get("coverage_proof_digest")
            ),
            "raw_proof_digest": proof_or_missing(document.get("raw_proof_digest")),
            "receipt_proof_digest": proof_or_missing(
                document.get("receipt_proof_digest")
            ),
            "validation_proof_digest": proof_or_missing(
                document.get("validation_proof_digest")
            ),
            "b0_proof_digest": proof_or_missing(document.get("b0_proof_digest")),
            "b4_proof_digest": proof_or_missing(document.get("b4_proof_digest")),
            "source_generation": pin_or_missing(document.get("source_generation")),
            "applied_sync_generation": pin_or_missing(
                document.get("applied_sync_generation")
            ),
            "export_cursor": pin_or_missing(document.get("export_cursor")),
            "applied_cursor": pin_or_missing(document.get("applied_cursor")),
            "pit_contract_digests": pit,
            "feature_generation": pin_or_missing(document.get("feature_generation")),
            "catalog_generation": pin_or_missing(document.get("catalog_generation")),
            "created_at": pin_or_missing(document.get("created_at")),
            "published_at": pin_or_missing(document.get("published_at")),
        }
        digest = _manifest_digest_for(body)
        if declared is not None and str(declared) != digest:
            raise MassResearchDisabledError("ReadyManifest manifest_digest mismatch")
        return cls(manifest_digest=digest, **body)  # type: ignore[arg-type]


def _manifest_digest_for(body: Mapping[str, Any]) -> str:
    document = dict(body)
    document.pop("manifest_digest", None)
    return canonical_digest(document)


def build_ready_manifest(
    *,
    snapshot_id: str,
    profile_id: str,
    publication_scope: str = "PILOT",
    profile_version: str | None = None,
    profile_digest: str | None = None,
    plan_ids: Sequence[str] | None = None,
    plan_set_digest: str | None = None,
    dependency_closure_digest: str | None = None,
    dataset_ids: Sequence[str] | None = None,
    dataset_membership_digest: str | None = None,
    coverage_proof_digest: str | None = None,
    raw_proof_digest: str | None = None,
    receipt_proof_digest: str | None = None,
    validation_proof_digest: str | None = None,
    b0_proof_digest: str | None = None,
    b4_proof_digest: str | None = None,
    source_generation: str | None = None,
    applied_sync_generation: str | None = None,
    export_cursor: str | None = None,
    applied_cursor: str | None = None,
    pit_contract_digests: Mapping[str, str] | None = None,
    feature_generation: str | None = None,
    catalog_generation: str | None = None,
    created_at: str | None = None,
    published_at: str | None = None,
) -> ReadyManifest:
    """Publisher helper: assemble a ReadyManifest. Omitted proofs stay MISSING.

    Does not publish live READY and does not invent COMPLETE/FRESH/B0 PASS.
    """
    created = created_at or _now().isoformat()
    pit = pit_contract_digests or {"pit_api": MISSING}
    membership = (
        dataset_membership_digest
        if dataset_membership_digest is not None
        else compute_dataset_membership_digest(dataset_ids)
    )
    from data_contracts.coverage import coverage_policy_set_binding

    try:
        policy_set = coverage_policy_set_binding(list(dataset_ids or ()))
        coverage_policy_version = str(policy_set["policy_version"])
        coverage_policy_digest = str(policy_set["policy_digest"])
    except (KeyError, ValueError):
        coverage_policy_version = MISSING
        coverage_policy_digest = MISSING
    return ReadyManifest.from_dict(
        {
            "format": READY_MANIFEST_FORMAT,
            "snapshot_id": snapshot_id,
            "publication_scope": publication_scope,
            "profile_id": profile_id,
            "profile_version": pin_or_missing(profile_version),
            "profile_digest": proof_or_missing(profile_digest),
            "plan_ids": list(plan_ids or ()),
            "plan_set_digest": proof_or_missing(plan_set_digest),
            "dependency_closure_digest": proof_or_missing(
                dependency_closure_digest
            ),
            "dataset_ids": list(dataset_ids or ()),
            "dataset_membership_digest": proof_or_missing(membership),
            "coverage_policy_version": coverage_policy_version,
            "coverage_policy_digest": proof_or_missing(coverage_policy_digest),
            "coverage_proof_digest": proof_or_missing(coverage_proof_digest),
            "raw_proof_digest": proof_or_missing(raw_proof_digest),
            "receipt_proof_digest": proof_or_missing(receipt_proof_digest),
            "validation_proof_digest": proof_or_missing(validation_proof_digest),
            "b0_proof_digest": proof_or_missing(b0_proof_digest),
            "b4_proof_digest": proof_or_missing(b4_proof_digest),
            "source_generation": pin_or_missing(source_generation),
            "applied_sync_generation": pin_or_missing(applied_sync_generation),
            "export_cursor": pin_or_missing(export_cursor),
            "applied_cursor": pin_or_missing(applied_cursor),
            "pit_contract_digests": {
                str(key): proof_or_missing(value) for key, value in pit.items()
            },
            "feature_generation": pin_or_missing(feature_generation),
            "catalog_generation": pin_or_missing(catalog_generation),
            "created_at": created,
            "published_at": published_at or MISSING,
        }
    )


@dataclass(frozen=True, slots=True)
class ExactFourPilotReadyBinding:
    """Canonical aggregate profile for the four controlled-pilot plans."""

    plans: tuple[Any, ...]
    closures: tuple[Any, ...]
    profiles: tuple[Any, ...]
    publication_scope: str = "PILOT"
    profile_id: str = "controlled-pilot/exact-four"
    profile_version: str = "research-data-profile-set/v1"

    def __post_init__(self) -> None:
        from research.dependency_closure import verify_plan_dependency_closure
        from research.experiment_plans import (
            PILOT_EXPERIMENT_PLAN_IDS,
            PILOT_PLAN_COUNT,
            load_experiment_plan_closures,
            load_experiment_plan_profiles,
            load_experiment_plans,
        )

        if (
            self.publication_scope != "PILOT"
            or self.profile_id != "controlled-pilot/exact-four"
            or self.profile_version != "research-data-profile-set/v1"
        ):
            raise MassResearchDisabledError(
                "controlled pilot READY identity is not canonical"
            )

        if (
            len(self.plans) != PILOT_PLAN_COUNT
            or len(self.closures) != PILOT_PLAN_COUNT
            or len(self.profiles) != PILOT_PLAN_COUNT
        ):
            raise MassResearchDisabledError(
                f"controlled pilot READY requires exactly {PILOT_PLAN_COUNT} plans"
            )
        plan_ids = tuple(plan.plan_id for plan in self.plans)
        if plan_ids != PILOT_EXPERIMENT_PLAN_IDS:
            raise MassResearchDisabledError(
                "controlled pilot READY plan ids/order are not canonical exact-four"
            )
        if len(plan_ids) != len(set(plan_ids)):
            raise MassResearchDisabledError("controlled pilot plan ids are not unique")
        if tuple(closure.plan_id for closure in self.closures) != plan_ids:
            raise MassResearchDisabledError(
                "controlled pilot closure order does not match plan order"
            )
        if tuple(profile.plan_id for profile in self.profiles) != plan_ids:
            raise MassResearchDisabledError(
                "controlled pilot profile order does not match plan order"
            )
        for plan, closure, profile in zip(
            self.plans, self.closures, self.profiles, strict=True
        ):
            verify_plan_dependency_closure(plan, closure)
            if (
                profile.plan_digest != closure.plan_digest
                or profile.dependency_closure_digest != closure.closure_digest
                or tuple(profile.required_datasets) != tuple(closure.required_datasets)
                or profile.period_start != closure.period_start
                or profile.period_end != closure.period_end
                or profile.required_lookback_trading_days
                != closure.required_lookback_trading_days
                or tuple(dict(item) for item in profile.dataset_scopes)
                != tuple(scope.to_dict() for scope in closure.dataset_scopes)
            ):
                raise MassResearchDisabledError(
                    f"controlled pilot profile binding mismatch for {plan.plan_id}"
                )

        # Public construction cannot turn a self-consistent alternate set into
        # the governed pilot. Compare every canonical artifact and digest with
        # the checked-in exact-four compiler output.
        canonical_plans = load_experiment_plans()
        canonical_closures = load_experiment_plan_closures()
        canonical_profiles = load_experiment_plan_profiles()
        if tuple(plan.to_dict() for plan in self.plans) != tuple(
            plan.to_dict() for plan in canonical_plans
        ):
            raise MassResearchDisabledError(
                "controlled pilot ExperimentPlan digest chain is noncanonical"
            )
        if tuple(closure.to_dict() for closure in self.closures) != tuple(
            closure.to_dict() for closure in canonical_closures
        ):
            raise MassResearchDisabledError(
                "controlled pilot dependency closure digest chain is noncanonical"
            )
        if tuple(profile.to_dict() for profile in self.profiles) != tuple(
            profile.to_dict() for profile in canonical_profiles
        ):
            raise MassResearchDisabledError(
                "controlled pilot profile digest chain is noncanonical"
            )

    @property
    def plan_ids(self) -> tuple[str, ...]:
        return tuple(plan.plan_id for plan in self.plans)

    @property
    def plan_set_digest(self) -> str:
        return canonical_digest(
            [
                {"plan_id": closure.plan_id, "plan_digest": closure.plan_digest}
                for closure in self.closures
            ]
        )

    @property
    def closure_set_digest(self) -> str:
        return canonical_digest(
            [
                {
                    "plan_id": closure.plan_id,
                    "closure_digest": closure.closure_digest,
                }
                for closure in self.closures
            ]
        )

    @property
    def profile_digest(self) -> str:
        return canonical_digest([profile.to_dict() for profile in self.profiles])

    @property
    def required_datasets(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    dataset_id
                    for profile in self.profiles
                    for dataset_id in profile.required_datasets
                }
            )
        )

    @property
    def feature_dependencies(self) -> tuple[Mapping[str, Any], ...]:
        unique: dict[str, Mapping[str, Any]] = {}
        for profile in self.profiles:
            for dependency in profile.feature_dependencies:
                digest = canonical_digest(dict(dependency))
                unique[digest] = dict(dependency)
        return tuple(unique[key] for key in sorted(unique))

    @property
    def contract_versions(self) -> Mapping[str, str]:
        from data_contracts.coverage import coverage_policy_set_binding

        versions: dict[str, str] = {}
        for profile in self.profiles:
            for key, value in profile.contract_versions.items():
                if key in {"coverage_policy", "coverage_policy_digest"}:
                    continue
                previous = versions.get(str(key))
                if previous is not None and previous != str(value):
                    raise MassResearchDisabledError(
                        f"controlled pilot contract version conflict: {key}"
                    )
                versions[str(key)] = str(value)
        policy_set = coverage_policy_set_binding(list(self.required_datasets))
        versions["coverage_policy"] = str(policy_set["policy_version"])
        versions["coverage_policy_digest"] = str(policy_set["policy_digest"])
        return versions

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_scope": self.publication_scope,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "plan_ids": list(self.plan_ids),
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_digest": self.closure_set_digest,
            "required_datasets": list(self.required_datasets),
            "profiles": [profile.to_dict() for profile in self.profiles],
        }


@dataclass(frozen=True, slots=True)
class VerifiedPilotReadyPublication:
    """Atomic exact-four publication result with its signed pilot capability."""

    snapshot: Any
    readiness: Any
    readiness_path: Path

    def __post_init__(self) -> None:
        from paper_runtime.snapshot import ReadySnapshot
        from research.readiness import VerifiedPilotReadiness

        if not isinstance(self.snapshot, ReadySnapshot):
            raise MassResearchDisabledError("ReadySnapshot publication required")
        if not isinstance(self.readiness, VerifiedPilotReadiness):
            raise MassResearchDisabledError(
                "VerifiedPilotReadiness publication required"
            )
        if self.readiness.snapshot_id != self.snapshot.snapshot_id:
            raise MassResearchDisabledError(
                "published snapshot/readiness identity mismatch"
            )
        if not Path(self.readiness_path).is_file():
            raise MassResearchDisabledError(
                "immutable readiness attestation sidecar is missing"
            )

    @property
    def snapshot_id(self) -> str:
        return str(self.snapshot.snapshot_id)

    @property
    def db_path(self) -> Path:
        return Path(self.snapshot.db_path)

    @property
    def manifest_path(self) -> Path:
        return Path(self.snapshot.manifest_path)

    @property
    def manifest(self) -> Mapping[str, Any]:
        return self.snapshot.manifest

    @property
    def committed_at(self) -> str:
        return str(self.snapshot.committed_at)


def load_exact_four_pilot_ready_binding(
    *, root: Path | None = None
) -> ExactFourPilotReadyBinding:
    """Compile the only supported pilot READY plan/profile/closure binding."""
    from research.experiment_plans import (
        load_experiment_plan_closures,
        load_experiment_plan_profiles,
        load_experiment_plans,
    )

    return ExactFourPilotReadyBinding(
        plans=load_experiment_plans(root=root),
        closures=load_experiment_plan_closures(root=root),
        profiles=load_experiment_plan_profiles(root=root),
    )


def serialize_ready_manifest(manifest: ReadyManifest, path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(manifest.to_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def load_ready_manifest(path: str | Path) -> ReadyManifest:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise MassResearchDisabledError(f"ReadyManifest file is not an object: {source}")
    return ReadyManifest.from_dict(raw)


def build_profile_bound_ready_manifest_from_snapshot_document(
    document: Mapping[str, Any],
    *,
    profile: Any,
) -> ReadyManifest:
    """Build the closed manifest from the publisher's retained evidence."""
    from data_contracts.coverage import (
        coverage_policy_binding,
        coverage_policy_set_binding,
    )
    from pit.models import PIT_API_VERSION
    from research.research_data_profile import official_mode

    snapshot_id = document.get("snapshot_id")
    if not is_sha256_digest(snapshot_id) or document.get("state") != "READY":
        raise MassResearchDisabledError("profile-bound snapshot is not READY")
    required = document.get("required_datasets")
    if (
        not isinstance(required, list)
        or len(required) != len(profile.required_datasets)
        or set(required) != set(profile.required_datasets)
    ):
        raise MassResearchDisabledError(
            "profile-bound snapshot does not exactly match the research profile"
        )
    coverage_proof = document.get("coverage_proof")
    if not isinstance(coverage_proof, Mapping) or not is_sha256_digest(
        coverage_proof.get("proof_digest")
    ):
        raise MassResearchDisabledError("snapshot coverage proof missing")
    expected_policy_set = coverage_policy_set_binding(list(profile.required_datasets))
    if (
        coverage_proof.get("policy_version")
        != expected_policy_set["policy_version"]
        or coverage_proof.get("policy_digest")
        != expected_policy_set["policy_digest"]
        or document.get("coverage_policy_version")
        != expected_policy_set["policy_version"]
        or document.get("coverage_policy_digest")
        != expected_policy_set["policy_digest"]
    ):
        raise MassResearchDisabledError(
            "snapshot governed Coverage policy-set binding mismatch"
        )
    profile_evidence = document.get("profile_coverage_evidence")
    if not isinstance(profile_evidence, Mapping) or set(profile_evidence) != set(
        profile.required_datasets
    ):
        raise MassResearchDisabledError(
            "snapshot profile coverage evidence is not exact"
        )

    source: dict[str, str] = {}
    exported: dict[str, str] = {}
    applied: dict[str, str] = {}
    signed_projection_cursors: set[str] = set()
    for dataset_id in profile.required_datasets:
        row = profile_evidence.get(dataset_id)
        if not isinstance(row, Mapping):
            raise MassResearchDisabledError(
                f"snapshot profile evidence missing for {dataset_id}"
            )
        source_value = str(row.get("source_generation") or "").strip()
        export_value = str(row.get("export_cursor") or "").strip()
        applied_value = str(
            row.get("applied_sync_generation") or row.get("applied_cursor") or ""
        ).strip()
        expected_policy = coverage_policy_binding(dataset_id)
        if (
            row.get("status") != "COMPLETE"
            or row.get("projection_status") == "STALE"
            or row.get("coverage_mode") != official_mode(dataset_id)
            or any(
                row.get(field) != expected_policy[field]
                for field in ("policy_id", "policy_version", "policy_digest")
            )
            or not source_value
            or not export_value
            or source_value != export_value
            or source_value != applied_value
        ):
            raise MassResearchDisabledError(
                f"snapshot profile evidence is not current COMPLETE for {dataset_id}"
            )
        source[dataset_id] = source_value
        exported[dataset_id] = export_value
        applied[dataset_id] = applied_value
        if row.get("signed_projection_document_digest"):
            signed_projection_cursors.add(applied_value)

    # A verified Ops envelope is useful only when it describes the exact
    # generation applied to this local snapshot.  The signature protects the
    # remote cursor chain; this comparison closes the remaining remote->local
    # boundary before any ReadyManifest can be built.
    if signed_projection_cursors:
        local_change_seq = str(document.get("change_seq") or "").strip()
        if signed_projection_cursors != {local_change_seq}:
            raise MassResearchDisabledError(
                "signed Ops Projection applied cursor does not match the "
                "local snapshot generation"
            )

    dependency_scope = document.get("dependency_scope_evidence")
    if (
        not isinstance(dependency_scope, Mapping)
        or dependency_scope.get("format") != "pit-dependency-scope-proof/v1"
        or dependency_scope.get("status") != "PASS"
        or dependency_scope.get("profile_digest") != profile.profile_digest
        or dependency_scope.get("plan_set_digest") != profile.plan_set_digest
        or dependency_scope.get("dependency_closure_digest")
        != profile.closure_set_digest
        or not is_sha256_digest(dependency_scope.get("proof_digest"))
    ):
        raise MassResearchDisabledError(
            "snapshot PIT dependency-period availability proof is missing or invalid"
        )
    scope_body = {
        key: value
        for key, value in dependency_scope.items()
        if key != "proof_digest"
    }
    if canonical_digest(scope_body) != dependency_scope.get("proof_digest"):
        raise MassResearchDisabledError(
            "snapshot PIT dependency-period availability proof digest mismatch"
        )

    raw_manifests = document.get("raw_manifests")
    validations = document.get("validations")
    quality = document.get("quality")
    ready_evidence = document.get("ready_evidence")
    if not isinstance(raw_manifests, Mapping) or not raw_manifests:
        raise MassResearchDisabledError("snapshot raw proof evidence missing")
    if not isinstance(validations, list) or not validations:
        raise MassResearchDisabledError("snapshot validation proof evidence missing")
    if (
        not isinstance(quality, Mapping)
        or quality.get("status") != "PASS"
        or quality.get("failures") not in ([], ())
    ):
        raise MassResearchDisabledError("snapshot B0/quality evidence is not PASS")
    if (
        not isinstance(ready_evidence, Mapping)
        or ready_evidence.get("passed") is not True
        or not isinstance(ready_evidence.get("items"), list)
    ):
        raise MassResearchDisabledError(
            "snapshot READY policy evidence is missing or not PASS"
        )
    ready_items = {
        str(row.get("name")): row
        for row in ready_evidence["items"]
        if isinstance(row, Mapping) and row.get("name")
    }
    required_ready_items = {
        "CoverageEvidence",
        "RawRetentionEvidence",
        "ValidationEvidence",
        "NaturalKeyEvidence",
        "QualityEvidence",
        "SyncGenerationEvidence",
    }
    if (
        not required_ready_items <= set(ready_items)
        or any(ready_items[name].get("passed") is not True for name in required_ready_items)
    ):
        raise MassResearchDisabledError(
            "snapshot READY policy typed evidence is incomplete"
        )
    quality_evidence = ready_items["QualityEvidence"]
    quality_detail = quality_evidence.get("detail")
    if (
        not isinstance(quality_detail, Mapping)
        or quality_detail.get("b0_status") != "PASS"
        or quality_detail.get("quality_status") != "PASS"
    ):
        raise MassResearchDisabledError("snapshot B0 evidence is not PASS")
    sync_evidence = ready_items["SyncGenerationEvidence"]
    sync_detail = sync_evidence.get("detail")
    if not isinstance(sync_detail, Mapping):
        raise MassResearchDisabledError("snapshot sync evidence detail is missing")
    try:
        local_source_generation = int(sync_detail["source_generation"])
        local_applied_generation = int(sync_detail["applied_sync_generation"])
        manifest_change_seq = int(document["change_seq"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "snapshot source/applied generation evidence is malformed"
        ) from exc
    if (
        local_source_generation <= 0
        or local_source_generation != local_applied_generation
        or local_applied_generation != manifest_change_seq
    ):
        raise MassResearchDisabledError(
            "snapshot source/applied generation evidence is not current"
        )
    quality_results = quality.get("results")
    if not isinstance(quality_results, list):
        raise MassResearchDisabledError("snapshot B4 evidence is missing")
    b4_results = [
        dict(row)
        for row in quality_results
        if isinstance(row, Mapping) and row.get("check_id") == "B4"
    ]
    if not b4_results or any(row.get("status") != "pass" for row in b4_results):
        raise MassResearchDisabledError("snapshot B4 evidence is not PASS")
    created_at = document.get("created_at")
    published_at = document.get("committed_at")

    plan_ids = tuple(
        str(item) for item in getattr(profile, "plan_ids", ()) if str(item)
    )
    if not plan_ids and str(getattr(profile, "plan_id", "") or ""):
        plan_ids = (str(profile.plan_id),)
    plan_digest = str(
        getattr(profile, "plan_set_digest", "")
        or getattr(profile, "plan_digest", "")
    )
    closure_digest = str(
        getattr(profile, "closure_set_digest", "")
        or getattr(profile, "dependency_closure_digest", "")
    )
    publication_scope = str(
        getattr(profile, "publication_scope", "")
        or ("PILOT" if getattr(profile, "plan_id", None) else "")
    )
    if (
        not plan_ids
        or not is_sha256_digest(plan_digest)
        or not is_sha256_digest(closure_digest)
        or publication_scope != "PILOT"
    ):
        raise MassResearchDisabledError(
            "READY publication requires an explicit plan-bound PILOT profile; "
            "generic/core Mass publication is disabled"
        )

    return build_ready_manifest(
        snapshot_id=str(snapshot_id),
        publication_scope=publication_scope,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_digest=profile.profile_digest,
        plan_ids=plan_ids,
        plan_set_digest=plan_digest,
        dependency_closure_digest=closure_digest,
        dataset_ids=profile.required_datasets,
        coverage_proof_digest=canonical_digest(
            {
                "coverage_proof_digest": coverage_proof["proof_digest"],
                "coverage_policy_version": coverage_proof["policy_version"],
                "coverage_policy_digest": coverage_proof["policy_digest"],
                "profile_id": profile.profile_id,
                "profile_version": profile.profile_version,
                "profile_evidence_by_dataset": profile_evidence,
            }
        ),
        raw_proof_digest=canonical_digest(raw_manifests),
        receipt_proof_digest=canonical_digest(
            {
                "coverage_receipt_count": coverage_proof.get("receipt_count"),
                "trusted_receipt_proof_digest": coverage_proof["proof_digest"],
            }
        ),
        validation_proof_digest=canonical_digest(validations),
        b0_proof_digest=canonical_digest(
            {
                "quality_policy_version": document.get("quality_policy_version"),
                "ready_policy_quality_evidence": quality_evidence,
            }
        ),
        b4_proof_digest=canonical_digest(b4_results),
        source_generation=canonical_digest(source),
        applied_sync_generation=canonical_digest(applied),
        export_cursor=canonical_digest(exported),
        applied_cursor=canonical_digest(applied),
        pit_contract_digests={
            "pit_api": canonical_digest({"pit_api_version": PIT_API_VERSION}),
            "dependency_scope": str(dependency_scope["proof_digest"]),
        },
        feature_generation=canonical_digest(
            {
                "profile_digest": profile.profile_digest,
                "feature_dependencies": profile.feature_dependencies,
            }
        ),
        catalog_generation=canonical_digest(
            {
                "profile_digest": profile.profile_digest,
                "contract_versions": profile.contract_versions,
                "dataset_ids": profile.required_datasets,
            }
        ),
        created_at=str(created_at or MISSING),
        published_at=str(published_at or MISSING),
    )


def _verify_exact_four_pit_dependency_scope(
    db_path: str | Path,
    binding: ExactFourPilotReadyBinding,
) -> dict[str, Any]:
    """Prove the immutable local DB has PIT-visible rows for every plan scope.

    Dataset-level COMPLETE alone is insufficient: historical rows re-fetched
    after a plan period are not visible to that historical ``as_of``.  This
    proof checks the local row-level ``available_at`` wall, including every
    derivable feature lookback, and is recomputed on the immutable artifact
    before the readiness sidecar is signed.
    """
    source = Path(db_path)
    if not source.is_file():
        raise MassResearchDisabledError(
            f"PIT dependency scope database is missing: {source}"
        )
    uri = "file:" + str(source.resolve()) + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise MassResearchDisabledError(
            "cannot open PIT dependency scope database"
        ) from exc
    try:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(jquants_records)")
        }
        required_columns = {"dataset", "event_time", "available_at"}
        if not required_columns <= columns:
            raise MassResearchDisabledError(
                "PIT dependency scope requires jquants_records dataset/event_time/available_at"
            )
        entries: list[dict[str, Any]] = []
        for profile in binding.profiles:
            for raw_scope in profile.dataset_scopes:
                scope = dict(raw_scope)
                dataset_id = str(scope["dataset_id"])
                period_start = str(scope["period_start"])
                period_end = str(scope["period_end"])
                lookback = int(scope["required_lookback_trading_days"])
                start_as_of = f"{period_start}T23:59:59+09:00"
                end_as_of = f"{period_end}T23:59:59+09:00"
                row = conn.execute(
                    """
                    SELECT
                      SUM(CASE WHEN substr(event_time, 1, 10) <= ?
                                    AND julianday(available_at) <= julianday(?)
                               THEN 1 ELSE 0 END) AS visible_at_start,
                      SUM(CASE WHEN substr(event_time, 1, 10) BETWEEN ? AND ?
                                    AND julianday(available_at) <= julianday(?)
                               THEN 1 ELSE 0 END) AS visible_in_period,
                      COUNT(DISTINCT CASE
                        WHEN substr(event_time, 1, 10) < ?
                         AND julianday(available_at) <= julianday(?)
                        THEN substr(event_time, 1, 10) END
                      ) AS visible_pre_period_dates
                    FROM jquants_records
                    WHERE dataset = ?
                    """,
                    (
                        period_start,
                        start_as_of,
                        period_start,
                        period_end,
                        end_as_of,
                        period_start,
                        start_as_of,
                        dataset_id,
                    ),
                ).fetchone()
                visible_at_start = int(row[0] or 0) if row is not None else 0
                visible_in_period = int(row[1] or 0) if row is not None else 0
                visible_pre_dates = int(row[2] or 0) if row is not None else 0
                if (
                    visible_at_start <= 0
                    or visible_in_period <= 0
                    or visible_pre_dates < lookback
                ):
                    raise MassResearchDisabledError(
                        "PIT dependency scope is not usable for "
                        f"{profile.plan_id}/{dataset_id}: "
                        f"visible_at_start={visible_at_start}, "
                        f"visible_in_period={visible_in_period}, "
                        f"visible_pre_period_dates={visible_pre_dates}, "
                        f"required_lookback={lookback}"
                    )
                entries.append(
                    {
                        "plan_id": profile.plan_id,
                        "dataset_id": dataset_id,
                        "period_start": period_start,
                        "period_end": period_end,
                        "required_lookback_trading_days": lookback,
                        "visible_at_start": visible_at_start,
                        "visible_in_period": visible_in_period,
                        "visible_pre_period_dates": visible_pre_dates,
                    }
                )
    except sqlite3.Error as exc:
        raise MassResearchDisabledError(
            "PIT dependency scope query failed closed"
        ) from exc
    finally:
        conn.close()
    body = {
        "format": "pit-dependency-scope-proof/v1",
        "status": "PASS",
        "profile_digest": binding.profile_digest,
        "plan_set_digest": binding.plan_set_digest,
        "dependency_closure_digest": binding.closure_set_digest,
        "entries": entries,
    }
    return {**body, "proof_digest": canonical_digest(body)}


def _verified_production_projection_evidence(
    signed_document: Mapping[str, Any] | None,
    required_datasets: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Verify one signed Ops envelope and derive the bounded READY input.

    Raw ``OPS_PROJECTION_DB`` rows and caller-created JSON mappings are never
    authority.  The registry contains public keys only; its default checked-in
    document intentionally has no active key until operations provisions one.
    """
    from data_contracts.coverage import (
        coverage_policy_binding,
        coverage_policy_set_binding,
    )
    from ops.projection_signing import (
        OpsProjectionPublicKeyRegistry,
        OpsProjectionSignatureError,
    )
    from ops.projection_meta import DEFAULT_MAX_AGE_SECONDS

    if not isinstance(signed_document, Mapping):
        raise MassResearchDisabledError(
            "production READY requires a signed Ops Projection evidence envelope"
        )
    try:
        # Production trust roots are loaded by the publication service.  A
        # caller-provided registry would let the caller sign its own envelope
        # and turn a syntactically valid document into READY authority.
        registry = OpsProjectionPublicKeyRegistry.load_pinned()
        if not isinstance(registry, OpsProjectionPublicKeyRegistry):
            raise OpsProjectionSignatureError(
                "Ops Projection public-key registry required"
            )
        envelope = registry.verify(signed_document)
        evidence = registry.verified_dataset_evidence(
            signed_document, tuple(str(item) for item in required_datasets)
        )
    except OpsProjectionSignatureError as exc:
        raise MassResearchDisabledError(
            f"signed Ops Projection evidence rejected: {exc}"
        ) from exc

    if envelope.get("projection_status") != "FRESH":
        raise MassResearchDisabledError(
            "signed Ops Projection evidence is not FRESH"
        )
    try:
        generated_at = datetime.fromisoformat(
            str(envelope.get("generated_at") or "").replace("Z", "+00:00")
        )
        if generated_at.tzinfo is None:
            raise ValueError("timezone required")
        age_seconds = (_now() - generated_at).total_seconds()
    except (TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "signed Ops Projection generated_at is malformed"
        ) from exc
    if age_seconds < -300 or age_seconds > DEFAULT_MAX_AGE_SECONDS:
        raise MassResearchDisabledError(
            "signed Ops Projection evidence is outside the freshness SLA"
        )
    signed_coverage = envelope.get("dataset_coverage")
    if not isinstance(signed_coverage, Mapping):  # verifier validates shape
        raise MassResearchDisabledError(
            "signed Ops Projection dataset Coverage evidence is missing"
        )
    try:
        signed_policy_set = coverage_policy_set_binding(
            sorted(str(dataset_id) for dataset_id in signed_coverage)
        )
    except (KeyError, ValueError) as exc:
        raise MassResearchDisabledError(
            "signed Ops Projection contains an unknown governed policy row"
        ) from exc
    if (
        envelope.get("coverage_policy_version")
        != signed_policy_set["policy_version"]
        or envelope.get("coverage_policy_digest")
        != signed_policy_set["policy_digest"]
    ):
        raise MassResearchDisabledError(
            "signed Ops Projection Coverage policy-set binding mismatch"
        )
    if envelope.get("b0_status") != "PASS" or envelope.get("b4_status") != "PASS":
        raise MassResearchDisabledError(
            "signed Ops Projection B0/B4 evidence is not PASS"
        )
    cursor_values = (
        envelope.get("source_generation"),
        envelope.get("export_cursor"),
        envelope.get("applied_cursor"),
    )
    if (
        any(not isinstance(value, int) or value <= 0 for value in cursor_values)
        or len(set(cursor_values)) != 1
    ):
        raise MassResearchDisabledError(
            "signed Ops Projection source/export/applied cursor is null or not current"
        )

    document_digest = canonical_digest(dict(signed_document))
    issuer_key_id = str(signed_document.get("issuer_key_id") or "").strip()
    for dataset_id, row in evidence.items():
        expected_policy = coverage_policy_binding(dataset_id)
        if any(
            row.get(field) != expected_policy[field]
            for field in ("policy_id", "policy_version", "policy_digest")
        ):
            raise MassResearchDisabledError(
                f"signed Ops Projection governed policy binding mismatch for {dataset_id}"
            )
        row["signed_projection_document_digest"] = document_digest
        row["signed_projection_issuer_key_id"] = issuer_key_id
    return evidence


def _publish_exact_four_pilot_ready_snapshot_impl(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    signed_projection_document: Mapping[str, Any],
) -> Any:
    """Publish one immutable READY generation bound to the exact-four closure.

    The caller cannot choose dataset membership, plan ids, or closure digests.
    They are compiled from the governed exact-four plans before the runtime
    publication transaction starts.
    """
    from paper_runtime.snapshot import _publish_ready_snapshot
    from research.research_data_profile import profile_ready

    governed = load_exact_four_pilot_ready_binding()
    evidence = _verified_production_projection_evidence(
        signed_projection_document,
        governed.required_datasets,
    )
    if not isinstance(evidence, Mapping) or set(
        evidence
    ) != set(governed.required_datasets):
        raise MassResearchDisabledError(
            "pilot READY evidence must exactly match the dependency closure"
        )
    for profile in governed.profiles:
        if not profile_ready(profile, evidence):
            raise MassResearchDisabledError(
                f"pilot READY evidence is incomplete for {profile.plan_id}"
            )
    for dataset_id in governed.required_datasets:
        row = evidence.get(dataset_id)
        if not isinstance(row, Mapping):
            raise MassResearchDisabledError(
                f"pilot READY evidence missing for {dataset_id}"
            )
        source = str(row.get("source_generation") or "").strip()
        exported = str(row.get("export_cursor") or "").strip()
        applied = str(
            row.get("applied_sync_generation") or row.get("applied_cursor") or ""
        ).strip()
        if not source or source != exported or exported != applied:
            raise MassResearchDisabledError(
                f"pilot READY cursor chain is missing or not current for {dataset_id}"
            )
        scopes = [
            dict(scope)
            for profile in governed.profiles
            for scope in profile.dataset_scopes
            if scope.get("dataset_id") == dataset_id
        ]
        required_start = min(str(scope["period_start"]) for scope in scopes)
        required_end = max(str(scope["period_end"]) for scope in scopes)
        observed_start = str(row.get("observed_start") or "")[:10]
        observed_end = str(row.get("observed_end") or "")[:10]
        if (
            not observed_start
            or not observed_end
            or observed_start > required_start
            or observed_end < required_end
        ):
            raise MassResearchDisabledError(
                "pilot READY Coverage does not span the dependency period for "
                f"{dataset_id}: observed={observed_start}..{observed_end}, "
                f"required={required_start}..{required_end}"
            )

    def _build(document: Mapping[str, Any]) -> Mapping[str, Any]:
        scope_proof = _verify_exact_four_pit_dependency_scope(
            staging_db, governed
        )
        enriched = dict(document)
        enriched["dependency_scope_evidence"] = scope_proof
        return build_profile_bound_ready_manifest_from_snapshot_document(
            enriched, profile=governed
        ).to_dict()

    published_attestation: dict[str, Any] = {}

    def _attest(ready: Any) -> Path:
        from paper_runtime.snapshot_persist import _atomic_json
        from research.readiness import _load_pinned_ready_publication_signer

        manifest = ready_manifest_from_snapshot_document(ready.manifest)
        immutable_scope_proof = _verify_exact_four_pit_dependency_scope(
            ready.db_path, governed
        )
        if (
            manifest.pit_contract_digests.get("dependency_scope")
            != immutable_scope_proof["proof_digest"]
        ):
            raise MassResearchDisabledError(
                "immutable snapshot PIT dependency scope proof drifted before signing"
            )
        signer = _load_pinned_ready_publication_signer()
        readiness = signer._mint_pilot(
            manifest,
            db_path=ready.db_path,
            profile_binding=governed,
        )
        readiness_path = ready.db_path.with_name(
            f"{ready.db_path.stem}.{readiness.attestation_id}.readiness.json"
        )
        try:
            _atomic_json(readiness_path, readiness.to_dict(), mode=0o444)
        except Exception:
            # `_atomic_json` is replace-last, but a filesystem error may be
            # raised after the destination appears. Never retain a signed
            # capability for a publication that the caller observes failing.
            readiness_path.unlink(missing_ok=True)
            raise
        published_attestation.update(
            readiness=readiness,
            readiness_path=readiness_path,
        )
        return readiness_path

    snapshot = _publish_ready_snapshot(
        staging_db,
        snapshot_dir,
        required_datasets=governed.required_datasets,
        _profile_coverage_evidence=evidence,
        _ready_manifest_builder=_build,
        _ready_attestation_builder=_attest,
    )
    if set(published_attestation) != {"readiness", "readiness_path"}:
        raise MassResearchDisabledError(
            "atomic pilot readiness attestation was not produced"
        )
    return VerifiedPilotReadyPublication(
        snapshot=snapshot,
        readiness=published_attestation["readiness"],
        readiness_path=Path(published_attestation["readiness_path"]),
    )


def publish_exact_four_pilot_ready_snapshot(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    signed_projection_document: Mapping[str, Any],
) -> Any:
    """Production exact-four READY publisher; signed Ops authority is required.

    The public surface has no fixture switch, unsigned evidence mapping, or
    caller-selected plan/profile binding.
    """
    return _publish_exact_four_pilot_ready_snapshot_impl(
        staging_db,
        snapshot_dir,
        signed_projection_document=signed_projection_document,
    )


def ready_manifest_from_snapshot_document(document: Mapping[str, Any]) -> ReadyManifest:
    """Read the publisher-owned ReadyManifest and bind it to its outer snapshot.

    Legacy snapshot fields are intentionally not upgraded into READY proofs at
    read time.  The publisher must have emitted the closed manifest while it
    still had the profile, raw, validation, B0, generation, and PIT evidence.
    """
    if not isinstance(document, Mapping):
        raise MassResearchDisabledError("snapshot document must be an object")
    if document.get("format") == READY_MANIFEST_FORMAT:
        return ReadyManifest.from_dict(document)
    nested = document.get("ready_manifest")
    if not isinstance(nested, Mapping):
        raise MassResearchDisabledError(
            "snapshot document has no publisher-owned ReadyManifest"
        )
    manifest = ReadyManifest.from_dict(nested)
    if document.get("state") != "READY":
        raise MassResearchDisabledError("outer snapshot is not READY")
    if manifest.snapshot_id != document.get("snapshot_id"):
        raise MassResearchDisabledError("ReadyManifest snapshot_id binding mismatch")
    required = document.get("required_datasets")
    if not isinstance(required, list) or sorted(required) != sorted(manifest.dataset_ids):
        raise MassResearchDisabledError("ReadyManifest dataset membership binding mismatch")
    if manifest.published_at != document.get("committed_at"):
        raise MassResearchDisabledError("ReadyManifest published_at binding mismatch")
    profile = validate_ready_manifest_profile_binding(manifest)
    expected = build_profile_bound_ready_manifest_from_snapshot_document(
        document, profile=profile
    )
    if manifest.to_dict() != expected.to_dict():
        raise MassResearchDisabledError("ReadyManifest publisher evidence binding mismatch")
    return manifest


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or value.strip() in ABSENT_PROOFS:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def missing_ready_manifest_proofs(manifest: ReadyManifest) -> list[str]:
    """Proof fields that are UNKNOWN/MISSING. Absence is not PASS."""
    body = manifest.to_dict()
    missing: list[str] = []
    if body.get("manifest_digest") != _manifest_digest_for(
        manifest.to_canonical_dict()
    ):
        missing.append("manifest_digest.binding")
    if not is_sha256_digest(body.get("snapshot_id")):
        missing.append("snapshot_id")
    if body.get("publication_scope") not in {"PILOT", "MASS"}:
        missing.append("publication_scope")
    for field in ("profile_id", "profile_version"):
        value = body.get(field)
        if not isinstance(value, str) or value.strip() in ABSENT_PROOFS:
            missing.append(field)
    dataset_ids = body.get("dataset_ids")
    if (
        not isinstance(dataset_ids, list)
        or not dataset_ids
        or any(not isinstance(item, str) or not item.strip() for item in dataset_ids)
        or len(dataset_ids) != len(set(dataset_ids))
    ):
        missing.append("dataset_ids")
    elif compute_dataset_membership_digest(dataset_ids) != body.get(
        "dataset_membership_digest"
    ):
        missing.append("dataset_membership_digest.binding")
    if dataset_ids:
        from data_contracts.coverage import coverage_policy_set_binding

        try:
            expected_policy = coverage_policy_set_binding(dataset_ids)
        except (KeyError, ValueError):
            missing.append("coverage_policy.binding")
        else:
            if body.get("coverage_policy_version") != expected_policy["policy_version"]:
                missing.append("coverage_policy_version.binding")
            if body.get("coverage_policy_digest") != expected_policy["policy_digest"]:
                missing.append("coverage_policy_digest.binding")
    if (
        not isinstance(body.get("coverage_policy_version"), str)
        or str(body.get("coverage_policy_version")).strip() in ABSENT_PROOFS
    ):
        missing.append("coverage_policy_version")
    plan_ids = body.get("plan_ids")
    if (
        not isinstance(plan_ids, list)
        or not plan_ids
        or any(not isinstance(item, str) or not item.strip() for item in plan_ids)
        or len(plan_ids) != len(set(plan_ids))
    ):
        missing.append("plan_ids")
    for field in PROOF_DIGEST_FIELDS:
        if not is_sha256_digest(body.get(field)):
            missing.append(field)
    for field in GENERATION_PIN_FIELDS:
        value = body.get(field)
        if not isinstance(value, str) or value.strip() in ABSENT_PROOFS:
            missing.append(field)
    if (
        body.get("source_generation") not in ABSENT_PROOFS
        and body.get("applied_sync_generation") not in ABSENT_PROOFS
        and body.get("source_generation") != body.get("applied_sync_generation")
    ):
        missing.append("source_generation.current_sync")
    cursor_values = [
        body.get("source_generation"),
        body.get("export_cursor"),
        body.get("applied_cursor"),
    ]
    if all(value not in ABSENT_PROOFS for value in cursor_values) and len(
        set(cursor_values)
    ) != 1:
        missing.append("source_export_applied_cursor.current_sync")
    timestamps = {field: _aware_datetime(body.get(field)) for field in TIMESTAMP_FIELDS}
    for field, value in timestamps.items():
        if value is None:
            missing.append(field)
    if (
        timestamps["created_at"] is not None
        and timestamps["published_at"] is not None
        and timestamps["published_at"] < timestamps["created_at"]
    ):
        missing.append("published_at.order")
    pit = body.get("pit_contract_digests")
    if not isinstance(pit, Mapping) or not pit:
        missing.append("pit_contract_digests")
    else:
        for key, value in pit.items():
            if not is_sha256_digest(value):
                missing.append(f"pit_contract_digests.{key}")
    return missing


def validate_ready_manifest_profile_binding(
    manifest: ReadyManifest,
    *,
    profile: Any | None = None,
) -> Any:
    """Require exact membership and identity against the governed profile."""
    from research.research_data_profile import ResearchDataProfile

    if manifest.publication_scope == "MASS":
        raise MassResearchDisabledError(
            "Mass ReadyManifest validation requires a separately governed Mass "
            "authority; Mass Research remains disabled"
        )

    governed = profile
    if governed is None:
        if (
            manifest.publication_scope == "PILOT"
            and manifest.profile_id == "controlled-pilot/exact-four"
        ):
            governed = load_exact_four_pilot_ready_binding()
        else:
            from research.experiment_plans import load_experiment_plan_profiles

            governed = next(
                (
                    item
                    for item in load_experiment_plan_profiles()
                    if item.profile_id == manifest.profile_id
                ),
                None,
            )
        if governed is None:
            raise MassResearchDisabledError(
                f"governed profile not supplied for {manifest.profile_id!r}"
            )
    if not isinstance(governed, (ResearchDataProfile, ExactFourPilotReadyBinding)):
        raise MassResearchDisabledError("ResearchDataProfile required")
    if manifest.profile_id != governed.profile_id:
        raise MassResearchDisabledError("ReadyManifest profile_id mismatch")
    if manifest.profile_version != governed.profile_version:
        raise MassResearchDisabledError("ReadyManifest profile_version mismatch")
    if manifest.profile_digest != governed.profile_digest:
        raise MassResearchDisabledError("ReadyManifest profile_digest mismatch")
    governed_scope = str(
        getattr(governed, "publication_scope", "")
        or ("PILOT" if getattr(governed, "plan_id", None) else "")
    )
    if manifest.publication_scope != governed_scope:
        raise MassResearchDisabledError("ReadyManifest publication_scope mismatch")
    governed_plan_ids = tuple(
        str(item) for item in getattr(governed, "plan_ids", ()) if str(item)
    )
    if not governed_plan_ids and str(getattr(governed, "plan_id", "") or ""):
        governed_plan_ids = (str(governed.plan_id),)
    if not governed_plan_ids or governed_scope != "PILOT":
        raise MassResearchDisabledError(
            "ReadyManifest requires an explicit governed plan binding"
        )
    if manifest.plan_ids != governed_plan_ids:
        raise MassResearchDisabledError("ReadyManifest plan_ids mismatch")
    expected_plan_set = str(
        getattr(governed, "plan_set_digest", "")
        or getattr(governed, "plan_digest", "")
    )
    expected_closure = str(
        getattr(governed, "closure_set_digest", "")
        or getattr(governed, "dependency_closure_digest", "")
    )
    if not is_sha256_digest(expected_plan_set) or not is_sha256_digest(
        expected_closure
    ):
        raise MassResearchDisabledError(
            "governed profile has no explicit plan/dependency digest authority"
        )
    if manifest.plan_set_digest != expected_plan_set:
        raise MassResearchDisabledError("ReadyManifest plan_set_digest mismatch")
    if manifest.dependency_closure_digest != expected_closure:
        raise MassResearchDisabledError(
            "ReadyManifest dependency_closure_digest mismatch"
        )
    if (
        len(manifest.dataset_ids) != len(governed.required_datasets)
        or set(manifest.dataset_ids) != set(governed.required_datasets)
    ):
        raise MassResearchDisabledError(
            "ReadyManifest dataset_ids do not exactly match the research profile"
        )
    expected_membership = compute_dataset_membership_digest(governed.required_datasets)
    if manifest.dataset_membership_digest != expected_membership:
        raise MassResearchDisabledError(
            "ReadyManifest dataset_membership_digest does not match the research profile"
        )
    from data_contracts.coverage import coverage_policy_set_binding

    expected_policy = coverage_policy_set_binding(list(governed.required_datasets))
    if (
        manifest.coverage_policy_version != expected_policy["policy_version"]
        or manifest.coverage_policy_digest != expected_policy["policy_digest"]
    ):
        raise MassResearchDisabledError(
            "ReadyManifest governed Coverage policy-set binding mismatch"
        )
    return governed


def core_profile_source_capability_gaps(*, root: Path | None = None) -> tuple[str, ...]:
    """Core required dataset ids with no SourceCapability file.

    Missing ids are UNKNOWN, not invented PASS. Does not write V3 JSON.
    """
    base = root or repo_root()
    spec_path = base / CORE_PROFILE_REL
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    required = raw.get("required_datasets")
    if not isinstance(required, list) or not required:
        raise MassResearchDisabledError("core profile required_datasets missing")
    cap_dir = base / SOURCE_CAPABILITY_REL
    missing = [
        str(dataset_id)
        for dataset_id in required
        if not (cap_dir / f"{dataset_id}.json").is_file()
    ]
    return tuple(missing)


def require_core_profile_deps_subseteq_source_capability_registry(
    *, root: Path | None = None
) -> None:
    """Build invariant: every core dataset has a SourceCapability file."""
    missing = core_profile_source_capability_gaps(root=root)
    if missing:
        raise AssertionError(
            "core profile datasets missing SourceCapability files: "
            + ", ".join(missing)
        )


READY_MANIFEST_SCHEMA: dict[str, Any] = load_ready_manifest_schema()

__all__ = [
    "ABSENT_PROOFS",
    "GENERATION_PIN_FIELDS",
    "MISSING",
    "PROOF_DIGEST_FIELDS",
    "READY_MANIFEST_FORMAT",
    "READY_MANIFEST_SCHEMA",
    "SCHEMA_REL",
    "UNKNOWN",
    "TIMESTAMP_FIELDS",
    "ExactFourPilotReadyBinding",
    "ReadyManifest",
    "VerifiedPilotReadyPublication",
    "build_ready_manifest",
    "build_profile_bound_ready_manifest_from_snapshot_document",
    "canonical_digest",
    "compute_dataset_membership_digest",
    "core_profile_source_capability_gaps",
    "is_sha256_digest",
    "load_ready_manifest",
    "load_ready_manifest_schema",
    "load_exact_four_pilot_ready_binding",
    "missing_ready_manifest_proofs",
    "pin_or_missing",
    "publish_exact_four_pilot_ready_snapshot",
    "proof_or_missing",
    "ready_manifest_from_snapshot_document",
    "require_core_profile_deps_subseteq_source_capability_registry",
    "serialize_ready_manifest",
    "validate_ready_manifest_document",
    "validate_ready_manifest_profile_binding",
]
