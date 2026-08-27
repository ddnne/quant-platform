from __future__ import annotations

import copy
import json

import pytest

from scripts import quant_ops_mcp_live_module_acceptance as acceptance
from scripts.cloudflare_binding_manifest import build_manifest
from scripts.receipt_authority_pending_live_acceptance import (
    _expected_bindings,
    _expected_migration_tag,
    _expected_named_handlers,
)


SHA = "a" * 40
ACCOUNT = "b" * 32
VERSION = "11111111-1111-4111-8111-111111111111"
DIGEST = "sha256:" + "c" * 64


def _deployment() -> dict[str, object]:
    return {
        "id": "22222222-2222-4222-8222-222222222222",
        "versions": [{"percentage": 100, "version_id": VERSION}],
    }


def _provenance() -> dict[str, object]:
    return {
        "local_main_module": "index.js",
        "local_main_module_digest": DIGEST,
        "local_main_module_bytes": 123,
        "live_main_module": "download/index.js",
        "live_main_module_digest": DIGEST,
        "live_main_module_bytes": 123,
    }


def _version(
    worker: str = "quant-ops-mcp",
    environment: str = "production",
) -> dict[str, object]:
    surface = build_manifest()["workers"][worker][environment]
    bindings = []
    for row in _expected_bindings(surface).values():
        rendered = dict(row)
        if rendered.get("namespace_id") == "<LIVE_NAMESPACE_ID>":
            rendered["namespace_id"] = "d" * 32
        bindings.append(rendered)
    runtime = {
        "compatibility_date": surface["compatibility_date"],
        "usage_model": "standard",
    }
    if surface["compatibility_flags"]:
        runtime["compatibility_flags"] = surface["compatibility_flags"]
    migration_tag = _expected_migration_tag(surface)
    if migration_tag is not None:
        runtime["migration_tag"] = migration_tag
    handlers = ["fetch"]
    if surface["crons"]:
        handlers.append("scheduled")
    if surface["queue_consumers"]:
        handlers.append("queue")
    script = {
        "etag": "e" * 64,
        "handlers": handlers,
        "last_deployed_from": "wrangler",
    }
    named_handlers = _expected_named_handlers(surface)
    if named_handlers:
        script["named_handlers"] = named_handlers
    return {
        "id": VERSION,
        "metadata": {
            "source": "wrangler",
            "has_preview": False,
            "created_on": "2026-08-28T00:00:00Z",
        },
        "resources": {
            "bindings": bindings,
            "script": script,
            "script_runtime": runtime,
        },
    }


def _active_documents() -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    active = build_manifest()["active_workers"]
    return (
        {worker: _deployment() for worker in active},
        {worker: _version(worker) for worker in active},
    )


def test_exact_module_acceptance_binds_manifest_and_agents_dependency() -> None:
    deployments, versions = _active_documents()
    version = versions["quant-ops-mcp"]
    result = acceptance.validate_live_quant_ops_module(
        environment="production",
        source_sha=SHA,
        account_id=ACCOUNT,
        deployments_before=deployments,
        deployments_after=copy.deepcopy(deployments),
        versions_before=versions,
        versions_after=copy.deepcopy(versions),
        source_provenance=_provenance(),
    )
    assert result["status"] == "VERIFIED_EXACT_MODULE_BYTES"
    assert result["module_digest"] == DIGEST
    assert result["binding_manifest_schema_version"] == (
        "cloudflare-active-worker-bindings/v8"
    )
    assert result["binding_manifest_digest"].startswith("sha256:")
    assert result["agents_dependency"]["resolved_version"] == "0.17.4"
    assert result["agents_dependency"]["package_lock_digest"].startswith("sha256:")
    assert result["binding_names"] == sorted(
        row["name"] for row in version["resources"]["bindings"]
    )
    assert result["durable_object_namespace_id"] == "d" * 32
    assert set(result["active_version_surfaces"]) == set(
        build_manifest()["active_workers"]
    )
    for surface in result["active_version_surfaces"].values():
        assert surface["deployment_bracket_before_digest"] == surface[
            "deployment_bracket_after_digest"
        ]
        assert surface["version_bracket_before_digest"] == surface[
            "version_bracket_after_digest"
        ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("deployment-race", "changed during"),
        ("version-race", "selected version changed"),
        ("split-traffic", "exactly one version"),
        ("module-substitution", "differs from"),
        ("extra-provenance", "fields are not closed"),
        ("missing-active-worker", "every active Worker exactly"),
        ("binding-drift", "live binding.*drifted"),
        ("service-binding", "binding-name inventory drifted"),
        ("cross-service-binding", "distributes a Quant Ops capability"),
        ("cross-do-stub", "distributes a Quant Ops capability"),
        ("do-handler", "live binding.*drifted"),
        ("migration-runtime", "compatibility runtime drifted"),
        ("compatibility-runtime", "compatibility runtime drifted"),
    ),
)
def test_exact_module_acceptance_rejects_race_or_caller_substitution(
    mutation: str,
    message: str,
) -> None:
    before, version_before = _active_documents()
    after = copy.deepcopy(before)
    version_after = copy.deepcopy(version_before)
    quant_version = version_before["quant-ops-mcp"]
    provenance = _provenance()
    if mutation == "deployment-race":
        after["quant-ops-mcp"]["id"] = "33333333-3333-4333-8333-333333333333"
    elif mutation == "split-traffic":
        before["quant-ops-mcp"]["versions"] = [
            {"percentage": 50, "version_id": VERSION},
            {"percentage": 50, "version_id": VERSION},
        ]
        after = copy.deepcopy(before)
    elif mutation == "version-race":
        version_after["quant-ops-mcp"]["metadata"][
            "created_on"
        ] = "2026-08-28T00:00:01Z"
    elif mutation == "module-substitution":
        provenance["live_main_module_digest"] = "sha256:" + "d" * 64
    elif mutation == "extra-provenance":
        provenance["caller_manifest_digest"] = DIGEST
    elif mutation == "missing-active-worker":
        version_before.pop("ingestion-jsda")
        version_after.pop("ingestion-jsda")
    elif mutation == "binding-drift":
        d1 = next(
            row
            for row in quant_version["resources"]["bindings"]
            if row["type"] == "d1"
        )
        d1["database_id"] = "f" * 32
        version_after = copy.deepcopy(version_before)
    elif mutation == "service-binding":
        quant_version["resources"]["bindings"].append({
            "name": "UNREVIEWED_SERVICE",
            "type": "service",
            "service": "unreviewed-worker",
            "environment": "production",
            "entrypoint": "UnreviewedEntrypoint",
        })
        version_after = copy.deepcopy(version_before)
    elif mutation == "cross-service-binding":
        version_before["ingestion-jsda"]["resources"]["bindings"].append({
            "name": "OPS_AGENT",
            "type": "service",
            "service": "quant-platform-ops-read-mcp",
            "environment": "production",
            "entrypoint": "QuantOpsMcpAgent",
        })
        version_after = copy.deepcopy(version_before)
    elif mutation == "cross-do-stub":
        version_before["ingestion-jsda"]["resources"]["bindings"].append({
            "name": "MCP_OBJECT",
            "type": "durable_object_namespace",
            "class_name": "QuantOpsMcpAgent",
            "script_name": "quant-platform-ops-read-mcp",
            "namespace_id": "f" * 32,
        })
        version_after = copy.deepcopy(version_before)
    elif mutation == "do-handler":
        durable = next(
            row
            for row in quant_version["resources"]["bindings"]
            if row["type"] == "durable_object_namespace"
        )
        durable["class_name"] = "UnreviewedAgent"
        version_after = copy.deepcopy(version_before)
    elif mutation == "migration-runtime":
        quant_version["resources"]["script_runtime"]["migration_tag"] = "v2"
        version_after = copy.deepcopy(version_before)
    else:
        quant_version["resources"]["script_runtime"][
            "compatibility_date"
        ] = "2026-08-02"
        version_after = copy.deepcopy(version_before)
    with pytest.raises(acceptance.QuantOpsMcpLiveAcceptanceError, match=message):
        acceptance.validate_live_quant_ops_module(
            environment="production",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments_before=before,
            deployments_after=after,
            versions_before=version_before,
            versions_after=version_after,
            source_provenance=provenance,
        )


def test_live_collection_brackets_selected_version_and_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployments, versions = _active_documents()
    active = build_manifest()["active_workers"]
    documents = iter([
        *[deployments[worker] for worker in active],
        *[versions[worker] for worker in active],
        *[copy.deepcopy(versions[worker]) for worker in active],
        *[copy.deepcopy(deployments[worker]) for worker in active],
    ])
    commands: list[tuple[str, ...]] = []

    def wrangler_json(**kwargs: object) -> object:
        commands.append(tuple(kwargs["arguments"]))
        return next(documents)

    monkeypatch.setattr(acceptance, "_wrangler_json", wrangler_json)
    monkeypatch.setattr(
        acceptance,
        "_source_provenance",
        lambda **_kwargs: _provenance(),
    )
    result = acceptance.collect_live_quant_ops_module(
        environment="production",
        source_sha=SHA,
        account_id=ACCOUNT,
        api_token="test-token",
    )
    assert result["status"] == "VERIFIED_EXACT_MODULE_BYTES"
    assert commands == [
        *[("deployments", "status", "--json") for _worker in active],
        *[("versions", "view", VERSION, "--json") for _worker in active],
        *[("versions", "view", VERSION, "--json") for _worker in active],
        *[("deployments", "status", "--json") for _worker in active],
    ]


def test_cli_rechecks_source_after_complete_live_collection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean_checks = 0

    def clean_source(_sha: str) -> None:
        nonlocal clean_checks
        clean_checks += 1
        if clean_checks == 2:
            raise RuntimeError("source changed during collection")

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    monkeypatch.setattr(acceptance, "_require_exact_clean_source", clean_source)
    monkeypatch.setattr(
        acceptance,
        "_require_official_origin_main",
        lambda _sha: None,
    )
    monkeypatch.setattr(
        acceptance,
        "collect_live_quant_ops_module",
        lambda **_kwargs: {
            "environment": "production",
            "deployment_version_id": VERSION,
            "module_digest": DIGEST,
        },
    )
    assert acceptance.main([
        "--environment",
        "production",
        "--expected-source-sha",
        SHA,
        "--expected-account-id",
        ACCOUNT,
    ]) == 1
    output = capsys.readouterr()
    assert "source changed during collection" in output.err
    assert "acceptance: ok" not in output.out
    assert clean_checks == 2


def test_cli_normalizes_source_check_process_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable(_sha: str) -> None:
        raise OSError("git is unavailable")

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    monkeypatch.setattr(
        acceptance,
        "_require_exact_clean_source",
        unavailable,
    )
    assert acceptance.main([
        "--environment",
        "production",
        "--expected-source-sha",
        SHA,
        "--expected-account-id",
        ACCOUNT,
    ]) == 1
    output = capsys.readouterr()
    assert "git is unavailable" in output.err
    assert "acceptance: ok" not in output.out


def test_cli_can_emit_canonical_json_for_immutable_evidence_intake(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "status": "VERIFIED_EXACT_MODULE_BYTES",
        "module_digest": DIGEST,
        "deployment_version_id": VERSION,
        "environment": "production",
    }
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    monkeypatch.setattr(
        acceptance,
        "_require_exact_clean_source",
        lambda _sha: None,
    )
    monkeypatch.setattr(
        acceptance,
        "_require_official_origin_main",
        lambda _sha: None,
    )
    monkeypatch.setattr(
        acceptance,
        "collect_live_quant_ops_module",
        lambda **_kwargs: result,
    )
    assert acceptance.main([
        "--environment",
        "production",
        "--expected-source-sha",
        SHA,
        "--expected-account-id",
        ACCOUNT,
        "--json",
    ]) == 0
    rendered = capsys.readouterr().out.strip()
    assert json.loads(rendered) == result
    assert rendered == json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
