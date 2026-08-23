"""Research readiness attestation bound to the immutable READY verifier.

Operator override cannot substitute for readiness.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
    require_budget_capability,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(payload: Mapping[str, Any] | list[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class VerifiedResearchReadiness:
    """Attestation minted only after READY verifier PASS."""

    attestation_id: str
    snapshot_id: str
    ready_state: str
    ready_manifest_digest: str
    immutable_db_digest: str
    coverage_policy_version: str
    coverage_proof_digest: str
    governed_membership_digest: str
    raw_proof_digest: str
    b0_quality_proof_digest: str
    source_generation: str
    applied_sync_generation: str
    verified_at: str
    expires_at: str
    evidence_digest: str
    signature: str
    issuer: str = "ResearchReadinessService/v2"

    def to_canonical_body(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "snapshot_id": self.snapshot_id,
            "ready_state": self.ready_state,
            "ready_manifest_digest": self.ready_manifest_digest,
            "immutable_db_digest": self.immutable_db_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_proof_digest": self.coverage_proof_digest,
            "governed_membership_digest": self.governed_membership_digest,
            "raw_proof_digest": self.raw_proof_digest,
            "b0_quality_proof_digest": self.b0_quality_proof_digest,
            "source_generation": self.source_generation,
            "applied_sync_generation": self.applied_sync_generation,
            "verified_at": self.verified_at,
            "expires_at": self.expires_at,
            "evidence_digest": self.evidence_digest,
            "issuer": self.issuer,
        }

    def is_expired(self, *, now: datetime | None = None) -> bool:
        clock = now or _now()
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return clock > expires

    def is_valid(
        self,
        *,
        expected_snapshot_id: str | None = None,
        hmac_secret: bytes | None = None,
        now: datetime | None = None,
    ) -> bool:
        if self.ready_state != "READY":
            return False
        if self.is_expired(now=now):
            return False
        if expected_snapshot_id is not None and self.snapshot_id != expected_snapshot_id:
            return False
        if not self.signature.startswith("hmac-sha256:"):
            return False
        secret = hmac_secret or _attestation_secret()
        expected = _sign_attestation(self.to_canonical_body(), secret)
        return _hmac_eq(self.signature, expected)

    def require_valid(self, **kwargs: Any) -> "VerifiedResearchReadiness":
        if not self.is_valid(**kwargs):
            raise MassResearchDisabledError(
                "VerifiedResearchReadiness invalid, expired, or signature mismatch"
            )
        return self


def _host_receipt_pem_disabled() -> bool:
    """True under pytest or QUANT_READINESS_DISABLE_HOST_PEM=1.

    QUANT_READINESS_HMAC_SECRET still applies. Missing secret is fail-closed.
    """
    import os

    if os.environ.get("QUANT_READINESS_DISABLE_HOST_PEM", "").strip() == "1":
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _attestation_secret() -> bytes:
    """HMAC secret for attestation MAC (QUANT_READINESS_HMAC_SECRET or ~/.config)."""
    import os

    env = os.environ.get("QUANT_READINESS_HMAC_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    path = Path.home() / ".config" / "quant-platform" / "readiness_hmac_secret"
    if path.is_file():
        return path.read_bytes().strip()
    if not _host_receipt_pem_disabled():
        key = Path.home() / ".config" / "quant-platform" / "receipt_signing_key.pem"
        if key.is_file():
            return hashlib.sha256(key.read_bytes() + b"|readiness-v2").digest()
    raise MassResearchDisabledError("readiness HMAC secret not configured")


def _sign_attestation(body: Mapping[str, Any], secret: bytes) -> str:
    import hmac as hm

    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
    dig = hm.new(secret, raw, hashlib.sha256).digest()
    return "hmac-sha256:" + base64.b64encode(dig).decode("ascii")


def _hmac_eq(a: str, b: str) -> bool:
    import hmac as hm

    return hm.compare_digest(a.encode(), b.encode())


@dataclass(frozen=True)
class OperatorOverrideCapability:
    """Non-safety policy override only — never substitutes for readiness."""

    override_id: str
    reason: str
    operator_identity: str
    issued_at: str
    expires_at: str
    audit_artifact_digest: str
    scope: str

    ALLOWED_SCOPES = frozenset(
        {"hold_period", "selection_threshold", "single_extra_experiment"}
    )

    def __post_init__(self) -> None:
        if self.scope not in self.ALLOWED_SCOPES:
            raise ValueError(
                f"operator override scope {self.scope!r} not allowed; "
                f"cannot bypass safety gates"
            )


class OperatorOverrideService:
    """Mints non-safety overrides only."""

    def __init__(self, *, audit_dir: Path | None = None) -> None:
        self._audit_dir = audit_dir

    def mint(
        self,
        *,
        reason: str,
        operator_identity: str,
        scope: str,
        ttl_seconds: int = 3600,
    ) -> OperatorOverrideCapability:
        if scope not in OperatorOverrideCapability.ALLOWED_SCOPES:
            raise ValueError(f"scope {scope!r} cannot bypass structural safety")
        if not reason.strip() or not operator_identity.strip():
            raise ValueError("reason and operator_identity required")
        if ttl_seconds < 60 or ttl_seconds > 86_400:
            raise ValueError("ttl_seconds must be in [60, 86400]")
        issued = _now()
        expires = issued + timedelta(seconds=ttl_seconds)
        override_id = str(uuid4())
        body = {
            "override_id": override_id,
            "reason": reason.strip(),
            "operator_identity": operator_identity.strip(),
            "issued_at": issued.isoformat(),
            "expires_at": expires.isoformat(),
            "scope": scope,
        }
        digest = _digest(body)
        if self._audit_dir is not None:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            (self._audit_dir / f"override-{override_id}.json").write_text(
                json.dumps({**body, "digest": digest}, indent=2), encoding="utf-8"
            )
        return OperatorOverrideCapability(
            override_id=override_id,
            reason=reason.strip(),
            operator_identity=operator_identity.strip(),
            issued_at=issued.isoformat(),
            expires_at=expires.isoformat(),
            audit_artifact_digest=digest,
            scope=scope,
        )


class ResearchReadinessService:
    """Mint attestation only from verified immutable READY snapshot."""

    def __init__(
        self,
        *,
        snapshot_dir: str | Path,
        snapshot_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        self._snapshot_dir = Path(snapshot_dir)
        self._snapshot_id = snapshot_id
        self._ttl = ttl_seconds

    def mint(self) -> VerifiedResearchReadiness:
        from paper_runtime.snapshot import (
            describe_snapshot,
            latest_ready_snapshot,
        )

        if not self._snapshot_dir.is_dir():
            raise MassResearchDisabledError(
                f"READY snapshot dir missing: {self._snapshot_dir}"
            )
        try:
            if self._snapshot_id:
                ready = describe_snapshot(self._snapshot_dir, self._snapshot_id)
            else:
                ready = latest_ready_snapshot(self._snapshot_dir)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise MassResearchDisabledError(
                f"READY verifier failed: {exc}"
            ) from exc

        manifest = dict(ready.manifest)
        artifact_path = ready.artifact_path
        db_digest = _file_sha256(artifact_path)
        coverage_proof = str(
            manifest.get("coverage_proof_digest")
            or manifest.get("coverage_digest")
            or ""
        )
        if not coverage_proof.startswith("sha256:"):
            raise MassResearchDisabledError("READY manifest missing coverage proof digest")
        membership = str(
            manifest.get("governed_membership_digest")
            or manifest.get("membership_digest")
            or ""
        )
        if not membership.startswith("sha256:"):
            raise MassResearchDisabledError(
                "READY manifest missing governed membership digest"
            )
        raw_proof = str(manifest.get("raw_proof_digest") or "")
        if not raw_proof.startswith("sha256:"):
            raise MassResearchDisabledError("READY manifest missing raw proof digest")
        b0_proof = str(
            manifest.get("b0_quality_proof_digest")
            or manifest.get("quality_digest")
            or ""
        )
        if not b0_proof.startswith("sha256:"):
            raise MassResearchDisabledError("READY manifest missing B0/quality proof digest")
        source_gen = str(
            manifest.get("source_generation")
            or manifest.get("export_generation")
            or ""
        )
        applied_gen = str(
            manifest.get("applied_sync_generation")
            or manifest.get("apply_generation")
            or ""
        )
        if not source_gen or not applied_gen:
            raise MassResearchDisabledError(
                "READY manifest missing source/applied sync generation pins"
            )
        pin = manifest.get("export_apply_pin") or {}
        if not isinstance(pin, Mapping) or not pin:
            if source_gen != applied_gen and not manifest.get("export_apply_bound"):
                raise MassResearchDisabledError(
                    "READY manifest lacks export/apply generation binding"
                )

        verified_at = _now()
        expires_at = verified_at + timedelta(seconds=max(60, self._ttl))
        attestation_id = str(uuid4())
        evidence = {
            "snapshot_id": ready.snapshot_id,
            "manifest_digest": str(manifest.get("manifest_digest") or ""),
            "db_digest": db_digest,
            "coverage_proof": coverage_proof,
            "membership": membership,
            "raw_proof": raw_proof,
            "b0_proof": b0_proof,
            "source_gen": source_gen,
            "applied_gen": applied_gen,
        }
        body = {
            "attestation_id": attestation_id,
            "snapshot_id": ready.snapshot_id,
            "ready_state": "READY",
            "ready_manifest_digest": str(manifest.get("manifest_digest") or ""),
            "immutable_db_digest": db_digest,
            "coverage_policy_version": str(
                manifest.get("coverage_policy_version") or ""
            ),
            "coverage_proof_digest": coverage_proof,
            "governed_membership_digest": membership,
            "raw_proof_digest": raw_proof,
            "b0_quality_proof_digest": b0_proof,
            "source_generation": source_gen,
            "applied_sync_generation": applied_gen,
            "verified_at": verified_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "evidence_digest": _digest(evidence),
            "issuer": "ResearchReadinessService/v2",
        }
        if not body["ready_manifest_digest"].startswith("sha256:"):
            raise MassResearchDisabledError("READY manifest_digest missing")
        sig = _sign_attestation(body, _attestation_secret())
        return VerifiedResearchReadiness(signature=sig, **body)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def require_mass_research_start(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedResearchReadiness | None,
    expected_snapshot_id: str | None = None,
) -> tuple[ResearchBudgetCapability, VerifiedResearchReadiness]:
    """Fail-closed mass start: budget + valid unexpired readiness only."""
    cap = require_budget_capability(budget)
    if readiness is None:
        raise MassResearchDisabledError(
            "VerifiedResearchReadiness required; operator override cannot substitute"
        )
    if not isinstance(readiness, VerifiedResearchReadiness):
        raise MassResearchDisabledError("readiness must be VerifiedResearchReadiness")
    readiness.require_valid(expected_snapshot_id=expected_snapshot_id)
    return cap, readiness


__all__ = [
    "MassResearchDisabledError",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "ResearchReadinessService",
    "VerifiedResearchReadiness",
    "require_mass_research_start",
]
