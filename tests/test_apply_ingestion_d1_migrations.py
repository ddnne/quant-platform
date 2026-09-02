"""Essential invariants for the small single-operator D1 migration owner."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Sequence

import pytest

from scripts import apply_ingestion_d1_migrations as owner
from scripts.d1_ingestion_migration_validation import MIGRATIONS


SHA = "a" * 40
LEASE_OWNER = "apply:" + "1" * 32
NONCE = "2" * 64
BOOKMARK = "00000001-00000002-00000003-" + "d" * 32


class D1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(owner.BOOTSTRAP.read_text(encoding="utf-8"))
        self.apply_calls = 0
        self.apply_returncode = 0
        self.backend_version = "production"

    def runner(
        self, argv: Sequence[str], _cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        if args[-1:] == ["--version"]:
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ["d1", "info"]:
            binding = owner.canonical_binding("staging")
            payload = {
                "name": binding["database_name"],
                "uuid": binding["database_id"],
                "version": self.backend_version,
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if args[1:4] == ["d1", "time-travel", "info"]:
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"current_bookmark": BOOKMARK}), ""
            )
        if args[1:4] == ["d1", "migrations", "apply"]:
            self.apply_calls += 1
            return subprocess.CompletedProcess(args, self.apply_returncode, "", "")
        if "--file" in args:
            self.connection.executescript(
                Path(args[args.index("--file") + 1]).read_text(encoding="utf-8")
            )
            return subprocess.CompletedProcess(args, 0, "applied", "")
        if "--command" not in args:
            raise AssertionError(args)
        sql = args[args.index("--command") + 1]
        before = self.connection.total_changes
        try:
            cursor = self.connection.execute(sql)
        except sqlite3.DatabaseError as exc:
            return subprocess.CompletedProcess(args, 1, "", str(exc))
        rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        payload = [{
            "success": True,
            "results": rows,
            "meta": {"changes": self.connection.total_changes - before},
        }]
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")


def identity() -> dict[str, Any]:
    return owner._identity("staging", SHA)


def acquire(store: D1) -> dict[str, Any]:
    return owner.acquire_authorized_mutation_lease(
        environment="staging",
        source_sha=SHA,
        runner=store.runner,
        lease_owner_token=LEASE_OWNER,
        lease_nonce_token=NONCE,
    )


def test_0023_bootstraps_exactly_on_live_through_0010() -> None:
    connection = sqlite3.connect(":memory:")
    for migration in MIGRATIONS[:10]:
        connection.executescript(migration.read_text(encoding="utf-8"))
    connection.executescript(owner.BOOTSTRAP.read_text(encoding="utf-8"))
    assert connection.execute(
        "SELECT phase,remote_spawned FROM quant_ingest_mutation_lease"
    ).fetchone() == ("vacant", 0)
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"quant_ingest_mutation_lease", "jsda_v3_cutover_run"} <= tables
    connection.close()


def test_npm_wrangler_symlink_must_resolve_to_pinned_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "worker"
    target = worker / "node_modules/wrangler/bin/wrangler.js"
    target.parent.mkdir(parents=True)
    target.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    binary = worker / "node_modules/.bin/wrangler"
    binary.parent.mkdir()
    binary.symlink_to("../wrangler/bin/wrangler.js")
    monkeypatch.setattr(owner, "WORKER", worker)
    assert owner._wrangler_prefix("staging")[0] == [str(binary)]
    binary.unlink()
    wrong = worker / "wrong"
    wrong.write_text("x", encoding="utf-8")
    binary.symlink_to(wrong)
    with pytest.raises(owner.GuardedMigrationError, match="pinned local Wrangler"):
        owner._wrangler_prefix("staging")
    with pytest.raises(owner.GuardedMigrationError, match="pinned local Wrangler"):
        owner.time_travel_bookmark("staging")


def test_time_travel_requires_exact_production_backend_without_node_modules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = D1()
    monkeypatch.setattr(owner, "WORKER", tmp_path / "worker-without-node-modules")
    assert owner.time_travel_bookmark("staging", runner=store.runner)["bookmark"] == BOOKMARK
    store.backend_version = "alpha"
    with pytest.raises(owner.GuardedMigrationError, match="production backend"):
        owner.time_travel_bookmark("staging", runner=store.runner)


def test_lease_is_exclusive_and_expired_process_free_acquire_is_reclaimable() -> None:
    store = D1()
    lease = acquire(store)
    assert lease["phase"] == "acquired"
    with pytest.raises(owner.GuardedMigrationError, match="already held"):
        owner.acquire_authorized_mutation_lease(
            environment="staging",
            source_sha=SHA,
            runner=store.runner,
            lease_owner_token="apply:" + "3" * 32,
            lease_nonce_token="4" * 64,
        )
    store.connection.execute(
        "UPDATE quant_ingest_mutation_lease SET expires_at='2020-01-01T00:00:00Z'"
    )
    replacement = owner.acquire_authorized_mutation_lease(
        environment="staging",
        source_sha=SHA,
        runner=store.runner,
        lease_owner_token="apply:" + "3" * 32,
        lease_nonce_token="4" * 64,
    )
    assert replacement["owner"] == "apply:" + "3" * 32


def test_apply_fences_before_spawn_and_returns_process_free_verifying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = D1()
    acquire(store)
    phases_at_spawn: list[tuple[str, int]] = []
    original = store.runner

    def runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if list(argv)[1:4] == ["d1", "migrations", "apply"]:
            row = store.connection.execute(
                "SELECT phase,remote_spawned FROM quant_ingest_mutation_lease"
            ).fetchone()
            phases_at_spawn.append((str(row[0]), int(row[1])))
        return original(argv, cwd)

    prefix, binding = owner._runner_wrangler_prefix("staging", runner=runner)
    owner._apply_remote_migrations(
        environment="staging",
        binding=binding,
        runner=runner,
        prefix=prefix,
        identity=identity(),
        owner=LEASE_OWNER,
        nonce=NONCE,
    )
    assert phases_at_spawn == [("migrating", 1)]
    assert tuple(store.connection.execute(
        "SELECT phase,remote_spawned FROM quant_ingest_mutation_lease"
    ).fetchone()) == ("verifying", 0)


def test_spawn_failure_is_sticky_and_cannot_be_silently_resumed() -> None:
    store = D1()
    acquire(store)
    store.apply_returncode = 1
    prefix, binding = owner._runner_wrangler_prefix(
        "staging", runner=store.runner
    )
    with pytest.raises(owner.GuardedMigrationError, match="apply failed"):
        owner._apply_remote_migrations(
            environment="staging",
            binding=binding,
            runner=store.runner,
            prefix=prefix,
            identity=identity(),
            owner=LEASE_OWNER,
            nonce=NONCE,
        )
    assert tuple(store.connection.execute(
        "SELECT phase,remote_spawned FROM quant_ingest_mutation_lease"
    ).fetchone()) == ("recovery_required", 1)
    with pytest.raises(owner.GuardedMigrationError, match="identity is not active"):
        owner.resume_owned_mutation_lease(
            identity=identity(), environment="staging", owner=LEASE_OWNER,
            nonce=NONCE, runner=store.runner,
        )


def test_expired_verifying_lease_resumes_only_for_same_process_free_owner() -> None:
    store = D1()
    acquire(store)
    store.connection.execute(
        "UPDATE quant_ingest_mutation_lease SET phase='verifying',remote_spawned=0,"
        "expires_at='2020-01-01T00:00:00Z'"
    )
    renewed = owner.resume_owned_mutation_lease(
        identity=identity(), environment="staging", owner=LEASE_OWNER,
        nonce=NONCE, runner=store.runner,
    )
    assert renewed["phase"] == "verifying"
    assert owner._parse_utc_instant(renewed["expires_at"], label="expiry") > owner._now()


def test_acquire_accepts_lost_response_only_after_exact_same_owner_observation() -> None:
    store = D1()
    original = store.runner
    lost = {"once": True}

    def runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        if lost["once"] and "--command" in args:
            sql = args[args.index("--command") + 1]
            if sql.startswith("UPDATE quant_ingest_mutation_lease SET"):
                lost["once"] = False
                original(argv, cwd)
                return subprocess.CompletedProcess(args, 1, "", "timeout")
        return original(argv, cwd)

    lease = owner.acquire_authorized_mutation_lease(
        environment="staging", source_sha=SHA, runner=runner,
        lease_owner_token=LEASE_OWNER, lease_nonce_token=NONCE,
    )
    assert lease["owner"] == LEASE_OWNER
    assert lease["phase"] == "acquired"
    assert lease["remote_spawned"] == 0


def test_unobserved_acquire_stays_held_then_only_expired_process_free_is_reclaimed() -> None:
    store = D1()
    original = store.runner
    hidden = {"enabled": True}

    def uncertain(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        if "--command" in args:
            sql = args[args.index("--command") + 1]
            if sql.startswith("UPDATE quant_ingest_mutation_lease SET"):
                original(argv, cwd)
                return subprocess.CompletedProcess(args, 1, "", "timeout")
            if hidden["enabled"] and sql.startswith("SELECT environment"):
                return subprocess.CompletedProcess(args, 1, "", "timeout")
        return original(argv, cwd)

    with pytest.raises(owner.GuardedMigrationError, match="D1 execute failed"):
        owner.acquire_authorized_mutation_lease(
            environment="staging", source_sha=SHA, runner=uncertain,
            lease_owner_token=LEASE_OWNER, lease_nonce_token=NONCE,
        )
    hidden["enabled"] = False
    with pytest.raises(owner.GuardedMigrationError, match="already held"):
        owner.acquire_authorized_mutation_lease(
            environment="staging", source_sha=SHA, runner=store.runner,
            lease_owner_token="apply:" + "3" * 32,
            lease_nonce_token="4" * 64,
        )
    store.connection.execute(
        "UPDATE quant_ingest_mutation_lease SET expires_at='2020-01-01T00:00:00Z'"
    )
    replacement = owner.acquire_authorized_mutation_lease(
        environment="staging", source_sha=SHA, runner=store.runner,
        lease_owner_token="apply:" + "3" * 32,
        lease_nonce_token="4" * 64,
    )
    assert replacement["owner"] == "apply:" + "3" * 32


def test_no_local_database_export_or_backup_path_remains() -> None:
    assert not hasattr(owner, "apply_guarded")
    assert not hasattr(owner, "recover_guarded")
    assert not hasattr(owner, "put_create_only_private_backup")
