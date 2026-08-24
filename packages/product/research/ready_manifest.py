"""Single ReadyManifest type — publisher, coherence, ReadinessService.

SoT: ``specs/ready/ready_manifest.schema.json``. Missing proofs are
UNKNOWN/MISSING, never default PASS. Does not publish live READY.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

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
    "dataset_membership_digest",
    "coverage_proof_digest",
    "raw_proof_digest",
    "validation_proof_digest",
    "b0_proof_digest",
)
GENERATION_PIN_FIELDS: tuple[str, ...] = (
    "source_generation",
    "applied_sync_generation",
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
    profile_id: str
    profile_digest: str
    dataset_membership_digest: str
    coverage_proof_digest: str
    raw_proof_digest: str
    validation_proof_digest: str
    b0_proof_digest: str
    source_generation: str
    applied_sync_generation: str
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
            "profile_id": self.profile_id,
            "profile_digest": self.profile_digest,
            "dataset_membership_digest": self.dataset_membership_digest,
            "coverage_proof_digest": self.coverage_proof_digest,
            "raw_proof_digest": self.raw_proof_digest,
            "validation_proof_digest": self.validation_proof_digest,
            "b0_proof_digest": self.b0_proof_digest,
            "source_generation": self.source_generation,
            "applied_sync_generation": self.applied_sync_generation,
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
        body = {
            "format": str(document.get("format") or ""),
            "snapshot_id": str(document.get("snapshot_id") or ""),
            "profile_id": str(document.get("profile_id") or ""),
            "profile_digest": proof_or_missing(document.get("profile_digest")),
            "dataset_membership_digest": proof_or_missing(
                document.get("dataset_membership_digest")
            ),
            "coverage_proof_digest": proof_or_missing(
                document.get("coverage_proof_digest")
            ),
            "raw_proof_digest": proof_or_missing(document.get("raw_proof_digest")),
            "validation_proof_digest": proof_or_missing(
                document.get("validation_proof_digest")
            ),
            "b0_proof_digest": proof_or_missing(document.get("b0_proof_digest")),
            "source_generation": pin_or_missing(document.get("source_generation")),
            "applied_sync_generation": pin_or_missing(
                document.get("applied_sync_generation")
            ),
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
    profile_digest: str | None = None,
    dataset_ids: Sequence[str] | None = None,
    dataset_membership_digest: str | None = None,
    coverage_proof_digest: str | None = None,
    raw_proof_digest: str | None = None,
    validation_proof_digest: str | None = None,
    b0_proof_digest: str | None = None,
    source_generation: str | None = None,
    applied_sync_generation: str | None = None,
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
    return ReadyManifest.from_dict(
        {
            "format": READY_MANIFEST_FORMAT,
            "snapshot_id": snapshot_id,
            "profile_id": profile_id,
            "profile_digest": proof_or_missing(profile_digest),
            "dataset_membership_digest": proof_or_missing(membership),
            "coverage_proof_digest": proof_or_missing(coverage_proof_digest),
            "raw_proof_digest": proof_or_missing(raw_proof_digest),
            "validation_proof_digest": proof_or_missing(validation_proof_digest),
            "b0_proof_digest": proof_or_missing(b0_proof_digest),
            "source_generation": pin_or_missing(source_generation),
            "applied_sync_generation": pin_or_missing(applied_sync_generation),
            "pit_contract_digests": {
                str(key): proof_or_missing(value) for key, value in pit.items()
            },
            "feature_generation": pin_or_missing(feature_generation),
            "catalog_generation": pin_or_missing(catalog_generation),
            "created_at": created,
            "published_at": published_at or MISSING,
        }
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


def ready_manifest_from_snapshot_document(document: Mapping[str, Any]) -> ReadyManifest:
    """Project a snapshot document onto ReadyManifest.

    Reads ReadyManifest fields or Coverage V2 ``proof_digest`` only. Does not
    accept coverage_digest / membership_digest / quality_digest aliases and
    does not treat a PASS label as a proof digest.
    """
    if not isinstance(document, Mapping):
        raise MassResearchDisabledError("snapshot document must be an object")
    if document.get("format") == READY_MANIFEST_FORMAT:
        return ReadyManifest.from_dict(document)

    snapshot_id = str(document.get("snapshot_id") or "")
    if not is_sha256_digest(snapshot_id):
        snapshot_id = canonical_digest({"snapshot_id": snapshot_id or MISSING})

    coverage = document.get("coverage_proof_digest")
    if not is_sha256_digest(coverage):
        proof = document.get("coverage_v2_proof")
        coverage = proof.get("proof_digest") if isinstance(proof, Mapping) else None

    raw = document.get("raw_proof_digest")
    if not is_sha256_digest(raw):
        raws = document.get("raw_manifests")
        raw = canonical_digest(raws) if isinstance(raws, Mapping) and raws else MISSING

    validation = document.get("validation_proof_digest")
    if not is_sha256_digest(validation):
        rows = document.get("validations")
        validation = canonical_digest(rows) if isinstance(rows, list) and rows else MISSING

    b0 = document.get("b0_proof_digest") or document.get("b0_quality_proof_digest")
    if not is_sha256_digest(b0):
        b0 = MISSING

    membership = document.get("dataset_membership_digest")
    if not is_sha256_digest(membership):
        required = document.get("required_datasets")
        membership = (
            compute_dataset_membership_digest(required)
            if isinstance(required, list) and required
            else MISSING
        )

    pit_raw = document.get("pit_contract_digests")
    if isinstance(pit_raw, Mapping) and pit_raw:
        pit = {str(key): proof_or_missing(value) for key, value in pit_raw.items()}
    else:
        pit = {"pit_api": MISSING}

    profile_id = str(document.get("profile_id") or "core")
    return build_ready_manifest(
        snapshot_id=snapshot_id,
        profile_id=profile_id,
        profile_digest=document.get("profile_digest"),
        dataset_membership_digest=membership,
        coverage_proof_digest=coverage,
        raw_proof_digest=raw,
        validation_proof_digest=validation,
        b0_proof_digest=b0,
        source_generation=document.get("source_generation"),
        applied_sync_generation=document.get("applied_sync_generation"),
        pit_contract_digests=pit,
        feature_generation=document.get("feature_generation"),
        catalog_generation=document.get("catalog_generation"),
        created_at=str(document.get("created_at") or document.get("committed_at") or MISSING),
        published_at=str(document.get("published_at") or MISSING),
    )


def missing_ready_manifest_proofs(manifest: ReadyManifest) -> list[str]:
    """Proof fields that are UNKNOWN/MISSING. Absence is not PASS."""
    body = manifest.to_dict()
    missing: list[str] = []
    if not is_sha256_digest(body.get("snapshot_id")):
        missing.append("snapshot_id")
    for field in PROOF_DIGEST_FIELDS:
        if not is_sha256_digest(body.get(field)):
            missing.append(field)
    for field in GENERATION_PIN_FIELDS:
        value = body.get(field)
        if not isinstance(value, str) or value.strip() in ABSENT_PROOFS:
            missing.append(field)
    pit = body.get("pit_contract_digests")
    if not isinstance(pit, Mapping) or not pit:
        missing.append("pit_contract_digests")
    else:
        for key, value in pit.items():
            if not is_sha256_digest(value):
                missing.append(f"pit_contract_digests.{key}")
    return missing


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def mint_verified_research_readiness(
    manifest: ReadyManifest,
    *,
    db_path: str | Path | None = None,
    immutable_db_digest: str | None = None,
    ttl_seconds: int = 3600,
    now: datetime | None = None,
) -> Any:
    """Mint VerifiedResearchReadiness from a ReadyManifest. Fail closed.

    UNKNOWN/MISSING proofs raise. No fixture default PASS. Does not publish
    live READY. Readiness HMAC is distinct from the receipt signer.
    """
    from data_contracts.coverage import POLICY_VERSION as COVERAGE_POLICY_VERSION
    from research.readiness import (
        VerifiedResearchReadiness,
        _attestation_secret,
        _sign_attestation,
    )

    if not isinstance(manifest, ReadyManifest):
        raise MassResearchDisabledError("ReadyManifest required")
    missing = missing_ready_manifest_proofs(manifest)
    if missing:
        raise MassResearchDisabledError(
            "ReadyManifest proofs UNKNOWN/MISSING: " + ", ".join(missing)
        )
    db_digest = immutable_db_digest
    if db_digest is None and db_path is not None:
        artifact = Path(db_path)
        if not artifact.is_file():
            raise MassResearchDisabledError(f"READY snapshot artifact missing: {artifact}")
        db_digest = _file_sha256(artifact)
    if not is_sha256_digest(db_digest):
        raise MassResearchDisabledError(
            "ReadyManifest proofs UNKNOWN/MISSING: immutable_db_digest"
        )

    clock = now or _now()
    expires = clock + timedelta(seconds=max(60, ttl_seconds))
    attestation_id = str(uuid4())
    body_manifest = manifest.to_dict()
    evidence = {
        "snapshot_id": manifest.snapshot_id,
        "manifest_digest": body_manifest["manifest_digest"],
        "db_digest": db_digest,
        "coverage_proof": manifest.coverage_proof_digest,
        "membership": manifest.dataset_membership_digest,
        "raw_proof": manifest.raw_proof_digest,
        "validation_proof": manifest.validation_proof_digest,
        "b0_proof": manifest.b0_proof_digest,
        "source_gen": manifest.source_generation,
        "applied_gen": manifest.applied_sync_generation,
        "pit": dict(manifest.pit_contract_digests),
        "feature_generation": manifest.feature_generation,
        "catalog_generation": manifest.catalog_generation,
    }
    body = {
        "attestation_id": attestation_id,
        "snapshot_id": manifest.snapshot_id,
        "ready_state": "READY",
        "ready_manifest_digest": body_manifest["manifest_digest"],
        "immutable_db_digest": db_digest,
        "coverage_policy_version": COVERAGE_POLICY_VERSION,
        "coverage_proof_digest": manifest.coverage_proof_digest,
        "governed_membership_digest": manifest.dataset_membership_digest,
        "raw_proof_digest": manifest.raw_proof_digest,
        "b0_quality_proof_digest": manifest.b0_proof_digest,
        "source_generation": manifest.source_generation,
        "applied_sync_generation": manifest.applied_sync_generation,
        "verified_at": clock.isoformat(),
        "expires_at": expires.isoformat(),
        "evidence_digest": canonical_digest(evidence),
        "issuer": "ResearchReadinessService/v2",
    }
    signature = _sign_attestation(body, _attestation_secret())
    return VerifiedResearchReadiness(signature=signature, **body)


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
    "ReadyManifest",
    "build_ready_manifest",
    "canonical_digest",
    "compute_dataset_membership_digest",
    "core_profile_source_capability_gaps",
    "is_sha256_digest",
    "load_ready_manifest",
    "load_ready_manifest_schema",
    "mint_verified_research_readiness",
    "missing_ready_manifest_proofs",
    "pin_or_missing",
    "proof_or_missing",
    "ready_manifest_from_snapshot_document",
    "require_core_profile_deps_subseteq_source_capability_registry",
    "serialize_ready_manifest",
    "validate_ready_manifest_document",
]
