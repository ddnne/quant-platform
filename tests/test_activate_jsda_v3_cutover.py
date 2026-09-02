"""Essential invariants for the single-operator Cloudflare cutover."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
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


def test_staging_drill_persists_remote_and_local_undo_before_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cutover.migration, "time_travel_bookmark",
        lambda *_a, **_k: {"bookmark": UNDO},
    )
    events: list[str] = []
    monkeypatch.setattr(
        cutover, "_record_run_document",
        lambda *_a, **_k: events.append("remote-intent"),
    )

    def restore(_environment: str, bookmark: str, **_kwargs: object) -> str:
        events.append(f"restore:{bookmark}")
        base = cutover._receipt_path("staging", value["run_id"])
        if bookmark == BASELINE:
            assert events[0] == "remote-intent"
            assert base.with_name(f"{base.stem}.staging-intent.json").exists()
            return UNDO
        return BASELINE

    monkeypatch.setattr(cutover, "_restore_bookmark", restore)
    cutover._staging_drill(value, token="token", account="account")
    assert events[:3] == ["remote-intent", f"restore:{BASELINE}", f"restore:{UNDO}"]
    assert events[-1] == "remote-intent"


def test_staging_crash_at_baseline_recovers_from_persisted_undo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    cutover._evidence(value, "staging-intent", {"baseline": BASELINE, "undo": UNDO})
    monkeypatch.setattr(
        cutover.migration, "time_travel_bookmark",
        lambda *_a, **_k: {"bookmark": BASELINE},
    )
    restored: list[str] = []
    monkeypatch.setattr(
        cutover, "_restore_bookmark",
        lambda _environment, bookmark, **_kwargs: restored.append(bookmark) or BASELINE,
    )
    monkeypatch.setattr(cutover, "_record_run_document", lambda *_a, **_k: None)
    cutover._recover_staging_drill(value, token="token", account="account")
    assert restored == [UNDO]


def test_cutover_refuses_time_travel_drill_until_cron_and_queue_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    monkeypatch.setattr(cutover, "_status", lambda *_a, **_k: {"phase": "queue_paused"})
    unsafe = state()
    unsafe["schedules"] = [{"cron": "* * * * *"}]
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: unsafe)
    called = {"drill": 0}
    monkeypatch.setattr(
        cutover, "_staging_drill", lambda *_a, **_k: called.__setitem__("drill", 1)
    )
    with pytest.raises(cutover.JsdaCutoverError, match="stopped Cron and Queue"):
        cutover._continue(value, token="token", account="account")
    assert called["drill"] == 0


def test_post_pause_enqueue_race_blocks_activate_resume_and_rollback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cutover, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    drained = state()
    paused = deepcopy(drained)
    paused["queue"]["paused"] = True
    raced = deepcopy(paused)
    raced["queue"]["backlog"] = 1
    calls = {"bookmark": 0, "drill": 0}
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
        cutover, "_staging_drill",
        lambda *_a, **_k: calls.__setitem__("drill", calls["drill"] + 1),
    )
    with pytest.raises(cutover.JsdaCutoverError, match="Queue is not empty"):
        cutover._continue(value, token="token", account="account")
    assert calls["drill"] == 0

    monkeypatch.setattr(cutover, "_load_receipt", lambda *_a, **_k: value)
    observations = iter([drained, drained, drained, raced])
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: deepcopy(next(observations)))
    with pytest.raises(cutover.JsdaCutoverError, match="Queue is not empty"):
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_remote_staging_admission_uses_activated_run_and_live_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = cutover.compiled_cutover_config_digest()
    drain = "sha256:" + "d" * 64

    def rows(_environment: str, sql: str, **_kwargs: object):
        if "jsda_v3_cutover_run" in sql:
            return [{
                "source_sha": SHA, "selected_version_tag": SHA,
                "cutover_config_digest": digest,
                "drain_evidence_digest": drain, "phase": "activated",
            }]
        return [{
            "phase": "v3_active", "activated_source_sha": SHA,
            "cutover_config_digest": digest, "drain_evidence_digest": drain,
        }]

    monkeypatch.setattr(cutover, "_d1_rows", rows)
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: exact_live())
    cutover._require_staging_admission(SHA, token="token", account="account")


def test_rollback_stops_and_drains_before_persisted_undo_and_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    monkeypatch.setattr(cutover, "_load_receipt", lambda *_a, **_k: value)
    initial = state("production")
    drained = deepcopy(initial)
    drained["schedules"] = []
    quiesced = deepcopy(drained)
    quiesced["queue"]["paused"] = True
    observations = iter([initial, drained, drained, quiesced])
    events: list[str] = []

    def observe(*_args: object, **_kwargs: object) -> dict[str, Any]:
        events.append("observe")
        return deepcopy(next(observations))

    monkeypatch.setattr(cutover, "_observe", observe)
    monkeypatch.setattr(cutover, "_set_schedules", lambda *_a, **_k: events.append("cron"))
    monkeypatch.setattr(cutover, "_queue_action", lambda *_a, **_k: events.append("queue-pause"))
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        cutover.migration, "time_travel_bookmark",
        lambda *_a, **_k: events.append("bookmark") or {"bookmark": UNDO},
    )
    monkeypatch.setattr(
        cutover, "_evidence",
        lambda _receipt, name, _doc: events.append(f"evidence:{name}"),
    )
    monkeypatch.setattr(
        cutover, "_restore_bookmark", lambda *_a, **_k: events.append("restore") or UNDO
    )
    monkeypatch.setattr(
        cutover, "_selected",
        lambda *_a, **_k: {
            "version_id": value["prior_version_id"],
            "deployment_id": value["prior_deployment_id"],
            "version_tag": value["prior_version_tag"],
        },
    )
    monkeypatch.setattr(
        cutover, "_queue", lambda *_a, **_k: {"paused": value["prior_queue_paused"]}
    )
    monkeypatch.setattr(
        cutover.migration, "observe_mutation_lease_authority", lambda **_k: None
    )
    monkeypatch.setattr(cutover, "_remove_control_intent", lambda *_a: events.append("remove"))
    result = cutover.rollback("staging", value["run_id"], yes=True)
    assert result["status"] == "ROLLED_BACK"
    assert events.index("bookmark") > events.index("queue-pause")
    assert events.index("evidence:rollback-intent") < events.index("restore")
    assert events.index("restore") < events.index("evidence:rollback-undo")


def test_rollback_resume_at_target_consumes_existing_intent_without_second_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = receipt(monkeypatch, tmp_path)
    cutover._evidence(
        value, "rollback-intent", {"target": BASELINE, "undo": UNDO}
    )
    monkeypatch.setattr(cutover, "_credentials", lambda: ("token", "account"))
    monkeypatch.setattr(cutover, "_load_receipt", lambda *_a, **_k: value)
    quiesced = state()
    quiesced["queue"]["paused"] = True
    monkeypatch.setattr(cutover, "_observe", lambda *_a, **_k: deepcopy(quiesced))
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        cutover.migration, "time_travel_bookmark",
        lambda *_a, **_k: {"bookmark": BASELINE},
    )
    restores = {"count": 0}
    monkeypatch.setattr(
        cutover, "_restore_bookmark",
        lambda *_a, **_k: restores.__setitem__("count", restores["count"] + 1),
    )
    monkeypatch.setattr(
        cutover, "_selected",
        lambda *_a, **_k: {
            "version_id": value["prior_version_id"],
            "deployment_id": value["prior_deployment_id"],
            "version_tag": value["prior_version_tag"],
        },
    )
    monkeypatch.setattr(
        cutover, "_queue", lambda *_a, **_k: {"paused": value["prior_queue_paused"]}
    )
    monkeypatch.setattr(cutover, "_set_schedules", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cutover.migration, "observe_mutation_lease_authority", lambda **_k: None
    )
    result = cutover.rollback("staging", value["run_id"], yes=True)
    assert result["status"] == "ROLLED_BACK"
    assert restores["count"] == 0


def test_normal_deploy_commands_cannot_bypass_operator() -> None:
    package = json.loads((cutover.WORKER / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]
    assert "activate_jsda_v3_cutover.py" in scripts["deploy"]
    assert "activate_jsda_v3_cutover.py" in scripts["deploy:staging"]
    assert scripts["deploy:unsafe-dev"].startswith("wrangler deploy")
