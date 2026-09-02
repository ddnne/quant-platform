from __future__ import annotations

import base64
import copy
import hashlib
import io
import inspect
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.error import HTTPError

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import receipt_authority_pending_live_acceptance as live
from scripts import receipt_authority_staging_active_gate as active


SHA = "1" * 40
ACCOUNT = "2" * 32
ACCESS_AUD = "3" * 64
ACCESS_APP_ID = "30000000-0000-4000-8000-000000000001"
ACCESS_POLICY_ID = "30000000-0000-4000-8000-000000000002"
ACCESS_TOKEN_ID = "30000000-0000-4000-8000-000000000003"
ACCESS_CLIENT_ID = "5" * 32 + ".access"
ACCESS_DOMAIN = "receipt-activation-observer.example.workers.dev"
ACCESS_URL = f"https://{ACCESS_DOMAIN}"
ACCESS_WORKER_ID = "4" * 32


def _schema_rows() -> list[dict[str, Any]]:
    database = sqlite3.connect(":memory:")
    migration = (
        active.ROOT
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "migrations"
        / "0019_receipt_authority_recovery_smoke.sql"
    ).read_text(encoding="utf-8")
    database.executescript(migration)
    fields = ("type", "name", "tbl_name", "sql")
    return [
        dict(zip(fields, row, strict=True))
        for row in database.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name IN (?,?,?) ORDER BY type,name",
            (
                "receipt_authority_recovery_audit_attestations",
                "receipt_authority_recovery_audit_monotonic",
                "receipt_authority_recovery_audit_no_delete",
            ),
        )
    ]


SCHEMA_ROWS = _schema_rows()


def _access_manifest(path: Path) -> Path:
    document = json.loads(active.ACCESS_MANIFEST_PATH.read_text(encoding="utf-8"))
    document["status"] = "ACTIVE"
    document["account_id"] = ACCOUNT
    document["application"].update({
        "id": ACCESS_APP_ID,
        "aud": ACCESS_AUD,
        "destinations": [{"type": "worker", "worker_id": ACCESS_WORKER_ID}],
    })
    document["worker"]["id"] = ACCESS_WORKER_ID
    document["endpoint"]["hostname"] = ACCESS_DOMAIN
    document["endpoint"]["url"] = ACCESS_URL
    document["policy"]["id"] = ACCESS_POLICY_ID
    document["policy"]["include"] = [{
        "service_token": {"token_id": ACCESS_TOKEN_ID}
    }]
    document["service_token"]["token_id"] = ACCESS_TOKEN_ID
    path.write_bytes(active._canonical_bytes(document))
    return path


def _access_snapshot() -> dict[str, Any]:
    return {
        "worker": {
            "id": ACCESS_WORKER_ID,
            "name": "quant-platform-receipt-activation-observer-staging",
            "subdomain": {
                "enabled": True,
                "previews_enabled": False,
                "url": ACCESS_URL,
            },
        },
        "application": {
            "id": ACCESS_APP_ID,
            "aud": ACCESS_AUD,
            "type": "self_hosted",
            "destinations": [{
                "type": "worker",
                "worker_id": ACCESS_WORKER_ID,
            }],
        },
        "policy": {
            "id": ACCESS_POLICY_ID,
            "name": "receipt-activation-observer-service-auth",
            "precedence": 1,
            "decision": "non_identity",
            "include": [{"service_token": {"token_id": ACCESS_TOKEN_ID}}],
            "exclude": [],
            "require": [],
        },
        "service_token": {
            "id": ACCESS_TOKEN_ID,
            "name": "receipt-activation-observer-gate",
            "duration": "8760h",
            "enabled": True,
            "expires_at": "2027-08-28T00:00:00Z",
            "updated_at": "2026-08-28T00:00:00Z",
            "client_secret_version": 1,
        },
        "covering_application_ids": [],
    }


def _access_api_inventory(
    manifest: dict[str, Any],
    *,
    additional_app: dict[str, Any] | None = None,
    selected_app_updates: dict[str, Any] | None = None,
    policy_updates: dict[str, Any] | None = None,
    worker_updates: dict[str, Any] | None = None,
    observed_paths: list[str] | None = None,
) -> Callable[..., tuple[Any, Any]]:
    selected_app = {
        "id": manifest["application"]["id"],
        "aud": manifest["application"]["aud"],
        "type": "self_hosted",
        "destinations": copy.deepcopy(manifest["application"]["destinations"]),
    }
    selected_app.update(selected_app_updates or {})
    applications = [selected_app]
    if additional_app is not None:
        applications.append(additional_app)
    policy = {
        "id": manifest["policy"]["id"],
        "name": manifest["policy"]["name"],
        "precedence": 1,
        "decision": "non_identity",
        "include": copy.deepcopy(manifest["policy"]["include"]),
        "exclude": [],
        "require": [],
    }
    policy.update(policy_updates or {})
    token = {
        "id": manifest["service_token"]["token_id"],
        "name": manifest["service_token"]["name"],
        "client_id": ACCESS_CLIENT_ID,
        "duration": "8760h",
        "enabled": True,
        "expires_at": "2027-08-28T00:00:00Z",
        "updated_at": "2026-08-28T00:00:00Z",
        "client_secret_version": 1,
    }
    worker = {
        "id": manifest["worker"]["id"],
        "name": manifest["worker"]["script_name"],
        "subdomain": {
            "enabled": True,
            "previews_enabled": False,
            "url": manifest["endpoint"]["url"],
        },
    }
    worker.update(copy.deepcopy(worker_updates or {}))

    def request(path: str, **_arguments: Any) -> tuple[Any, Any]:
        if observed_paths is not None:
            observed_paths.append(path)
        if "/workers/workers/" in path:
            return copy.deepcopy(worker), None
        if "/access/apps?" in path:
            return applications, {"total_count": len(applications)}
        if "/policies?" in path:
            return [policy], {"total_count": 1}
        if "/access/service_tokens?" in path:
            return [token], {"total_count": 1}
        raise AssertionError(f"unexpected Cloudflare API path: {path}")

    return request


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
    for ordinal, (role, _worker) in enumerate(active.ACTIVE_CHAIN, start=1):
        surface = surfaces[role]
        deployment_id = f"00000000-0000-4000-8000-{ordinal:012d}"
        version_id = f"10000000-0000-4000-8000-{ordinal:012d}"
        message = (
            active._observer_message(SHA)
            if role == "observer"
            else live.deployment_message(role, "staging", SHA, "ACTIVE")
        )
        deployments[role] = {
            "id": deployment_id,
            "created_on": {
                "acquisition": "2026-08-28T08:00:05.000Z",
                "authority": "2026-08-28T08:00:10.000Z",
                "caller": "2026-08-28T08:00:20.000Z",
                "observer": "2026-08-28T08:00:25.000Z",
            }[role],
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
        if surface["compatibility_flags"]:
            runtime["compatibility_flags"] = copy.deepcopy(
                surface["compatibility_flags"]
            )
        migration = live._expected_migration_tag(surface)
        if migration is not None:
            runtime["migration_tag"] = migration
        versions[role] = {
            "id": version_id,
            "annotations": {
                "workers/message": message,
                "workers/tag": (
                    active._observer_tag(SHA)
                    if role == "observer"
                    else live.version_tag(role, "staging", SHA, "ACTIVE")
                ),
                "workers/triggered_by": "version_upload",
            },
            "metadata": {
                "created_on": {
                    "acquisition": "2026-08-28T08:00:01.000Z",
                    "authority": "2026-08-28T08:00:02.000Z",
                    "caller": "2026-08-28T08:00:11.000Z",
                    "observer": "2026-08-28T08:00:21.000Z",
                }[role],
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


def _observer_documents(
    attestation: dict[str, Any],
    versions: dict[str, Any],
    *,
    challenge: str = "f" * 64,
) -> tuple[bytes, dict[str, Any]]:
    exact_text = active._canonical_bytes(attestation).decode("utf-8")
    caller_version_id = versions["caller"]["id"]
    reservation_id = active._canonical_digest({
        "schema_version": "staging-receipt-audit-reservation/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "source_sha": SHA,
        "caller_worker_version_id": caller_version_id,
    })
    claims = json.loads(base64.b64decode(attestation["signed_claims_base64"]))
    premium_body = {
        "schema_version": "receipt-operator-audit-evidence/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "caller_source_sha": SHA,
        "caller_worker_version_id": caller_version_id,
        "caller_worker_version_tag": live.version_tag(
            "caller", "staging", SHA, "ACTIVE"
        ),
        "d1_schema_digest": active.RECOVERY_AUDIT_SCHEMA_DIGEST,
        "reservation_id": reservation_id,
        "authority_operation_id": claims["operation_id"],
        "request_nonce": claims["request_nonce"],
        "signed_attestation_digest": active._canonical_digest(attestation),
        "signed_attestation_json_utf8_base64": base64.b64encode(
            exact_text.encode("utf-8")
        ).decode("ascii"),
        "signed_attestation_json_utf8_length": len(exact_text.encode("utf-8")),
    }
    premium = {
        **premium_body,
        "evidence_digest": active._canonical_digest(premium_body),
    }
    response_body = {
        "schema_version": "receipt-activation-observer-response/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "challenge": challenge,
        "observer_source_sha": SHA,
        "observer_worker_version_id": versions["observer"]["id"],
        "observer_worker_version_tag": active._observer_tag(SHA),
        "access_authenticated": True,
        "access_aud": ACCESS_AUD,
        "premium_evidence": premium,
        "premium_evidence_digest": premium["evidence_digest"],
    }
    response = {
        **response_body,
        "response_digest": active._canonical_digest(response_body),
    }
    d1 = {
        "schema_rows": copy.deepcopy(SCHEMA_ROWS),
        "attestation_rows": [{
            "reservation_id": reservation_id,
            "source_sha": SHA,
            "caller_worker_version_id": caller_version_id,
            "authority_operation_id": claims["operation_id"],
            "request_nonce": claims["request_nonce"],
            "state": "ATTESTED",
            "signed_attestation_digest": active._canonical_digest(attestation),
            "signed_attestation_json": exact_text,
        }],
    }
    return active._canonical_bytes(response), d1


def _refresh_observer(evidence: dict[str, Any]) -> None:
    response, d1 = _observer_documents(
        evidence["attestation"],
        evidence["versions"],
        challenge=evidence["challenge"],
    )
    evidence["observer_response"] = response
    evidence["d1_snapshot"] = d1


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
    evidence = {
        "private_key": private_key,
        "key_id": key_id,
        "registry_path": registry_path,
        "deployments": deployments,
        "versions": versions,
        "public": public,
        "provenance": provenance,
        "attestation": attestation,
        "challenge": "f" * 64,
        "access_manifest_path": _access_manifest(tmp_path / "access.json"),
        "access_snapshot": _access_snapshot(),
    }
    _refresh_observer(evidence)
    return evidence


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
        "observer_response_bytes": evidence["observer_response"],
        "observer_challenge": evidence["challenge"],
        "access_snapshot": evidence["access_snapshot"],
        "d1_snapshot": evidence["d1_snapshot"],
        "access_manifest_path": evidence["access_manifest_path"],
        "registry_path": evidence["registry_path"],
    }
    arguments.update(overrides)
    return active._validate_staging_active_transition_core(**arguments)


def test_exact_audit_only_transition_uses_real_signature_and_separate_digests(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    result = _validate(evidence)
    assert result["format"] == "receipt-authority-staging-active-transition/v3"
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
    assert set(result["workers"]) == {
        "acquisition", "authority", "caller", "observer"
    }
    assert result["access_aud"] == ACCESS_AUD
    assert result["observer_challenge"] == evidence["challenge"]
    assert result["d1_schema_digest"] == active.RECOVERY_AUDIT_SCHEMA_DIGEST
    assert result["deployment_pair_digest"] == active._canonical_digest(
        {
            "schema_version": "receipt-audit-deployment-pair/v2",
            "environment": "staging",
            "authority_deployment_id": evidence["deployments"]["authority"]["id"],
            "authority_worker_version_id": evidence["versions"]["authority"]["id"],
            "caller_deployment_id": evidence["deployments"]["caller"]["id"],
            "caller_worker_version_id": evidence["versions"]["caller"]["id"],
            "active_key_id": evidence["key_id"],
            "registry_digest": json.loads(
                evidence["registry_path"].read_text(encoding="utf-8")
            )["registry_digest"],
        }
    )


def test_authority_change_requires_a_newer_coordinated_caller_version(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)

    new_authority_version = "20000000-0000-4000-8000-000000000002"
    evidence["deployments"]["authority"]["versions"][0]["version_id"] = (
        new_authority_version
    )
    evidence["deployments"]["authority"]["id"] = (
        "20000000-0000-4000-8000-000000000012"
    )
    evidence["deployments"]["authority"]["created_on"] = (
        "2026-08-28T08:00:12.000Z"
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
    _refresh_observer(evidence)
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="Premium caller version was not uploaded after authority deployment",
    ):
        _validate(evidence)

    new_caller_version = "20000000-0000-4000-8000-000000000003"
    evidence["deployments"]["caller"]["versions"][0]["version_id"] = (
        new_caller_version
    )
    evidence["deployments"]["caller"]["id"] = (
        "20000000-0000-4000-8000-000000000014"
    )
    evidence["deployments"]["caller"]["created_on"] = (
        "2026-08-28T08:00:14.000Z"
    )
    evidence["versions"]["caller"]["id"] = new_caller_version
    evidence["versions"]["caller"]["metadata"]["created_on"] = (
        "2026-08-28T08:00:13.000000Z"
    )
    evidence["attestation"] = _attestation(
        evidence["private_key"], evidence["key_id"], evidence["versions"]
    )
    _refresh_observer(evidence)
    result = _validate(evidence)
    assert result["workers"]["authority"]["deployment_version_id"] == (
        new_authority_version
    )
    assert result["workers"]["caller"]["deployment_version_id"] == (
        new_caller_version
    )


def test_same_version_redeployment_after_attestation_is_rejected(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["deployments"]["caller"]["id"] = (
        "30000000-0000-4000-8000-000000000003"
    )
    evidence["deployments"]["caller"]["created_on"] = (
        "2026-08-28T08:02:00.000Z"
    )

    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="Receipt audit recovery predates ACTIVE deployment",
    ):
        _validate(evidence)


def test_reversed_authority_and_caller_deployment_order_is_rejected(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["deployments"]["caller"]["created_on"] = (
        "2026-08-28T08:00:09.000Z"
    )

    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="Premium caller deployment was not coordinated after authority deployment",
    ):
        _validate(evidence)


def test_attestation_must_be_issued_after_both_current_deployments(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    evidence["deployments"]["authority"]["created_on"] = (
        "2026-08-28T08:01:01.000Z"
    )

    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="Receipt audit recovery predates ACTIVE deployment",
    ):
        _validate(evidence)


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
        "access_snapshot": evidence["access_snapshot"],
        "d1_snapshot": evidence["d1_snapshot"],
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
        "_load_access_manifest",
        lambda *_args, **_kwargs: json.loads(
            evidence["access_manifest_path"].read_text(encoding="utf-8")
        ),
    )
    monkeypatch.setattr(
        active,
        "_fetch_observer_response",
        lambda **_arguments: evidence["observer_response"],
    )
    monkeypatch.setattr(
        active,
        "_write_content_addressed_result",
        lambda result: dict(result),
    )
    monkeypatch.setattr(
        active,
        "_remeasure_staging_active_tail",
        lambda **_arguments: (
            copy.deepcopy(documents["deployment_bracket_after"]),
            copy.deepcopy(documents["public_bracket_after"]),
            copy.deepcopy(documents["access_snapshot"]),
            copy.deepcopy(documents["d1_snapshot"]),
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
    assert validated[0]["access_manifest_path"] == active.ACCESS_MANIFEST_PATH
    assert validated[0]["observer_response_bytes"] == evidence["observer_response"]
    assert validated[0]["observer_challenge"].isalnum()
    assert len(validated[0]["observer_challenge"]) == 64

    drifted = copy.deepcopy(documents["deployment_bracket_after"])
    drifted["authority"]["id"] = "changed-after-attestation"
    monkeypatch.setattr(
        active,
        "_remeasure_staging_active_tail",
        lambda **_arguments: (
            drifted,
            copy.deepcopy(documents["public_bracket_after"]),
            copy.deepcopy(documents["access_snapshot"]),
            copy.deepcopy(documents["d1_snapshot"]),
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

    drifted_access = copy.deepcopy(documents["access_snapshot"])
    drifted_access["application"]["aud"] = "0" * 64
    monkeypatch.setattr(
        active,
        "_remeasure_staging_active_tail",
        lambda **_arguments: (
            copy.deepcopy(documents["deployment_bracket_after"]),
            copy.deepcopy(documents["public_bracket_after"]),
            drifted_access,
            copy.deepcopy(documents["d1_snapshot"]),
        ),
    )
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="Access app/policy/token changed",
    ):
        active.validate_staging_active_transition(
            source_sha=SHA,
            account_id=ACCOUNT,
            api_token="opaque-test-token",
        )

    drifted_d1 = copy.deepcopy(documents["d1_snapshot"])
    drifted_d1["attestation_rows"][0]["state"] = "CHANGED"
    monkeypatch.setattr(
        active,
        "_remeasure_staging_active_tail",
        lambda **_arguments: (
            copy.deepcopy(documents["deployment_bracket_after"]),
            copy.deepcopy(documents["public_bracket_after"]),
            copy.deepcopy(documents["access_snapshot"]),
            drifted_d1,
        ),
    )
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="D1 evidence changed",
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
    _refresh_observer(evidence)
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
    evidence["attestation"] = substituted
    _refresh_observer(evidence)
    with pytest.raises(
        active.ReceiptStagingActiveGateError,
        match="immutable caller/authority version/key pair drifted",
    ):
        _validate(evidence)


def test_gate_rejects_noncanonical_or_challenge_substituted_observer_bytes(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    _validate(evidence)
    pretty = json.dumps(json.loads(evidence["observer_response"]), indent=2).encode()
    with pytest.raises(active.ReceiptStagingActiveGateError, match="not canonical"):
        _validate(evidence, observer_response_bytes=pretty)
    with pytest.raises(active.ReceiptStagingActiveGateError, match="scope drifted"):
        _validate(evidence, observer_challenge="0" * 64)


def test_gate_rejects_access_aud_and_current_worker_version_substitution(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    for mutation in (
        lambda response: response.update(access_aud="0" * 64),
        lambda response: response.update(
            observer_worker_version_id="20000000-0000-4000-8000-000000000004"
        ),
        lambda response: response["premium_evidence"].update(
            caller_worker_version_id="20000000-0000-4000-8000-000000000003"
        ),
    ):
        response = json.loads(evidence["observer_response"])
        mutation(response)
        if response["premium_evidence"] != json.loads(
            evidence["observer_response"]
        )["premium_evidence"]:
            premium = response["premium_evidence"]
            premium_body = dict(premium)
            premium_body.pop("evidence_digest")
            premium["evidence_digest"] = active._canonical_digest(premium_body)
            response["premium_evidence_digest"] = premium["evidence_digest"]
        response_body = dict(response)
        response_body.pop("response_digest")
        response["response_digest"] = active._canonical_digest(response_body)
        with pytest.raises(active.ReceiptStagingActiveGateError, match="scope drifted"):
            _validate(evidence, observer_response_bytes=active._canonical_bytes(response))


@pytest.mark.parametrize("field", ["schema_rows", "attestation_rows"])
def test_gate_rejects_independent_d1_schema_and_exact_text_drift(
    tmp_path: Path,
    field: str,
) -> None:
    evidence = _evidence(tmp_path)
    drifted = copy.deepcopy(evidence["d1_snapshot"])
    if field == "schema_rows":
        drifted[field][0]["sql"] += " "
    else:
        drifted[field][0]["signed_attestation_json"] += " "
    with pytest.raises(active.ReceiptStagingActiveGateError, match="D1"):
        _validate(evidence, d1_snapshot=drifted)


def test_access_inventory_requires_exact_worker_app_policy_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observed_paths: list[str] = []
    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, ACCESS_CLIENT_ID)
    monkeypatch.setattr(
        active,
        "_cloudflare_api",
        _access_api_inventory(manifest, observed_paths=observed_paths),
    )
    assert active._collect_access_snapshot(
        account_id=ACCOUNT,
        api_token="opaque",
        access_manifest=manifest,
    ) == _access_snapshot()
    assert observed_paths[0].endswith(f"/workers/workers/{ACCESS_WORKER_ID}")
    assert manifest["worker"]["script_name"] not in observed_paths[0]

    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, "wrong-client-id")
    with pytest.raises(active.ReceiptStagingActiveGateError, match="credential identity"):
        active._collect_access_snapshot(
            account_id=ACCOUNT,
            api_token="opaque",
            access_manifest=manifest,
        )
    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, ACCESS_CLIENT_ID)

    monkeypatch.setattr(
        active,
        "_cloudflare_api",
        _access_api_inventory(manifest, selected_app_updates={"aud": "0" * 64}),
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="drifted"):
        active._collect_access_snapshot(
            account_id=ACCOUNT,
            api_token="opaque",
            access_manifest=manifest,
        )

    monkeypatch.setattr(
        active,
        "_cloudflare_api",
        _access_api_inventory(manifest, policy_updates={"decision": "allow"}),
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="drifted"):
        active._collect_access_snapshot(
            account_id=ACCOUNT,
            api_token="opaque",
            access_manifest=manifest,
        )


@pytest.mark.parametrize(
    "worker_updates",
    [
        {"id": "6" * 32},
        {"name": "different-observer"},
        {
            "subdomain": {
                "enabled": False,
                "previews_enabled": False,
                "url": ACCESS_URL,
            }
        },
        {
            "subdomain": {
                "enabled": True,
                "previews_enabled": True,
                "url": ACCESS_URL,
            }
        },
        {
            "subdomain": {
                "enabled": True,
                "previews_enabled": False,
                "url": "https://different-observer.example.workers.dev",
            }
        },
    ],
)
def test_access_inventory_rejects_worker_or_subdomain_endpoint_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worker_updates: dict[str, Any],
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, ACCESS_CLIENT_ID)
    monkeypatch.setattr(
        active,
        "_cloudflare_api",
        _access_api_inventory(manifest, worker_updates=worker_updates),
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="endpoint drifted"):
        active._collect_access_snapshot(
            account_id=ACCOUNT,
            api_token="opaque",
            access_manifest=manifest,
        )


def test_access_manifest_rejects_endpoint_hostname_url_substitution(
    tmp_path: Path,
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["endpoint"]["hostname"] = "different-observer.example.workers.dev"
    manifest_path.write_bytes(active._canonical_bytes(document))
    with pytest.raises(active.ReceiptStagingActiveGateError, match="exact Service Auth"):
        active._load_access_manifest(manifest_path, account_id=ACCOUNT)


@pytest.mark.parametrize(
    "additional_app",
    [
        {
            "id": "40000000-0000-4000-8000-000000000001",
            "destinations": [{"type": "worker", "worker_id": ACCESS_WORKER_ID}],
        },
        {
            "id": "40000000-0000-4000-8000-000000000002",
            "destinations": [{
                "type": "preview_worker", "worker_id": ACCESS_WORKER_ID
            }],
        },
        {
            "id": "40000000-0000-4000-8000-000000000003",
            "destinations": [{"type": "all_workers"}],
        },
        {
            "id": "40000000-0000-4000-8000-000000000004",
            "destinations": [{"type": "all_preview_workers"}],
        },
        {
            "id": "40000000-0000-4000-8000-000000000005",
            "destinations": [{
                "type": "public", "uri": f"https://{ACCESS_DOMAIN}/admin"
            }],
        },
        {
            "id": "40000000-0000-4000-8000-000000000006",
            "domain": ACCESS_DOMAIN,
        },
        {
            "id": "40000000-0000-4000-8000-000000000007",
            "self_hosted_domains": ["*.example.workers.dev"],
        },
    ],
)
def test_access_inventory_rejects_every_covering_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    additional_app: dict[str, Any],
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, ACCESS_CLIENT_ID)
    monkeypatch.setattr(
        active,
        "_cloudflare_api",
        _access_api_inventory(manifest, additional_app=additional_app),
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="drifted"):
        active._collect_access_snapshot(
            account_id=ACCOUNT,
            api_token="opaque",
            access_manifest=manifest,
        )


def test_access_inventory_rejects_selected_app_hostname_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, ACCESS_CLIENT_ID)
    monkeypatch.setattr(
        active,
        "_cloudflare_api",
        _access_api_inventory(
            manifest,
            selected_app_updates={"domain": ACCESS_DOMAIN},
        ),
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="hostname scope"):
        active._collect_access_snapshot(
            account_id=ACCOUNT,
            api_token="opaque",
            access_manifest=manifest,
        )


def test_cloudflare_zero_trust_9999_is_an_operational_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = active._canonical_bytes({
        "success": False,
        "errors": [{"code": 9999, "message": "not initialized"}],
    })

    def fail(_request: Any, *, timeout: int) -> Any:
        assert timeout == 30
        raise HTTPError(
            "https://api.cloudflare.com/client/v4/accounts/x/access/apps",
            403,
            "forbidden",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(
        active,
        "_pinned_https_opener",
        lambda: SimpleNamespace(open=fail),
    )
    with pytest.raises(active.ReceiptStagingActiveGateError, match="9999"):
        active._cloudflare_api("/accounts/x/access/apps", api_token="opaque")


def test_observer_fetch_requires_environment_credentials_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    monkeypatch.delenv(active.ACCESS_CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(active.ACCESS_CLIENT_SECRET_ENV, raising=False)
    with pytest.raises(active.ReceiptStagingActiveGateError, match="process environment"):
        active._fetch_observer_response(challenge="f" * 64, access_manifest=manifest)


def test_observer_fetch_probes_unauthenticated_then_exact_access_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    exact = b'{"closed":true}'
    observed: list[dict[str, str]] = []

    class Response:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
            "pragma": "no-cache",
            "x-content-type-options": "nosniff",
        }

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return exact

        def getcode(self) -> int:
            return 200

        def geturl(self) -> str:
            return (
                f"https://{ACCESS_DOMAIN}/v1/receipt-authority/audit-evidence?"
                f"challenge={'f' * 64}"
            )

    def open_request(request: Any, *, timeout: int) -> Any:
        assert timeout == 30
        headers = {key.lower(): value for key, value in request.header_items()}
        observed.append(headers)
        if "cf-access-client-id" not in headers:
            raise HTTPError(request.full_url, 403, "forbidden", {}, io.BytesIO(b""))
        return Response()

    monkeypatch.setenv(active.ACCESS_CLIENT_ID_ENV, "client-id")
    monkeypatch.setenv(active.ACCESS_CLIENT_SECRET_ENV, "client-secret")
    monkeypatch.setattr(
        active,
        "_pinned_https_opener",
        lambda: SimpleNamespace(open=open_request),
    )
    assert active._fetch_observer_response(
        challenge="f" * 64,
        access_manifest=manifest,
    ) == exact
    assert len(observed) == 2
    assert "cf-access-client-id" not in observed[0]
    assert observed[1]["cf-access-client-id"] == "client-id"
    assert observed[1]["cf-access-client-secret"] == "client-secret"


def test_content_addressed_output_is_create_only_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "repo" / "data" / "ops"
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(active, "ROOT", root)
    monkeypatch.setattr(active, "OUTPUT_DIR", output)
    document = active._write_content_addressed_result({"status": "accepted"})
    assert active._write_content_addressed_result({"status": "accepted"}) == document
    paths = list(output.iterdir())
    assert len(paths) == 1
    paths[0].write_text("changed", encoding="utf-8")
    with pytest.raises(active.ReceiptStagingActiveGateError, match="collision"):
        active._write_content_addressed_result({"status": "accepted"})


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
