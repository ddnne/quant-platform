"""Behavioral checks for the launchd local-authority runner configuration."""

from __future__ import annotations

import json

import pytest

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
            "wrangler_config_path": "/protected/wrangler.toml",
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
