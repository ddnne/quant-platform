"""Behavioral safety checks for the macOS authority bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
import plistlib

import pytest

from scripts import bootstrap_local_authorities as bootstrap


def test_default_plan_is_non_mutating_and_covers_six_local_principals() -> None:
    plan = bootstrap.build_plan("production")
    assert plan["mode"] == "DRY_RUN"
    assert plan["requires_human_sudo"] is True
    assert plan["creates_private_keys"] is False
    assert plan["loads_launchd_jobs"] is False
    assert plan["activates_registries"] is False
    assert plan["changes_declared_pending_mode"] is False
    assert {row["authority_id"] for row in plan["deployments"]} == {
        "d1_sync",
        "ops_projection",
        "coverage_transition",
        "ready",
        "trader",
        "controlled_execution",
    }
    assert all(row["declared_mode"] == "PENDING_NO_KEY" for row in plan["deployments"])


def test_cli_defaults_to_json_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert bootstrap.main(["--environment", "staging"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "DRY_RUN"
    assert len(result["deployments"]) == 6


def test_apply_requires_a_human_root_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 501)
    with pytest.raises(bootstrap.BootstrapError, match="interactive human.*sudo"):
        bootstrap.apply_plan("staging")


def test_live_audit_never_promotes_pending_contract() -> None:
    state = bootstrap.audit_state("production")
    assert state["mutation_performed"] is False
    assert state["open_p0_ids"]
    assert all(
        row["declared_mode"] == "PENDING_NO_KEY"
        and row["observed_state"] == "NOT_ACTIVATED"
        for row in state["deployments"]
    )


def test_launchd_template_uses_socket_activation_and_no_secret_values() -> None:
    raw = bootstrap.LAUNCHD_TEMPLATE.read_bytes()
    document = plistlib.loads(raw)
    assert document["UserName"] == "__SERVICE_USER__"
    assert document["Sockets"]["Listener"]["SockPathMode"] == 0o600
    assert "EnvironmentVariables" not in document
    assert b"PRIVATE_KEY" not in raw
    assert b"TOKEN" not in raw
