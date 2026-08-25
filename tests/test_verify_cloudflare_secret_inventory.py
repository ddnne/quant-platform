from __future__ import annotations

import json
import subprocess

import pytest

from scripts.verify_cloudflare_secret_inventory import (
    SecretInventoryError,
    expected_production_secret_names,
    live_secret_names,
    parse_wrangler_secret_list,
    verify_live_secret_inventory,
    wrangler_command,
)


def _completed(payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=("wrangler",),
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_parses_names_only_and_rejects_value_shaped_output() -> None:
    assert parse_wrangler_secret_list(
        '[{"name":"TOKEN_B","type":"secret_text"},'
        '{"name":"TOKEN_A","type":"secret_text"}]'
    ) == ("TOKEN_A", "TOKEN_B")
    with pytest.raises(SecretInventoryError, match="row shape drifted"):
        parse_wrangler_secret_list(
            '[{"name":"TOKEN_A","type":"secret_text","value":"must-not-pass"}]'
        )


def test_exact_live_inventory_matches_every_active_worker() -> None:
    expected = expected_production_secret_names()

    def runner(command: tuple[str, ...], **_kwargs: object):
        worker = next(
            worker for worker in expected if f"/{worker}/" in command[0]
        )
        return _completed(
            [{"name": name, "type": "secret_text"} for name in expected[worker]]
        )

    assert verify_live_secret_inventory(runner=runner) == list(expected)


def test_missing_or_unexpected_live_name_fails_closed() -> None:
    def runner(_command: tuple[str, ...], **_kwargs: object):
        return _completed([{"name": "UNEXPECTED", "type": "secret_text"}])

    with pytest.raises(SecretInventoryError, match="production secret-name drift"):
        verify_live_secret_inventory(["ingestion-jsda"], runner=runner)


def test_wrangler_failure_does_not_relay_command_output() -> None:
    secret_value = "provider-secret-value-must-stay-redacted"

    def runner(_command: tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            args=("wrangler",),
            returncode=1,
            stdout="",
            stderr=secret_value,
        )

    with pytest.raises(SecretInventoryError) as captured:
        live_secret_names("ingestion-jsda", runner=runner)
    assert secret_value not in str(captured.value)


def test_command_is_read_only_production_name_inventory() -> None:
    command = wrangler_command("ingestion-jsda")
    assert command[1:] == (
        "secret",
        "list",
        "--env",
        "production",
        "--format",
        "json",
    )
