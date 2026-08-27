from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import uuid

import pytest

from scripts import finding_ledger_gate


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_release_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_release_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

SHA = "a" * 40
OBSERVED_AT = "2026-08-25T07:00:00Z"


def _closed_test_ledger() -> finding_ledger_gate.FindingLedgerSnapshot:
    document = json.loads(
        (ROOT / "docs" / "phase633_finding_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    for finding in document["findings"]:
        if finding["severity"] == "P0":
            finding["status"] = "FIXED"
    raw = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    snapshot = finding_ledger_gate._evaluate_ledger_bytes(raw)
    assert snapshot.release_allowed
    return snapshot


TEST_LEDGER = _closed_test_ledger()


@pytest.fixture(autouse=True)
def _use_closed_test_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release,
        "require_pinned_finding_ledger_gate",
        lambda: TEST_LEDGER,
    )


def provenance(collector: str, label: str) -> dict[str, object]:
    return {
        "schema_version": release.OBSERVATION_SCHEMA_VERSION,
        "collector": collector,
        "evidence_id": str(uuid.uuid5(uuid.NAMESPACE_URL, label)),
        "observed_at": OBSERVED_AT,
        "source_sha": SHA,
        "response_digest": "sha256:" + "e" * 64,
    }


def payload() -> dict[str, object]:
    workers = tuple(sorted(release._ACTIVE_WORKERS))
    version = "11111111-1111-4111-8111-111111111111"
    binding_digest = "sha256:" + "c" * 64
    restore = {
        "evidence_id": "33333333-3333-4333-8333-333333333333",
        "verified_at": OBSERVED_AT,
        "source_sha": SHA,
        "engine": "sqlite3-cli+integrity_check",
        "integrity_check": "ok",
        "canonical_minimum_schema": "PASS",
        "required_nonempty_tables": "PASS",
        "schema_digest": "sha256:" + "f" * 64,
        "table_count": 25,
    }
    database = {
        "environment": "production",
        "name": release._GOVERNED_DATABASE_NAME,
        "id": release._GOVERNED_DATABASE_ID,
        "schema_profile": release._BACKUP_SCHEMA_PROFILE,
    }
    backup_header = {
        "format": release._BACKUP_FORMAT,
        "cipher": "AES-256-GCM",
        "key_id": "sha256:" + "1" * 64,
        "nonce": "AAAAAAAAAAAAAAAA",
        "database": database,
        "exported_at": "2026-08-25T06:00:00Z",
        "restore": restore,
        "plaintext_bytes": 100,
        "plaintext_digest": "sha256:" + "b" * 64,
    }
    deployments = {
        worker: {
            environment: {
                "version_id": version,
                "source_sha": SHA,
                "effective_bindings_digest": binding_digest,
                "provenance": provenance(
                    "cloudflare-workers-versions-api/v1",
                    f"deployment:{worker}:{environment}",
                ),
            }
            for environment in ("staging", "production")
        }
        for worker in workers
    }
    return {
        "source_sha": SHA,
        "origin_main_sha": SHA,
        "required_check": {
            "context": "Workers Builds: quant-platform-ci-aggregate-staging",
            "app_id": 85455,
            "app_slug": "cloudflare-workers-and-pages",
            "strict": True,
            "conclusion": "success",
            "head_sha": SHA,
            "check_run_id": 12345,
            "details_url": "https://github.com/ddnne/quant-platform/runs/12345",
            "provenance": provenance(
                "github-check-runs-api/v1", "required-check"
            ),
        },
        "cloudflare_build": {
            "build_id": "22222222-2222-4222-8222-222222222222",
            "conclusion": "success",
            "source_sha": SHA,
            "provenance": provenance(
                "cloudflare-workers-builds-api/v1", "cloudflare-build"
            ),
        },
        "merged_prs": [42],
        "open_prs": [],
        "finding_ledger": TEST_LEDGER.evidence_payload(),
        "deployments": deployments,
        "migrations": {
            environment: {
                target: {
                    "status": "APPLIED",
                    "pending": 0,
                    "canonical_manifest_digest": release._CANONICAL_MIGRATION_MANIFEST_DIGEST,
                    "applied_migrations": list(release._CANONICAL_MIGRATIONS[target]),
                    "provenance": provenance(
                        "wrangler-d1-migrations-list/v1",
                        f"migration:{environment}:{target}",
                    ),
                }
                for target in sorted(release._MIGRATION_TARGETS)
            }
            for environment in ("staging", "production")
        },
        "smoke": {
            environment: {
                worker: {
                    "result": "PASS",
                    "source_sha": SHA,
                    "deployment_version_id": version,
                    **(
                        {
                            "endpoint": "/health/ready",
                            "http_status": 200,
                            "product_ready": True,
                            "cutover": "V3_ACTIVE",
                            "response_digest": "sha256:" + "e" * 64,
                        }
                        if worker == "quant-platform-ingestion-jsda"
                        else {}
                    ),
                    "provenance": provenance(
                        "release-smoke-runner/v1",
                        f"smoke:{environment}:{worker}",
                    ),
                }
                for worker in workers
            }
            for environment in ("staging", "production")
        },
        "quant_mcp": {
            "tool_count": 17,
            "expected_tool_count": 17,
            "tools": list(release._MCP_TOOL_NAMES),
            "schema_digest": release._ACCEPTED_MCP_SCHEMA_DIGEST,
            "expected_schema_digest": release._ACCEPTED_MCP_SCHEMA_DIGEST,
            "deployment_version_id": version,
            "projection": "STALE",
            "projection_generation": "projgen-example",
            "refresh_success": False,
            "b0": "UNKNOWN",
            "b4": "UNKNOWN",
            "ready": "UNKNOWN",
            "source_cursor": 2891143,
            "export_cursor": None,
            "applied_cursor": None,
            "provenance": provenance("quant-mcp-tools-list/v1", "quant-mcp"),
        },
        "backup": {
            "format": release._BACKUP_FORMAT,
            "cipher": "AES-256-GCM",
            "encrypted": True,
            "verified": True,
            "plaintext_bytes": 100,
            "plaintext_digest": "sha256:" + "b" * 64,
            "ciphertext_bytes": 800,
            "ciphertext_digest": "sha256:" + "d" * 64,
            "authenticated_metadata_digest": release._digest_bytes(
                release.canonical_bytes(backup_header)
            ),
            "database": database,
            "exported_at": "2026-08-25T06:00:00Z",
            "restore": restore,
            "key_id": "sha256:" + "1" * 64,
            "nonce": "AAAAAAAAAAAAAAAA",
        },
        "controlled_pilot": {
            "decision": "NO-GO",
            "executed": False,
            "reason_code": "TRUSTED_HISTORICAL_REPROOF_UNAVAILABLE",
            "reason": "The exact-four historical dependency closure lacks trusted reproof.",
            "blocker_evidence_digest": "sha256:" + "9" * 64,
            "automatic_promotion": False,
            "provenance": provenance(
                "controlled-pilot-gate/v1", "controlled-pilot"
            ),
        },
        "mass_research": "NO-GO",
        "rollback_status": "NOT_REQUIRED",
    }


def proven_go(facts: dict[str, object]) -> None:
    digest_fields = (
        "experiment_plan_digest",
        "strategy_spec_set_digest",
        "feature_ref_set_digest",
        "profile_digest",
        "closure_digest",
        "governed_membership_digest",
        "coverage_proof_digest",
        "raw_receipt_proof_digest",
        "b0_b4_result_digest",
        "cursor_chain_digest",
        "ready_manifest_digest",
        "ready_attestation_digest",
        "trader_authorization_digest",
        "immutable_snapshot_digest",
        "paper_artifact_digest",
        "risk_artifact_digest",
        "selection_artifact_digest",
        "knowledge_artifact_digest",
    )
    facts["controlled_pilot"] = {
        "decision": "GO",
        "executed": True,
        "automatic_promotion": False,
        "ready_snapshot_id": "ready-exact-four-immutable-001",
        "plan_count": 4,
        "generations": 1,
        **{field: "sha256:" + f"{index:x}" * 64 for index, field in enumerate(digest_fields, 1)},
        "provenance": provenance(
            "controlled-pilot-gate/v1", "controlled-pilot-go"
        ),
    }
    # Normalize the simple generated values to exactly 64 hex characters.
    for field in digest_fields:
        facts["controlled_pilot"][field] = (  # type: ignore[index]
            "sha256:"
            + facts["controlled_pilot"][field].removeprefix("sha256:")[:64]  # type: ignore[index,union-attr]
        )
    mcp = facts["quant_mcp"]
    mcp.update(  # type: ignore[union-attr]
        {
            "projection": "FRESH",
            "refresh_success": True,
            "b0": "PASS",
            "b4": "PASS",
            "ready": "READY",
            "source_cursor": 3000000,
            "export_cursor": 3000000,
            "applied_cursor": 3000000,
        }
    )


def validate_untrusted_candidate(facts: dict[str, object]) -> None:
    release._validate_untrusted_candidate_schema_for_tests(facts)


def test_candidate_schema_is_deterministic_but_cannot_publish(tmp_path: Path) -> None:
    facts = payload()
    output = tmp_path / "release"
    validate_untrusted_candidate(facts)
    assert release.payload_digest(facts) == release.payload_digest(facts)
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="caller-supplied JSON is schema-only and untrusted",
    ):
        release.build_envelope(facts)
    with pytest.raises(release.ReleaseObservationAuthorityUnavailable):
        release.write_envelope(facts, output)
    assert not output.exists()


def test_cli_rejects_before_reading_any_caller_document(tmp_path: Path) -> None:
    missing = tmp_path / "caller-observations.json"
    output = tmp_path / "release"
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="signed release-observation authority",
    ):
        release.main([str(missing), "--output-dir", str(output)])
    assert not output.exists()


def test_public_builder_never_treats_even_invalid_json_as_evidence() -> None:
    with pytest.raises(release.ReleaseObservationAuthorityUnavailable):
        release.build_envelope({"collector": "caller-self-claim"})


def test_writer_guard_is_independent_of_a_replaced_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "release"
    monkeypatch.setattr(
        release,
        "build_envelope",
        lambda payload: {
            "schema_version": release.SCHEMA_VERSION,
            "evidence_digest": release.payload_digest(payload),
            "payload": dict(payload),
        },
    )
    with pytest.raises(release.ReleaseObservationAuthorityUnavailable):
        release.write_envelope({"collector": "caller-self-claim"}, output)
    assert not output.exists()


def test_pending_authority_contract_matches_missing_jsda_collector_transport() -> None:
    contract = json.loads(
        (ROOT / "specs/cloudflare/release_observation_authority.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["authority_status"] == "PENDING"
    assert contract["active_key_count"] == 0
    assert contract["publication_authorized"] is False
    assert contract["caller_supplied_json_trusted"] is False
    jsda = contract["collectors"]["jsda_readiness"]
    assert jsda == {
        "target_worker": "quant-platform-ingestion-jsda",
        "endpoint": "/health/ready",
        "transport": "private-service-binding",
        "binding_name": None,
        "transport_implemented": False,
        "status": "HOLD",
    }
    bindings = json.loads(
        (ROOT / "specs/cloudflare/active_worker_bindings.json").read_text(
            encoding="utf-8"
        )
    )["workers"]["ingestion-jsda"]
    for environment in ("base", "staging", "production"):
        assert bindings[environment]["services"] == []
        assert bindings[environment]["workers_dev"] is False
        assert bindings[environment]["preview_urls"] is False
        assert bindings[environment]["routes"] == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_sha", "short", "full lowercase Git SHA"),
        ("mass_research", "GO", "Mass Research NO-GO"),
        ("controlled_pilot", "MAYBE", "must be an object"),
    ],
)
def test_release_evidence_rejects_policy_drift(
    field: str, value: object, message: str
) -> None:
    facts = payload()
    facts[field] = value
    with pytest.raises(ValueError, match=message):
        validate_untrusted_candidate(facts)


def test_release_evidence_requires_exact_pinned_finding_ledger() -> None:
    missing = payload()
    del missing["finding_ledger"]
    with pytest.raises(ValueError, match="field membership drift"):
        validate_untrusted_candidate(missing)

    wrong_digest = payload()
    wrong_digest["finding_ledger"]["ledger_digest"] = "sha256:" + "0" * 64  # type: ignore[index]
    with pytest.raises(ValueError, match="pinned ledger digest"):
        validate_untrusted_candidate(wrong_digest)

    invented_open = payload()
    invented_open["finding_ledger"]["open_p0_ids"] = ["A2"]  # type: ignore[index]
    with pytest.raises(ValueError, match="open P0 ids"):
        validate_untrusted_candidate(invented_open)

    invented_field = payload()
    invented_field["finding_ledger"]["reviewed"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="finding_ledger schema drift"):
        validate_untrusted_candidate(invented_field)


def test_release_evidence_rejects_secrets_provider_tokens_and_local_paths() -> None:
    secret = payload()
    secret["quant_mcp"]["unexpected_api_token"] = "do-not-publish"  # type: ignore[index]
    with pytest.raises(ValueError, match="secret-shaped key"):
        validate_untrusted_candidate(secret)

    provider_tokens = (
        "gho_abcdefghijklmn" + "opqrstuvwxyz123456",
        "ghp_abcdefghijklmn" + "opqrstuvwxyz123456",
        "github_pat_abcdefghij" + "klmnopqrstuvwxyz123456",
        "sk-proj-abcdefghijkl" + "mnopqrstuvwxyz123456",
    )
    for provider_token in provider_tokens:
        secret = payload()
        secret["controlled_pilot"]["reason"] = provider_token  # type: ignore[index]
        with pytest.raises(ValueError, match="secret-shaped material"):
            validate_untrusted_candidate(secret)

    for absolute in (
        "/tmp/private/result.json",
        "C:\\temp\\result.json",
        "~/result.json",
        "file:///tmp/result.json",
    ):
        local = payload()
        local["controlled_pilot"]["reason"] = absolute  # type: ignore[index]
        with pytest.raises(ValueError, match="local absolute path"):
            validate_untrusted_candidate(local)


def test_nested_schemas_are_closed_and_provenance_is_source_bound() -> None:
    facts = payload()
    facts["required_check"]["note"] = "self reported"  # type: ignore[index]
    with pytest.raises(ValueError, match="required_check schema drift"):
        validate_untrusted_candidate(facts)

    facts = payload()
    del facts["smoke"]["production"][  # type: ignore[index]
        "quant-platform-ingestion-jsda"
    ]["provenance"]["observed_at"]
    with pytest.raises(ValueError, match="provenance schema drift"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["cloudflare_build"]["provenance"]["source_sha"] = "f" * 40  # type: ignore[index]
    with pytest.raises(ValueError, match="collector and source SHA"):
        validate_untrusted_candidate(facts)


def test_release_evidence_requires_check_build_deploy_and_smoke_identity() -> None:
    facts = payload()
    facts["required_check"]["head_sha"] = "f" * 40  # type: ignore[index]
    with pytest.raises(ValueError, match="authoritative Cloudflare App"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["deployments"].pop("quant-platform-ingestion-jsda")  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="exactly the active Worker inventory"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["smoke"]["production"]["quant-platform-ingestion-jsda"][  # type: ignore[index]
        "deployment_version_id"
    ] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(ValueError, match="deployed source/version"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["smoke"]["production"]["quant-platform-ingestion-jsda"][  # type: ignore[index]
        "source_sha"
    ] = "f" * 40
    with pytest.raises(ValueError, match="deployed source/version"):
        validate_untrusted_candidate(facts)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpoint", "/health"),
        ("http_status", 503),
        ("product_ready", False),
        ("cutover", "PENDING"),
        ("response_digest", "sha256:" + "d" * 64),
    ],
)
def test_jsda_smoke_requires_ready_endpoint_and_bound_ready_response(
    field: str, value: object
) -> None:
    facts = payload()
    jsda = facts["smoke"]["production"]["quant-platform-ingestion-jsda"]  # type: ignore[index]
    jsda[field] = value
    with pytest.raises(ValueError, match="must prove HTTP 200 product readiness"):
        validate_untrusted_candidate(facts)


def test_jsda_smoke_rejects_generic_health_pass_schema() -> None:
    facts = payload()
    jsda = facts["smoke"]["production"]["quant-platform-ingestion-jsda"]  # type: ignore[index]
    for field in (
        "endpoint",
        "http_status",
        "product_ready",
        "cutover",
        "response_digest",
    ):
        del jsda[field]
    with pytest.raises(ValueError, match="schema drift"):
        validate_untrusted_candidate(facts)


def test_fake_or_incomplete_migration_evidence_is_rejected() -> None:
    facts = payload()
    facts["migrations"]["production"]["invented-db"] = {  # type: ignore[index]
        "status": "APPLIED"
    }
    with pytest.raises(ValueError, match="canonical targets"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["migrations"]["production"]["quant-ingest"]["pending"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="unapplied migrations"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["migrations"]["production"]["quant-ingest"][  # type: ignore[index]
        "applied_migrations"
    ] = []
    with pytest.raises(ValueError, match="canonical migration sequence"):
        validate_untrusted_candidate(facts)


def test_exact_mcp_names_schema_and_deployment_are_required() -> None:
    facts = payload()
    facts["quant_mcp"]["tools"][0] = "invented_tool"  # type: ignore[index]
    with pytest.raises(ValueError, match="exact 17 tools"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["quant_mcp"]["schema_digest"] = "sha256:" + "1" * 64  # type: ignore[index]
    with pytest.raises(ValueError, match="accepted schema digest"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["quant_mcp"]["deployment_version_id"] = (  # type: ignore[index]
        "99999999-9999-4999-8999-999999999999"
    )
    with pytest.raises(ValueError, match="accepted Ops MCP deployment"):
        validate_untrusted_candidate(facts)


def test_release_evidence_rejects_empty_unverified_or_unbound_backup() -> None:
    facts = payload()
    facts["backup"]["plaintext_bytes"] = 0  # type: ignore[index]
    with pytest.raises(ValueError, match="non-empty verified"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["backup"]["verified"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="non-empty verified"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["backup"]["database"]["id"] = "11111111-1111-4111-8111-111111111111"  # type: ignore[index]
    with pytest.raises(ValueError, match="governed production D1"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["backup"]["authenticated_metadata_digest"] = "sha256:" + "0" * 64  # type: ignore[index]
    with pytest.raises(ValueError, match="authenticated metadata digest"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["backup"]["note"] = "invented-field"  # type: ignore[index]
    with pytest.raises(ValueError, match="schema drift"):
        validate_untrusted_candidate(facts)


def test_release_evidence_rejects_unproven_go_and_generic_no_go() -> None:
    facts = payload()
    facts["controlled_pilot"] = {
        "decision": "GO",
        "executed": True,
        "automatic_promotion": False,
        "provenance": provenance(
            "controlled-pilot-gate/v1", "unproven-controlled-pilot"
        ),
    }
    with pytest.raises(ValueError, match="schema drift"):
        validate_untrusted_candidate(facts)

    facts = payload()
    facts["controlled_pilot"]["reason"] = "not ready"  # type: ignore[index]
    with pytest.raises(ValueError, match="specific evidenced blocker"):
        validate_untrusted_candidate(facts)


def test_complete_exact_four_go_chain_is_accepted_but_cannot_promote() -> None:
    facts = payload()
    proven_go(facts)
    validate_untrusted_candidate(facts)

    facts["controlled_pilot"]["automatic_promotion"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="without promotion"):
        validate_untrusted_candidate(facts)
