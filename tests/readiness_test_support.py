"""Test-only constructors for READY capabilities and configured consumers.

Production modules deliberately expose no signer, verifier, clock, digest, or
fixture-policy injection API.  Unit tests that need a synthetic signed
capability keep those powers under ``tests`` and exercise production consumers
through their configured public-key loader.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research.readiness import (
    ReadinessPublicKeyRegistry,
    VerifiedPilotReadiness,
    _ReadyPublicationSigner,
)
from research.ready_manifest import (
    ReadyManifest,
    canonical_digest,
    load_exact_four_pilot_ready_binding,
    missing_ready_manifest_proofs,
    validate_ready_manifest_profile_binding,
)
from selection.budget_ledger import MassResearchDisabledError


def make_readiness_signer(
    *,
    key_id: str = "test-readiness-v1",
    private_key: Ed25519PrivateKey | None = None,
) -> _ReadyPublicationSigner:
    """Create a private publication signer strictly for test fixtures."""
    key = private_key or Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return _ReadyPublicationSigner._from_private_pem(
        key_id=key_id,
        private_pem=private_pem,
    )


def mint_pilot_readiness(
    manifest: ReadyManifest,
    *,
    publisher: _ReadyPublicationSigner | None = None,
    immutable_db_digest: str,
    profile_binding: Any | None = None,
    now: datetime | None = None,
    ttl_seconds: int = 3600,
) -> VerifiedPilotReadiness:
    """Mint a synthetic capability without adding a product signing seam."""
    if not isinstance(manifest, ReadyManifest):
        raise MassResearchDisabledError("ReadyManifest required")
    if manifest.publication_scope != VerifiedPilotReadiness.EXPECTED_SCOPE:
        raise MassResearchDisabledError(
            "PILOT readiness requires a PILOT ReadyManifest"
        )
    missing = missing_ready_manifest_proofs(manifest)
    if missing:
        raise MassResearchDisabledError(
            "ReadyManifest proofs UNKNOWN/MISSING: " + ", ".join(missing)
        )
    binding = profile_binding or load_exact_four_pilot_ready_binding()
    validate_ready_manifest_profile_binding(manifest, profile=binding)
    signer = publisher or make_readiness_signer()
    clock = now or datetime.now(timezone.utc)
    expires = clock + timedelta(seconds=max(60, ttl_seconds))
    evidence = {
        "manifest": manifest.to_dict(),
        "immutable_db_digest": immutable_db_digest,
    }
    body = {
        "attestation_id": str(uuid4()),
        "readiness_scope": VerifiedPilotReadiness.EXPECTED_SCOPE,
        "snapshot_id": manifest.snapshot_id,
        "profile_id": manifest.profile_id,
        "profile_version": manifest.profile_version,
        "profile_digest": manifest.profile_digest,
        "plan_ids": tuple(manifest.plan_ids),
        "plan_set_digest": manifest.plan_set_digest,
        "dependency_closure_digest": manifest.dependency_closure_digest,
        "universe_rule_digest": manifest.universe_rule_digest,
        "resolved_universe_digest": manifest.resolved_universe_digest,
        "dataset_ids": tuple(manifest.dataset_ids),
        "ready_state": "READY",
        "ready_manifest_digest": manifest.to_dict()["manifest_digest"],
        "immutable_db_digest": immutable_db_digest,
        "coverage_policy_version": manifest.coverage_policy_version,
        "coverage_policy_digest": manifest.coverage_policy_digest,
        "coverage_proof_digest": manifest.coverage_proof_digest,
        "governed_membership_digest": manifest.dataset_membership_digest,
        "raw_proof_digest": manifest.raw_proof_digest,
        "receipt_proof_digest": manifest.receipt_proof_digest,
        "validation_proof_digest": manifest.validation_proof_digest,
        "b0_quality_proof_digest": manifest.b0_proof_digest,
        "b4_quality_proof_digest": manifest.b4_proof_digest,
        "source_generation": manifest.source_generation,
        "export_cursor": manifest.export_cursor,
        "applied_cursor": manifest.applied_cursor,
        "verified_at": clock.isoformat(),
        "expires_at": expires.isoformat(),
        "evidence_digest": canonical_digest(evidence),
        "key_id": signer.key_id,
        "issuer": "ReadyPublicationService/v3",
    }
    signature = signer._sign(
        {"format": VerifiedPilotReadiness.FORMAT, **body}
    )
    minted = VerifiedPilotReadiness(signature=signature, **body)
    if not minted.is_valid(verifier=signer._public_registry(), now=clock):
        raise MassResearchDisabledError(
            "synthetic VerifiedPilotReadiness failed its signed invariants"
        )
    return minted


def controlled_pilot_execution_service(
    *,
    verifier: ReadinessPublicKeyRegistry,
    trader_verifier: Any,
    paper_store: Any | None = None,
) -> Any:
    """Construct the public execution service under a test-only config patch."""
    from execution.paper_service import ControlledPilotExecutionService
    from execution.trader_authority import (
        TraderAuthorizationPublicKeyRegistry,
    )

    with patch.object(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        return_value=verifier,
    ), patch.object(
        TraderAuthorizationPublicKeyRegistry,
        "load_pinned",
        return_value=trader_verifier,
    ):
        service = ControlledPilotExecutionService(paper_store=paper_store)

    class _PinnedTestControlledPilotService:
        def execute(self, **kwargs: Any) -> Any:
            with patch.object(
                ReadinessPublicKeyRegistry,
                "load_pinned",
                return_value=verifier,
            ), patch.object(
                TraderAuthorizationPublicKeyRegistry,
                "load_pinned",
                return_value=trader_verifier,
            ):
                return service.execute(**kwargs)

    return _PinnedTestControlledPilotService()


def make_trader_authorization_issuer(
    *,
    key_id: str = "test-trader-authorization-v1",
    private_key: Ed25519PrivateKey | None = None,
) -> Any:
    """Create an independent private DTO signer strictly inside tests."""
    key = private_key or Ed25519PrivateKey.generate()
    return _TestTraderAuthorizationSigner(key_id=key_id, private_key=key)


def issue_trader_authorization(
    issuer: Any,
    *,
    readiness_verifier: ReadinessPublicKeyRegistry,
    **kwargs: Any,
) -> Any:
    """Issue under an ephemeral readiness trust root for unit tests."""
    return issuer.issue(readiness_verifier=readiness_verifier, **kwargs)


def _test_trader_canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _test_trader_digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        _test_trader_canonical_bytes(payload)
    ).hexdigest()


class _TestTraderAuthorizationSigner:
    """Test-owned signer; production exposes only the corresponding verifier."""

    def __init__(
        self, *, key_id: str, private_key: Ed25519PrivateKey
    ) -> None:
        self._key_id = str(key_id)
        self._private_key = private_key

    def issue(
        self,
        *,
        readiness_verifier: ReadinessPublicKeyRegistry,
        decision: Any,
        experiment_plan: Any,
        plan_set_binding: Any,
        ready_manifest: Any,
        readiness: Any,
        resolved_universe: Any,
        ttl_seconds: int = 1800,
    ) -> Any:
        from execution.trader_authority import (
            TRADER_AUTHORIZATION_FORMAT,
            TRADER_AUTHORIZATION_ISSUER,
            TraderAuthorizationPublicKeyRegistry,
            VerifiedTraderAuthorization,
        )
        from strategies.spec import strategy_spec_digest

        # Test fixtures still prove their READY signature before deriving the
        # DTO.  Production re-checks the complete digest chain at consumption.
        readiness.require_valid(
            expected_snapshot_id=ready_manifest.snapshot_id,
            expected_plan_set_digest=plan_set_binding.plan_set_digest,
            expected_closure_digest=plan_set_binding.closure_set_digest,
            verifier=readiness_verifier,
        )
        seconds = int(ttl_seconds)
        if seconds < 60 or seconds > 1800:
            raise MassResearchDisabledError(
                "trader authorization ttl must be between 60 and 1800 seconds"
            )
        issued = datetime.now(timezone.utc)
        body: dict[str, Any] = {
            "format": TRADER_AUTHORIZATION_FORMAT,
            "mode": "paper",
            "strategy_id": decision.strategy_spec.strategy_id,
            "strategy_spec_hash": strategy_spec_digest(decision.strategy_spec),
            "max_gross_weight": float(decision.max_gross_weight),
            "ready_snapshot_id": ready_manifest.snapshot_id,
            "ready_manifest_digest": ready_manifest.manifest_digest,
            "readiness_attestation_id": readiness.attestation_id,
            "profile_digest": plan_set_binding.profile_digest,
            "plan_set_digest": plan_set_binding.plan_set_digest,
            "dependency_closure_digest": plan_set_binding.closure_set_digest,
            "universe_contract_id": resolved_universe.rule_id,
            "universe_rule_digest": resolved_universe.rule_digest,
            "resolved_universe_digest": (
                resolved_universe.resolved_membership_digest
            ),
            "period_start": experiment_plan.period_start,
            "period_end": experiment_plan.period_end,
            "cost_scenario": experiment_plan.cost_scenario,
            "issued_at": issued.isoformat(),
            "expires_at": (issued + timedelta(seconds=seconds)).isoformat(),
            "key_id": self._key_id,
            "issuer": TRADER_AUTHORIZATION_ISSUER,
        }
        body["authorization_id"] = _test_trader_digest(body)
        signature = "ed25519:" + base64.b64encode(
            self._private_key.sign(_test_trader_canonical_bytes(body))
        ).decode("ascii")
        authorization = VerifiedTraderAuthorization(
            signature=signature,
            **{key: value for key, value in body.items() if key != "format"},
        )
        verifier = TraderAuthorizationPublicKeyRegistry(
            {self._key_id: self._private_key.public_key()}
        )
        with patch.object(
            TraderAuthorizationPublicKeyRegistry,
            "load_pinned",
            return_value=verifier,
        ):
            if not authorization.is_valid(now=issued):
                raise MassResearchDisabledError(
                    "synthetic trader authorization failed signed invariants"
                )
        return authorization


def controlled_pilot_scheduler(
    *,
    verifier: ReadinessPublicKeyRegistry,
    **kwargs: Any,
) -> Any:
    """Construct the public scheduler under a test-only config patch."""
    from research.phase7_pilot import ControlledPilotScheduler

    with patch.object(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        return_value=verifier,
    ):
        return ControlledPilotScheduler(**kwargs)
