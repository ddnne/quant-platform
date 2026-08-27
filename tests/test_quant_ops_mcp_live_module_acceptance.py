from __future__ import annotations

import copy

import pytest

from scripts import quant_ops_mcp_live_module_acceptance as acceptance


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


def test_exact_module_acceptance_binds_manifest_and_agents_dependency() -> None:
    deployment = _deployment()
    result = acceptance.validate_live_quant_ops_module(
        environment="production",
        source_sha=SHA,
        account_id=ACCOUNT,
        deployment_before=deployment,
        deployment_after=copy.deepcopy(deployment),
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("deployment-race", "changed during"),
        ("split-traffic", "exactly one version"),
        ("module-substitution", "differs from"),
        ("extra-provenance", "fields are not closed"),
    ),
)
def test_exact_module_acceptance_rejects_race_or_caller_substitution(
    mutation: str,
    message: str,
) -> None:
    before = _deployment()
    after = copy.deepcopy(before)
    provenance = _provenance()
    if mutation == "deployment-race":
        after["id"] = "33333333-3333-4333-8333-333333333333"
    elif mutation == "split-traffic":
        before["versions"] = [
            {"percentage": 50, "version_id": VERSION},
            {"percentage": 50, "version_id": VERSION},
        ]
        after = copy.deepcopy(before)
    elif mutation == "module-substitution":
        provenance["live_main_module_digest"] = "sha256:" + "d" * 64
    else:
        provenance["caller_manifest_digest"] = DIGEST
    with pytest.raises(acceptance.QuantOpsMcpLiveAcceptanceError, match=message):
        acceptance.validate_live_quant_ops_module(
            environment="production",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployment_before=before,
            deployment_after=after,
            source_provenance=provenance,
        )
