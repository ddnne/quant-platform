from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import receipt_authority_pending_live_acceptance as live
from scripts import receipt_authority_staging_active_gate as active


SHA = "1" * 40
ACCOUNT = "2" * 32


def _registry(path: Path, public_raw: bytes) -> tuple[Path, str]:
    key_id = "receipt-staging-" + hashlib.sha256(public_raw).hexdigest()[:16]
    document = json.loads(
        active.SCOPED_REGISTRY_PATHS["staging"].read_text(encoding="utf-8")
    )
    document["authority_status"] = "ACTIVE"
    document["keys"] = [{
        "key_id": key_id,
        "algorithm": "Ed25519",
        "public_key_base64": base64.b64encode(public_raw).decode("ascii"),
        "status": "active",
    }]
    body = dict(document)
    body.pop("registry_digest")
    document["registry_digest"] = active._canonical_digest(body)
    path.write_bytes(active._canonical_bytes(document))
    return path, key_id


def _chain_documents(
    key_id: str,
    registry_digest: str,
) -> tuple[dict[str, Any], ...]:
    surfaces = active._active_surfaces(key_id, registry_digest)
    deployments: dict[str, Any] = {}
    versions: dict[str, Any] = {}
    public: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for ordinal, (role, _worker) in enumerate(live.CHAIN, start=1):
        surface = surfaces[role]
        deployment_id = f"00000000-0000-4000-8000-{ordinal:012d}"
        version_id = f"10000000-0000-4000-8000-{ordinal:012d}"
        message = live.deployment_message(role, "staging", SHA, "ACTIVE")
        deployments[role] = {
            "id": deployment_id,
            "source": "wrangler",
            "strategy": "percentage",
            "annotations": {
                "workers/message": message,
                "workers/triggered_by": "deployment",
            },
            "versions": [{"version_id": version_id, "percentage": 100}],
        }
        bindings = []
        for row in live._expected_bindings(surface).values():
            materialized = copy.deepcopy(row)
            if materialized.get("namespace_id") == "<LIVE_NAMESPACE_ID>":
                materialized["namespace_id"] = f"{ordinal:x}" * 32
            bindings.append(materialized)
        script: dict[str, Any] = {
            "etag": f"{ordinal:x}" * 64,
            "handlers": ["fetch"] + (["scheduled"] if surface["crons"] else []),
            "last_deployed_from": "wrangler",
        }
        named = live._expected_named_handlers(surface)
        if named:
            script["named_handlers"] = copy.deepcopy(named)
        runtime: dict[str, Any] = {
            "compatibility_date": surface["compatibility_date"],
            "usage_model": "standard",
        }
        migration = live._expected_migration_tag(surface)
        if migration is not None:
            runtime["migration_tag"] = migration
        versions[role] = {
            "id": version_id,
            "annotations": {
                "workers/message": message,
                "workers/tag": live.version_tag(role, "staging", SHA, "ACTIVE"),
                "workers/triggered_by": "version_upload",
            },
            "metadata": {
                "created_on": f"2026-08-28T08:00:00.00000{ordinal}Z",
                "source": "wrangler",
                "has_preview": False,
            },
            "resources": {
                "script": script,
                "script_runtime": runtime,
                "bindings": bindings,
            },
        }
        public[role] = {
            "subdomain": {
                "enabled": surface["workers_dev"],
                "previews_enabled": surface["preview_urls"],
            },
            "routes": [],
            "custom_domains": [],
            "custom_domain_total": 0,
            "schedules": {
                "schedules": [
                    {
                        "cron": cron,
                        "created_on": "2026-08-28T08:00:00.000000Z",
                        "modified_on": "2026-08-28T08:00:00.000000Z",
                    }
                    for cron in surface["crons"]
                ],
            },
            "script_settings": {
                "logpush": False,
                "observability": copy.deepcopy(surface["observability"]),
                "tail_consumers": copy.deepcopy(surface["tail_consumers"]),
            },
        }
        digest = "sha256:" + f"{ordinal:x}" * 64
        provenance[role] = {
            "local_main_module": "index.js",
            "local_main_module_digest": digest,
            "local_main_module_bytes": 100 + ordinal,
            "live_main_module": "src/index.js",
            "live_main_module_digest": digest,
            "live_main_module_bytes": 100 + ordinal,
        }
    return deployments, versions, public, provenance


def _attestation(
    private_key: Ed25519PrivateKey,
    key_id: str,
    versions: dict[str, Any],
    *,
    mutate_claims: Callable[[dict[str, Any]], None] | None = None,
    mutate_envelope: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    nonce = "a" * 64
    operation_id = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-canary-identity/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "caller_source_sha": SHA,
        "caller_worker_version_id": versions["caller"]["id"],
        "caller_worker_version_tag": live.version_tag(
            "caller", "staging", SHA, "ACTIVE"
        ),
        "request_nonce": nonce,
    })
    initial_created_at = "2026-08-28T08:00:30.000Z"
    recovered_at = "2026-08-28T08:01:00.000Z"
    replay_confirmed_at = "2026-08-28T08:01:01.000Z"
    initial_state_digest = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-initial-state/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_digest": operation_id,
        "state": "RECOVERY_REQUIRED",
        "created_at": initial_created_at,
    })
    initial_result_digest = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-initial-result/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": nonce,
        "state": "RECOVERY_REQUIRED",
        "initial_state_digest": initial_state_digest,
        "created_at": initial_created_at,
    })
    initial_event_digest = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-event-link/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "event": "INITIAL_COMMITTED",
        "payload_digest": initial_state_digest,
        "prior_event_digest": None,
        "observed_at": initial_created_at,
    })
    recovery_event_digest = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-event/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": nonce,
        "event": "RECOVERY_COMPLETED",
        "from_state": "RECOVERY_REQUIRED",
        "to_state": "RECOVERED_PENDING_REPLAY",
        "initial_state_digest": initial_state_digest,
        "initial_result_digest": initial_result_digest,
        "recovered_at": recovered_at,
    })
    recovery_event_tail_digest = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-event-link/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "event": "RECOVERY_COMPLETED",
        "payload_digest": recovery_event_digest,
        "prior_event_digest": initial_event_digest,
        "observed_at": recovered_at,
    })
    first_recovery_result_digest = active._canonical_digest({
        "schema_version": "receipt-audit-first-recovery-result/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": nonce,
        "initial_state_digest": initial_state_digest,
        "initial_result_digest": initial_result_digest,
        "recovery_event_digest": recovery_event_digest,
        "recovery_event_tail_digest": recovery_event_tail_digest,
        "recovered_at": recovered_at,
        "state": "RECOVERED_PENDING_REPLAY",
    })
    replay_event_digest = active._canonical_digest({
        "schema_version": "receipt-audit-replay-event/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": nonce,
        "event": "REPLAY_CONFIRMED",
        "from_state": "RECOVERED_PENDING_REPLAY",
        "to_state": "AUDIT_FINALIZED",
        "first_recovery_result_digest": first_recovery_result_digest,
        "recovery_event_digest": recovery_event_digest,
        "recovery_event_tail_digest": recovery_event_tail_digest,
        "replay_confirmed_at": replay_confirmed_at,
    })
    replay_event_tail_digest = active._canonical_digest({
        "schema_version": "receipt-audit-recovery-event-link/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "event": "REPLAY_CONFIRMED",
        "payload_digest": replay_event_digest,
        "prior_event_digest": recovery_event_tail_digest,
        "observed_at": replay_confirmed_at,
    })
    claims = {
        "schema_version": "receipt-audit-recovery-attestation-claims/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "authority_instance_digest": active._authority_instance_digest(),
        "authority_source_sha": SHA,
        "authority_worker_version_id": versions["authority"]["id"],
        "authority_worker_version_tag": live.version_tag(
            "authority", "staging", SHA, "ACTIVE"
        ),
        "caller_source_sha": SHA,
        "caller_worker_version_id": versions["caller"]["id"],
        "caller_worker_version_tag": live.version_tag(
            "caller", "staging", SHA, "ACTIVE"
        ),
        "operation_id": operation_id,
        "request_nonce": nonce,
        "initial_state": "RECOVERY_REQUIRED",
        "initial_state_digest": initial_state_digest,
        "initial_result_digest": initial_result_digest,
        "initial_created_at": initial_created_at,
        "recovery_event": "RECOVERY_COMPLETED",
        "recovery_event_digest": recovery_event_digest,
        "recovery_event_tail_digest": recovery_event_tail_digest,
        "recovered_at": recovered_at,
        "first_recovery_state": "RECOVERED_PENDING_REPLAY",
        "first_recovery_result_digest": first_recovery_result_digest,
        "replay_event": "REPLAY_CONFIRMED",
        "replay_event_digest": replay_event_digest,
        "replay_event_tail_digest": replay_event_tail_digest,
        "replay_confirmed_at": replay_confirmed_at,
        "replayed": True,
        "final_state": "AUDIT_FINALIZED",
        "issuer_key_id": key_id,
        "issued_at": replay_confirmed_at,
    }
    if mutate_claims is not None:
        mutate_claims(claims)
    signed = active._canonical_bytes(claims)
    envelope = {
        "schema_version": "receipt-audit-recovery-attestation/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "issuer_class": "ReceiptEvidenceAuthorityAuditSigner",
        "issuer_key_id": key_id,
        "authority_instance_digest": active._authority_instance_digest(),
        "signed_claims_base64": base64.b64encode(signed).decode("ascii"),
        "signed_claims_digest": active._digest_bytes(signed),
        "signature": "ed25519:" + base64.b64encode(
            private_key.sign(signed)
        ).decode("ascii"),
        "issued_at": replay_confirmed_at,
    }
    if mutate_envelope is not None:
        mutate_envelope(envelope)
    return envelope


def _evidence(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    registry_path, key_id = _registry(tmp_path / "registry.json", public_raw)
    registry_digest = json.loads(
        registry_path.read_text(encoding="utf-8")
    )["registry_digest"]
    deployments, versions, public, provenance = _chain_documents(
        key_id, registry_digest
    )
    attestation = _attestation(private_key, key_id, versions)
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_bytes(active._canonical_bytes(attestation))
    return {
        "private_key": private_key,
        "key_id": key_id,
        "registry_path": registry_path,
        "deployments": deployments,
        "versions": versions,
        "public": public,
        "provenance": provenance,
        "attestation": attestation,
        "attestation_path": attestation_path,
    }


def _validate(evidence: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    arguments = {
        "source_sha": SHA,
        "account_id": ACCOUNT,
        "deployments": evidence["deployments"],
        "versions": evidence["versions"],
        "public_surfaces": evidence["public"],
        "source_provenance": evidence["provenance"],
        "deployment_bracket_after": copy.deepcopy(evidence["deployments"]),
        "public_bracket_after": copy.deepcopy(evidence["public"]),
        "recovery_attestation_path": evidence["attestation_path"],
        "registry_path": evidence["registry_path"],
    }
    arguments.update(overrides)
    return active._validate_staging_active_transition_core(**arguments)


def test_exact_audit_only_transition_uses_real_signature_and_separate_digests(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    result = _validate(evidence)
    assert result["format"] == "receipt-authority-staging-active-transition/v2"
    assert result["authority_mode"] == "ACTIVE"
    assert result["eligibility"] == "AUDIT_ONLY"
    assert result["research_eligible"] is False
    assert result["positive_operation_invoked_by_gate"] is False
    assert result["signed_attestation_digest"] == active._canonical_digest(
        evidence["attestation"]
    )
    assert result["signed_claims_digest"] == evidence["attestation"][
        "signed_claims_digest"
    ]
    assert result["signed_attestation_digest"] != result["signed_claims_digest"]
    assert set(result["workers"]) == {"acquisition", "authority", "caller"}
    assert active._SHA256.fullmatch(result["deployment_pair_digest"])


def test_authority_change_requires_a_newer_coordinated_caller_version(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)

    new_authority_version = "20000000-0000-4000-8000-000000000002"
    evidence["deployments"]["authority"]["versions"][0]["version_id"] = (
        new_authority_version
    )
    evidence["versions"]["authority"]["id"] = new_authority_version
    evidence["versions"]["authority"]["metadata"]["created_on"] = (
        "2026-08-28T08:00:10.000000Z"
    )

    # An attestation signed for the previous immutable pair must not be
    # reusable after any authority deployment change.
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="immutable caller/authority version/key pair drifted",
    ):
        _validate(evidence)

    # Even a fresh authority attestation is insufficient while the old caller
    # version remains selected. The caller must be redeployed after authority.
    evidence["attestation"] = _attestation(
        evidence["private_key"], evidence["key_id"], evidence["versions"]
    )
    evidence["attestation_path"].write_bytes(
        active._canonical_bytes(evidence["attestation"])
    )
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="Premium caller version was not coordinated after authority activation",
    ):
        _validate(evidence)

    new_caller_version = "20000000-0000-4000-8000-000000000003"
    evidence["deployments"]["caller"]["versions"][0]["version_id"] = (
        new_caller_version
    )
    evidence["versions"]["caller"]["id"] = new_caller_version
    evidence["versions"]["caller"]["metadata"]["created_on"] = (
        "2026-08-28T08:00:11.000000Z"
    )
    evidence["attestation"] = _attestation(
        evidence["private_key"], evidence["key_id"], evidence["versions"]
    )
    evidence["attestation_path"].write_bytes(
        active._canonical_bytes(evidence["attestation"])
    )
    result = _validate(evidence)
    assert result["workers"]["authority"]["deployment_version_id"] == (
        new_authority_version
    )
    assert result["workers"]["caller"]["deployment_version_id"] == (
        new_caller_version
    )


def test_public_validator_has_no_evidence_or_trust_root_injection() -> None:
    parameters = inspect.signature(active.validate_staging_active_transition).parameters
    assert set(parameters) == {"source_sha", "account_id", "api_token"}


def test_public_validator_collects_live_and_owns_fixed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _evidence(tmp_path)
    documents = {
        "deployments": evidence["deployments"],
        "versions": evidence["versions"],
        "public_surfaces": evidence["public"],
        "source_provenance": evidence["provenance"],
        "deployment_bracket_after": copy.deepcopy(evidence["deployments"]),
        "public_bracket_after": copy.deepcopy(evidence["public"]),
    }
    source_checks: list[str] = []
    collected: list[tuple[str, str, str]] = []
    validated: list[dict[str, Any]] = []

    monkeypatch.setattr(
        live,
        "_require_exact_clean_source",
        lambda value: source_checks.append(f"clean:{value}"),
    )
    monkeypatch.setattr(
        live,
        "_require_official_origin_main",
        lambda value: source_checks.append(f"origin:{value}"),
    )

    def collect(*, source_sha: str, account_id: str, api_token: str) -> Any:
        collected.append((source_sha, account_id, api_token))
        return documents

    def validate_core(**arguments: Any) -> dict[str, Any]:
        validated.append(arguments)
        return {"status": "accepted"}

    monkeypatch.setattr(active, "_collect_staging_active_documents", collect)
    monkeypatch.setattr(
        active,
        "_remeasure_staging_active_tail",
        lambda **_arguments: (
            copy.deepcopy(documents["deployment_bracket_after"]),
            copy.deepcopy(documents["public_bracket_after"]),
        ),
    )
    monkeypatch.setattr(
        active, "_validate_staging_active_transition_core", validate_core
    )
    assert active.validate_staging_active_transition(
        source_sha=SHA,
        account_id=ACCOUNT,
        api_token="opaque-test-token",
    ) == {"status": "accepted"}
    assert collected == [(SHA, ACCOUNT, "opaque-test-token")]
    assert source_checks == [
        f"clean:{SHA}",
        f"origin:{SHA}",
        f"clean:{SHA}",
        f"origin:{SHA}",
    ]
    assert validated[0]["registry_path"] == active.SCOPED_REGISTRY_PATHS["staging"]
    assert validated[0]["recovery_attestation_path"] == (
        active.STAGING_AUDIT_ATTESTATION_PATH
    )

    drifted = copy.deepcopy(documents["deployment_bracket_after"])
    drifted["authority"]["id"] = "changed-after-attestation"
    monkeypatch.setattr(
        active,
        "_remeasure_staging_active_tail",
        lambda **_arguments: (
            drifted,
            copy.deepcopy(documents["public_bracket_after"]),
        ),
    )
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="changed after attestation verification",
    ):
        active.validate_staging_active_transition(
            source_sha=SHA,
            account_id=ACCOUNT,
            api_token="opaque-test-token",
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda evidence: evidence["deployments"]["authority"].update(id="changed"),
            "changed",
        ),
        (
            lambda evidence: evidence["public"]["caller"].update(routes=[{}]),
            "changed",
        ),
        (
            lambda evidence: evidence["attestation"].update(go_override=True),
            "attestation is invalid",
        ),
        (
            lambda evidence: evidence["attestation"].update(
                eligibility="TRUSTED_COLLECTION"
            ),
            "attestation is invalid",
        ),
        (
            lambda evidence: evidence["attestation"].update(
                signed_claims_digest=active._canonical_digest(evidence["attestation"])
            ),
            "signature is invalid",
        ),
        (
            lambda evidence: evidence["attestation"].update(
                signature="ed25519:" + base64.b64encode(b"x" * 64).decode("ascii")
            ),
            "signature is invalid",
        ),
    ],
)
def test_gate_rejects_races_positive_eligibility_and_digest_confusion(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    evidence = _evidence(tmp_path)
    after_deployments = copy.deepcopy(evidence["deployments"])
    after_public = copy.deepcopy(evidence["public"])
    mutation(evidence)
    evidence["attestation_path"].write_bytes(
        active._canonical_bytes(evidence["attestation"])
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match=match):
        _validate(
            evidence,
            deployment_bracket_after=after_deployments,
            public_bracket_after=after_public,
        )


def test_gate_rejects_self_signed_source_and_version_substitution(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    substituted = _attestation(
        evidence["private_key"],
        evidence["key_id"],
        evidence["versions"],
        mutate_claims=lambda claims: claims.update(authority_source_sha="2" * 40),
    )
    evidence["attestation_path"].write_bytes(active._canonical_bytes(substituted))
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="immutable caller/authority version/key pair drifted",
    ):
        _validate(evidence)


def test_gate_reads_attestation_once_and_requires_canonical_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _evidence(tmp_path)
    original = Path.read_bytes
    reads = 0

    def counted(path: Path) -> bytes:
        nonlocal reads
        if path == evidence["attestation_path"]:
            reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    _validate(evidence)
    assert reads == 1

    evidence["attestation_path"].write_text(
        json.dumps(evidence["attestation"], indent=2), encoding="utf-8"
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="not canonical"):
        _validate(evidence)


def test_registry_key_id_must_derive_from_exact_public_key(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    registry = json.loads(evidence["registry_path"].read_text(encoding="utf-8"))
    registry["keys"][0]["key_id"] = "receipt-staging-" + "f" * 16
    body = dict(registry)
    body.pop("registry_digest")
    registry["registry_digest"] = active._canonical_digest(body)
    evidence["registry_path"].write_bytes(active._canonical_bytes(registry))
    with pytest.raises(active.ReceiptStagingActiveGateError, match="key identity"):
        _validate(evidence)
