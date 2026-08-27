#!/usr/bin/env python3
"""Validate the frozen seven-principal signing capability graph.

This module reads public contract material only.  It never creates an OS user,
loads or creates a private key, or calls Cloudflare.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_SPECS = ROOT / "specs" / "authorities"
MANIFEST = AUTHORITY_SPECS / "authority-principal-manifest.json"
MANIFEST_SCHEMA = AUTHORITY_SPECS / "authority-principal-manifest.schema.json"
PROTOCOL_SCHEMAS = {
    "frozen_mirror_request": AUTHORITY_SPECS / "frozen_mirror_request.schema.json",
    "frozen_mirror_handoff": AUTHORITY_SPECS / "frozen_mirror_handoff.schema.json",
    "authority_event": AUTHORITY_SPECS / "authority_event.schema.json",
    "trader_webauthn_challenge": (
        AUTHORITY_SPECS / "trader_webauthn_challenge.schema.json"
    ),
    "trader_webauthn_assertion": (
        AUTHORITY_SPECS / "trader_webauthn_assertion.schema.json"
    ),
    "jquants_acquisition_rpc": (
        AUTHORITY_SPECS / "jquants_acquisition_rpc.schema.json"
    ),
}
# Parallel lanes must add each independently reviewed path here and its digest
# to the manifest in the same commit. A caller cannot bless a new protocol by
# self-declaring only its digest.
PARALLEL_PROTOCOL_SCHEMAS: dict[str, Path] = {
    "receipt_verify_public_keys": (
        ROOT / "specs" / "receipts" / "receipt_verify_public_keys.schema.json"
    ),
    "jquants_acquisition_collection": (
        ROOT / "specs" / "receipts" / "jquants_acquisition_collection.schema.json"
    ),
    "exact_four_authority_protocol": (
        ROOT / "specs" / "ready" / "exact_four_authority_protocol.schema.json"
    ),
    "exact_four_result_manifest": (
        ROOT / "specs" / "ready" / "exact_four_result_manifest.schema.json"
    ),
    "exact_four_trader_authorization_v2": (
        ROOT
        / "specs"
        / "ready"
        / "exact_four_trader_authorization_v2.schema.json"
    ),
}

PRINCIPALS = (
    "receipt",
    "d1_sync",
    "ops_projection",
    "coverage_transition",
    "ready",
    "trader",
    "controlled_execution",
)
LOCAL_OS_PRINCIPALS = frozenset(PRINCIPALS) - {"receipt"}
EXPECTED_RUNTIME = {
    principal: (
        "cloudflare_worker" if principal == "receipt" else "local_os_service"
    )
    for principal in PRINCIPALS
}
ALLOWED_CALLERS = {
    "receipt": ("governed_ingestion",),
    "d1_sync": ("ops_scheduler", "ops_projection", "coverage_transition"),
    "ops_projection": ("ops_scheduler",),
    "coverage_transition": ("coverage_scheduler",),
    "ready": ("ready_publisher",),
    "trader": ("human_approval_gateway",),
    "controlled_execution": ("controlled_pilot_orchestrator",),
}
_BOTH_ENVIRONMENTS = ["staging", "production"]


def _acl(
    caller: str,
    operation: str,
    purpose: str,
    authentication: str = "local_peer_credentials",
) -> dict[str, Any]:
    return {
        "authenticated_caller": caller,
        "target_operation": operation,
        "purpose": purpose,
        "environments": _BOTH_ENVIRONMENTS,
        "authentication": authentication,
    }


EXPECTED_METHOD_ACL = {
    "receipt": [
        _acl(
            "governed_ingestion",
            "receipt:issue_for_segment",
            "trusted_collection_receipt",
            "cloudflare_typed_service_binding",
        ),
        _acl(
            "governed_ingestion",
            "receipt:recover_issue",
            "trusted_collection_receipt_recovery",
            "cloudflare_typed_service_binding",
        ),
        _acl(
            "governed_ingestion",
            "receipt:public_key_registration",
            "receipt_key_registry_proposal",
            "cloudflare_typed_service_binding",
        ),
    ],
    "d1_sync": [
        _acl("ops_scheduler", "d1_sync:sync_now", "sync_current"),
        _acl(
            "ops_projection",
            "frozen_mirror:readonly_handoff",
            "ops_projection",
        ),
        _acl(
            "coverage_transition",
            "frozen_mirror:readonly_handoff",
            "coverage_transition",
        ),
        _acl(
            "coverage_transition",
            "coverage_transition_apply:apply_signed",
            "coverage_transition_apply",
        ),
    ],
    "ops_projection": [
        _acl(
            "ops_scheduler",
            "ops_projection:render_and_sign",
            "render_current_projection",
        )
    ],
    "coverage_transition": [
        _acl(
            "coverage_scheduler",
            "coverage_transition:authorize_and_apply",
            "coverage_v3_transition",
        )
    ],
    "ready": [
        _acl(
            "ready_publisher",
            "ready:publish_profile_plan_bound",
            "profile_plan_closure_ready",
        )
    ],
    "trader": [
        _acl(
            "human_approval_gateway",
            "trader:authorize_exact_four_batch_human_present",
            "exact_four_human_approval",
            "webauthn_human_presence",
        )
    ],
    "controlled_execution": [
        _acl(
            "controlled_pilot_orchestrator",
            "controlled_execution:execute_exact_four_one_shot",
            "exact_four_one_shot",
        )
    ],
}
EXPECTED_PENDING_DEPENDENCIES = {
    "receipt": [
        {
            "dependency_id": "receipt_authority_operational_activation",
            "status": "PENDING",
            "required_contract": (
                "PENDING deploy, wrapped-key public registration, reviewed registry "
                "activation, then exact ACTIVE key-id deploy"
            ),
            "observed_implementation": (
                "Worker, typed caller/acquisition bindings, append/finalize/recover "
                "ledgers, runtime tests, and migrations are present; Cloudflare "
                "resources, wrap secret, migration apply, registration review, ACTIVE "
                "deploy, and dataset reproof remain unprovisioned"
            ),
            "activation_blocked": True,
        }
    ],
    "trader": [
        {
            "dependency_id": "verified_pilot_readiness_v2",
            "status": "PENDING",
            "required_contract": (
                "VerifiedPilotReadinessV2 from the dedicated READY verifier"
            ),
            "observed_implementation": (
                "positive READY type and Trader preparation entrypoint remain "
                "unconstructible and fail closed"
            ),
            "activation_blocked": True,
        },
        {
            "dependency_id": "governed_trader_rp_registry",
            "status": "PENDING",
            "required_contract": (
                "pinned environment-scoped RP id and HTTPS origin registry"
            ),
            "observed_implementation": (
                "wire evidence is frozen; active governed RP registry count is zero"
            ),
            "activation_blocked": True,
        },
        {
            "dependency_id": "governed_webauthn_challenge_generator",
            "status": "PENDING",
            "required_contract": (
                "authority-generated 32-or-more-byte CSPRNG challenge with "
                "generation evidence"
            ),
            "observed_implementation": (
                "canonical decoding and byte-size bounds are frozen; randomness "
                "cannot be inferred from submitted bytes and no generator is active"
            ),
            "activation_blocked": True,
        },
        {
            "dependency_id": "webauthn_credential_registry_and_signature_verifier",
            "status": "PENDING",
            "required_contract": (
                "pinned active WebAuthn credential registry and signature verifier"
            ),
            "observed_implementation": (
                "canonical bytes and evidence links validate; no credential is active "
                "and no signature is verified"
            ),
            "activation_blocked": True,
        },
        {
            "dependency_id": "atomic_one_use_and_counter_ledger",
            "status": "PENDING",
            "required_contract": (
                "one transaction atomically consumes challenge and advances counter"
            ),
            "observed_implementation": (
                "transaction wire and CAS invariants are frozen; no ledger is provisioned"
            ),
            "activation_blocked": True,
        },
        {
            "dependency_id": "append_only_trader_authority_event_store",
            "status": "PENDING",
            "required_contract": (
                "authority-event/v2 append-only store atomically unique on "
                "environment, authority, stable decision/transaction key, request, "
                "and ledger transaction/event identity; retry returns only the "
                "byte-identical committed event"
            ),
            "observed_implementation": (
                "stable decision and transaction keys are remeasured; no atomic "
                "exactly-once store is provisioned"
            ),
            "activation_blocked": True,
        },
        {
            "dependency_id": "controlled_execution_v2_consumer",
            "status": "PENDING",
            "required_contract": (
                "consumer accepts only VerifiedPilotReadinessV2 and "
                "VerifiedExactFourTraderAuthorizationV2"
            ),
            "observed_implementation": (
                "typed positive interface is frozen and unconditionally PENDING"
            ),
            "activation_blocked": True,
        },
    ],
    **{
        principal: []
        for principal in PRINCIPALS
        if principal not in {"receipt", "trader"}
    },
}
EXPECTED_PROVIDES = {
    "receipt": (
        "receipt:issue_for_segment",
        "receipt:recover_issue",
        "receipt:public_key_registration",
    ),
    "d1_sync": (
        "d1_sync:sync_now",
        "frozen_mirror:readonly_handoff",
        "coverage_transition_apply:apply_signed",
    ),
    "ops_projection": ("ops_projection:render_and_sign",),
    "coverage_transition": ("coverage_transition:authorize_and_apply",),
    "ready": ("ready:publish_profile_plan_bound",),
    "trader": ("trader:authorize_exact_four_batch_human_present",),
    "controlled_execution": ("controlled_execution:execute_exact_four_one_shot",),
}
EXPECTED_CAPABILITIES = {
    "receipt": (
        "jquants_acquisition:fetch_governed_page",
        "raw_immutable:create_only",
        "structured_immutable:create_only",
        "structured_natural_key:segment_read",
        "receipt_ledger:append",
        "receipt_signature:sign",
        "receipt_key_registration:export_public",
    ),
    "d1_sync": (
        "cloudflare_d1:quant_ingest_export",
        "mirror_store:write",
        "frozen_mirror:readonly_handoff",
        "d1_sync_audit:sign",
        "d1_sync_event_ledger:append",
    ),
    "ops_projection": (
        "frozen_mirror:readonly_consume",
        "ops_projection:render",
        "ops_projection_signature:sign",
        "ops_projection_store:append_activate",
        "ops_projection_event_ledger:append",
    ),
    "coverage_transition": (
        "frozen_mirror:readonly_consume",
        "coverage_transition:derive",
        "coverage_transition_signature:sign",
        "coverage_transition_apply:request",
        "coverage_transition_event_ledger:append",
    ),
    "ready": (
        "ops_projection:verified_read",
        "immutable_snapshot:read",
        "ready_attestation:sign",
        "ready_store:append",
        "ready_event_ledger:append",
    ),
    "trader": (
        "ready_attestation:verified_read",
        "human_decision:read",
        "trader_authorization:sign",
        "trader_authorization_ledger:append",
    ),
    "controlled_execution": (
        "ready_attestation:verified_read",
        "trader_authorization:verified_read",
        "immutable_snapshot:read",
        "paper_execution:execute_bounded",
        "controlled_artifact:sign",
        "controlled_artifact_store:append",
    ),
}
FORBIDDEN_CAPABILITIES = {
    "receipt": (
        "other_signer_private_key:read",
        "ops_projection_signature:sign",
        "ready_attestation:sign",
        "general_complete:mint",
    ),
    "d1_sync": (
        "other_signer_private_key:read",
        "ops_projection_signature:sign",
        "coverage_transition_signature:sign",
        "ready_attestation:sign",
    ),
    "ops_projection": (
        "source_d1:write",
        "source_d1:direct_bind",
        "mcp_quota_db:write",
        "ready_private_key:read",
        "other_signer_private_key:read",
    ),
    "coverage_transition": (
        "source_d1:write",
        "source_d1:direct_bind",
        "ready_private_key:read",
        "other_signer_private_key:read",
    ),
    "ready": (
        "source_d1:write",
        "receipt_private_key:read",
        "ops_projection_private_key:read",
        "other_signer_private_key:read",
    ),
    "trader": (
        "automatic_approval:authorize",
        "raw_db:read",
        "other_signer_private_key:read",
        "controlled_execution_signature:sign",
    ),
    "controlled_execution": (
        "external_http:request",
        "raw_db:read",
        "ingestion_secrets:read",
        "automatic_promotion:execute",
        "other_signer_private_key:read",
    ),
}
EXPECTED_RESIDUAL_RISK = "cloudflare_workers_scripts_write_account_scope"

# Updated atomically with the reviewed checked-in manifest.  The manifest also
# contains its own body digest; this independent code pin prevents a caller from
# changing the contract and merely recomputing that self-declared digest.
PINNED_MANIFEST_DIGEST = (
    "sha256:d6afc3fddc29a12b5472213b06acb64d881f9cd63fe91a001c3c273a5428cb84"
)

_BROAD_CAPABILITY_TOKENS = frozenset(
    {"account", "admin", "all", "full", "global", "manage", "owner", "root"}
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot load authority contract JSON: {path}") from exc
    if type(value) is not dict:
        raise ValueError(f"authority contract must be an object: {path}")
    return value


def _require_exact_json(value: Any, *, path: str = "$") -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path}: object keys must be exact strings")
            _require_exact_json(item, path=f"{path}.{key}")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _require_exact_json(item, path=f"{path}[{index}]")
        return
    if type(value) not in {str, int, bool, type(None)}:
        raise ValueError(f"{path}: value is not an exact JSON built-in")


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    if type(value) is not dict:
        raise TypeError("canonical authority contract input must be one exact dict")
    _require_exact_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def manifest_body_digest(manifest: Mapping[str, Any]) -> str:
    if type(manifest) is not dict:
        raise TypeError("authority principal manifest must be one exact dict")
    return canonical_digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    )


def _schema_validate(document: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - dependency installation failure
        raise RuntimeError("jsonschema is required for authority contract validation") from exc

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if not errors:
        return
    error = errors[0]
    location = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.path
    )
    raise ValueError(
        f"authority principal manifest schema violation at {location}: "
        f"{error.message}"
    )


def _reject_broad_capability(value: str, *, field: str) -> None:
    tokens = set(re.split(r"[^a-z0-9]+", value.lower()))
    if "*" in value or tokens.intersection(_BROAD_CAPABILITY_TOKENS):
        raise ValueError(f"{field}: wildcard or broad capability is forbidden: {value}")


def _claim_unique(
    claims: dict[str, tuple[str, str]],
    *,
    value: str,
    principal: str,
    environment: str,
    field: str,
) -> None:
    previous = claims.get(value)
    if previous is not None:
        raise ValueError(
            f"duplicate {field}: {value} belongs to both "
            f"{previous[0]}/{previous[1]} and {principal}/{environment}"
        )
    claims[value] = (principal, environment)


def _expected_cloudflare_resources(
    *, principal: str, environment: str
) -> list[dict[str, str]]:
    suffix = "-staging" if environment == "staging" else ""
    if principal == "receipt":
        return [
            {
                "provider": "cloudflare",
                "kind": "r2",
                "resource_ref": f"cloudflare:{environment}:r2:quant-raw{suffix}",
                "access": "create_only_read",
            },
            {
                "provider": "cloudflare",
                "kind": "r2",
                "resource_ref": (
                    f"cloudflare:{environment}:r2:quant-structured{suffix}"
                ),
                "access": "create_only_read",
            },
            {
                "provider": "cloudflare",
                "kind": "d1",
                "resource_ref": f"cloudflare:{environment}:d1:quant-ingest{suffix}",
                "access": "segment_reconcile_receipt_append",
            },
            {
                "provider": "cloudflare",
                "kind": "durable_object",
                "resource_ref": (
                    f"cloudflare:{environment}:durable_object:"
                    f"receipt-evidence-authority{suffix}"
                ),
                "access": "key_sign_event_append",
            },
            {
                "provider": "cloudflare",
                "kind": "service_binding",
                "resource_ref": (
                    f"cloudflare:{environment}:service_binding:"
                    f"quant-platform-ingestion-secrets{suffix}"
                ),
                "access": "typed_jquants_acquisition_rpc",
                "binding_name": "JQUANTS_ACQUISITION",
            },
        ]
    if principal == "d1_sync":
        return [
            {
                "provider": "cloudflare",
                "kind": "d1",
                "resource_ref": f"cloudflare:{environment}:d1:quant-ingest{suffix}",
                "access": "export_read",
            }
        ]
    if principal == "ops_projection":
        return [
            {
                "provider": "cloudflare",
                "kind": "d1",
                "resource_ref": (
                    f"cloudflare:{environment}:d1:quant-ops-projection{suffix}"
                ),
                "access": "append_activate",
            }
        ]
    return []


def _validate_environment_resource(
    resource: Mapping[str, Any], *, principal: str, environment: str
) -> None:
    reference = str(resource["resource_ref"])
    access = str(resource["access"])
    _reject_broad_capability(reference, field=f"{principal}/{environment}.resource_ref")
    _reject_broad_capability(access, field=f"{principal}/{environment}.access")
    expected_prefix = f"cloudflare:{environment}:"
    if not reference.startswith(expected_prefix):
        raise ValueError(
            f"{principal}/{environment}: Cloudflare resource crosses environment: "
            f"{reference}"
        )
    resource_name = reference.rsplit(":", 1)[-1]
    if environment == "staging" and not resource_name.endswith("-staging"):
        raise ValueError(
            f"{principal}/staging: production resource is forbidden: {reference}"
        )
    if environment == "production" and resource_name.endswith("-staging"):
        raise ValueError(
            f"{principal}/production: staging resource is forbidden: {reference}"
        )


def _validate_local_deployment(
    deployment: Mapping[str, Any], *, principal: str, environment: str
) -> None:
    expected_identity = f"qp-{environment}-{principal.replace('_', '-')}-authority"
    expected_user = f"qp_{environment}_{principal}_authority"
    expected_store_prefix = f"local-protected://{environment}/{principal}/"
    expected_socket = f"/var/run/quant-platform/{environment}/{principal}.sock"
    if deployment.get("service_identity") != expected_identity:
        raise ValueError(f"{principal}/{environment}: service identity drift")
    if deployment.get("service_user") != expected_user:
        raise ValueError(f"{principal}/{environment}: service user drift")
    if principal == "trader":
        expected_key_ref = (
            f"webauthn://{environment}/trader/platform-or-hardware-credential"
        )
        if deployment.get("key_backend") != "webauthn_platform_or_hardware":
            raise ValueError(f"trader/{environment}: file-backed Trader key is forbidden")
        if deployment.get("approval_backend") != "human_presence_required":
            raise ValueError(f"trader/{environment}: human presence is required")
        if deployment.get("private_key_ref") != expected_key_ref:
            raise ValueError(f"trader/{environment}: WebAuthn credential drift")
    else:
        expected_key_prefix = f"local-protected://{environment}/{principal}/"
        if deployment.get("key_backend") != "protected_local_key":
            raise ValueError(f"{principal}/{environment}: key backend drift")
        if deployment.get("approval_backend") != "service_policy":
            raise ValueError(f"{principal}/{environment}: approval backend drift")
        if not str(deployment.get("private_key_ref", "")).startswith(
            expected_key_prefix
        ):
            raise ValueError(f"{principal}/{environment}: private key ownership drift")
    if not str(deployment.get("event_store_ref", "")).startswith(
        expected_store_prefix
    ):
        raise ValueError(f"{principal}/{environment}: event store ownership drift")
    if deployment.get("socket_path") != expected_socket:
        raise ValueError(f"{principal}/{environment}: socket ownership drift")


def _validate_receipt_deployment(
    deployment: Mapping[str, Any], *, environment: str
) -> None:
    suffix = "-staging" if environment == "staging" else ""
    if deployment.get("worker_ref") != "platform/workers/receipt-evidence-authority":
        raise ValueError(f"receipt/{environment}: Worker package drift")
    if deployment.get("worker_name") != (
        f"quant-platform-receipt-evidence-authority{suffix}"
    ):
        raise ValueError(f"receipt/{environment}: Worker identity drift")
    expected_worker_name = f"quant-platform-receipt-evidence-authority{suffix}"
    incoming = deployment.get("incoming_service_binding")
    expected_incoming = {
        "binding_name": "RECEIPT_EVIDENCE_AUTHORITY",
        "caller_id": "governed_ingestion",
        "caller_worker_ref": "platform/workers/ingestion-premium",
        "target_worker_name": expected_worker_name,
    }
    if incoming != expected_incoming:
        raise ValueError(f"receipt/{environment}: incoming Service Binding drift")
    if deployment.get("durable_object_binding") != "RECEIPT_EVIDENCE_AUTHORITY_DO":
        raise ValueError(f"receipt/{environment}: Durable Object binding drift")
    if deployment.get("durable_object_class") != "ReceiptEvidenceAuthority":
        raise ValueError(f"receipt/{environment}: Durable Object class drift")
    if deployment.get("key_backend") != (
        "durable_object_aes_gcm_wrapped_webcrypto_non_extractable"
    ):
        raise ValueError(f"receipt/{environment}: extractable Receipt key is forbidden")
    if deployment.get("approval_backend") != "service_policy":
        raise ValueError(f"receipt/{environment}: approval backend drift")
    if (
        deployment.get("workers_dev") is not False
        or deployment.get("preview_urls") is not False
        or deployment.get("routes") != []
        or deployment.get("public_fetch_behavior") != "NOT_FOUND_404"
        or deployment.get("secret_names") != ["RECEIPT_KEY_WRAP_KEY"]
    ):
        raise ValueError(f"receipt/{environment}: private wrapped-key Worker surface drift")
    key_prefix = f"durable-object-sqlite-wrapped://{environment}/receipt/"
    store_prefix = f"durable-object-sqlite://{environment}/receipt/"
    if not str(deployment.get("private_key_ref", "")).startswith(key_prefix):
        raise ValueError(f"receipt/{environment}: WebCrypto key custody drift")
    if not str(deployment.get("event_store_ref", "")).startswith(store_prefix):
        raise ValueError(f"receipt/{environment}: SQLite DO event store drift")


def _validate_semantics(manifest: dict[str, Any]) -> None:
    principals = manifest["principals"]
    if tuple(principals) != PRINCIPALS:
        raise ValueError("authority principal order or membership drift")
    residuals = manifest["residual_risks"]
    if tuple(residuals) != (EXPECTED_RESIDUAL_RISK,):
        raise ValueError("authority residual-risk inventory drift")
    residual = residuals[EXPECTED_RESIDUAL_RISK]
    if (
        residual.get("affected_principal") != "receipt"
        or residual.get("status") != "OPEN"
        or residual.get("scope") != "ACCOUNT_WIDE"
    ):
        raise ValueError("Cloudflare Scripts Write residual may not be closed by manifest")

    unique_claims: dict[str, dict[str, tuple[str, str]]] = {
        "service identity": {},
        "service user": {},
        "private key": {},
        "event store": {},
        "socket": {},
    }
    key_owners: dict[str, str] = {}

    for principal, document in principals.items():
        if document["principal_id"] != principal:
            raise ValueError(f"{principal}: embedded principal id drift")
        if document["runtime"] != EXPECTED_RUNTIME[principal]:
            raise ValueError(f"{principal}: authority runtime drift")
        if tuple(document["allowed_callers"]) != ALLOWED_CALLERS[principal]:
            raise ValueError(f"{principal}: unauthorized peer in allowed callers")
        if document["method_acl"] != EXPECTED_METHOD_ACL[principal]:
            raise ValueError(f"{principal}: method ACL surface drift")
        derived_callers = tuple(
            dict.fromkeys(row["authenticated_caller"] for row in document["method_acl"])
        )
        if derived_callers != ALLOWED_CALLERS[principal]:
            raise ValueError(f"{principal}: allowed callers are not derived from method ACL")
        if document["pending_dependencies"] != EXPECTED_PENDING_DEPENDENCIES[principal]:
            raise ValueError(f"{principal}: pending dependency inventory drift")
        if tuple(document["provides"]) != EXPECTED_PROVIDES[principal]:
            raise ValueError(f"{principal}: provided operation surface drift")
        if tuple(document["capabilities"]) != EXPECTED_CAPABILITIES[principal]:
            raise ValueError(f"{principal}: positive capability surface drift")
        if tuple(document["forbidden_capabilities"]) != FORBIDDEN_CAPABILITIES[
            principal
        ]:
            raise ValueError(f"{principal}: forbidden capability surface drift")
        for field in ("provides", "capabilities", "allowed_callers"):
            for value in document[field]:
                _reject_broad_capability(str(value), field=f"{principal}.{field}")

        for environment, deployment in document["deployments"].items():
            if deployment["mode"] != "PENDING_NO_KEY":
                raise ValueError(f"{principal}/{environment}: authority is not PENDING")
            if deployment["private_key_state"] != "ABSENT_UNTIL_ACTIVATION":
                raise ValueError(
                    f"{principal}/{environment}: checked-in contract may not claim a key"
                )
            if principal == "receipt":
                _validate_receipt_deployment(deployment, environment=environment)
                identity = str(deployment["worker_name"])
            else:
                _validate_local_deployment(
                    deployment, principal=principal, environment=environment
                )
                identity = str(deployment["service_identity"])
                _claim_unique(
                    unique_claims["service user"],
                    value=str(deployment["service_user"]),
                    principal=principal,
                    environment=environment,
                    field="service user",
                )
                _claim_unique(
                    unique_claims["socket"],
                    value=str(deployment["socket_path"]),
                    principal=principal,
                    environment=environment,
                    field="socket",
                )

            _claim_unique(
                unique_claims["service identity"],
                value=identity,
                principal=principal,
                environment=environment,
                field="service identity",
            )
            key_ref = str(deployment["private_key_ref"])
            _claim_unique(
                unique_claims["private key"],
                value=key_ref,
                principal=principal,
                environment=environment,
                field="private key",
            )
            key_owners[key_ref] = principal
            _claim_unique(
                unique_claims["event store"],
                value=str(deployment["event_store_ref"]),
                principal=principal,
                environment=environment,
                field="event store",
            )
            expected_readable_refs = (
                [] if principal in {"receipt", "trader"} else [key_ref]
            )
            if deployment["readable_private_key_refs"] != expected_readable_refs:
                raise ValueError(
                    f"{principal}/{environment}: private-key readability violates "
                    "the key backend contract"
                )
            for resource in deployment["cloudflare_resources"]:
                _validate_environment_resource(
                    resource, principal=principal, environment=environment
                )
            expected_resources = _expected_cloudflare_resources(
                principal=principal, environment=environment
            )
            if deployment["cloudflare_resources"] != expected_resources:
                raise ValueError(
                    f"{principal}/{environment}: Cloudflare capability graph drift"
                )

    for principal, document in principals.items():
        for environment, deployment in document["deployments"].items():
            for key_ref in deployment["readable_private_key_refs"]:
                owner = key_owners.get(key_ref)
                if owner is not None and owner != principal:
                    raise ValueError(
                        f"{principal}/{environment}: signer-to-signer private-key "
                        f"access to {owner} is forbidden"
                    )


def validate_manifest(manifest: dict[str, Any]) -> None:
    _require_exact_json(manifest)
    schema = _load_strict_json(MANIFEST_SCHEMA)
    _schema_validate(manifest, schema)

    expected_schema_digest = canonical_digest(schema)
    if manifest["schema_digest"] != expected_schema_digest:
        raise ValueError("authority principal manifest schema digest drift")
    for name, path in PROTOCOL_SCHEMAS.items():
        expected = canonical_digest(_load_strict_json(path))
        if manifest["protocol_schema_digests"][name] != expected:
            raise ValueError(f"authority protocol schema digest drift: {name}")
    if set(manifest["protocol_schema_digests"]) != set(PROTOCOL_SCHEMAS):
        raise ValueError("authority protocol schema membership drift")
    parallel = manifest["parallel_protocol_schema_digests"]
    if set(parallel) != set(PARALLEL_PROTOCOL_SCHEMAS):
        raise ValueError("parallel authority protocol schema membership drift")
    for name, path in PARALLEL_PROTOCOL_SCHEMAS.items():
        if parallel[name] != canonical_digest(_load_strict_json(path)):
            raise ValueError(f"parallel authority protocol schema digest drift: {name}")

    _validate_semantics(manifest)
    body_digest = manifest_body_digest(manifest)
    if manifest["manifest_digest"] != body_digest:
        raise ValueError("authority principal manifest self-digest drift")
    if body_digest != PINNED_MANIFEST_DIGEST:
        raise ValueError("authority principal manifest differs from the code-pinned contract")


def load_and_validate_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    manifest = _load_strict_json(path)
    validate_manifest(manifest)
    return manifest


def main() -> int:
    try:
        manifest = load_and_validate_manifest()
    except (RuntimeError, ValueError) as exc:
        print(f"Authority principal manifest: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"Authority principal manifest: ok ({manifest['manifest_digest']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
