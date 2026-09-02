#!/usr/bin/env python3
"""Single-operator JSDA v3 cutover for Cloudflare.

The path is intentionally small: stop Cron, observe a stable drain, pause the
Queue, persist a Time Travel rollback point, migrate under one D1 lease,
verify, deploy, activate, then restore the prior Cron/Queue state.  Failures
stay stopped and require the explicit --rollback command.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import apply_ingestion_d1_migrations as migration
from scripts import _jsda_cutover_cloudflare as cloudflare
from scripts.d1_ingestion_migration_validation import MIGRATION_NAMES
from scripts.receipt_authority_pending_gate import (
    PendingReceiptAuthorityError,
    _require_exact_clean_source,
)
from scripts.receipt_authority_pending_live_acceptance import (
    ReceiptPendingLiveAcceptanceError,
    _require_official_origin_main,
)
ROOT = Path(__file__).resolve().parents[1]
WORKER = cloudflare.WORKER
SURFACE = cloudflare.SURFACE
JsdaCutoverError = cloudflare.JsdaCutoverError
_command = cloudflare._command
_config = cloudflare._config
_d1_batch = cloudflare._d1_batch
_d1_rows = cloudflare._d1_rows
_queue = cloudflare._queue
_queue_action = cloudflare._queue_action
_schedules = cloudflare._schedules
_selected = cloudflare._selected
_set_schedules = cloudflare._set_schedules
_wrangler = cloudflare._wrangler
_wrangler_json = cloudflare._wrangler_json
compiled_cutover_config_digest = cloudflare.compiled_cutover_config_digest
STATE_ROOT = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") \
    / "quant-platform" / "jsda-cutover"
MAX_RECEIPT = 64 * 1024
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OWNER = re.compile(r"^apply:[0-9a-f]{32}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_BOOKMARK = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{32}$")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_bytes(value)).hexdigest()


def _credentials() -> tuple[str, str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account:
        raise JsdaCutoverError("Cloudflare credentials are required")
    return token, account


def _migration_runner(token: str, account: str):
    def run(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        del cwd
        return _command(argv, environment="staging", token=token,
                        account=account, timeout=700)
    return run


def _source_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    sha = result.stdout.strip()
    if result.returncode or not _SHA.fullmatch(sha):
        raise JsdaCutoverError("source SHA is invalid")
    try:
        _require_exact_clean_source(sha)
        _require_official_origin_main(sha)
    except (PendingReceiptAuthorityError, ReceiptPendingLiveAcceptanceError) as exc:
        raise JsdaCutoverError("source is not current clean origin/main") from exc
    return sha


def _observe(environment: str, *, token: str, account: str) -> dict[str, Any]:
    state = migration.observe_migration_state(
        environment, runner=_migration_runner(token, account)
    )
    queue = _queue(str(SURFACE[environment]["queue"]), token=token, account=account)
    selected = _selected(environment, token=token, account=account)
    tables = {
        row["name"] for row in _d1_rows(
            environment, "SELECT name FROM sqlite_master WHERE type='table'",
            token=token, account=account,
        ) if isinstance(row.get("name"), str)
    }
    jobs: dict[str, int | None] = {}
    for table in (
        "jsda_acquisition_jobs", "jsda_acquisition_jobs_v2",
        "jsda_acquisition_jobs_v3",
    ):
        if table not in tables:
            jobs[table] = None
        else:
            row = _d1_rows(
                environment,
                f"SELECT COUNT(*) AS n FROM {table} WHERE state IN "
                "('pending','queued','running','retry','waiting_children','failed_transient')",
                token=token, account=account,
            )
            jobs[table] = int(row[0]["n"])
    control = None
    if "jsda_v3_cutover_control" in tables:
        rows = _d1_rows(
            environment, "SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1",
            token=token, account=account,
        )
        control = rows[0].get("phase") if rows else None
    return {
        "source_sha": _source_sha(),
        **selected,
        **state,
        "queue": queue,
        "schedules": _schedules(environment, token=token, account=account),
        "jobs": jobs,
        "cutover_phase": control,
    }


def _require_drained(state: Mapping[str, Any], *, after_migration: bool) -> None:
    queue = state.get("queue")
    jobs = state.get("jobs")
    if not isinstance(queue, Mapping) or queue.get("backlog") != 0:
        raise JsdaCutoverError("main Queue is not empty")
    if not isinstance(jobs, Mapping):
        raise JsdaCutoverError("job state is unobserved")
    for table, value in jobs.items():
        if value is None and not after_migration:
            continue
        if value != 0:
            raise JsdaCutoverError(f"{table} is not drained")
    if after_migration and (
        state.get("pending_migrations") != []
        or state.get("applied_migrations") != list(MIGRATION_NAMES)
        or state.get("schema_observations") != []
    ):
        raise JsdaCutoverError("canonical migrations are not exact")


def _root() -> Path:
    root = STATE_ROOT.expanduser().absolute()
    if ROOT.resolve() in root.parents or root == ROOT.resolve():
        raise JsdaCutoverError("receipt store must be outside the worktree")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root.resolve()


def _receipt_path(environment: str, run_id: str) -> Path:
    directory = _root() / environment
    directory.mkdir(exist_ok=True, mode=0o700)
    return directory / f"{run_id.removeprefix('sha256:')}.json"


def _intent_path(environment: str, source_sha: str) -> Path:
    return _receipt_path(environment, source_sha).with_suffix(".control-intent.json")


def _create_only(path: Path, value: Mapping[str, Any]) -> None:
    encoded = _bytes(value) + b"\n"
    if len(encoded) > MAX_RECEIPT:
        raise JsdaCutoverError("external evidence is too large")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != encoded:
                raise JsdaCutoverError("external evidence already differs")
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _build_receipt(
    environment: str, intent: Mapping[str, Any], travel: Mapping[str, str],
) -> dict[str, Any]:
    core = {
        "schema_version": "jsda-cutover/v2",
        "environment": environment,
        "source_sha": intent["source_sha"],
        "prior_version_id": intent["prior_version_id"],
        "prior_deployment_id": intent["prior_deployment_id"],
        "prior_version_tag": intent["prior_version_tag"],
        "prior_schedules": intent["prior_schedules"],
        "prior_queue_paused": intent["prior_queue_paused"],
        "prior_applied_migrations": intent["prior_applied_migrations"],
        "rollback_bookmark": travel["bookmark"],
        "database": dict(travel),
        "config_digest": intent["config_digest"],
        "control_intent_digest": intent["intent_digest"],
        "lease_owner": intent["lease_owner"],
        "lease_fence": intent["lease_fence"],
        "created_at": _utc(),
    }
    run_id = _digest(core)
    unsigned = {**core, "run_id": run_id}
    return {**unsigned, "receipt_digest": _digest(unsigned)}


def _control_intent(environment: str, state: Mapping[str, Any]) -> dict[str, Any]:
    source_sha = str(state["source_sha"])
    path = _intent_path(environment, source_sha)
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JsdaCutoverError("control intent is malformed") from exc
    else:
        core = {
            "schema_version": "jsda-control-intent/v1",
            "environment": environment,
            "source_sha": source_sha,
            "config_digest": compiled_cutover_config_digest(),
            "prior_version_id": state["version_id"],
            "prior_deployment_id": state["deployment_id"],
            "prior_version_tag": state["version_tag"],
            "prior_schedules": state["schedules"],
            "prior_queue_paused": state["queue"]["paused"],
            "prior_applied_migrations": state["applied_migrations"],
            "lease_owner": f"apply:{secrets.token_hex(16)}",
            "lease_fence": secrets.token_hex(32),
            "created_at": _utc(),
        }
        value = {**core, "intent_digest": _digest(core)}
        _create_only(path, value)
    if not isinstance(value, dict):
        raise JsdaCutoverError("control intent is malformed")
    unsigned = {key: item for key, item in value.items() if key != "intent_digest"}
    if (
        value.get("environment") != environment
        or value.get("source_sha") != source_sha
        or value.get("config_digest") != compiled_cutover_config_digest()
        or value.get("intent_digest") != _digest(unsigned)
        or not _OWNER.fullmatch(str(value.get("lease_owner") or ""))
        or not _NONCE.fullmatch(str(value.get("lease_fence") or ""))
    ):
        raise JsdaCutoverError("control intent binding is invalid")
    return value


def _remove_control_intent(receipt: Mapping[str, Any]) -> None:
    path = _intent_path(str(receipt["environment"]), str(receipt["source_sha"]))
    if not path.exists():
        return
    intent = json.loads(path.read_text(encoding="utf-8"))
    if intent.get("intent_digest") != receipt.get("control_intent_digest"):
        raise JsdaCutoverError("control intent differs from the receipt")
    path.unlink()


def _save_receipt(receipt: Mapping[str, Any]) -> Path:
    path = _receipt_path(str(receipt["environment"]), str(receipt["run_id"]))
    _create_only(path, receipt)
    return path


def _load_receipt(environment: str, run_id: str) -> dict[str, Any]:
    path = _receipt_path(environment, run_id)
    if (
        not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_RECEIPT
        or path.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise JsdaCutoverError("external receipt is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsdaCutoverError("external receipt is malformed") from exc
    if not isinstance(value, dict):
        raise JsdaCutoverError("external receipt is malformed")
    unsigned = {key: item for key, item in value.items() if key != "receipt_digest"}
    if (
        value.get("environment") != environment or value.get("run_id") != run_id
        or value.get("receipt_digest") != _digest(unsigned)
        or value.get("config_digest") != compiled_cutover_config_digest()
    ):
        raise JsdaCutoverError("external receipt binding is invalid")
    return value


def _evidence(receipt: Mapping[str, Any], name: str, document: Mapping[str, Any]) -> None:
    path = _receipt_path(str(receipt["environment"]), str(receipt["run_id"]))
    _create_only(
        path.with_name(f"{path.stem}.{name}.json"),
        {
            "run_id": receipt["run_id"], "receipt_digest": receipt["receipt_digest"],
            "name": name, "document": dict(document),
        },
    )


def _read_evidence(
    receipt: Mapping[str, Any], name: str,
) -> dict[str, Any] | None:
    base = _receipt_path(str(receipt["environment"]), str(receipt["run_id"]))
    path = base.with_name(f"{base.stem}.{name}.json")
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_RECEIPT:
        raise JsdaCutoverError(f"{name} evidence is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsdaCutoverError(f"{name} evidence is malformed") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("run_id") != receipt["run_id"]
        or value.get("receipt_digest") != receipt["receipt_digest"]
        or value.get("name") != name
        or not isinstance(value.get("document"), Mapping)
    ):
        raise JsdaCutoverError(f"{name} evidence binding is invalid")
    return dict(value["document"])


def _restore_bookmark(
    environment: str, bookmark: str, *, token: str, account: str,
) -> str:
    result = _wrangler_json(
        ["d1", "time-travel", "restore", str(SURFACE[environment]["d1"]),
         "--bookmark", bookmark, "--json"],
        environment=environment, token=token, account=account,
    )
    if not isinstance(result, Mapping) or result.get("bookmark") != bookmark:
        raise JsdaCutoverError("Time Travel restored the wrong bookmark")
    previous = result.get("previous_bookmark")
    if not isinstance(previous, str) or not _BOOKMARK.fullmatch(previous):
        raise JsdaCutoverError("Time Travel undo bookmark is missing")
    return previous


def _staging_drill(
    receipt: Mapping[str, Any], *, token: str, account: str,
) -> None:
    if receipt["environment"] != "staging":
        return
    proof = _receipt_path("staging", str(receipt["run_id"])).with_name(
        f"{str(receipt['run_id']).removeprefix('sha256:')}.staging-proof.json"
    )
    if proof.exists():
        return
    runner = _migration_runner(token, account)
    undo = migration.time_travel_bookmark("staging", runner=runner)["bookmark"]
    baseline = str(receipt["rollback_bookmark"])
    intent = {
        "phase": "queue_paused", "staging_drill": "restore_pending",
        "baseline": baseline, "undo": undo,
    }
    _record_run_document(
        receipt, "queue_paused", intent, token=token, account=account
    )
    _evidence(receipt, "staging-intent", {"baseline": baseline, "undo": undo})
    returned = _restore_bookmark("staging", baseline, token=token, account=account)
    if returned != undo:
        raise JsdaCutoverError("staging restore returned the wrong undo bookmark")
    _evidence(receipt, "staging-restored", {"baseline": baseline, "undo": undo})
    returned = _restore_bookmark("staging", undo, token=token, account=account)
    if returned != baseline:
        raise JsdaCutoverError("staging undo did not return to the baseline")
    _create_only(proof, {"run_id": receipt["run_id"], "baseline": baseline, "undo": undo})
    _record_run_document(
        receipt, "queue_paused",
        {
            "phase": "queue_paused", "staging_drill": "verified",
            "baseline": baseline, "undo": undo,
        },
        token=token, account=account,
    )


def _recover_staging_drill(
    receipt: Mapping[str, Any], *, token: str, account: str,
) -> None:
    if receipt["environment"] != "staging":
        return
    base = _receipt_path("staging", str(receipt["run_id"]))
    intent_path = base.with_name(f"{base.stem}.staging-intent.json")
    proof_path = base.with_name(f"{base.stem}.staging-proof.json")
    if not intent_path.exists() or proof_path.exists():
        return
    try:
        intent = json.loads(intent_path.read_text(encoding="utf-8"))["document"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise JsdaCutoverError("staging Time Travel intent is malformed") from exc
    baseline = str(receipt["rollback_bookmark"])
    undo = intent.get("undo") if isinstance(intent, Mapping) else None
    if (
        not isinstance(intent, Mapping)
        or intent.get("baseline") != baseline
        or not isinstance(undo, str)
    ):
        raise JsdaCutoverError("staging Time Travel intent is invalid")
    current = migration.time_travel_bookmark(
        "staging", runner=_migration_runner(token, account)
    )["bookmark"]
    if current == undo:
        _create_only(
            proof_path,
            {"run_id": receipt["run_id"], "baseline": baseline, "undo": undo},
        )
        _record_run_document(
            receipt, "queue_paused",
            {
                "phase": "queue_paused", "staging_drill": "verified",
                "baseline": baseline, "undo": undo,
            },
            token=token, account=account,
        )
        return
    if current != baseline:
        raise JsdaCutoverError("staging Time Travel recovery is ambiguous")
    returned = _restore_bookmark("staging", undo, token=token, account=account)
    if returned != baseline:
        raise JsdaCutoverError("staging Time Travel recovery returned wrong bookmark")
    _create_only(
        proof_path, {"run_id": receipt["run_id"], "baseline": baseline, "undo": undo}
    )
    _record_run_document(
        receipt, "queue_paused",
        {
            "phase": "queue_paused", "staging_drill": "verified",
            "baseline": baseline, "undo": undo,
        },
        token=token, account=account,
    )


RUN_COLUMNS = (
    "run_id,environment,source_sha,selected_version_id,selected_deployment_id,"
    "selected_version_tag,cutover_config_digest,rollback_bookmark,owner,fence,"
    "phase,evidence_digest,drain_evidence_digest,document_json,updated_at"
)
def _status(
    receipt: Mapping[str, Any], *, token: str, account: str,
) -> dict[str, Any] | None:
    rows = _d1_rows(
        str(receipt["environment"]),
        f"SELECT {RUN_COLUMNS} FROM jsda_v3_cutover_run WHERE run_id=?",
        params=[receipt["run_id"]], token=token, account=account,
    )
    if len(rows) > 1:
        raise JsdaCutoverError("cutover run is ambiguous")
    return rows[0] if rows else None


def _start(receipt: Mapping[str, Any], *, token: str, account: str) -> None:
    environment = str(receipt["environment"])
    evidence = {
        "phase": "queue_paused",
        "rollback_bookmark": receipt["rollback_bookmark"],
        "cron_stopped": True,
        "queue_paused": True,
    }
    document = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    params = [
        receipt["run_id"], environment, receipt["source_sha"],
        receipt["prior_version_id"], receipt["prior_deployment_id"],
        receipt["source_sha"], receipt["config_digest"],
        receipt["rollback_bookmark"], receipt["lease_owner"],
        receipt["lease_fence"], "queue_paused", _digest(evidence),
        None, document, _utc(),
    ]
    _d1_batch(
        environment,
        [{"sql": f"INSERT OR IGNORE INTO jsda_v3_cutover_run({RUN_COLUMNS}) VALUES ({','.join('?' for _ in params)})", "params": params}],
        token=token, account=account,
    )
    if _status(receipt, token=token, account=account) is None:
        raise JsdaCutoverError("cutover run was not persisted")


def _record_run_document(
    receipt: Mapping[str, Any], phase: str, document: Mapping[str, Any],
    *, token: str, account: str,
) -> None:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
    result = _d1_batch(
        str(receipt["environment"]),
        [{
            "sql": "UPDATE jsda_v3_cutover_run SET evidence_digest=?,"
                   "document_json=?,updated_at=? WHERE run_id=? AND phase=? "
                   "AND owner=? AND fence=?",
            "params": [
                _digest(document), encoded, _utc(), receipt["run_id"], phase,
                receipt["lease_owner"], receipt["lease_fence"],
            ],
        }],
        token=token, account=account,
    )[0]
    meta = result.get("meta")
    if not isinstance(meta, Mapping) or meta.get("changes") != 1:
        raise JsdaCutoverError("cutover evidence CAS failed")


def _advance(
    receipt: Mapping[str, Any], from_phase: str, to_phase: str,
    *, token: str, account: str, drain_digest: str | None = None,
) -> None:
    document = {"phase": to_phase}
    result = _d1_batch(
        str(receipt["environment"]),
        [{
            "sql": "UPDATE jsda_v3_cutover_run SET phase=?,evidence_digest=?,"
                   "drain_evidence_digest=?,document_json=?,updated_at=? "
                   "WHERE run_id=? AND phase=? AND owner=? AND fence=?",
            "params": [
                to_phase, _digest(document), drain_digest,
                json.dumps(document, separators=(",", ":")), _utc(),
                receipt["run_id"], from_phase, receipt["lease_owner"],
                receipt["lease_fence"],
            ],
        }],
        token=token, account=account,
    )[0]
    changes = result.get("meta", {}).get("changes") if isinstance(result.get("meta"), Mapping) else None
    if changes != 1:
        raise JsdaCutoverError("cutover phase CAS failed")


def _lease_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return migration._identity(str(receipt["environment"]), str(receipt["source_sha"]))


def _activate_control(
    receipt: Mapping[str, Any], state: Mapping[str, Any], *, token: str,
    account: str,
) -> None:
    _require_drained(state, after_migration=True)
    queue = state["queue"]
    document = {
        "schema_version": "jsda-v3-drain/v2",
        "source_sha": receipt["source_sha"],
        "config_digest": receipt["config_digest"],
        "queue_backlog": queue["backlog"],
        "jobs": state["jobs"],
    }
    drain = _digest(document)
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
    results = _d1_batch(
        str(receipt["environment"]),
        [
            {"sql": "INSERT OR IGNORE INTO jsda_v3_drain_evidence(drain_evidence_digest,observed_at,document_json) VALUES (?,?,?)", "params": [drain, _utc(), encoded]},
            {"sql": "UPDATE jsda_v3_cutover_control SET phase='v3_active',activated_at=?,activated_source_sha=?,cutover_config_digest=?,drain_evidence_digest=? WHERE singleton=1 AND phase='bridge'", "params": [_utc(), receipt["source_sha"], receipt["config_digest"], drain]},
            {"sql": "UPDATE jsda_v3_cutover_run SET phase='v3_active',evidence_digest=?,drain_evidence_digest=?,document_json=?,updated_at=? WHERE run_id=? AND phase='deployed' AND owner=? AND fence=?", "params": [_digest({"phase": "v3_active"}), drain, encoded, _utc(), receipt["run_id"], receipt["lease_owner"], receipt["lease_fence"]]},
        ],
        token=token, account=account,
    )
    for result in results[1:]:
        meta = result.get("meta")
        if not isinstance(meta, Mapping) or meta.get("changes") != 1:
            raise JsdaCutoverError("atomic cutover activation failed")


def _require_staging_admission(
    source_sha: str, *, token: str, account: str,
) -> None:
    runs = _d1_rows(
        "staging",
        "SELECT source_sha,selected_version_tag,cutover_config_digest,"
        "drain_evidence_digest,phase FROM jsda_v3_cutover_run "
        "WHERE source_sha=? AND phase='activated' ORDER BY updated_at DESC LIMIT 1",
        params=[source_sha], token=token, account=account,
    )
    controls = _d1_rows(
        "staging",
        "SELECT phase,activated_source_sha,cutover_config_digest,"
        "drain_evidence_digest FROM jsda_v3_cutover_control WHERE singleton=1",
        token=token, account=account,
    )
    if len(runs) != 1 or len(controls) != 1:
        raise JsdaCutoverError("staging cutover admission is absent")
    run, control = runs[0], controls[0]
    config = compiled_cutover_config_digest()
    if (
        run.get("source_sha") != source_sha
        or run.get("selected_version_tag") != source_sha
        or run.get("cutover_config_digest") != config
        or not _DIGEST.fullmatch(str(run.get("drain_evidence_digest") or ""))
        or control.get("phase") != "v3_active"
        or control.get("activated_source_sha") != source_sha
        or control.get("cutover_config_digest") != config
        or control.get("drain_evidence_digest") != run.get("drain_evidence_digest")
    ):
        raise JsdaCutoverError("staging cutover admission is not exact")
    live = _observe("staging", token=token, account=account)
    _require_drained(live, after_migration=True)
    queue = live.get("queue")
    if (
        live["version_tag"] != source_sha
        or live["schedules"] != []
        or live.get("cutover_phase") != "v3_active"
        or not isinstance(queue, Mapping)
        or queue.get("paused") is not False
    ):
        raise JsdaCutoverError("staging live smoke is not exact")


def _continue(
    receipt: Mapping[str, Any], *, token: str, account: str,
) -> dict[str, Any]:
    environment = str(receipt["environment"])
    runner = _migration_runner(token, account)
    while True:
        run = _status(receipt, token=token, account=account)
        if run is None:
            raise JsdaCutoverError("cutover run is missing")
        phase = str(run["phase"])
        state = _observe(environment, token=token, account=account)
        if state["source_sha"] != receipt["source_sha"]:
            raise JsdaCutoverError("source SHA changed during cutover")
        if phase == "queue_paused":
            if state["schedules"] or not state["queue"]["paused"]:
                raise JsdaCutoverError("migration requires stopped Cron and Queue")
            _require_drained(state, after_migration=False)
            _staging_drill(receipt, token=token, account=account)
            identity = _lease_identity(receipt)
            lease = migration.revalidate_mutation_lease(
                identity=identity, environment=environment,
                owner=str(receipt["lease_owner"]), nonce=str(receipt["lease_fence"]),
                runner=runner, require_unexpired=False,
            )
            if state["pending_migrations"]:
                if lease["phase"] != "acquired" or lease["remote_spawned"] != 0:
                    raise JsdaCutoverError("migration lease requires explicit recovery")
                prefix, binding = migration._wrangler_prefix(environment)
                migration._apply_remote_migrations(
                    environment=environment, binding=binding, prefix=prefix,
                    identity=identity, owner=str(receipt["lease_owner"]),
                    nonce=str(receipt["lease_fence"]), runner=runner,
                )
            exact = _observe(environment, token=token, account=account)
            _require_drained(exact, after_migration=True)
            _advance(receipt, phase, "bridge_established", token=token, account=account)
        elif phase == "bridge_established":
            if state["version_tag"] != receipt["source_sha"]:
                result = _command(
                    [str(_wrangler()), "deploy", "--message", str(receipt["source_sha"]),
                     "--tag", str(receipt["source_sha"]), *_config(environment)],
                    environment=environment, token=token, account=account, timeout=300,
                )
                if result.returncode:
                    raise JsdaCutoverError("JSDA deploy failed")
            deployed = _observe(environment, token=token, account=account)
            if deployed["version_tag"] != receipt["source_sha"]:
                raise JsdaCutoverError("deployed Worker source is not exact")
            _advance(receipt, phase, "deployed", token=token, account=account)
        elif phase == "deployed":
            _activate_control(receipt, state, token=token, account=account)
        elif phase == "v3_active":
            desired_pause = receipt["prior_queue_paused"] is True
            if state["queue"]["paused"] is not desired_pause:
                _queue_action(
                    environment, "pause-delivery" if desired_pause else "resume-delivery",
                    token=token, account=account,
                )
            if state["schedules"] != receipt["prior_schedules"]:
                _set_schedules(
                    environment, list(receipt["prior_schedules"]), token=token,
                    account=account,
                )
            _advance(receipt, phase, "activated", token=token, account=account)
        elif phase == "activated":
            lease = migration.observe_mutation_lease_authority(
                environment=environment, runner=runner
            )
            if lease and lease.get("owner") == receipt["lease_owner"]:
                migration.release_mutation_lease(
                    environment=environment, owner=str(receipt["lease_owner"]),
                    nonce=str(receipt["lease_fence"]), runner=runner,
                )
            return {"status": "ACTIVATED", "run_id": receipt["run_id"]}
        else:
            raise JsdaCutoverError("cutover phase is invalid")


def activate(environment: str, *, yes: bool) -> dict[str, Any]:
    if not yes:
        raise JsdaCutoverError("--activate requires --yes")
    token, account = _credentials()
    baseline = _observe(environment, token=token, account=account)
    if environment == "production":
        _require_staging_admission(
            str(baseline["source_sha"]), token=token, account=account
        )
    intent = _control_intent(environment, baseline)
    if baseline["schedules"]:
        _set_schedules(environment, [], token=token, account=account)
    first = _observe(environment, token=token, account=account)
    time.sleep(2)
    second = _observe(environment, token=token, account=account)
    _require_drained(first, after_migration=False)
    _require_drained(second, after_migration=False)
    if not second["queue"]["paused"]:
        _queue_action(environment, "pause-delivery", token=token, account=account)
    quiesced = _observe(environment, token=token, account=account)
    if quiesced["schedules"] or not quiesced["queue"]["paused"]:
        raise JsdaCutoverError("Cron and Queue did not quiesce")
    _require_drained(quiesced, after_migration=False)
    travel = migration.time_travel_bookmark(
        environment, runner=_migration_runner(token, account)
    )
    receipt = _build_receipt(environment, intent, travel)
    _save_receipt(receipt)
    runner = _migration_runner(token, account)
    migration.bootstrap_mutation_lease_authority(
        environment=environment, runner=runner,
        pre_bootstrap_bookmark=str(receipt["rollback_bookmark"]),
        resume_owner_token=str(receipt["lease_owner"]),
        resume_nonce_token=str(receipt["lease_fence"]),
    )
    migration.acquire_authorized_mutation_lease(
        environment=environment, source_sha=str(receipt["source_sha"]), runner=runner,
        lease_owner_token=str(receipt["lease_owner"]),
        lease_nonce_token=str(receipt["lease_fence"]),
    )
    _start(receipt, token=token, account=account)
    result = _continue(receipt, token=token, account=account)
    _remove_control_intent(receipt)
    return result


def resume(environment: str, run_id: str, *, yes: bool) -> dict[str, Any]:
    if not yes:
        raise JsdaCutoverError("--resume requires --yes")
    token, account = _credentials()
    receipt = _load_receipt(environment, run_id)
    _recover_staging_drill(receipt, token=token, account=account)
    identity = _lease_identity(receipt)
    runner = _migration_runner(token, account)
    run = _status(receipt, token=token, account=account)
    if not run or run.get("phase") != "activated":
        try:
            migration.renew_mutation_lease(
                identity=identity, environment=environment,
                owner=str(receipt["lease_owner"]), nonce=str(receipt["lease_fence"]),
                runner=runner,
            )
        except migration.GuardedMigrationError:
            migration.resume_owned_mutation_lease(
                identity=identity, environment=environment,
                owner=str(receipt["lease_owner"]), nonce=str(receipt["lease_fence"]),
                runner=runner,
            )
    result = _continue(receipt, token=token, account=account)
    _remove_control_intent(receipt)
    return result


def rollback(environment: str, run_id: str, *, yes: bool) -> dict[str, Any]:
    if not yes:
        raise JsdaCutoverError("--rollback requires --yes")
    token, account = _credentials()
    receipt = _load_receipt(environment, run_id)
    live = _observe(environment, token=token, account=account)
    if live["schedules"]:
        _set_schedules(environment, [], token=token, account=account)
    first = _observe(environment, token=token, account=account)
    time.sleep(2)
    second = _observe(environment, token=token, account=account)
    _require_drained(first, after_migration=False)
    _require_drained(second, after_migration=False)
    if not second["queue"]["paused"]:
        _queue_action(environment, "pause-delivery", token=token, account=account)
    quiesced = _observe(environment, token=token, account=account)
    if quiesced["schedules"] or not quiesced["queue"]["paused"]:
        raise JsdaCutoverError("rollback requires stopped Cron and Queue")
    _require_drained(quiesced, after_migration=False)
    runner = _migration_runner(token, account)
    current_bookmark = migration.time_travel_bookmark(environment, runner=runner)["bookmark"]
    intent = _read_evidence(receipt, "rollback-intent")
    target = str(receipt["rollback_bookmark"])
    if intent is None:
        intent = {"target": target, "undo": current_bookmark}
        _evidence(receipt, "rollback-intent", intent)
    undo = str(intent.get("undo") or "")
    if intent.get("target") != target or not _BOOKMARK.fullmatch(undo):
        raise JsdaCutoverError("rollback intent is invalid")
    if current_bookmark == undo:
        returned = _restore_bookmark(environment, target, token=token, account=account)
        if returned != undo:
            raise JsdaCutoverError("rollback returned the wrong undo bookmark")
    elif current_bookmark != target:
        raise JsdaCutoverError("rollback recovery bookmark is ambiguous")
    _evidence(receipt, "rollback-undo", {"undo": undo})
    current = _selected(environment, token=token, account=account)
    if current["version_id"] != receipt["prior_version_id"]:
        command = [str(_wrangler()), "rollback", str(receipt["prior_version_id"]),
                   "--yes", *_config(environment)]
        result = _command(command, environment=environment, token=token,
                          account=account, timeout=300)
        if result.returncode:
            raise JsdaCutoverError("Worker rollback failed")
    queue = _queue(str(SURFACE[environment]["queue"]), token=token, account=account)
    desired = receipt["prior_queue_paused"] is True
    if queue["paused"] is not desired:
        action = "pause-delivery" if desired else "resume-delivery"
        _queue_action(environment, action, token=token, account=account)
    _set_schedules(environment, list(receipt["prior_schedules"]),
                   token=token, account=account)
    authority = migration.observe_mutation_lease_authority(
        environment=environment, runner=runner)
    if (
        authority
        and authority.get("owner") == receipt["lease_owner"]
        and int(authority.get("remote_spawned") or 0) == 0
    ):
        migration.release_mutation_lease(
            environment=environment, owner=str(receipt["lease_owner"]),
            nonce=str(receipt["lease_fence"]), runner=runner,
            allow_recovery=True,
        )
    _evidence(receipt, "rollback-complete", {"undo": undo})
    _remove_control_intent(receipt)
    return {"status": "ROLLED_BACK", "run_id": run_id, "undo_bookmark": undo}


def check(environment: str) -> dict[str, Any]:
    token, account = _credentials()
    first = _observe(environment, token=token, account=account)
    time.sleep(2)
    second = _observe(environment, token=token, account=account)
    keys = ("source_sha", "version_id", "version_tag", "pending_migrations")
    if any(first[key] != second[key] for key in keys):
        raise JsdaCutoverError("Cloudflare state changed during observation")
    return {"status": "CHECKED", "environment": environment, "state": second}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("check", "activate", "resume", "rollback"):
        mode.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    operation = next(name for name in ("check", "activate", "resume", "rollback")
                     if getattr(args, name))
    if operation == "check":
        result = check(args.environment)
    elif operation == "activate":
        result = activate(args.environment, yes=args.yes)
    else:
        if not args.run_id:
            raise JsdaCutoverError("--run-id is required")
        handler = resume if operation == "resume" else rollback
        result = handler(args.environment, args.run_id, yes=args.yes)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except JsdaCutoverError as exc:
        raise SystemExit(str(exc)) from exc
