#!/usr/bin/env python3
"""Build a closed, content-addressed, non-secret release evidence envelope.

The input is a normalized set of observations, not a free-form release report.
Every remote observation carries collector provenance, response digest, evidence
ID, timestamp, and source SHA. Nested objects are closed schemas: an invented
field, omitted proof, stale deployment, or untraceable claim fails publication.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

try:
    from scripts.finding_ledger_gate import (
        FindingLedgerSnapshot,
        require_pinned_finding_ledger_gate,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from finding_ledger_gate import (  # type: ignore[no-redef]
        FindingLedgerSnapshot,
        require_pinned_finding_ledger_gate,
    )


SCHEMA_VERSION = "quant-platform-release-evidence/v3"
OBSERVATION_SCHEMA_VERSION = "quant-platform-release-observation/v1"
REQUIRED_FIELDS = (
    "source_sha",
    "origin_main_sha",
    "required_check",
    "cloudflare_build",
    "merged_prs",
    "open_prs",
    "finding_ledger",
    "deployments",
    "migrations",
    "smoke",
    "quant_mcp",
    "backup",
    "controlled_pilot",
    "mass_research",
    "rollback_status",
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_REQUIRED_CHECK_CONTEXT = "Workers Builds: quant-platform-ci-aggregate-staging"
_REQUIRED_CHECK_APP_ID = 85455
_ACTIVE_WORKERS = frozenset(
    {
        "quant-platform-ingestion-secrets",
        "quant-platform-ingestion-premium",
        "quant-platform-ingestion-jsda",
        "quant-platform-ops-read-mcp",
        "quant-platform-research-ai-gateway",
        "quant-platform-research-mass-eval",
    }
)
_MIGRATION_TARGETS = frozenset(
    {"quant-ingest", "quant-ops-projection", "quant-ops-quota"}
)
_MCP_TOOL_NAMES = (
    "ops_status",
    "source_inventory",
    "endpoint_status",
    "projection_status",
    "collection_sla_status",
    "ingestion_last_run",
    "dataset_coverage",
    "coverage_gaps",
    "coverage_segments",
    "backfill_status",
    "validation_summary",
    "b0_status",
    "latest_ready_snapshot",
    "snapshot_quality",
    "raw_retention_status",
    "sync_status",
    "storage_plane_status",
)
_ACCEPTED_MCP_SCHEMA_DIGEST = (
    "sha256:dad7cd29ef002e76ee1f9802b8685a179f94fcbd0bb2e6df685858e41c1778d3"
)
_BACKUP_FORMAT = "quant-platform-d1-backup/aes-256-gcm-v2"
_BACKUP_SCHEMA_PROFILE = "quant-ingest-production/v1"
_GOVERNED_DATABASE_NAME = "quant-ingest"
_GOVERNED_DATABASE_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
_MINIMUM_BACKUP_TABLE_COUNT = 14
_NO_GO_REASON_CODES = frozenset(
    {
        "TRUSTED_HISTORICAL_REPROOF_UNAVAILABLE",
        "READY_UNAVAILABLE",
        "LIVE_PROJECTION_NOT_READY",
        "DEPENDENCY_CLOSURE_UNPROVEN",
        "P0_UNRESOLVED",
    }
)
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:secret|token|password|private_key|api_key|credential)(?:$|_)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:-----BEGIN (?:OPENSSH |EC |RSA |)PRIVATE KEY-----|"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{16,}\b|"
    r"\bgithub_pat_[A-Za-z0-9_]{16,}\b|"
    r"\bglpat-[A-Za-z0-9_-]{16,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*)",
    re.IGNORECASE,
)

_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION_MANIFEST = _ROOT / "specs" / "cloudflare" / "d1_migration_manifest.json"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def payload_digest(payload: Mapping[str, Any]) -> str:
    return _digest_bytes(canonical_bytes(payload))


def _load_migration_contract() -> tuple[str, dict[str, tuple[dict[str, str], ...]]]:
    raw_bytes = _MIGRATION_MANIFEST.read_bytes()
    raw = json.loads(raw_bytes)
    targets = raw.get("targets") if isinstance(raw, Mapping) else None
    if not isinstance(targets, Mapping) or set(targets) != _MIGRATION_TARGETS:
        raise ValueError("canonical D1 migration manifest target set is invalid")
    contract: dict[str, tuple[dict[str, str], ...]] = {}
    for target in sorted(_MIGRATION_TARGETS):
        observed = targets.get(target)
        migrations = observed.get("migrations") if isinstance(observed, Mapping) else None
        if not isinstance(migrations, list) or not migrations:
            raise ValueError("canonical D1 migration manifest is incomplete")
        normalized: list[dict[str, str]] = []
        for migration in migrations:
            if not isinstance(migration, Mapping):
                raise ValueError("canonical D1 migration manifest is invalid")
            migration_id = str(migration.get("migration_id") or "")
            checksum = str(migration.get("checksum") or "")
            if not migration_id.startswith(target + ":") or not _DIGEST.fullmatch(checksum):
                raise ValueError("canonical D1 migration manifest is invalid")
            normalized.append({"migration_id": migration_id, "checksum": checksum})
        contract[target] = tuple(normalized)
    return _digest_bytes(raw_bytes), contract


_CANONICAL_MIGRATION_MANIFEST_DIGEST, _CANONICAL_MIGRATIONS = (
    _load_migration_contract()
)


def _walk(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                raise ValueError(
                    f"release evidence contains a secret-shaped key: {'.'.join(path + (key,))}"
                )
            _walk(item, path + (key,))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, path + (str(index),))
        return
    if not isinstance(value, str):
        return
    if _SENSITIVE_VALUE.search(value):
        raise ValueError(
            f"release evidence contains secret-shaped material at {'.'.join(path)}"
        )
    if (
        value.startswith(("~/", "~\\", "file://"))
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    ):
        raise ValueError(
            f"release evidence contains a local absolute path at {'.'.join(path)}"
        )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_mapping(
    value: Any, label: str, keys: Iterable[str]
) -> Mapping[str, Any]:
    observed = _require_mapping(value, label)
    expected = frozenset(keys)
    if set(observed) != expected:
        missing = sorted(expected - set(observed))
        extra = sorted(set(observed) - expected)
        raise ValueError(f"{label} schema drift: missing={missing}, extra={extra}")
    return observed


def _require_digest(value: Any, label: str) -> str:
    rendered = str(value or "")
    if not _DIGEST.fullmatch(rendered):
        raise ValueError(f"{label} must be sha256:<hex>")
    return rendered


def _require_uuid(value: Any, label: str) -> str:
    rendered = str(value or "")
    if not _UUID.fullmatch(rendered):
        raise ValueError(f"{label} must be a UUID")
    return rendered


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_timestamp(value: Any, label: str) -> datetime:
    rendered = str(value or "")
    if not _RFC3339_UTC.fullmatch(rendered):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        observed = datetime.fromisoformat(rendered[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if observed.tzinfo is None or observed.utcoffset() != timezone.utc.utcoffset(observed):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    return observed


def _validate_https_url(value: Any, label: str) -> None:
    rendered = str(value or "")
    parsed = urlsplit(rendered)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{label} must be a credential-free HTTPS URL")


def _validate_provenance(
    value: Any,
    label: str,
    *,
    expected_collector: str,
    source_sha: str,
) -> Mapping[str, Any]:
    provenance = _exact_mapping(
        value,
        label,
        {
            "schema_version",
            "collector",
            "evidence_id",
            "observed_at",
            "source_sha",
            "response_digest",
        },
    )
    if (
        provenance["schema_version"] != OBSERVATION_SCHEMA_VERSION
        or provenance["collector"] != expected_collector
        or provenance["source_sha"] != source_sha
    ):
        raise ValueError(f"{label} is not bound to its collector and source SHA")
    _require_uuid(provenance["evidence_id"], f"{label}.evidence_id")
    _require_timestamp(provenance["observed_at"], f"{label}.observed_at")
    _require_digest(provenance["response_digest"], f"{label}.response_digest")
    return provenance


def _validate_required_check(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    required = _exact_mapping(
        payload["required_check"],
        "required_check",
        {
            "context",
            "app_id",
            "app_slug",
            "strict",
            "conclusion",
            "head_sha",
            "check_run_id",
            "details_url",
            "provenance",
        },
    )
    if (
        required["context"] != _REQUIRED_CHECK_CONTEXT
        or required["app_id"] != _REQUIRED_CHECK_APP_ID
        or required["app_slug"] != "cloudflare-workers-and-pages"
        or required["strict"] is not True
        or str(required["conclusion"]).lower() != "success"
        or required["head_sha"] != source_sha
    ):
        raise ValueError("required_check is not the authoritative Cloudflare App success")
    _require_positive_int(required["check_run_id"], "required_check.check_run_id")
    _validate_https_url(required["details_url"], "required_check.details_url")
    _validate_provenance(
        required["provenance"],
        "required_check.provenance",
        expected_collector="github-check-runs-api/v1",
        source_sha=source_sha,
    )


def _validate_cloudflare_build(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    build = _exact_mapping(
        payload["cloudflare_build"],
        "cloudflare_build",
        {"build_id", "conclusion", "source_sha", "provenance"},
    )
    _require_uuid(build["build_id"], "cloudflare_build.build_id")
    if str(build["conclusion"]).lower() != "success" or build["source_sha"] != source_sha:
        raise ValueError("cloudflare_build must be a successful build of source_sha")
    _validate_provenance(
        build["provenance"],
        "cloudflare_build.provenance",
        expected_collector="cloudflare-workers-builds-api/v1",
        source_sha=source_sha,
    )


def _validate_deployments(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    deployments = _require_mapping(payload["deployments"], "deployments")
    if set(deployments) != _ACTIVE_WORKERS:
        raise ValueError("deployments must contain exactly the six active Workers")
    for worker, raw in deployments.items():
        environments = _require_mapping(raw, f"deployments.{worker}")
        if set(environments) != {"staging", "production"}:
            raise ValueError(f"deployments.{worker} must contain staging and production")
        for environment, raw_row in environments.items():
            label = f"deployments.{worker}.{environment}"
            row = _exact_mapping(
                raw_row,
                label,
                {
                    "version_id",
                    "source_sha",
                    "effective_bindings_digest",
                    "provenance",
                },
            )
            _require_uuid(row["version_id"], f"{label}.version_id")
            _require_digest(
                row["effective_bindings_digest"], f"{label}.effective_bindings_digest"
            )
            if row["source_sha"] != source_sha:
                raise ValueError(f"{label} is not pinned to release source SHA")
            _validate_provenance(
                row["provenance"],
                f"{label}.provenance",
                expected_collector="cloudflare-workers-versions-api/v1",
                source_sha=source_sha,
            )


def _validate_migrations(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    migrations = _require_mapping(payload["migrations"], "migrations")
    if set(migrations) != {"staging", "production"}:
        raise ValueError("migrations must contain staging and production")
    for environment, targets_raw in migrations.items():
        targets = _require_mapping(targets_raw, f"migrations.{environment}")
        if set(targets) != _MIGRATION_TARGETS:
            raise ValueError(
                f"migrations.{environment} must contain exactly the canonical targets"
            )
        for target, raw_row in targets.items():
            label = f"migrations.{environment}.{target}"
            row = _exact_mapping(
                raw_row,
                label,
                {
                    "status",
                    "pending",
                    "canonical_manifest_digest",
                    "applied_migrations",
                    "provenance",
                },
            )
            if row["pending"] != 0 or row["status"] != "APPLIED":
                raise ValueError(f"{label} has unapplied migrations")
            if row["canonical_manifest_digest"] != _CANONICAL_MIGRATION_MANIFEST_DIGEST:
                raise ValueError(f"{label} is not bound to the canonical migration manifest")
            if row["applied_migrations"] != list(_CANONICAL_MIGRATIONS[target]):
                raise ValueError(f"{label} does not prove the canonical migration sequence")
            _validate_provenance(
                row["provenance"],
                f"{label}.provenance",
                expected_collector="wrangler-d1-migrations-list/v1",
                source_sha=source_sha,
            )


def _validate_smoke(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    smoke = _require_mapping(payload["smoke"], "smoke")
    deployments = _require_mapping(payload["deployments"], "deployments")
    if set(smoke) != {"staging", "production"}:
        raise ValueError("smoke must contain staging and production")
    for environment, workers_raw in smoke.items():
        workers = _require_mapping(workers_raw, f"smoke.{environment}")
        if set(workers) != _ACTIVE_WORKERS:
            raise ValueError(
                f"smoke.{environment} must cover exactly the six active Workers"
            )
        for worker, raw_row in workers.items():
            label = f"smoke.{environment}.{worker}"
            row = _exact_mapping(
                raw_row,
                label,
                {"result", "source_sha", "deployment_version_id", "provenance"},
            )
            if (
                row["result"] != "PASS"
                or row["source_sha"] != source_sha
                or row["deployment_version_id"]
                != deployments[worker][environment]["version_id"]
            ):
                raise ValueError(f"{label} is not a PASS for the deployed source/version")
            _validate_provenance(
                row["provenance"],
                f"{label}.provenance",
                expected_collector="release-smoke-runner/v1",
                source_sha=source_sha,
            )


def _validate_quant_mcp(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    mcp = _exact_mapping(
        payload["quant_mcp"],
        "quant_mcp",
        {
            "tool_count",
            "expected_tool_count",
            "tools",
            "schema_digest",
            "expected_schema_digest",
            "deployment_version_id",
            "projection",
            "projection_generation",
            "refresh_success",
            "b0",
            "b4",
            "ready",
            "source_cursor",
            "export_cursor",
            "applied_cursor",
            "provenance",
        },
    )
    tools = mcp["tools"]
    if (
        mcp["tool_count"] != 17
        or mcp["expected_tool_count"] != 17
        or not isinstance(tools, list)
        or tuple(tools) != _MCP_TOOL_NAMES
        or mcp["schema_digest"] != _ACCEPTED_MCP_SCHEMA_DIGEST
        or mcp["expected_schema_digest"] != _ACCEPTED_MCP_SCHEMA_DIGEST
    ):
        raise ValueError("quant_mcp must prove the exact 17 tools and accepted schema digest")
    deployments = _require_mapping(payload["deployments"], "deployments")
    if (
        mcp["deployment_version_id"]
        != deployments["quant-platform-ops-read-mcp"]["production"]["version_id"]
    ):
        raise ValueError("quant_mcp is not bound to the accepted Ops MCP deployment")
    if mcp["projection"] not in {"FRESH", "STALE", "NOT_PROJECTED"}:
        raise ValueError("quant_mcp.projection is invalid")
    if not isinstance(mcp["projection_generation"], str) or not mcp[
        "projection_generation"
    ].strip():
        raise ValueError("quant_mcp.projection_generation is required")
    if type(mcp["refresh_success"]) is not bool:
        raise ValueError("quant_mcp.refresh_success must be boolean")
    for gate in ("b0", "b4"):
        if mcp[gate] not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError(f"quant_mcp.{gate} is invalid")
    if mcp["ready"] not in {"READY", "NOT_READY", "UNKNOWN"}:
        raise ValueError("quant_mcp.ready is invalid")
    for cursor in ("source_cursor", "export_cursor", "applied_cursor"):
        value = mcp[cursor]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"quant_mcp.{cursor} must be a non-negative integer or null")
    _validate_provenance(
        mcp["provenance"],
        "quant_mcp.provenance",
        expected_collector="quant-mcp-tools-list/v1",
        source_sha=source_sha,
    )


def _validate_backup(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    backup = _exact_mapping(
        payload["backup"],
        "backup",
        {
            "format",
            "cipher",
            "encrypted",
            "verified",
            "plaintext_bytes",
            "plaintext_digest",
            "ciphertext_bytes",
            "ciphertext_digest",
            "authenticated_metadata_digest",
            "database",
            "exported_at",
            "restore",
            "key_id",
            "nonce",
        },
    )
    database = _exact_mapping(
        backup["database"],
        "backup.database",
        {"name", "id", "schema_profile"},
    )
    restore = _exact_mapping(
        backup["restore"],
        "backup.restore",
        {
            "evidence_id",
            "verified_at",
            "source_sha",
            "engine",
            "integrity_check",
            "canonical_minimum_schema",
            "required_nonempty_tables",
            "schema_digest",
            "table_count",
        },
    )
    plaintext_bytes = backup["plaintext_bytes"]
    ciphertext_bytes = backup["ciphertext_bytes"]
    if (
        backup["format"] != _BACKUP_FORMAT
        or backup["cipher"] != "AES-256-GCM"
        or backup["encrypted"] is not True
        or backup["verified"] is not True
        or type(plaintext_bytes) is not int
        or plaintext_bytes <= 0
        or type(ciphertext_bytes) is not int
        or ciphertext_bytes <= plaintext_bytes
    ):
        raise ValueError("backup must be a non-empty verified AES-256-GCM v2 artifact")
    _require_digest(backup["plaintext_digest"], "backup.plaintext_digest")
    _require_digest(backup["ciphertext_digest"], "backup.ciphertext_digest")
    _require_digest(
        backup["authenticated_metadata_digest"],
        "backup.authenticated_metadata_digest",
    )
    _require_digest(backup["key_id"], "backup.key_id")
    try:
        nonce = base64.b64decode(str(backup.get("nonce") or ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("backup.nonce must be authenticated AES-GCM nonce") from exc
    if len(nonce) != 12:
        raise ValueError("backup.nonce must be authenticated AES-GCM nonce")
    if database != {
        "name": _GOVERNED_DATABASE_NAME,
        "id": _GOVERNED_DATABASE_ID,
        "schema_profile": _BACKUP_SCHEMA_PROFILE,
    }:
        raise ValueError("backup is not the governed production D1 database")
    exported_at = _require_timestamp(backup["exported_at"], "backup.exported_at")
    verified_at = _require_timestamp(restore["verified_at"], "backup.restore.verified_at")
    if verified_at < exported_at:
        raise ValueError("backup restore verification predates its export")
    if (
        restore["source_sha"] != source_sha
        or restore["engine"] != "sqlite3-cli+integrity_check"
        or restore["integrity_check"] != "ok"
        or restore["canonical_minimum_schema"] != "PASS"
        or restore["required_nonempty_tables"] != "PASS"
        or type(restore["table_count"]) is not int
        or restore["table_count"] < _MINIMUM_BACKUP_TABLE_COUNT
    ):
        raise ValueError("backup lacks governed restore, integrity, and schema proof")
    _require_uuid(restore["evidence_id"], "backup.restore.evidence_id")
    _require_digest(restore["schema_digest"], "backup.restore.schema_digest")
    authenticated_header = {
        "format": backup["format"],
        "cipher": backup["cipher"],
        "key_id": backup["key_id"],
        "nonce": backup["nonce"],
        "database": dict(database),
        "exported_at": backup["exported_at"],
        "restore": dict(restore),
        "plaintext_bytes": plaintext_bytes,
        "plaintext_digest": backup["plaintext_digest"],
    }
    if backup["authenticated_metadata_digest"] != _digest_bytes(
        canonical_bytes(authenticated_header)
    ):
        raise ValueError("backup authenticated metadata digest does not match its evidence")


def _validate_finding_ledger(
    payload: Mapping[str, Any], snapshot: FindingLedgerSnapshot
) -> None:
    evidence = _exact_mapping(
        payload["finding_ledger"],
        "finding_ledger",
        {"ledger_digest", "open_p0_ids"},
    )
    if evidence["ledger_digest"] != snapshot.digest:
        raise ValueError("finding_ledger is not bound to the pinned ledger digest")
    open_ids = evidence["open_p0_ids"]
    if (
        not isinstance(open_ids, list)
        or any(not isinstance(value, str) for value in open_ids)
        or open_ids != list(snapshot.open_p0_ids)
    ):
        raise ValueError("finding_ledger open P0 ids do not match the pinned gate")


def _validate_controlled_pilot(payload: Mapping[str, Any]) -> None:
    source_sha = str(payload["source_sha"])
    pilot = _require_mapping(payload["controlled_pilot"], "controlled_pilot")
    decision = pilot.get("decision")
    common_keys = {
        "decision",
        "executed",
        "automatic_promotion",
        "provenance",
    }
    if decision == "NO-GO":
        pilot = _exact_mapping(
            pilot,
            "controlled_pilot",
            common_keys | {"reason_code", "reason", "blocker_evidence_digest"},
        )
        reason = str(pilot["reason"] or "").strip()
        if (
            pilot["executed"] is not False
            or pilot["automatic_promotion"] is not False
            or pilot["reason_code"] not in _NO_GO_REASON_CODES
            or len(reason) < 16
            or reason.lower() in {"none", "n/a", "unknown", "not ready"}
        ):
            raise ValueError(
                "NO-GO pilot must be unexecuted with a specific evidenced blocker"
            )
        _require_digest(
            pilot["blocker_evidence_digest"],
            "controlled_pilot.blocker_evidence_digest",
        )
    elif decision == "GO":
        digest_fields = {
            "experiment_plan_digest",
            "strategy_spec_set_digest",
            "feature_ref_set_digest",
            "profile_digest",
            "closure_digest",
            "governed_membership_digest",
            "coverage_proof_digest",
            "raw_receipt_proof_digest",
            "b0_b4_result_digest",
            "cursor_chain_digest",
            "ready_manifest_digest",
            "ready_attestation_digest",
            "trader_authorization_digest",
            "immutable_snapshot_digest",
            "paper_artifact_digest",
            "risk_artifact_digest",
            "selection_artifact_digest",
            "knowledge_artifact_digest",
        }
        pilot = _exact_mapping(
            pilot,
            "controlled_pilot",
            common_keys
            | digest_fields
            | {"ready_snapshot_id", "plan_count", "generations"},
        )
        if (
            pilot["executed"] is not True
            or pilot["automatic_promotion"] is not False
            or pilot["plan_count"] != 4
            or pilot["generations"] != 1
            or not isinstance(pilot["ready_snapshot_id"], str)
            or not pilot["ready_snapshot_id"].strip()
        ):
            raise ValueError("GO pilot must be one exact-four execution without promotion")
        for field in digest_fields:
            _require_digest(pilot[field], f"controlled_pilot.{field}")
        mcp = _require_mapping(payload["quant_mcp"], "quant_mcp")
        if (
            mcp["projection"] != "FRESH"
            or mcp["refresh_success"] is not True
            or mcp["b0"] != "PASS"
            or mcp["b4"] != "PASS"
            or mcp["ready"] != "READY"
            or type(mcp["applied_cursor"]) is not int
            or mcp["applied_cursor"] != mcp["source_cursor"]
            or mcp["applied_cursor"] != mcp["export_cursor"]
        ):
            raise ValueError("GO pilot requires current FRESH/PASS/READY live evidence")
    else:
        raise ValueError("controlled_pilot.decision must be GO or NO-GO")
    _validate_provenance(
        pilot["provenance"],
        "controlled_pilot.provenance",
        expected_collector="controlled-pilot-gate/v1",
        source_sha=source_sha,
    )


def _validate_remote_acceptance(payload: Mapping[str, Any]) -> None:
    _validate_required_check(payload)
    _validate_cloudflare_build(payload)
    _validate_deployments(payload)
    _validate_migrations(payload)
    _validate_smoke(payload)
    _validate_quant_mcp(payload)


def validate_payload(payload: Mapping[str, Any]) -> None:
    snapshot = require_pinned_finding_ledger_gate()
    expected = frozenset(REQUIRED_FIELDS)
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        extra = sorted(set(payload) - expected)
        raise ValueError(
            f"release evidence field membership drift: missing={missing}, extra={extra}"
        )
    # Reject secrets and host-local paths first so malformed nesting cannot use
    # an earlier schema error to mask accidental credential publication.
    _walk(payload)
    for field in ("source_sha", "origin_main_sha"):
        if not _SHA.fullmatch(str(payload[field])):
            raise ValueError(f"{field} must be a full lowercase Git SHA")
    if payload["source_sha"] != payload["origin_main_sha"]:
        raise ValueError("release source SHA must equal observed origin/main SHA")
    if payload["open_prs"] != []:
        raise ValueError("release evidence requires zero open PRs")
    merged_prs = payload["merged_prs"]
    if (
        not isinstance(merged_prs, list)
        or not merged_prs
        or any(type(number) is not int or number <= 0 for number in merged_prs)
        or len(set(merged_prs)) != len(merged_prs)
    ):
        raise ValueError("merged_prs must contain unique positive PR numbers")
    _validate_finding_ledger(payload, snapshot)
    _validate_remote_acceptance(payload)
    _validate_backup(payload)
    _validate_controlled_pilot(payload)
    if payload["mass_research"] != "NO-GO":
        raise ValueError("Phase 6.3.1 release evidence must keep Mass Research NO-GO")
    if payload["rollback_status"] not in {"NOT_REQUIRED", "ROLLED_BACK_VERIFIED"}:
        raise ValueError("rollback_status must be NOT_REQUIRED or ROLLED_BACK_VERIFIED")


def build_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_payload(payload)
    digest = payload_digest(payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_digest": digest,
        "payload": dict(payload),
    }


def write_envelope(payload: Mapping[str, Any], output_dir: Path) -> Path:
    envelope = build_envelope(payload)
    digest_hex = envelope["evidence_digest"].removeprefix("sha256:")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"quant-platform-release-evidence-{digest_hex}.json"
    rendered = json.dumps(envelope, ensure_ascii=False, indent=2) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"content-addressed evidence collision: {target.name}")
        return target
    target.write_text(rendered, encoding="utf-8")
    target.chmod(0o444)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="normalized non-secret release observations JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    require_pinned_finding_ledger_gate()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("release evidence input must be a JSON object")
    target = write_envelope(raw, args.output_dir)
    print(target.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
