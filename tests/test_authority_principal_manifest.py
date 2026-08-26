"""Behavioral validation for the seven-principal authority contract."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "authority_principal_manifest.py"
SPEC = importlib.util.spec_from_file_location("authority_principal_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
manifest_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest_module)


def _manifest() -> dict[str, object]:
    return json.loads(manifest_module.MANIFEST.read_text(encoding="utf-8"))


def _schema(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / "specs" / "authorities" / name).read_text(encoding="utf-8")
    )


def _validate_schema(name: str, document: dict[str, object]) -> None:
    Draft202012Validator(
        _schema(name), format_checker=FormatChecker()
    ).validate(document)


def _digest(character: str = "a") -> str:
    return "sha256:" + character * 64


def _handoff() -> dict[str, object]:
    tables = {
        name: 0
        for name in (
            "jquants_market_calendar",
            "jquants_listed_info",
            "jquants_daily_bars",
            "jquants_records",
            "jquants_market_calendar_revisions",
            "jquants_listed_info_revisions",
            "jquants_daily_bars_revisions",
            "jquants_records_revisions",
            "ingestion_run_log",
            "ingestion_validation",
            "ingestion_watermarks",
            "raw_retention_manifests",
            "coverage_segments",
            "collection_receipts",
        )
    }
    return {
        "schema_version": "authenticated-applied-mirror-handoff/v2",
        "authority_domain": "quant-platform/d1-sync/frozen-mirror/v2",
        "request_id": "00000000-0000-4000-8000-000000000001",
        "request_digest": _digest("0"),
        "environment": "production",
        "authenticated_caller": "ops_projection",
        "target_operation": "frozen_mirror:readonly_handoff",
        "purpose": "ops_projection",
        "source_d1_name": "quant-ingest",
        "source_d1_id": "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
        "signed_audit_document_json": "{}",
        "signed_audit_document_digest": _digest("1"),
        "signed_audit_issuer_key_id": "d1-sync-test-v1",
        "source_change_seq": 0,
        "applied_change_seq": 0,
        "descriptor_open_mode": "O_RDONLY",
        "descriptor_identity": {
            "device": 0,
            "inode": 1,
            "size": 4096,
            "sha256": _digest("2"),
        },
        "mirror_identity_digest": _digest("3"),
        "source_content_digest": _digest("4"),
        "local_content_digest": _digest("4"),
        "source_schema_digest": _digest("5"),
        "local_schema_digest": _digest("5"),
        "table_counts": tables,
        "journal_mode": "delete",
        "opened_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
        "fd_count": 1,
        "handoff_digest": _digest("7"),
    }


def _event(request_id: str) -> dict[str, object]:
    return {
        "schema_version": "authority-event/v2",
        "environment": "production",
        "authority_id": "receipt",
        "sequence": 1,
        "event_id": "00000000-0000-4000-8000-000000000002",
        "idempotency_key": _digest("5"),
        "request_id": request_id,
        "event_type": "PREPARED",
        "subject_id": "segment-1",
        "prior_event_digest": None,
        "payload_schema": "receipt-event/v1",
        "payload_digest": _digest("6"),
        "payload_json": "{}",
        "observed_at": "2026-08-26T00:00:00Z",
        "event_digest": _digest("7"),
    }


def test_checked_in_manifest_and_schema_digests_are_valid() -> None:
    manifest = manifest_module.load_and_validate_manifest()
    assert tuple(manifest["principals"]) == manifest_module.PRINCIPALS
    assert manifest["activation_status"] == "PENDING"
    assert manifest["manifest_digest"] == manifest_module.PINNED_MANIFEST_DIGEST


def test_runtime_and_key_backend_discriminants_are_frozen() -> None:
    principals = _manifest()["principals"]
    assert principals["receipt"]["runtime"] == "cloudflare_worker"
    assert (
        principals["receipt"]["deployments"]["production"]["key_backend"]
        == "durable_object_webcrypto_non_extractable"
    )
    for principal in manifest_module.LOCAL_OS_PRINCIPALS - {"trader"}:
        assert principals[principal]["runtime"] == "local_os_service"
        assert (
            principals[principal]["deployments"]["production"]["key_backend"]
            == "protected_local_key"
        )
    trader = principals["trader"]["deployments"]["production"]
    assert trader["key_backend"] == "webauthn_platform_or_hardware"
    assert trader["approval_backend"] == "human_presence_required"


def test_receipt_worker_resource_graph_and_private_surface_are_exact() -> None:
    receipt = _manifest()["principals"]["receipt"]
    deployment = receipt["deployments"]["staging"]
    assert deployment["workers_dev"] is False
    assert deployment["preview_urls"] is False
    assert deployment["routes"] == []
    assert deployment["secret_names"] == []
    assert deployment["public_fetch_behavior"] == "NOT_FOUND_404"
    assert deployment["incoming_service_binding"]["binding_name"] == (
        "RECEIPT_EVIDENCE_AUTHORITY"
    )
    resources = deployment["cloudflare_resources"]
    assert any(
        row.get("binding_name") == "JQUANTS_ACQUISITION" for row in resources
    )
    assert any("quant-structured-staging" in row["resource_ref"] for row in resources)
    assert not any(
        "receipt-evidence-authority" in row["resource_ref"]
        for row in resources
        if row["kind"] == "service_binding"
    )
    assert receipt["capabilities"][:3] == [
        "jquants_acquisition:fetch_governed_page",
        "raw_immutable:create_only",
        "structured_immutable:create_only",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workers_dev", True),
        ("preview_urls", True),
        ("routes", [{"pattern": "example.invalid"}]),
        ("secret_names", ["PRIVATE_SIGNING_KEY"]),
        ("public_fetch_behavior", "HEALTH_200"),
    ],
)
def test_receipt_public_or_secret_surface_fails_closed(
    field: str, value: object
) -> None:
    drifted = _manifest()
    drifted["principals"]["receipt"]["deployments"]["staging"][field] = value
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)


def test_generic_ready_trader_and_execution_operations_are_absent() -> None:
    principals = _manifest()["principals"]
    assert principals["ready"]["service_entrypoint"] == (
        "ready.publish_profile_plan_bound"
    )
    assert principals["trader"]["service_entrypoint"] == (
        "trader.authorize_exact_four_batch_human_present"
    )
    assert principals["controlled_execution"]["service_entrypoint"] == (
        "controlled_execution.execute_exact_four_one_shot"
    )


@pytest.mark.parametrize("operation", ["missing", "extra"])
def test_missing_or_extra_principal_fails_closed(operation: str) -> None:
    drifted = _manifest()
    if operation == "missing":
        del drifted["principals"]["ready"]
    else:
        drifted["principals"]["rogue"] = copy.deepcopy(
            drifted["principals"]["ready"]
        )
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)


@pytest.mark.parametrize(
    ("field", "source", "target"),
    [
        ("service_identity", "d1_sync", "ops_projection"),
        ("service_user", "d1_sync", "ops_projection"),
        ("private_key_ref", "d1_sync", "ops_projection"),
        ("event_store_ref", "d1_sync", "ops_projection"),
        ("socket_path", "d1_sync", "ops_projection"),
    ],
)
def test_local_identity_key_store_and_socket_may_not_be_shared(
    field: str, source: str, target: str
) -> None:
    drifted = _manifest()
    source_value = drifted["principals"][source]["deployments"]["staging"][field]
    drifted["principals"][target]["deployments"]["staging"][field] = source_value
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)


def test_wildcard_or_broad_capability_fails_closed() -> None:
    drifted = _manifest()
    drifted["principals"]["ready"]["capabilities"].append(
        "cloudflare:account_admin"
    )
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)


@pytest.mark.parametrize(
    ("principal", "capability"),
    [
        ("ops_projection", "source_d1:write"),
        ("coverage_transition", "source_d1:write"),
        ("ready", "receipt_private_key:read"),
        ("controlled_execution", "external_http:request"),
    ],
)
def test_narrowly_named_privilege_escalation_fails_closed(
    principal: str, capability: str
) -> None:
    drifted = _manifest()
    drifted["principals"][principal]["capabilities"].append(capability)
    with pytest.raises(ValueError, match="positive capability surface drift"):
        manifest_module.validate_manifest(drifted)


def test_forbidden_capability_inventory_cannot_be_removed() -> None:
    drifted = _manifest()
    drifted["principals"]["controlled_execution"]["forbidden_capabilities"].pop()
    with pytest.raises(ValueError, match="forbidden capability surface drift"):
        manifest_module.validate_manifest(drifted)


def test_unauthorized_peer_fails_closed() -> None:
    drifted = _manifest()
    drifted["principals"]["ops_projection"]["allowed_callers"] = ["trader"]
    with pytest.raises(ValueError, match="unauthorized peer"):
        manifest_module.validate_manifest(drifted)


def test_method_acl_prevents_caller_operation_cartesian_product() -> None:
    drifted = _manifest()
    d1_sync = drifted["principals"]["d1_sync"]
    d1_sync["method_acl"][0]["authenticated_caller"] = "ops_projection"
    with pytest.raises(ValueError, match="method ACL surface drift"):
        manifest_module.validate_manifest(drifted)


def test_receipt_typed_acquisition_is_explicitly_pending() -> None:
    receipt = _manifest()["principals"]["receipt"]
    assert receipt["pending_dependencies"] == [
        {
            "dependency_id": "jquants_acquisition_typed_rpc",
            "status": "PENDING",
            "required_contract": (
                "WorkerEntrypoint.fetch_governed_page over JQUANTS_ACQUISITION"
            ),
            "observed_implementation": (
                "HTTP fetch with X-Ingestion-Token shared header"
            ),
            "activation_blocked": True,
        }
    ]


def test_production_resource_in_staging_fails_closed() -> None:
    drifted = _manifest()
    resource = drifted["principals"]["d1_sync"]["deployments"]["staging"][
        "cloudflare_resources"
    ][0]
    resource["resource_ref"] = "cloudflare:production:d1:quant-ingest"
    with pytest.raises(ValueError, match="crosses environment"):
        manifest_module.validate_manifest(drifted)


def test_signer_to_signer_private_key_access_fails_closed() -> None:
    drifted = _manifest()
    d1_key = drifted["principals"]["d1_sync"]["deployments"]["staging"][
        "private_key_ref"
    ]
    drifted["principals"]["ready"]["deployments"]["staging"][
        "readable_private_key_refs"
    ] = [d1_key]
    with pytest.raises(ValueError, match="private-key readability"):
        manifest_module.validate_manifest(drifted)


def test_receipt_nonextractable_key_cannot_be_declared_readable() -> None:
    drifted = _manifest()
    receipt = drifted["principals"]["receipt"]["deployments"]["staging"]
    receipt["readable_private_key_refs"] = [receipt["private_key_ref"]]
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)


def test_trader_cannot_be_downgraded_to_a_file_key() -> None:
    drifted = _manifest()
    trader = drifted["principals"]["trader"]["deployments"]["staging"]
    trader["key_backend"] = "protected_local_key"
    trader["approval_backend"] = "service_policy"
    trader["private_key_ref"] = (
        "local-protected://staging/trader/ed25519-private-key"
    )
    trader["readable_private_key_refs"] = [trader["private_key_ref"]]
    with pytest.raises(ValueError, match="file-backed Trader key"):
        manifest_module.validate_manifest(drifted)


def test_trader_human_presence_cannot_be_removed() -> None:
    drifted = _manifest()
    trader = drifted["principals"]["trader"]["deployments"]["production"]
    trader["approval_backend"] = "service_policy"
    with pytest.raises(ValueError, match="human presence"):
        manifest_module.validate_manifest(drifted)


def test_account_wide_receipt_deploy_risk_cannot_be_marked_closed() -> None:
    drifted = _manifest()
    drifted["residual_risks"][
        "cloudflare_workers_scripts_write_account_scope"
    ]["status"] = "CLOSED"
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)


def test_frozen_mirror_request_is_a_closed_transport_trigger() -> None:
    request = {
        "schema_version": "d1-frozen-mirror-request/v2",
        "request_id": "00000000-0000-4000-8000-000000000001",
        "environment": "production",
        "authenticated_caller": "ops_projection",
        "target_authority": "d1_sync",
        "target_operation": "frozen_mirror:readonly_handoff",
        "purpose": "ops_projection",
        "issued_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
        "request_digest": _digest("0"),
    }
    _validate_schema("frozen_mirror_request.schema.json", request)
    request["db_path"] = "/tmp/caller.sqlite3"
    with pytest.raises(Exception):
        _validate_schema("frozen_mirror_request.schema.json", request)

    wrong_purpose = copy.deepcopy(request)
    del wrong_purpose["db_path"]
    wrong_purpose["purpose"] = "coverage_transition"
    with pytest.raises(Exception):
        _validate_schema("frozen_mirror_request.schema.json", wrong_purpose)


def test_frozen_handoff_accepts_initial_sequence_and_exact_fourteen_tables() -> None:
    handoff = _handoff()
    _validate_schema("frozen_mirror_handoff.schema.json", handoff)
    assert handoff["source_change_seq"] == 0
    assert len(handoff["table_counts"]) == 14

    missing_table = copy.deepcopy(handoff)
    del missing_table["table_counts"]["collection_receipts"]
    with pytest.raises(Exception):
        _validate_schema("frozen_mirror_handoff.schema.json", missing_table)

    writable_handoff = copy.deepcopy(handoff)
    writable_handoff["fd_count"] = 2
    with pytest.raises(Exception):
        _validate_schema("frozen_mirror_handoff.schema.json", writable_handoff)

    staging = copy.deepcopy(handoff)
    staging["environment"] = "staging"
    with pytest.raises(Exception):
        _validate_schema("frozen_mirror_handoff.schema.json", staging)


@pytest.mark.parametrize(
    "request_id",
    [
        "00000000-0000-4000-8000-000000000001",
        "sha256:" + "8" * 64,
    ],
)
def test_authority_event_request_id_accepts_transport_or_content_identity(
    request_id: str,
) -> None:
    _validate_schema("authority_event.schema.json", _event(request_id))


def test_authority_event_is_closed() -> None:
    event = _event("sha256:" + "9" * 64)
    event["private_key_path"] = "/tmp/key.pem"
    with pytest.raises(Exception):
        _validate_schema("authority_event.schema.json", event)


def test_trader_webauthn_contract_requires_human_presence_and_environment_rp() -> None:
    challenge = {
        "schema_version": "trader-webauthn-challenge/v1",
        "environment": "production",
        "challenge_id": "00000000-0000-4000-8000-000000000003",
        "challenge_base64url": "A" * 43,
        "exact_four_authorization_digest": _digest("1"),
        "rp_id": "quant-platform.local",
        "origin": "https://quant-platform.local",
        "user_presence_required": True,
        "user_verification_required": True,
        "issued_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
        "one_use_key": _digest("2"),
        "challenge_digest": _digest("3"),
    }
    _validate_schema("trader_webauthn_challenge.schema.json", challenge)
    challenge["user_verification_required"] = False
    with pytest.raises(Exception):
        _validate_schema("trader_webauthn_challenge.schema.json", challenge)


def test_jquants_rpc_contract_exposes_no_url_token_or_headers() -> None:
    request = {
        "schema_version": "jquants-acquisition-rpc-request/v1",
        "environment": "staging",
        "operation": "fetch_governed_page",
        "dataset_id": "equities_bars_daily",
        "segment_id": "2026-08-26",
        "source_capability_digest": _digest("4"),
        "upstream_locator_ref": "registry://jquants/equities_bars_daily",
        "request_digest": _digest("5"),
    }
    _validate_schema("jquants_acquisition_rpc.schema.json", request)
    request["token"] = "must-not-cross-rpc"
    with pytest.raises(Exception):
        _validate_schema("jquants_acquisition_rpc.schema.json", request)


def test_parallel_protocol_digest_cannot_be_self_declared() -> None:
    drifted = _manifest()
    drifted["parallel_protocol_schema_digests"]["unreviewed"] = _digest("a")
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(drifted)
