"""Behavioral safety checks for the macOS authority bootstrap."""

from __future__ import annotations

import base64
import json
import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap_local_authorities as bootstrap
from scripts import local_authority_provisioning as provisioning


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
    trader = next(row for row in plan["deployments"] if row["authority_id"] == "trader")
    assert trader["key_backend"] == "webauthn_platform_or_hardware"
    assert trader["key_path"] is None
    peers = {row["caller"]: row for row in plan["local_peer_identities"]}
    assert peers["controlled_pilot_orchestrator"] == {
        "environment": "production",
        "caller": "controlled_pilot_orchestrator",
        "service_user": "qp_production_controlled_pilot_orchestrator",
        "runtime": "local_os_disabled_service",
    }
    controlled = next(
        row
        for row in plan["deployments"]
        if row["authority_id"] == "controlled_execution"
    )
    assert controlled["custody_reader_group"] == (
        "qp_production_controlled_execution_readers"
    )
    assert "ensure_controlled_only_custody_reader_group" in controlled["actions"]
    assert all(
        row["custody_reader_group"] is None
        for row in plan["deployments"]
        if row["authority_id"] != "controlled_execution"
    )


def test_prepare_users_provisions_controlled_only_custody_reader_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "authority_id": "controlled_execution",
        "environment": "staging",
        "service_user": "qp_controlled",
        "caller_group": "qp_staging_controlled_execution_callers",
        "custody_reader_group": "qp_staging_controlled_execution_readers",
        "service_dir": "/protected/controlled",
        "declared_mode": "PENDING_NO_KEY",
    }
    account = SimpleNamespace(
        pw_name="qp_controlled",
        pw_uid=503,
        pw_gid=20,
        pw_dir="/var/empty",
        pw_shell="/usr/bin/false",
    )
    memberships: list[tuple[str, tuple[str, ...], str]] = []
    monkeypatch.setattr(provisioning, "_require_human_root", lambda: None)
    monkeypatch.setattr(provisioning, "_deployments", lambda _selected: [row])
    monkeypatch.setattr(provisioning, "_local_peer_rows", lambda _selected: [])
    monkeypatch.setattr(provisioning, "_ensure_group", lambda: 20)
    monkeypatch.setattr(provisioning, "_used_ids", lambda *_args: set())
    monkeypatch.setattr(
        provisioning, "_ensure_directory", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(provisioning, "_ensure_user", lambda *_args, **_kwargs: 503)
    monkeypatch.setattr(
        provisioning, "_ensure_caller_group", lambda *_args, **_kwargs: 30
    )
    monkeypatch.setattr(
        provisioning,
        "_ensure_custody_reader_group",
        lambda *_args, **_kwargs: 40,
    )
    monkeypatch.setattr(
        provisioning,
        "_set_exact_group_members",
        lambda name, *, usernames, purpose: memberships.append(
            (name, usernames, purpose)
        ),
    )
    monkeypatch.setattr(provisioning.pwd, "getpwnam", lambda _name: account)
    monkeypatch.setattr(
        provisioning,
        "require_controlled_custody_reader_group",
        lambda **_kwargs: None,
    )

    result = provisioning.apply_plan("staging")

    assert memberships == [
        (
            "qp_staging_controlled_execution_readers",
            ("qp_controlled",),
            "custody reader",
        )
    ]
    assert result["deployments"][0]["custody_reader_group_gid"] == 40


def test_prepare_users_rejects_shared_gid_for_custody_reader_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "authority_id": "controlled_execution",
        "environment": "staging",
        "service_user": "qp_controlled",
        "caller_group": "qp_staging_controlled_execution_callers",
        "custody_reader_group": "qp_staging_controlled_execution_readers",
        "service_dir": "/protected/controlled",
        "declared_mode": "PENDING_NO_KEY",
    }
    monkeypatch.setattr(provisioning, "_require_human_root", lambda: None)
    monkeypatch.setattr(provisioning, "_deployments", lambda _selected: [row])
    monkeypatch.setattr(provisioning, "_local_peer_rows", lambda _selected: [])
    monkeypatch.setattr(provisioning, "_ensure_group", lambda: 20)
    monkeypatch.setattr(provisioning, "_used_ids", lambda *_args: set())
    monkeypatch.setattr(
        provisioning, "_ensure_directory", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(provisioning, "_ensure_user", lambda *_args, **_kwargs: 503)
    monkeypatch.setattr(
        provisioning, "_ensure_caller_group", lambda *_args, **_kwargs: 30
    )
    monkeypatch.setattr(
        provisioning,
        "_ensure_custody_reader_group",
        lambda *_args, **_kwargs: 20,
    )

    with pytest.raises(bootstrap.BootstrapError, match="reuses another capability"):
        provisioning.apply_plan("staging")


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


def test_bootstrap_and_positive_activation_are_closed_disjoint_action_sets() -> None:
    assert bootstrap.BOOTSTRAP_ONLY_ACTIONS == {
        "prepare-users",
        "generate-keys",
        "install-runtime-configs",
        "install-runtime-bundle",
        "render-plists",
        "install-plists",
        "registry-proposals",
    }
    assert bootstrap.POSITIVE_ACTIVATION_ACTIONS == {"load-plists", "activate"}
    assert bootstrap.BOOTSTRAP_ONLY_ACTIONS.isdisjoint(
        bootstrap.POSITIVE_ACTIVATION_ACTIONS
    )


def test_open_ledger_allows_only_inactive_root_bootstrap_not_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate_calls = 0

    def reject_gate():
        nonlocal gate_calls
        gate_calls += 1
        raise bootstrap.FindingLedgerError("OPEN P0")

    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bootstrap, "load_and_validate_manifest", dict)
    monkeypatch.setattr(bootstrap, "require_pinned_finding_ledger_gate", reject_gate)

    bootstrap._require_human_root()
    assert gate_calls == 0
    with pytest.raises(bootstrap.BootstrapError, match="strict.*rejected"):
        bootstrap._require_positive_activation()
    assert gate_calls == 1


def test_bootstrap_plans_cannot_claim_active_state() -> None:
    plans = (
        bootstrap.build_plan("staging"),
        bootstrap.generate_keys("staging", apply=False),
        bootstrap.install_runtime_configs("staging", apply=False, source_root=None),
        bootstrap.install_runtime_bundle(
            apply=False, expected_source_sha=None, root_python=None
        ),
        bootstrap.render_plists("staging", apply=False),
        bootstrap.install_plists("staging", apply=False),
        bootstrap.registry_proposals("staging", apply=False),
    )
    for plan in plans:
        assert plan["phase"] == "BOOTSTRAP_INACTIVE"
        assert plan["strict_gate_required"] is False
        assert plan["positive_activation_forbidden"] is True


def test_live_audit_never_promotes_pending_contract() -> None:
    state = bootstrap.audit_state("production")
    assert state["mutation_performed"] is False
    assert state["open_p0_ids"]
    assert all(
        row["declared_mode"] == "PENDING_NO_KEY"
        and row["observed_state"] == "NOT_ACTIVATED"
        for row in state["deployments"]
    )


def test_key_plan_never_generates_a_file_key_for_trader() -> None:
    plan = bootstrap.generate_keys("production", apply=False)
    trader = next(row for row in plan["deployments"] if row["authority_id"] == "trader")
    assert trader["action"] == "INITIALIZE_EVENT_STORE_WEBAUTHN_ENROLLMENT_REQUIRED"
    assert "GENERATE" not in trader["action"]


def test_key_generation_is_service_uid_scoped_idempotent_and_never_returns_seed(
    tmp_path: Path,
) -> None:
    service_dir = tmp_path / "ready"
    service_dir.mkdir(mode=0o700)
    row = next(
        item
        for item in bootstrap._deployments("staging")
        if item["authority_id"] == "ready"
    )
    row.update(
        {
            "service_dir": str(service_dir),
            "key_path": str(service_dir / "ed25519-private-key"),
            "public_metadata_path": str(service_dir / bootstrap.PUBLIC_METADATA_NAME),
            "ledger_path": str(service_dir / "authority-events.sqlite3"),
        }
    )
    first = bootstrap._generate_or_validate_key_material(row, expected_uid=os.geteuid())
    second = bootstrap._generate_or_validate_key_material(
        row, expected_uid=os.geteuid()
    )
    assert first["status"] == "CREATED"
    assert second["status"] == "ALREADY_PRESENT_VERIFIED"
    assert first["public_key_sha256"] == second["public_key_sha256"]
    key_path = service_dir / "ed25519-private-key"
    seed_b64 = base64.b64encode(key_path.read_bytes()).decode("ascii")
    assert seed_b64 not in json.dumps(first)
    assert key_path.stat().st_mode & 0o777 == 0o400


def test_all_mutating_subcommands_default_to_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for action in (
        "generate-keys",
        "install-runtime-configs",
        "install-runtime-bundle",
        "render-plists",
        "install-plists",
        "load-plists",
        "registry-proposals",
        "activate",
    ):
        assert bootstrap.main([action, "--environment", "staging"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["mode"] == "DRY_RUN"


def test_launchd_template_uses_socket_activation_and_no_secret_values() -> None:
    raw = bootstrap.LAUNCHD_TEMPLATE.read_bytes()
    document = plistlib.loads(raw)
    assert document["UserName"] == "__SERVICE_USER__"
    assert document["GroupName"] == "__CALLER_GROUP__"
    assert document["Sockets"]["Listener"]["SockPathMode"] == 0o660
    assert document["ProgramArguments"][:3] == [
        "__PYTHON_PATH__",
        "-I",
        "__BUNDLE_ENTRYPOINT__",
    ]
    assert document["WorkingDirectory"] == "__BUNDLE_ROOT__"
    assert b"__UV_PATH__" not in raw
    assert b"__REPOSITORY__" not in raw
    assert str(bootstrap._ROOT).encode() not in raw
    assert "EnvironmentVariables" not in document
    assert b"PRIVATE_KEY" not in raw
    assert b"TOKEN" not in raw


def test_runtime_configs_pin_exact_peer_users_without_arbitrary_mapping() -> None:
    rows = {row["authority_id"]: row for row in bootstrap._deployments("production")}
    assert bootstrap._runtime_config_template(rows["d1_sync"])["peer_callers"] == {
        "qp_production_ops_scheduler": "ops_scheduler",
        "qp_production_coverage_scheduler": "coverage_scheduler",
    }
    assert bootstrap._runtime_config_template(rows["ops_projection"])[
        "peer_callers"
    ] == {"qp_production_d1_sync_authority": "d1_sync"}
    assert bootstrap._runtime_config_template(rows["coverage_transition"])[
        "peer_callers"
    ] == {"qp_production_d1_sync_authority": "d1_sync"}
    trader = bootstrap._runtime_config_template(rows["trader"])
    controlled = bootstrap._runtime_config_template(rows["controlled_execution"])
    assert trader["peer_callers"] == {
        "qp_production_controlled_pilot_orchestrator": (
            "controlled_pilot_orchestrator"
        )
    }
    assert controlled["peer_callers"] == {
        "qp_production_trader_authority": "trader"
    }
    assert trader["resources"] == {
        "activation_document_path": (
            "/etc/quant-platform/authorities/trader/activation.json"
        )
    }
    assert controlled["resources"] == {
        "activation_document_path": (
            "/etc/quant-platform/authorities/controlled_execution/activation.json"
        )
    }
    assert "current_db" not in json.dumps(controlled)


def test_runtime_and_launchd_plans_cover_all_six_distinct_principals() -> None:
    configs = bootstrap.install_runtime_configs(
        "production", apply=False, source_root=None
    )
    plists = bootstrap.render_plists("production", apply=False)
    expected = {
        "d1_sync",
        "ops_projection",
        "coverage_transition",
        "ready",
        "trader",
        "controlled_execution",
    }
    assert {row["template"]["authority_id"] for row in configs["templates"]} == expected
    assert {row["authority_id"] for row in plists["plists"]} == expected
    assert configs["deferred_authorities"] == []
    assert plists["deferred_authorities"] == []
    deployments = bootstrap._deployments("production")
    assert len({row["service_user"] for row in deployments}) == 6
    assert len({row["socket_path"] for row in deployments}) == 6
    assert len({row["service_dir"] for row in deployments}) == 6
    assert len({row["ledger_path"] for row in deployments}) == 6
    file_keys = [row["key_path"] for row in deployments if row["key_path"]]
    assert len(set(file_keys)) == 5


def test_runtime_bundle_plan_requires_reviewed_root_python_artifact() -> None:
    plan = bootstrap.install_runtime_bundle(
        apply=False, expected_source_sha=None, root_python=None
    )
    requirement = plan["runtime_python_acquisition"]
    assert requirement["status"] == "HUMAN_REVIEWED_ROOT_RUNTIME_ARTIFACT_REQUIRED"
    assert requirement["minimum_python"] == "3.11"
    assert requirement["dependency_lock_digest"].startswith("sha256:")
    assert "approved_distribution_sha256" in requirement["required_human_inputs"]
    assert plan["launchd_uses_checkout_or_uv"] is False
    assert all(
        not row["launchd_eligible"]
        for row in requirement["host_candidates"]
        if str(row["path"]).startswith("/Users/")
    )
    remote = plan["d1_remote_sync_prerequisites"]
    assert remote["pinned_wrangler_version"] == "4.125.0"
    assert remote["governed_database_name"] == "quant-ingest"
    assert remote["credential_requirements"]["argv"] == "FORBIDDEN"
    assert remote["activation_status"] == "HUMAN_PROVISIONING_REQUIRED"
