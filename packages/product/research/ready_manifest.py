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
from weakref import WeakKeyDictionary

from qp_paths import repo_root
from selection.budget_ledger import MassResearchDisabledError
from storage.receipt_crypto import (
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
)

READY_MANIFEST_FORMAT: str = "ready-manifest/v1"
SCHEMA_REL: Path = Path("specs") / "ready" / "ready_manifest.schema.json"
CORE_PROFILE_REL: Path = Path("specs") / "research_profiles" / "core_v1.json"
MISSING: str = "MISSING"
UNKNOWN: str = "UNKNOWN"
ABSENT_PROOFS: frozenset[str] = frozenset({MISSING, UNKNOWN, ""})
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROOF_RE = re.compile(r"(?:sha256:[0-9a-f]{64}|UNKNOWN|MISSING)\Z")

PROOF_DIGEST_FIELDS: tuple[str, ...] = (
    "profile_digest",
    "plan_set_digest",
    "dependency_closure_digest",
    "universe_rule_digest",
    "resolved_universe_digest",
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
    universe_rule_digest: str
    resolved_universe_digest: str
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
            "universe_rule_digest": self.universe_rule_digest,
            "resolved_universe_digest": self.resolved_universe_digest,
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
            "universe_rule_digest": proof_or_missing(
                document.get("universe_rule_digest")
            ),
            "resolved_universe_digest": proof_or_missing(
                document.get("resolved_universe_digest")
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
    universe_rule_digest: str | None = None,
    resolved_universe_digest: str | None = None,
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
            "universe_rule_digest": proof_or_missing(universe_rule_digest),
            "resolved_universe_digest": proof_or_missing(
                resolved_universe_digest
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

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ExactFourPilotReadyBinding is final")

    plans: tuple[Any, ...]
    closures: tuple[Any, ...]
    profiles: tuple[Any, ...]
    publication_scope: str = "PILOT"
    profile_id: str = "controlled-pilot/exact-four"
    profile_version: str = "research-data-profile-set/v1"

    def __post_init__(self) -> None:
        from research.artifacts import ExperimentPlan
        from research.dependency_closure import (
            PlanDependencyClosure,
            verify_plan_dependency_closure,
        )
        from research.experiment_plans import (
            PILOT_EXPERIMENT_PLAN_IDS,
            PILOT_PLAN_COUNT,
            load_experiment_plan_closures,
            load_experiment_plan_profiles,
            load_experiment_plans,
        )
        from research.research_data_profile import ResearchDataProfile

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
        if any(type(plan) is not ExperimentPlan for plan in self.plans):
            raise MassResearchDisabledError(
                "controlled pilot READY requires exact ExperimentPlan artifacts"
            )
        if any(
            type(closure) is not PlanDependencyClosure for closure in self.closures
        ):
            raise MassResearchDisabledError(
                "controlled pilot READY requires exact PlanDependencyClosure artifacts"
            )
        if any(type(profile) is not ResearchDataProfile for profile in self.profiles):
            raise MassResearchDisabledError(
                "controlled pilot READY requires exact ResearchDataProfile artifacts"
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
        # Retain only compiler-owned immutable artifacts. Canonical equality
        # must not retain a caller list or a directly constructed artifact
        # whose nested mappings alias mutable state.
        object.__setattr__(self, "plans", tuple(canonical_plans))
        object.__setattr__(self, "closures", tuple(canonical_closures))
        object.__setattr__(self, "profiles", tuple(canonical_profiles))

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
            for dependency in profile.to_dict()["feature_dependencies"]:
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
    """Production publication proven by its immutable signed sidecar."""

    snapshot: Any
    readiness: Any
    readiness_path: Path

    def __post_init__(self) -> None:
        from paper_runtime.snapshot import ReadySnapshot, _file_sha256
        from paper_runtime.snapshot_read import (
            _read_immutable_regular_file,
            describe_snapshot,
        )

        from research.readiness import (
            ReadyPublicationAuthorityPending,
            VerifiedPilotReadiness,
            _load_verified_pilot_readiness_bytes,
        )

        if type(self.snapshot) is not ReadySnapshot or type(
            self.readiness
        ) is not VerifiedPilotReadiness:
            raise ReadyPublicationAuthorityPending(
                "READY publication PENDING; caller cannot construct the result"
            )
        try:
            reopened = describe_snapshot(
                self.snapshot.db_path.parent,
                self.snapshot.snapshot_id,
            )
        except Exception as exc:
            raise ReadyPublicationAuthorityPending(
                "READY publication marker cannot be independently reopened"
            ) from exc
        if (
            reopened.db_path != self.snapshot.db_path
            or reopened.manifest_path != self.snapshot.manifest_path
            or reopened.manifest != self.snapshot.manifest
        ):
            raise MassResearchDisabledError(
                "caller snapshot differs from independently reopened publication"
            )
        manifest = ready_manifest_from_snapshot_document(reopened.manifest)
        path = Path(self.readiness_path)
        marker_path = reopened.readiness_path
        marker_digest = reopened.readiness_digest
        marker_attestation_id = reopened.readiness_attestation_id
        marker_bytes = reopened.readiness_bytes
        if (
            not isinstance(marker_path, Path)
            or path != marker_path
            or type(marker_digest) is not str
            or not _SHA256_RE.fullmatch(marker_digest)
            or type(marker_attestation_id) is not str
            or not marker_attestation_id
            or type(marker_bytes) is not bytes
            or not marker_bytes
            or "sha256:" + hashlib.sha256(marker_bytes).hexdigest()
            != marker_digest
        ):
            raise MassResearchDisabledError(
                "published snapshot marker has no exact readiness bytes"
            )
        reloaded = _load_verified_pilot_readiness_bytes(
            marker_bytes,
            expected_environment="production",
            expected_snapshot_id=reopened.snapshot_id,
            expected_ready_manifest_digest=manifest.manifest_digest,
        )
        if (
            reloaded.to_dict() != self.readiness.to_dict()
            or reloaded.attestation_id != marker_attestation_id
            or self.readiness.immutable_db_digest != _file_sha256(reopened.db_path)
            or path.parent.resolve() != reopened.db_path.parent.resolve()
            or _read_immutable_regular_file(path, label="READY attestation")
            != marker_bytes
            or path.stat().st_mode & 0o222
        ):
            raise MassResearchDisabledError(
                "published snapshot/readiness immutable binding mismatch"
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
    coverage_proof_id = document.get("coverage_proof_id")
    if not isinstance(coverage_proof, Mapping) or not is_sha256_digest(
        coverage_proof.get("proof_digest")
    ) or not is_sha256_digest(coverage_proof_id):
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
    from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST

    if (
        not isinstance(dependency_scope, Mapping)
        or dependency_scope.get("format") != "pit-dependency-scope-proof/v1"
        or dependency_scope.get("status") != "PASS"
        or dependency_scope.get("profile_digest") != profile.profile_digest
        or dependency_scope.get("plan_set_digest") != profile.plan_set_digest
        or dependency_scope.get("dependency_closure_digest")
        != profile.closure_set_digest
        or dependency_scope.get("universe_rule_digest")
        != EXACT_FOUR_UNIVERSE_RULE_DIGEST
        or not is_sha256_digest(
            dependency_scope.get("resolved_universe_digest")
        )
        or not is_sha256_digest(
            dependency_scope.get("product_materialization_digest")
        )
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

    profile_document = profile.to_dict()
    feature_dependencies = profile_document.get("feature_dependencies")
    if feature_dependencies is None:
        feature_dependencies = [
            dict(item) for item in profile.feature_dependencies
        ]
    contract_versions = profile_document.get("contract_versions")
    if contract_versions is None:
        contract_versions = dict(profile.contract_versions)

    return build_ready_manifest(
        snapshot_id=str(snapshot_id),
        publication_scope=publication_scope,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_digest=profile.profile_digest,
        plan_ids=plan_ids,
        plan_set_digest=plan_digest,
        dependency_closure_digest=closure_digest,
        universe_rule_digest=str(dependency_scope["universe_rule_digest"]),
        resolved_universe_digest=str(
            dependency_scope["resolved_universe_digest"]
        ),
        dataset_ids=profile.required_datasets,
        coverage_proof_digest=canonical_digest(
            {
                "coverage_proof_digest": coverage_proof["proof_digest"],
                "coverage_proof_id": coverage_proof_id,
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
                "coverage_proof_id": coverage_proof_id,
                "product_materialization_digest": dependency_scope[
                    "product_materialization_digest"
                ],
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
                "feature_dependencies": feature_dependencies,
            }
        ),
        catalog_generation=canonical_digest(
            {
                "profile_digest": profile.profile_digest,
                "contract_versions": contract_versions,
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
    """Prove the exact natural-key closure consumed by the controlled pilot.

    A single historical row cannot prove a period.  This gate derives the
    versioned daily universe from the candidate snapshot, enumerates every
    calendar/master/bar/TOPIX/financials key needed by that universe and its
    longest lookback, enforces ``available_at <= decision as_of``, and then
    requires every selected key to belong to a current v4 signed collection
    closure whose structured digest reproduces from the local database.
    """
    from core.execution import close_as_of
    from data_contracts import coverage_contract_for
    from data_contracts.identity import natural_key as contract_natural_key
    from research.universe_contract import (
        EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        resolve_tse_prime_with_fins,
    )
    from storage.coverage_ledger import CollectionReceipt
    from ops.receipt_product import (
        canonical_product_artifact_bytes,
        product_artifact_body_digest,
        product_artifact_digest,
    )
    from storage.verified_receipt import require_verified_collection_closure

    periods = {
        (str(profile.period_start), str(profile.period_end))
        for profile in binding.profiles
    }
    if len(periods) != 1:
        raise MassResearchDisabledError(
            "exact-four plans must share one governed universe period"
        )
    period_start, period_end = next(iter(periods))
    max_lookback = max(
        int(scope["required_lookback_trading_days"])
        for profile in binding.profiles
        for scope in profile.dataset_scopes
    )
    resolved_universe = resolve_tse_prime_with_fins(
        db_path,
        period_start=period_start,
        period_end=period_end,
    )

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
        required_columns = {
            "source",
            "dataset",
            "natural_key",
            "event_time",
            "available_at",
            "ingested_at",
            "payload",
            "raw_payload",
        }
        if not required_columns <= columns:
            raise MassResearchDisabledError(
                "PIT dependency scope requires canonical jquants_records columns"
            )
        required_datasets = tuple(binding.required_datasets)
        expected_exact = {
            "equities_bars_daily",
            "equities_master",
            "fins_summary",
            "indices_bars_daily_topix",
            "markets_calendar",
        }
        if set(required_datasets) != expected_exact:
            raise MassResearchDisabledError(
                "exact-four PIT verifier dataset closure drifted"
            )
        placeholders = ",".join("?" for _ in required_datasets)
        raw_rows = conn.execute(
            "SELECT * FROM jquants_records WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) "
            "ORDER BY dataset,event_time,natural_key",
            required_datasets,
        ).fetchall()
        rows_by_dataset: dict[str, list[dict[str, Any]]] = {
            dataset_id: [] for dataset_id in required_datasets
        }

        def _as_datetime(value: Any, label: str) -> datetime:
            try:
                parsed = datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                )
            except (TypeError, ValueError) as exc:
                raise MassResearchDisabledError(
                    f"PIT dependency scope {label} is malformed"
                ) from exc
            if parsed.tzinfo is None:
                raise MassResearchDisabledError(
                    f"PIT dependency scope {label} lacks timezone"
                )
            return parsed

        def _payload_value(payload: Mapping[str, Any], *names: str) -> str:
            for name in names:
                value = payload.get(name)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ""

        for raw in raw_rows:
            original = dict(raw)
            dataset_id = str(original["dataset"])
            payload_raw: Any = original.get("payload")
            if isinstance(payload_raw, str):
                try:
                    payload_raw = json.loads(payload_raw)
                except json.JSONDecodeError as exc:
                    raise MassResearchDisabledError(
                        f"{dataset_id} payload is not JSON"
                    ) from exc
            if not isinstance(payload_raw, Mapping):
                raise MassResearchDisabledError(
                    f"{dataset_id} payload is missing"
                )
            payload = {str(key): value for key, value in payload_raw.items()}
            expected_key = contract_natural_key(payload, dataset_id)
            if (
                expected_key.startswith("hash:sha256:")
                or original.get("natural_key") != expected_key
            ):
                raise MassResearchDisabledError(
                    f"{dataset_id} natural key is noncanonical"
                )
            rows_by_dataset[dataset_id].append(
                {
                    "original": original,
                    "payload": payload,
                    "natural_key": str(original["natural_key"]),
                    "event_date": str(original["event_time"])[:10],
                    "event_at": _as_datetime(
                        original["event_time"], f"{dataset_id}.event_time"
                    ),
                    "available_at": _as_datetime(
                        original["available_at"], f"{dataset_id}.available_at"
                    ),
                }
            )

        calendar_by_date: dict[str, dict[str, Any]] = {}
        for row in rows_by_dataset["markets_calendar"]:
            day = row["event_date"]
            if day in calendar_by_date:
                raise MassResearchDisabledError(
                    f"markets_calendar duplicates natural date {day}"
                )
            calendar_by_date[day] = row

        start_clock = _as_datetime(close_as_of(period_start), "period_start")
        prior_trading = sorted(
            day
            for day, row in calendar_by_date.items()
            if day < period_start
            and row["available_at"] <= start_clock
            and _payload_value(
                row["payload"], "HolidayDivision", "HolDiv", "holiday_division"
            )
            == "1"
        )
        if len(prior_trading) < max_lookback:
            raise MassResearchDisabledError(
                "PIT dependency scope lacks the exact calendar lookback: "
                f"visible={len(prior_trading)}, required={max_lookback}"
            )
        lookback_dates = tuple(prior_trading[-max_lookback:])
        scope_start = lookback_dates[0] if lookback_dates else period_start

        cursor = datetime.fromisoformat(scope_start).date()
        end_date = datetime.fromisoformat(period_end).date()
        calendar_dates: list[str] = []
        while cursor <= end_date:
            calendar_dates.append(cursor.isoformat())
            cursor = cursor.fromordinal(cursor.toordinal() + 1)
        selected_keys: dict[str, set[str]] = {
            dataset_id: set() for dataset_id in required_datasets
        }
        trading_dates: list[str] = []
        for day in calendar_dates:
            row = calendar_by_date.get(day)
            if row is None:
                raise MassResearchDisabledError(
                    f"markets_calendar missing exact scope date {day}"
                )
            if row["available_at"] > _as_datetime(close_as_of(day), day):
                raise MassResearchDisabledError(
                    f"markets_calendar {day} is late at decision time"
                )
            selected_keys["markets_calendar"].add(row["natural_key"])
            if _payload_value(
                row["payload"], "HolidayDivision", "HolDiv", "holiday_division"
            ) == "1":
                trading_dates.append(day)
        in_period_trading = tuple(
            day for day in trading_dates if period_start <= day <= period_end
        )
        if tuple(resolved_universe.membership_by_date) != in_period_trading:
            raise MassResearchDisabledError(
                "resolved universe decision dates do not equal the exact calendar"
            )
        first_membership = resolved_universe.codes_for(in_period_trading[0])

        def _row_code(row: Mapping[str, Any]) -> str:
            return _payload_value(row["payload"], "Code", "code")

        for day in in_period_trading:
            decision_clock = _as_datetime(close_as_of(day), day)
            members = resolved_universe.codes_for(day)
            visible_master = [
                row
                for row in rows_by_dataset["equities_master"]
                if row["event_date"] <= day
                and row["event_at"] <= decision_clock
                and row["available_at"] <= decision_clock
            ]
            if not visible_master:
                raise MassResearchDisabledError(
                    f"equities_master missing daily PIT snapshot for {day}"
                )
            latest_snapshot = max(row["event_date"] for row in visible_master)
            master_by_code = {
                _row_code(row): row
                for row in visible_master
                if row["event_date"] == latest_snapshot and _row_code(row)
            }
            missing_master = sorted(set(members) - set(master_by_code))
            if missing_master:
                raise MassResearchDisabledError(
                    f"equities_master missing resolved members at {day}: "
                    f"{missing_master[:5]}"
                )
            for code in members:
                selected_keys["equities_master"].add(
                    master_by_code[code]["natural_key"]
                )
                fins = [
                    row
                    for row in rows_by_dataset["fins_summary"]
                    if _row_code(row) == code
                    and row["event_at"] <= decision_clock
                    and row["available_at"] <= decision_clock
                ]
                if not fins:
                    raise MassResearchDisabledError(
                        f"fins_summary missing or late for {code} at {day}"
                    )
                latest_fins = max(
                    fins,
                    key=lambda row: (
                        row["event_at"],
                        row["available_at"],
                        row["natural_key"],
                    ),
                )
                selected_keys["fins_summary"].add(latest_fins["natural_key"])

        for day in trading_dates:
            decision_clock = _as_datetime(close_as_of(day), day)
            members = (
                resolved_universe.codes_for(day)
                if day >= period_start
                else first_membership
            )
            for code in members:
                matches = [
                    row
                    for row in rows_by_dataset["equities_bars_daily"]
                    if row["event_date"] == day
                    and _row_code(row) == code
                    and row["event_at"] <= decision_clock
                    and row["available_at"] <= decision_clock
                ]
                if len(matches) != 1:
                    raise MassResearchDisabledError(
                        "equities_bars_daily natural-key closure missing/late for "
                        f"{code}/{day}: rows={len(matches)}"
                    )
                selected_keys["equities_bars_daily"].add(
                    matches[0]["natural_key"]
                )
            topix = [
                row
                for row in rows_by_dataset["indices_bars_daily_topix"]
                if row["event_date"] == day
                and row["event_at"] <= decision_clock
                and row["available_at"] <= decision_clock
            ]
            if len(topix) != 1:
                raise MassResearchDisabledError(
                    "indices_bars_daily_topix exact trading-date closure "
                    f"missing/late for {day}: rows={len(topix)}"
                )
            selected_keys["indices_bars_daily_topix"].add(
                topix[0]["natural_key"]
            )

        receipt_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(collection_receipts)")
        }
        required_receipt_columns = {
            "source",
            "dataset",
            "segment_id",
            "segment_start",
            "segment_end",
            "expected_scope",
            "expected_items",
            "observed_items",
            "raw_page_count",
            "raw_row_count",
            "structured_row_count",
            "pagination_exhausted",
            "digests_json",
            "run_id",
            "status",
            "error",
            "checked_at",
        }
        if not required_receipt_columns <= receipt_columns:
            raise MassResearchDisabledError(
                "PIT dependency scope requires signed collection receipt columns"
            )
        product_columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(receipt_product_materializations)"
            )
        }
        required_product_columns = {
            "operation_id", "run_id", "source", "dataset", "segment_id",
            "artifact_key", "artifact_digest", "artifact_body", "row_count",
            "byte_count",
            "manifest_key", "manifest_digest", "raw_manifest_key",
            "raw_manifest_digest", "raw_page_count", "raw_row_count",
            "raw_bytes", "committed_at",
        }
        if not required_product_columns <= product_columns:
            raise MassResearchDisabledError(
                "PIT dependency scope requires receipt product materializations"
            )
        run_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(ingestion_run_log)")
        }
        if "authority_operation_id" not in run_columns:
            raise MassResearchDisabledError(
                "PIT dependency scope requires authority-bound ingestion runs"
            )
        receipt_rows = conn.execute(
            "SELECT * FROM collection_receipts WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) ORDER BY checked_at,run_id",
            required_datasets,
        ).fetchall()
        verified_segments: dict[
            str, list[tuple[str, str, str, str]]
        ] = {
            dataset_id: [] for dataset_id in required_datasets
        }
        for raw in receipt_rows:
            stored = dict(raw)
            dataset_id = str(stored["dataset"])
            try:
                expected_scope = json.loads(str(stored["expected_scope"]))
                digests = json.loads(str(stored["digests_json"]))
                receipt = CollectionReceipt(
                    source=str(stored["source"]),
                    dataset=dataset_id,
                    segment_id=str(stored["segment_id"]),
                    segment_start=str(stored["segment_start"]),
                    segment_end=str(stored["segment_end"]),
                    expected_scope=expected_scope,
                    expected_items=(
                        None
                        if stored["expected_items"] is None
                        else int(stored["expected_items"])
                    ),
                    observed_items=int(stored["observed_items"]),
                    raw_page_count=int(stored["raw_page_count"]),
                    raw_row_count=int(stored["raw_row_count"]),
                    structured_row_count=int(stored["structured_row_count"]),
                    pagination_exhausted=bool(stored["pagination_exhausted"]),
                    digests=digests,
                    run_id=int(stored["run_id"]),
                    status=str(stored["status"]),
                    error=(
                        None if stored["error"] is None else str(stored["error"])
                    ),
                    checked_at=str(stored["checked_at"]),
                )
                closure = require_verified_collection_closure(
                    receipt,
                    expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                    expected_authority_instance_digest=(
                        PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                    ),
                    expected_policy_version=coverage_contract_for(
                        dataset_id
                    ).policy_version,
                )
                segment_rows = [
                    row["original"]
                    for row in rows_by_dataset[dataset_id]
                    if closure.segment_start[:10]
                    <= row["event_date"]
                    <= closure.segment_end[:10]
                ]
                segment_rows.sort(key=lambda row: str(row["natural_key"]))
                product_rows = conn.execute(
                    "SELECT * FROM receipt_product_materializations "
                    "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
                    (
                        closure.source,
                        closure.dataset,
                        closure.segment_id,
                        closure.run_id,
                    ),
                ).fetchall()
                if len(product_rows) != 1:
                    continue
                product = dict(product_rows[0])
                run_rows = conn.execute(
                    "SELECT id,source,runtime,status,authority_operation_id "
                    "FROM ingestion_run_log WHERE id=?",
                    (closure.run_id,),
                ).fetchall()
                raw_manifests = conn.execute(
                    "SELECT dataset,run_id,manifest_key,page_count,row_count,"
                    "raw_bytes,data_digest FROM raw_retention_manifests "
                    "WHERE dataset=? AND run_id=?",
                    (closure.dataset, closure.run_id),
                ).fetchall()
                observed_product_digest = product_artifact_digest(segment_rows)
                if (
                    closure.status != "SUCCESS"
                    or not closure.pagination_exhausted
                    or not closure.discovery_exhausted
                    or len(segment_rows) != closure.structured_row_count
                    or observed_product_digest != closure.structured_digest
                    or product["artifact_digest"] != observed_product_digest
                    or product_artifact_body_digest(product["artifact_body"])
                    != observed_product_digest
                    or len(product["artifact_body"].encode("utf-8"))
                    != product["byte_count"]
                    or canonical_product_artifact_bytes(segment_rows).decode(
                        "utf-8"
                    )
                    != product["artifact_body"]
                    or product["row_count"] != closure.structured_row_count
                    or product["raw_manifest_digest"]
                    != closure.raw_manifest_digest
                    or product["raw_page_count"] != closure.raw_page_count
                    or product["raw_row_count"] != closure.raw_row_count
                    or len(run_rows) != 1
                    or run_rows[0]["id"] != closure.run_id
                    or run_rows[0]["source"] != closure.source
                    or run_rows[0]["runtime"] != "receipt-evidence-authority"
                    or run_rows[0]["status"] != "SUCCESS"
                    or run_rows[0]["authority_operation_id"]
                    != product["operation_id"]
                    or len(raw_manifests) != 1
                    or raw_manifests[0]["manifest_key"]
                    != product["raw_manifest_key"]
                    or raw_manifests[0]["page_count"]
                    != closure.raw_page_count
                    or raw_manifests[0]["row_count"]
                    != closure.raw_row_count
                    or raw_manifests[0]["raw_bytes"] != product["raw_bytes"]
                    or raw_manifests[0]["data_digest"]
                    != closure.raw_manifest_digest
                ):
                    continue
            except Exception:
                continue
            verified_segments[dataset_id].append(
                (
                    closure.segment_start[:10],
                    closure.segment_end[:10],
                    closure.receipt_digest,
                    closure.structured_digest,
                )
            )

        entries: list[dict[str, Any]] = []
        for dataset_id in required_datasets:
            selected = selected_keys[dataset_id]
            if not selected:
                raise MassResearchDisabledError(
                    f"PIT dependency scope selected no keys for {dataset_id}"
                )
            row_by_key = {
                row["natural_key"]: row for row in rows_by_dataset[dataset_id]
            }
            used_receipts: set[str] = set()
            used_products: set[str] = set()
            for natural_key in selected:
                event_date = row_by_key[natural_key]["event_date"]
                matches = [
                    (receipt_digest, product_digest)
                    for segment_start, segment_end, receipt_digest, product_digest
                    in verified_segments[dataset_id]
                    if segment_start <= event_date <= segment_end
                ]
                if not matches:
                    raise MassResearchDisabledError(
                        "PIT dependency scope natural key is not bound to a "
                        f"current signed receipt: {dataset_id}/{natural_key}"
                    )
                receipt_digest, product_digest = sorted(matches)[-1]
                used_receipts.add(receipt_digest)
                used_products.add(product_digest)
            entries.append(
                {
                    "dataset_id": dataset_id,
                    "natural_key_count": len(selected),
                    "natural_key_digest": canonical_digest(sorted(selected)),
                    "receipt_digests": sorted(used_receipts),
                    "receipt_set_digest": canonical_digest(
                        sorted(used_receipts)
                    ),
                    "product_artifact_digests": sorted(used_products),
                    "product_artifact_set_digest": canonical_digest(
                        sorted(used_products)
                    ),
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
        "universe_rule_digest": EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        "resolved_universe_digest": (
            resolved_universe.resolved_membership_digest
        ),
        "universe_daily_summary": [
            {
                "decision_date": day,
                "member_count": len(codes),
                "membership_digest": canonical_digest(list(codes)),
            }
            for day, codes in resolved_universe.decision_memberships
        ],
        "period_start": period_start,
        "period_end": period_end,
        "lookback_trading_days": max_lookback,
        "entries": entries,
        "product_materialization_digest": canonical_digest(
            [
                {
                    "dataset_id": entry["dataset_id"],
                    "product_artifact_digests": entry[
                        "product_artifact_digests"
                    ],
                }
                for entry in entries
            ]
        ),
    }
    return {**body, "proof_digest": canonical_digest(body)}


def _verify_projection_evidence_facts(
    signed_document: dict[str, Any] | bytes | str | None,
    required_datasets: tuple[str, ...] | list[str],
    *,
    expected_environment: str,
) -> tuple[Mapping[str, Mapping[str, Any]], str, str]:
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
        OpsProjectionSignatureError,
        verified_pinned_ops_projection_dataset_evidence,
    )
    from ops.projection_meta import DEFAULT_MAX_AGE_SECONDS

    if type(signed_document) not in {dict, bytes, str}:
        raise MassResearchDisabledError(
            "production READY requires a signed Ops Projection evidence envelope"
        )
    if (
        type(required_datasets) not in {tuple, list}
        or not required_datasets
        or any(
            type(dataset_id) is not str or not dataset_id
            for dataset_id in required_datasets
        )
        or len(set(required_datasets)) != len(required_datasets)
    ):
        raise MassResearchDisabledError(
            "production READY requires exact unique dataset identifiers"
        )
    selected_datasets = tuple(required_datasets)
    try:
        # The production verifier has no registry/path argument.  The complete
        # current registry document, body digest, generation and prior pointer
        # are independently pinned in code.
        envelope, evidence = verified_pinned_ops_projection_dataset_evidence(
            signed_document,
            selected_datasets,
            expected_environment=expected_environment,
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
    except (TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "signed Ops Projection generated_at is malformed"
        ) from exc
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

    document_digests: set[str] = set()
    issuer_key_ids: set[str] = set()
    for dataset_id, row in evidence.items():
        expected_policy = coverage_policy_binding(dataset_id)
        if any(
            row.get(field) != expected_policy[field]
            for field in ("policy_id", "policy_version", "policy_digest")
        ):
            raise MassResearchDisabledError(
                f"signed Ops Projection governed policy binding mismatch for {dataset_id}"
            )
        document_digest = row.get("signed_projection_document_digest")
        issuer_key_id = row.get("signed_projection_issuer_key_id")
        if not is_sha256_digest(document_digest) or (
            type(issuer_key_id) is not str or not issuer_key_id
        ):
            raise MassResearchDisabledError(
                "signed Ops Projection verified document identity is missing"
            )
        document_digests.add(document_digest)
        issuer_key_ids.add(issuer_key_id)
    if len(document_digests) != 1 or len(issuer_key_ids) != 1:
        raise MassResearchDisabledError(
            "signed Ops Projection verified document identity is inconsistent"
        )
    try:
        age_seconds = (_now() - generated_at).total_seconds()
    except (TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "signed Ops Projection generated_at is malformed"
        ) from exc
    if age_seconds < -300 or age_seconds > DEFAULT_MAX_AGE_SECONDS:
        raise MassResearchDisabledError(
            "signed Ops Projection evidence is outside the freshness SLA"
        )
    return (
        evidence,
        next(iter(document_digests)),
        next(iter(issuer_key_ids)),
    )


def _build_verified_projection_evidence_authority(
    facts_verifier: Any,
):
    """Close verified-result minting over one process-private state registry."""

    states: WeakKeyDictionary[
        object,
        tuple[Mapping[str, Mapping[str, Any]], str, str],
    ] = WeakKeyDictionary()

    class _VerifiedProductionProjectionEvidence:
        """Opaque deep-immutable value from one successful Ops verification."""

        __slots__ = ("__weakref__",)

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError(
                "verified production projection evidence has no public constructor"
            )

        def __init_subclass__(cls, **_kwargs: object) -> None:
            raise TypeError(
                "verified production projection evidence is final"
            )

        def __setattr__(self, _name: str, _value: object) -> None:
            raise AttributeError(
                "verified production projection evidence is immutable"
            )

        def __delattr__(self, _name: str) -> None:
            raise AttributeError(
                "verified production projection evidence is immutable"
            )

        def _state(
            self,
        ) -> tuple[Mapping[str, Mapping[str, Any]], str, str]:
            if type(self) is not _VerifiedProductionProjectionEvidence:
                raise RuntimeError(
                    "production projection evidence was not verifier-minted"
                )
            try:
                return states[self]
            except KeyError as exc:
                raise RuntimeError(
                    "production projection evidence was not verifier-minted"
                ) from exc

        @property
        def rows(self) -> Mapping[str, Mapping[str, Any]]:
            return self._state()[0]

        @property
        def signed_document_digest(self) -> str:
            return self._state()[1]

        @property
        def issuer_key_id(self) -> str:
            return self._state()[2]

    def verified_projection_evidence(
        signed_document: dict[str, Any] | bytes | str | None,
        required_datasets: tuple[str, ...] | list[str],
        *,
        expected_environment: str,
    ) -> _VerifiedProductionProjectionEvidence:
        rows, document_digest, issuer_key_id = (
            facts_verifier(
                signed_document,
                required_datasets,
                expected_environment=expected_environment,
            )
        )
        verified = object.__new__(_VerifiedProductionProjectionEvidence)
        states[verified] = (rows, document_digest, issuer_key_id)
        return verified

    return (
        _VerifiedProductionProjectionEvidence,
        verified_projection_evidence,
    )


(
    _VerifiedProductionProjectionEvidence,
    _verified_projection_evidence,
) = _build_verified_projection_evidence_authority(
    _verify_projection_evidence_facts
)
del _build_verified_projection_evidence_authority
del _verify_projection_evidence_facts


def _verified_production_projection_evidence(
    signed_document: dict[str, Any] | bytes | str | None,
    required_datasets: tuple[str, ...] | list[str],
) -> _VerifiedProductionProjectionEvidence:
    """Compatibility wrapper for the production-only product publisher."""

    return _verified_projection_evidence(
        signed_document,
        required_datasets,
        expected_environment="production",
    )


def _publish_exact_four_pilot_ready_snapshot_impl(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    signed_projection_document: dict[str, Any] | bytes | str,
) -> Any:
    """Use the closed local READY client; no signer or fallback is accepted."""

    from paper_runtime.snapshot import (
        _publish_exact_four_pilot_ready_snapshot_via_authority,
    )
    from research.readiness import ReadyPublicationAuthorityPending
    from scripts.local_authority_service import (
        LocalAuthorityError,
        LocalAuthorityPending,
    )

    try:
        return _publish_exact_four_pilot_ready_snapshot_via_authority(
            staging_db,
            snapshot_dir,
            signed_projection_document=signed_projection_document,
        )
    except (LocalAuthorityPending, LocalAuthorityError) as exc:
        raise ReadyPublicationAuthorityPending(
            "READY authority PENDING; verified active local service is unavailable"
        ) from exc


def publish_exact_four_pilot_ready_snapshot(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    signed_projection_document: dict[str, Any] | bytes | str,
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
    from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST

    if manifest.universe_rule_digest != EXACT_FOUR_UNIVERSE_RULE_DIGEST:
        raise MassResearchDisabledError(
            "ReadyManifest universe_rule_digest is not canonical"
        )
    if not is_sha256_digest(manifest.resolved_universe_digest):
        raise MassResearchDisabledError(
            "ReadyManifest resolved_universe_digest is missing"
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
    """Core required dataset ids with no package-owned SourceCapability file.

    Missing ids are UNKNOWN, not invented PASS. Does not write V3 JSON.
    """
    base = root or repo_root()
    spec_path = base / CORE_PROFILE_REL
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    required = raw.get("required_datasets")
    if not isinstance(required, list) or not required:
        raise MassResearchDisabledError("core profile required_datasets missing")
    from data_contracts.source_capability import specs_dir as capability_dir

    cap_dir = capability_dir()
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
