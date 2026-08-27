"""Behavioral checks for the launchd local-authority runner configuration."""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from execution import controlled_execution_activation_v2 as controlled_activation
from execution.exact_four_codec import ExactFourAuthorityPending
from scripts import run_local_authority as runner


def _config() -> dict[str, object]:
    return {
        "format": runner.RUNTIME_CONFIG_FORMAT,
        "authority_id": "ready",
        "environment": "staging",
        "peer_callers": {"qp_staging_ready_publisher": "ready_publisher"},
        "resources": {"snapshot_root": "/governed/ready/snapshots"},
    }


def test_runtime_config_accepts_only_exact_authority_acl_and_resources() -> None:
    assert runner.validate_runtime_config(
        _config(), authority_id="ready", environment="staging"
    )["peer_callers"] == {"qp_staging_ready_publisher": "ready_publisher"}

    extra_peer = _config()
    extra_peer["peer_callers"]["qp_ops"] = "ops_scheduler"  # type: ignore[index]
    with pytest.raises(runner.AuthorityRunnerError, match="exact method ACL"):
        runner.validate_runtime_config(
            extra_peer, authority_id="ready", environment="staging"
        )

    extra_resource = _config()
    extra_resource["resources"]["raw_db"] = "/forbidden"  # type: ignore[index]
    with pytest.raises(runner.AuthorityRunnerError, match="resource capability"):
        runner.validate_runtime_config(
            extra_resource, authority_id="ready", environment="staging"
        )


def test_runtime_config_decoder_rejects_duplicate_keys_and_floats() -> None:
    duplicate = (
        b'{"authority_id":"ready","authority_id":"ready",'
        b'"environment":"staging","format":"local-authority-runtime-config/v1",'
        b'"peer_callers":{},"resources":{}}'
    )
    with pytest.raises(runner.AuthorityRunnerError, match="duplicates"):
        runner.decode_runtime_config(
            duplicate, authority_id="ready", environment="staging"
        )
    floating = json.dumps({**_config(), "resources": {"snapshot_root": 1.5}}).encode()
    with pytest.raises(runner.AuthorityRunnerError, match="forbidden number"):
        runner.decode_runtime_config(
            floating, authority_id="ready", environment="staging"
        )


def test_d1_runtime_requires_governed_mirror_credential_and_pinned_cli_paths() -> None:
    config = {
        "format": runner.RUNTIME_CONFIG_FORMAT,
        "authority_id": "d1_sync",
        "environment": "production",
        "peer_callers": {
            "qp_production_ops_scheduler": "ops_scheduler",
            "qp_production_coverage_scheduler": "coverage_scheduler",
        },
        "resources": {
            "governed_db_path": "/protected/applied.sqlite",
            "cloudflare_token_path": "/protected/cloudflare-token",
            "node_executable_path": "/protected/node",
            "wrangler_cli_path": "/protected/wrangler.js",
            "wrangler_cli_tree_path": "/protected/wrangler-tree",
            "wrangler_config_path": "/protected/wrangler.toml",
            "wrangler_lock_path": "/protected/package-lock.json",
        },
    }
    assert runner.validate_runtime_config(
        config,
        authority_id="d1_sync",
        environment="production",
    )["resources"]["cloudflare_token_path"] == "/protected/cloudflare-token"

    missing_credential = json.loads(json.dumps(config))
    del missing_credential["resources"]["cloudflare_token_path"]
    with pytest.raises(runner.AuthorityRunnerError, match="resource capability"):
        runner.validate_runtime_config(
            missing_credential,
            authority_id="d1_sync",
            environment="production",
        )


def test_long_running_authorities_receive_bounded_processing_leases() -> None:
    assert runner._processing_timeout_seconds("d1_sync") == 900.0
    assert runner._processing_timeout_seconds("ready") == 900.0
    assert runner._processing_timeout_seconds("trader") == 1800.0
    assert runner._processing_timeout_seconds("controlled_execution") == 1800.0


@pytest.mark.parametrize(
    ("authority_id", "peer_user", "peer", "activation_path"),
    (
        (
            "trader",
            "qp_production_controlled_pilot_orchestrator",
            "controlled_pilot_orchestrator",
            "/etc/quant-platform/authorities/trader/activation.json",
        ),
        (
            "controlled_execution",
            "qp_production_trader_authority",
            "trader",
            "/etc/quant-platform/authorities/controlled_execution/activation.json",
        ),
    ),
)
def test_execution_runtime_configs_are_closed_and_pin_activation(
    authority_id: str,
    peer_user: str,
    peer: str,
    activation_path: str,
) -> None:
    config = {
        "format": runner.RUNTIME_CONFIG_FORMAT,
        "authority_id": authority_id,
        "environment": "production",
        "peer_callers": {peer_user: peer},
        "resources": {"activation_document_path": activation_path},
    }
    assert runner.validate_runtime_config(
        config,
        authority_id=authority_id,
        environment="production",
    )["resources"] == {"activation_document_path": activation_path}
    assert "current_db" not in json.dumps(config)

    wrong_path = json.loads(json.dumps(config))
    wrong_path["resources"]["activation_document_path"] = "/tmp/activation.json"
    with pytest.raises(runner.AuthorityRunnerError, match="pinned authority"):
        runner.validate_runtime_config(
            wrong_path,
            authority_id=authority_id,
            environment="production",
        )

    mutable_db = json.loads(json.dumps(config))
    mutable_db["resources"]["current_db"] = "/tmp/current.sqlite"
    with pytest.raises(runner.AuthorityRunnerError, match="resource capability"):
        runner.validate_runtime_config(
            mutable_db,
            authority_id=authority_id,
            environment="production",
        )


def test_controlled_bootstrap_key_format_has_no_pem_or_generic_signer_fallback() -> None:
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    decoded = controlled_activation._decode_protected_writer_key_v2(raw)
    assert isinstance(decoded, Ed25519PrivateKey)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(ExactFourAuthorityPending, match="cannot be decoded"):
        controlled_activation._decode_protected_writer_key_v2(pem)
