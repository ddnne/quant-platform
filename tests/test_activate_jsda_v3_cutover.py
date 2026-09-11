"""Essential invariants for the single-operator Cloudflare cutover."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Mapping

import pytest

from scripts import activate_jsda_v3_cutover as cutover
from scripts.d1_ingestion_migration_validation import MIGRATION_NAMES


SHA = "c" * 40
BASELINE = "00000001-00000002-00000003-" + "d" * 32
UNDO = "00000002-00000003-00000004-" + "e" * 32


def state(environment: str = "staging") -> dict[str, Any]:
    return {
        "source_sha": SHA,
        "version_id": "10000000-0000-4000-8000-000000000001",
        "deployment_id": "00000000-0000-4000-8000-000000000001",
        "version_tag": "b" * 40,
        "schedules": [] if environment == "staging" else [{"cron": "30 1 * * *"}],
        "queue": {"id": "queue", "paused": False, "backlog": 0, "bytes": 0},
        "applied_migrations": list(MIGRATION_NAMES[:10]),
        "pending_migrations": list(MIGRATION_NAMES[10:]),
        "schema_observations": ["jsda_acquisition_jobs_v3"],
        "jobs": {
            "jsda_acquisition_jobs": 0,
            "jsda_acquisition_jobs_v2": None,
            "jsda_acquisition_jobs_v3": None,
        },
        "cutover_phase": None,
    }


def receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    intent = cutover._control_intent("staging", state())
    value = cutover._build_receipt(
        "staging",
        intent,
        {
            "bookmark": BASELINE,
            "database_id": "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
            "database_name": "quant-ingest-staging",
            "version": "production",
            "response_digest": "sha256:" + "f" * 64,
        },
    )
    cutover._save_receipt(value)
    return value


def no_remote_restore_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cutover, "_d1_rows", lambda *_a, **_k: [])


class SharedD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE jsda_v3_cutover_control (
                singleton INTEGER PRIMARY KEY,
                phase TEXT NOT NULL,
                activated_at TEXT,
                activated_source_sha TEXT,
                cutover_config_digest TEXT,
                drain_evidence_digest TEXT
            );
            INSERT INTO jsda_v3_cutover_control(singleton, phase) VALUES (1, 'bridge');
            CREATE TABLE jsda_v3_cutover_run (
                run_id TEXT PRIMARY KEY,
                environment TEXT,
                source_sha TEXT,
                selected_version_id TEXT,
                selected_deployment_id TEXT,
                selected_version_tag TEXT,
                cutover_config_digest TEXT,
                rollback_bookmark TEXT,
                owner TEXT,
                fence TEXT,
                phase TEXT,
                evidence_digest TEXT,
                drain_evidence_digest TEXT,
                document_json TEXT,
                updated_at TEXT
            );
            CREATE TABLE jsda_v3_drain_evidence (
                drain_evidence_digest TEXT PRIMARY KEY,
                observed_at TEXT,
                document_json TEXT
            );
            CREATE TABLE premium_writer_rows (
                id INTEGER PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE receipt_writer_rows (
                id INTEGER PRIMARY KEY,
                payload TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT INTO premium_writer_rows(id, payload) VALUES (1, 'before-bookmark')"
        )
        self.restore_calls = 0

    def insert_after_bookmark(self) -> None:
        self.connection.execute(
            "INSERT INTO premium_writer_rows(id, payload) VALUES (2, 'premium-after')"
        )
        self.connection.execute(
            "INSERT INTO receipt_writer_rows(id, payload) VALUES (1, 'receipt-after')"
        )

    def payloads(self) -> set[str]:
        premium = {
            row[0]
            for row in self.connection.execute(
                "SELECT payload FROM premium_writer_rows"
            )
        }
        receipt = {
            row[0]
            for row in self.connection.execute(
                "SELECT payload FROM receipt_writer_rows"
            )
        }
        return premium | receipt

    def restore(self) -> None:
        self.restore_calls += 1
        self.connection.execute("DELETE FROM premium_writer_rows WHERE id > 1")
        self.connection.execute("DELETE FROM receipt_writer_rows")

    def batch(
        self, _environment: str, statements: Any, **_kwargs: object
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for statement in statements:
            before = self.connection.total_changes
            cursor = self.connection.execute(
                statement["sql"], statement.get("params") or []
            )
            rows = (
                [dict(row) for row in cursor.fetchall()] if cursor.description else []
            )
            results.append({
                "success": True,
                "results": rows,
                "meta": {"changes": self.connection.total_changes - before},
            })
        return results

    def rows(
        self, _environment: str, sql: str, **kwargs: object
    ) -> list[dict[str, Any]]:
        params = list(kwargs.get("params") or [])
        cursor = self.connection.execute(sql, params)
        if cursor.description is None:
            return []
        return [dict(row) for row in cursor.fetchall()]


def exact_live() -> dict[str, Any]:
    value = state()
    value.update({
        "version_tag": SHA,
        "applied_migrations": list(MIGRATION_NAMES),
        "pending_migrations": [],
        "schema_observations": [],
        "jobs": {key: 0 for key in value["jobs"]},
        "cutover_phase": "v3_active",
    })
    return value


def test_receipt_is_small_external_create_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    path = cutover._receipt_path("staging", value["run_id"])
    assert path.stat().st_size < 64 * 1024
    assert cutover.ROOT.resolve() not in path.resolve().parents
    cutover._save_receipt(value)


def test_receipt_race_never_overwrites_competing_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    intent = cutover._control_intent("staging", state())
    value = cutover._build_receipt(
        "staging", intent,
        {"bookmark": BASELINE, "database_id": "id", "database_name": "db",
         "version": "production", "response_digest": "sha256:" + "f" * 64},
    )
    path = cutover._receipt_path("staging", value["run_id"])

    def race(_source: Path, target: Path, **_kwargs: object) -> None:
        target.write_bytes(b"competing\n")
        raise FileExistsError(target)

    monkeypatch.setattr(cutover.os, "link", race)
    with pytest.raises(cutover.JsdaCutoverError, match="already differs"):
        cutover._save_receipt(value)
    assert path.read_bytes() == b"competing\n"


def test_wrangler_accepts_only_standard_pinned_npm_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "worker"
    target = worker / "node_modules/wrangler/bin/wrangler.js"
    target.parent.mkdir(parents=True)
    target.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    binary = worker / "node_modules/.bin/wrangler"
    binary.parent.mkdir()
    binary.symlink_to("../wrangler/bin/wrangler.js")
    monkeypatch.setattr(cutover.cloudflare, "WORKER", worker)
    assert cutover._wrangler() == binary
    binary.unlink()
    wrong = worker / "wrong"
    wrong.write_text("x", encoding="utf-8")
    binary.symlink_to(wrong)
    with pytest.raises(cutover.JsdaCutoverError, match="invalid"):
        cutover._wrangler()


def test_control_intent_survives_pre_receipt_crash_and_preserves_prior_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    prior = state("production")
    intent = cutover._control_intent("production", prior)
    stopped = deepcopy(prior)
    stopped["schedules"] = []
    stopped["queue"]["paused"] = True
    stopped["version_id"] = "changed"
    resumed = cutover._control_intent("production", stopped)
    assert resumed == intent
    assert resumed["prior_schedules"] == prior["schedules"]
    assert resumed["prior_queue_paused"] is False
    assert resumed["prior_version_id"] == prior["version_id"]


def test_activate_captures_bookmark_only_after_intent_stop_stable_drain_and_pause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    no_remote_restore_intent(monkeypatch)
    baseline = state("production")
    drained = deepcopy(baseline)
    drained["schedules"] = []
    quiesced = deepcopy(drained)
    quiesced["queue"]["paused"] = True
    observations = iter([baseline, drained, drained, quiesced])
    events: list[str] = []

    def observe(*_args: object, **_kwargs: object) -> dict[str, Any]:
        events.append("observe")
        return deepcopy(next(observations))

    def stop(*_args: object, **_kwargs: object) -> None:
        assert list((tmp_path / "state" / "staging").glob("*.control-intent.json"))
        events.append("cron-stop")

    class StopAfterProof(RuntimeError):
        pass

    def bookmark(*_args: object, **_kwargs: object) -> dict[str, str]:
        events.append("bookmark")
        assert events == [
            "observe", "cron-stop", "observe", "observe", "queue-pause",
            "observe", "bookmark",
        ]
        raise StopAfterProof

    monkeypatch.setattr(cutover, "_observe", observe)
    monkeypatch.setattr(cutover, "_set_schedules", stop)
    monkeypatch.setattr(
        cutover, "_queue_action",
        lambda *_a, **_k: events.append("queue-pause"),
    )
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cutover.migration, "time_travel_bookmark", bookmark)
    with pytest.raises(StopAfterProof):
        cutover.activate("staging", yes=True)


def test_new_receipt_pins_forward_repair_without_changing_config_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    assert value["schema_version"] == cutover.RECEIPT_SCHEMA
    assert value["recovery_policy"] == cutover.RECOVERY_POLICY
    assert value["config_digest"] == cutover.compiled_cutover_config_digest()
    assert "rollback_bookmark" in value


def test_continue_applies_forward_migration_and_never_restores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    no_remote_restore_intent(monkeypatch)
    applied = {"n": 0}

    class StopAfterAdvance(RuntimeError):
        pass

    live = state()
    live["queue"]["paused"] = True
    live["schedules"] = []
    live["pending_migrations"] = list(MIGRATION_NAMES[10:])
    exact = deepcopy(live)
    exact["pending_migrations"] = []
    exact["applied_migrations"] = list(MIGRATION_NAMES)
    exact["schema_observations"] = []
    exact["jobs"] = {key: 0 for key in live["jobs"]}
    observations = iter([live, exact])
    monkeypatch.setattr(cutover, "_status", lambda *_a, **_k: {"phase": "queue_paused"})
    monkeypatch.setattr(
        cutover, "_observe", lambda *_a, **_k: deepcopy(next(observations))
    )
    monkeypatch.setattr(
        cutover.migration, "revalidate_mutation_lease",
        lambda **_k: {"phase": "acquired", "remote_spawned": 0},
    )
    monkeypatch.setattr(
        cutover.migration, "_wrangler_prefix", lambda *_a, **_k: (["wrangler"], "DB")
    )
    monkeypatch.setattr(
        cutover.migration, "_apply_remote_migrations",
        lambda **_k: applied.__setitem__("n", applied["n"] + 1),
    )
    monkeypatch.setattr(
        cutover, "_advance",
        lambda *_a, **_k: (_ for _ in ()).throw(StopAfterAdvance()),
    )
    with pytest.raises(StopAfterAdvance):
        cutover._continue(value, token="token", account="account")
    assert applied["n"] == 1


def test_cutover_refuses_migration_until_cron_and_queue_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    no_remote_restore_intent(monkeypatch)
    monkeypatch.setattr(cutover, "_status", lambda *_a, **_k: {"phase": "queue_paused"})
    unsafe = state()
    unsafe["schedules"] = [{"cron": "* * * * *"}]
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: unsafe)
    applied = {"n": 0}
    monkeypatch.setattr(
        cutover.migration, "_apply_remote_migrations",
        lambda **_k: applied.__setitem__("n", 1),
    )
    with pytest.raises(cutover.JsdaCutoverError, match="stopped Cron and Queue"):
        cutover._continue(value, token="token", account="account")
    assert applied["n"] == 0


def test_post_pause_enqueue_race_blocks_activate_and_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    no_remote_restore_intent(monkeypatch)
    drained = state()
    paused = deepcopy(drained)
    paused["queue"]["paused"] = True
    raced = deepcopy(paused)
    raced["queue"]["backlog"] = 1
    calls = {"bookmark": 0, "apply": 0}
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cutover, "_queue_action", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cutover.migration, "time_travel_bookmark",
        lambda *_a, **_k: calls.__setitem__("bookmark", calls["bookmark"] + 1),
    )
    observations = iter([drained, drained, drained, raced])
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: deepcopy(next(observations)))
    with pytest.raises(cutover.JsdaCutoverError, match="Queue is not empty"):
        cutover.activate("staging", yes=True)
    assert calls["bookmark"] == 0

    value = receipt(monkeypatch, tmp_path)
    monkeypatch.setattr(cutover, "_status", lambda *_a, **_k: {"phase": "queue_paused"})
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: raced)
    monkeypatch.setattr(
        cutover.migration, "_apply_remote_migrations",
        lambda **_k: calls.__setitem__("apply", calls["apply"] + 1),
    )
    with pytest.raises(cutover.JsdaCutoverError, match="Queue is not empty"):
        cutover._continue(value, token="token", account="account")
    assert calls["apply"] == 0

    with pytest.raises(cutover.JsdaCutoverError, match="FORWARD_REPAIR_REQUIRED"):
        cutover.rollback("staging", value["run_id"], yes=True)
    assert calls["bookmark"] == 0


def test_start_persists_intended_deployed_sha_not_prior_version_tag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    captured: list[Mapping[str, Any]] = []

    def batch(_environment: str, statements: Any, **_kwargs: object):
        captured.extend(statements)
        return [{"success": True, "meta": {"changes": 1}}]

    monkeypatch.setattr(cutover, "_d1_batch", batch)
    monkeypatch.setattr(cutover, "_status", lambda *_a, **_k: {"phase": "queue_paused"})
    cutover._start(value, token="token", account="account")
    assert captured[0]["params"][5] == SHA
    assert captured[0]["params"][5] != value["prior_version_tag"]


def test_atomic_activation_batches_drain_control_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = {
        "environment": "staging", "source_sha": SHA,
        "config_digest": "sha256:" + "1" * 64,
        "run_id": "sha256:" + "2" * 64,
        "lease_owner": "apply:" + "3" * 32, "lease_fence": "4" * 64,
    }
    captured: list[Mapping[str, Any]] = []

    def batch(_environment: str, statements: Any, **_kwargs: object):
        captured.extend(statements)
        return [{"success": True, "meta": {"changes": 1}}] * 3

    monkeypatch.setattr(cutover, "_d1_batch", batch)
    cutover._activate_control(value, exact_live(), token="token", account="account")
    assert ["jsda_v3_drain_evidence" in row["sql"] for row in captured] == [True, False, False]
    assert "jsda_v3_cutover_control" in captured[1]["sql"]
    assert "jsda_v3_cutover_run" in captured[2]["sql"]


def test_production_missing_remote_staging_admission_holds_before_bookmark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: state("production"))
    monkeypatch.setattr(cutover, "_d1_rows", lambda *_a, **_k: [])
    calls = {"bookmark": 0}
    monkeypatch.setattr(
        cutover.migration, "time_travel_bookmark",
        lambda *_a, **_k: calls.__setitem__("bookmark", 1),
    )
    with pytest.raises(cutover.JsdaCutoverError, match="admission is absent"):
        cutover.activate("production", yes=True)
    assert calls["bookmark"] == 0


def test_generated_drain_digest_survives_activation_and_admits_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    store = SharedD1()
    evidence = {"phase": "deployed"}
    columns = cutover.RUN_COLUMNS.split(",")
    store.connection.execute(
        f"INSERT INTO jsda_v3_cutover_run({cutover.RUN_COLUMNS}) "
        f"VALUES ({','.join('?' for _ in columns)})",
        [
            value["run_id"], "staging", value["source_sha"],
            value["prior_version_id"], value["prior_deployment_id"],
            value["source_sha"], value["config_digest"],
            value["rollback_bookmark"], value["lease_owner"],
            value["lease_fence"], "deployed", cutover._digest(evidence),
            None, json.dumps(evidence), cutover._utc(),
        ],
    )
    monkeypatch.setattr(cutover, "_d1_batch", store.batch)
    monkeypatch.setattr(cutover, "_d1_rows", store.rows)
    cutover._activate_control(value, exact_live(), token="token", account="account")
    cutover._advance(
        value, "v3_active", "activated", token="token", account="account"
    )
    run = dict(store.connection.execute(
        "SELECT phase, drain_evidence_digest FROM jsda_v3_cutover_run WHERE run_id=?",
        [value["run_id"]],
    ).fetchone())
    control = dict(store.connection.execute(
        "SELECT phase, activated_source_sha, drain_evidence_digest "
        "FROM jsda_v3_cutover_control WHERE singleton=1"
    ).fetchone())
    assert run["phase"] == "activated"
    assert control["phase"] == "v3_active"
    assert cutover._DIGEST.fullmatch(str(run["drain_evidence_digest"] or ""))
    assert run["drain_evidence_digest"] == control["drain_evidence_digest"]
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: exact_live())
    cutover._require_staging_admission(SHA, token="token", account="account")


def test_rollback_and_legacy_intent_refuse_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    store = SharedD1()
    store.insert_after_bookmark()
    store.restore()
    assert store.payloads() == {"before-bookmark"}
    assert store.restore_calls == 1
    store.insert_after_bookmark()
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    monkeypatch.setattr(cutover, "_load_receipt", lambda *_a, **_k: value)
    monkeypatch.setattr(cutover, "_d1_batch", store.batch)
    monkeypatch.setattr(cutover, "_d1_rows", store.rows)
    events: list[str] = []

    def command(args: Any, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        if "time-travel" in argv and "restore" in argv:
            store.restore()
            events.append("restore")
        events.append("wrangler")
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(cutover, "_command", command)
    monkeypatch.setattr(cutover.cloudflare, "_command", command)
    monkeypatch.setattr(
        cutover, "_set_schedules", lambda *_a, **_k: events.append("cron")
    )
    monkeypatch.setattr(
        cutover, "_queue_action", lambda *_a, **_k: events.append("queue")
    )
    monkeypatch.setattr(
        cutover.migration, "release_mutation_lease",
        lambda **_k: events.append("release"),
    )
    monkeypatch.setattr(
        cutover.migration, "renew_mutation_lease",
        lambda **_k: events.append("renew"),
    )
    monkeypatch.setattr(
        cutover.migration, "resume_owned_mutation_lease",
        lambda **_k: events.append("reacquire"),
    )
    monkeypatch.setattr(
        cutover, "_remove_control_intent", lambda *_a: events.append("remove")
    )
    with pytest.raises(cutover.JsdaCutoverError, match="FORWARD_REPAIR_REQUIRED"):
        cutover.rollback("staging", value["run_id"], yes=True)
    assert events == []
    assert store.restore_calls == 1
    assert store.payloads() == {
        "before-bookmark", "premium-after", "receipt-after",
    }

    cutover._evidence(value, "rollback-intent", {"target": BASELINE, "undo": UNDO})
    with pytest.raises(cutover.JsdaCutoverError, match="FORWARD_REPAIR_REQUIRED"):
        cutover.resume("staging", value["run_id"], yes=True)
    with pytest.raises(cutover.JsdaCutoverError, match="FORWARD_REPAIR_REQUIRED"):
        cutover.activate("staging", yes=True)
    assert events == []
    assert store.restore_calls == 1
    intent = cutover._receipt_path("staging", value["run_id"]).with_name(
        f"{cutover._receipt_path('staging', value['run_id']).stem}.rollback-intent.json"
    )
    assert intent.exists()
    assert store.payloads() == {
        "before-bookmark", "premium-after", "receipt-after",
    }


def test_remote_restore_pending_blocks_new_activate_before_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    pending = json.dumps({
        "phase": "queue_paused",
        "staging_drill": "restore_pending",
        "baseline": BASELINE,
        "undo": UNDO,
    })

    def rows(_environment: str, sql: str, **_kwargs: object) -> list[dict[str, Any]]:
        if "sqlite_master" in sql:
            return [{"name": "jsda_v3_cutover_run"}]
        return [{"run_id": "sha256:" + "a" * 64, "document_json": pending}]

    monkeypatch.setattr(cutover, "_d1_rows", rows)
    events: list[str] = []
    monkeypatch.setattr(
        cutover, "_set_schedules", lambda *_a, **_k: events.append("cron")
    )
    monkeypatch.setattr(
        cutover.migration, "acquire_authorized_mutation_lease",
        lambda **_k: events.append("acquire"),
    )
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: state())
    with pytest.raises(cutover.JsdaCutoverError, match="FORWARD_REPAIR_REQUIRED"):
        cutover.activate("staging", yes=True)
    assert events == []


def test_check_remains_available_with_unresolved_intent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    cutover._evidence(value, "rollback-intent", {"target": BASELINE, "undo": UNDO})
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    live = exact_live()
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: deepcopy(live))
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    result = cutover.check("staging")
    assert result["status"] == "CHECKED"
    assert result["state"]["cutover_phase"] == "v3_active"


def test_normal_deploy_commands_cannot_bypass_operator() -> None:
    package = json.loads((cutover.WORKER / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]
    assert "activate_jsda_v3_cutover.py" in scripts["deploy"]
    assert "activate_jsda_v3_cutover.py" in scripts["deploy:staging"]
    assert scripts["deploy:unsafe-dev"].startswith("wrangler deploy")
