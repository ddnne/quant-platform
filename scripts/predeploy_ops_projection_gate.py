#!/usr/bin/env python3
"""Fail MCP deploy unless dedicated D1 has a cryptographically verified SEALED generation.

Local dry-run/test commands do not import this module. Missing Cloudflare
credentials or an unprovisioned public SPKI fail closed for deploy.
Never print signed bodies, provider output, or secrets.

Premium is deployed first. MCP keeps its current binding until a SEALED
generation exists; this gate is that sequencing check, not a chicken-and-egg.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sys
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_der_public_key

from scripts.receipt_authority_pending_live_acceptance import (
    ReceiptPendingLiveAcceptanceError,
    _require_official_origin_main,
)


ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "platform" / "workers" / "quant-ops-mcp"
WRANGLER = OPS / "node_modules" / ".bin" / "wrangler"
PROJECTED_CONTENT_TABLES = (
    "collection_sla_status",
    "coverage_segments",
    "dataset_coverage",
    "endpoint_inventory",
    "ingestion_run_log",
    "ingestion_validation",
    "ingestion_watermarks",
    "ops_alerts",
    "ops_b0_status",
    "ops_projection_metadata",
    "ops_ready_snapshots",
    "ops_ready_state",
    "ops_snapshot_quality",
    "ops_storage_plane_status",
    "ops_sync_feed",
    "raw_retention_manifests",
    "receipt_product_materializations",
)
MAX_GENERATION_AGE = timedelta(minutes=30)
MAX_FUTURE_SKEW = timedelta(minutes=1)

_DB = {
    "production": ("quant-ops-projection", "wrangler.toml", "production"),
    "staging": ("quant-ops-projection-staging", "wrangler.staging.toml", None),
}


class PredeployGateError(RuntimeError):
    """Dedicated projection D1 is empty, unsigned, or unverifiable."""


def canonicalize(value: Any) -> Any:
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if isinstance(value, dict):
        return {key: canonicalize(value[key]) for key in sorted(value)}
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(canonicalize(value), separators=(",", ":"), ensure_ascii=False)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(OPS),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _canonical_utc(value: object, *, label: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise PredeployGateError(f"{label} is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PredeployGateError(f"{label} is not canonical UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PredeployGateError(f"{label} is not canonical UTC")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    if canonical != value:
        raise PredeployGateError(f"{label} is not canonical UTC")
    return parsed.astimezone(timezone.utc)


def _release_source_sha() -> str:
    head = _run(["git", "rev-parse", "HEAD"])
    origin = _run(["git", "rev-parse", "origin/main"])
    status = _run(["git", "status", "--porcelain"])
    sha = head.stdout.strip()
    if (
        head.returncode != 0
        or origin.returncode != 0
        or status.returncode != 0
        or status.stdout.strip()
        or sha != origin.stdout.strip()
        or len(sha) != 40
        or any(ch not in "0123456789abcdef" for ch in sha)
    ):
        raise PredeployGateError("deploy requires the clean merged origin/main HEAD")
    try:
        _require_official_origin_main(sha)
    except ReceiptPendingLiveAcceptanceError as exc:
        raise PredeployGateError(
            "deploy requires the current official remote main HEAD"
        ) from exc
    return sha


def _placeholder(value: str) -> bool:
    compact = value.replace("=", "")
    return bool(compact) and set(compact) <= {"A"}


def _load_spki(environment: str) -> tuple[str, bytes]:
    env_key = os.environ.get("OPS_PROJECTION_VERIFY_SPKI_B64") or ""
    config_name = _DB[environment][1]
    document = tomllib.loads((OPS / config_name).read_text(encoding="utf-8"))
    vars_map: Mapping[str, Any]
    if environment == "production":
        vars_map = (document.get("env") or {}).get("production", {}).get("vars") or document.get("vars") or {}
    else:
        vars_map = document.get("vars") or {}
    key_id = str(vars_map.get("OPS_PROJECTION_VERIFY_KEY_ID") or "")
    configured = str(vars_map.get("OPS_PROJECTION_VERIFY_SPKI_B64") or env_key)
    if not configured or _placeholder(configured) or not key_id:
        raise PredeployGateError("Ops Projection verify SPKI is unprovisioned")
    try:
        der = base64.b64decode(configured, validate=True)
        loaded = load_der_public_key(der)
    except (ValueError, TypeError) as exc:
        raise PredeployGateError("Ops Projection verify SPKI is invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise PredeployGateError("Ops Projection verify SPKI is not Ed25519")
    if loaded.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo) != der:
        raise PredeployGateError("Ops Projection verify SPKI encoding drifted")
    return key_id, der


def _d1_json(environment: str, command: str) -> list[dict[str, Any]]:
    database, config, env_name = _DB[environment]
    argv = [
        str(WRANGLER),
        "d1",
        "execute",
        database,
        "--remote",
        "--config",
        config,
        "--json",
        "--command",
        command,
    ]
    if env_name:
        argv.extend(["--env", env_name])
    completed = _run(argv)
    if completed.returncode != 0:
        raise PredeployGateError("cannot observe dedicated Ops Projection D1")
    try:
        payload = json.loads(completed.stdout[completed.stdout.find("["):])
        return list(payload[0]["results"])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise PredeployGateError("dedicated Ops Projection D1 observation is malformed") from exc


def _d1_bookmark(environment: str) -> str:
    database, config, env_name = _DB[environment]
    argv = [
        str(WRANGLER),
        "d1",
        "time-travel",
        "info",
        database,
        "--json",
        "--config",
        config,
    ]
    if env_name:
        argv.extend(["--env", env_name])
    completed = _run(argv)
    if completed.returncode != 0:
        raise PredeployGateError("cannot bind the Ops Projection D1 bookmark")
    matches = set(
        re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{32}",
            completed.stdout,
        )
    )
    if len(matches) != 1:
        raise PredeployGateError("Ops Projection D1 bookmark is absent or ambiguous")
    return next(iter(matches))


def _spki_raw32(der: bytes) -> bytes:
    prefix = bytes.fromhex("302a300506032b6570032100")
    if len(der) != 44 or not der.startswith(prefix):
        raise PredeployGateError("Ops Projection verify SPKI encoding drifted")
    return der[12:]


def _require_pinned_registry(environment: str, key_id: str, spki: bytes) -> dict[str, Any]:
    registry_name = (
        "verify_public_keys.staging.json"
        if environment == "staging"
        else "verify_public_keys.json"
    )
    registry = json.loads(
        (ROOT / "specs" / "ops_projection" / registry_name).read_text(encoding="utf-8")
    )
    if registry.get("purpose") != "ops_projection_verification":
        raise PredeployGateError("pinned Ops Projection registry purpose drifted")
    if registry.get("authority_instance") != "ops-projection-cloud":
        raise PredeployGateError("pinned Ops Projection authority instance drifted")
    if registry.get("authority_status") != "ACTIVE":
        raise PredeployGateError("pinned Ops Projection registry is not ACTIVE")
    if any(
        _placeholder(str(row.get("public_key_base64") or ""))
        for row in (registry.get("keys") or [])
        if isinstance(row, dict)
    ):
        raise PredeployGateError("pinned Ops Projection registry contains placeholder keys")
    matches = [
        row
        for row in (registry.get("keys") or [])
        if isinstance(row, dict)
        and row.get("key_id") == key_id
        and row.get("algorithm") == "Ed25519"
        and row.get("status") == "active"
        and row.get("environment") == environment
        and row.get("revoked_at") in {None, ""}
        and str(row.get("not_before") or "")
        and str(row.get("not_after") or "")
    ]
    if len(matches) != 1:
        raise PredeployGateError(
            "configured environment+key ID is not an ACTIVE registry member"
        )
    try:
        pinned = base64.b64decode(str(matches[0].get("public_key_base64") or ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise PredeployGateError("ACTIVE registry public key is malformed") from exc
    if pinned != _spki_raw32(spki):
        raise PredeployGateError(
            "configured environment+key ID+SPKI does not match an ACTIVE registry entry"
        )
    return dict(matches[0])


def require_sealed_active_generation(
    environment: str,
    *,
    intended_source_sha: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    if environment not in _DB:
        raise PredeployGateError("environment must be staging or production")
    if not os.environ.get("CLOUDFLARE_API_TOKEN") and not os.environ.get(
        "CLOUDFLARE_API_KEY"
    ):
        raise PredeployGateError(
            "MCP deploy requires Cloudflare credentials to prove a SEALED generation"
        )
    key_id, spki = _load_spki(environment)
    other = "staging" if environment == "production" else "production"
    other_key_id, _other_spki = _load_spki(other)
    if not other_key_id:
        raise PredeployGateError("configured environment key IDs must both be present")
    if other_key_id == key_id:
        raise PredeployGateError("production/staging key IDs must be environment-scoped")
    current_source_sha = _release_source_sha()
    if intended_source_sha is not None and intended_source_sha != current_source_sha:
        raise PredeployGateError("intended deployed source SHA is not the current merged HEAD")
    key_row = _require_pinned_registry(environment, key_id, spki)
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key_not_before = _canonical_utc(key_row.get("not_before"), label="key not_before")
    key_not_after = _canonical_utc(key_row.get("not_after"), label="key not_after")
    if evaluated_at < key_not_before or evaluated_at > key_not_after:
        raise PredeployGateError("Ops Projection verify key is outside its active validity window")
    opening_bookmark = _d1_bookmark(environment)
    rows = _d1_json(
        environment,
        "SELECT g.generation_id, g.status, g.signature, g.content_digest, "
        "g.source_db_digest, g.contract_digest, g.registry_digest, "
        "g.issuer_key_id, g.signed_envelope_json, g.coverage_policy_version, "
        "g.producer_commit_sha "
        "FROM ops_projection_active a JOIN ops_projection_generation g "
        "ON g.generation_id=a.generation_id WHERE a.singleton=1",
    )
    if len(rows) != 1:
        raise PredeployGateError("dedicated Ops Projection D1 has no active generation")
    sealed_rows = [dict(item) for item in rows]
    row = rows[0]
    if row.get("status") != "SEALED" or row.get("issuer_key_id") != key_id:
        raise PredeployGateError("active Ops Projection generation is not signed SEALED")
    producer = str(row.get("producer_commit_sha") or "")
    if len(producer) != 40 or any(ch not in "0123456789abcdef" for ch in producer):
        raise PredeployGateError("active generation is not bound to a Git SHA")
    if producer != current_source_sha:
        raise PredeployGateError("active generation producer SHA is not the intended deployed SHA")
    try:
        document = json.loads(str(row.get("signed_envelope_json") or ""))
    except json.JSONDecodeError as exc:
        raise PredeployGateError("signed Ops Projection envelope is invalid JSON") from exc
    envelope = document.get("envelope") if isinstance(document, dict) else None
    if not isinstance(envelope, dict):
        raise PredeployGateError("signed Ops Projection envelope is missing")
    if (
        envelope.get("generation_id") != row.get("generation_id")
        or envelope.get("content_digest") != row.get("content_digest")
        or envelope.get("source_db_digest") != row.get("source_db_digest")
        or envelope.get("contract_digest") != row.get("contract_digest")
        or envelope.get("environment") != environment
        or envelope.get("producer_commit_sha") != producer
    ):
        raise PredeployGateError("signed envelope does not bind the selected generation")
    generated_at = _canonical_utc(envelope.get("generated_at"), label="generated_at")
    if generated_at < key_not_before or generated_at > key_not_after:
        raise PredeployGateError("signed generation was produced outside the key validity window")
    if generated_at > evaluated_at + MAX_FUTURE_SKEW:
        raise PredeployGateError("signed generation is from the future")
    if evaluated_at - generated_at > MAX_GENERATION_AGE:
        raise PredeployGateError("signed generation is stale")
    body = {
        "schema_version": document.get("schema_version"),
        "algorithm": document.get("algorithm"),
        "issuer_key_id": document.get("issuer_key_id"),
        "envelope": envelope,
    }
    signature_value = str(row.get("signature") or "")
    if not signature_value.startswith("ed25519:"):
        raise PredeployGateError("Ops Projection signature material is malformed")
    try:
        signature = base64.b64decode(signature_value[len("ed25519:"):], validate=True)
        public_key = load_der_public_key(spki)
        assert isinstance(public_key, Ed25519PublicKey)
        public_key.verify(signature, _canonical_json(body).encode("utf-8"))
    except (InvalidSignature, ValueError, TypeError, AssertionError) as exc:
        raise PredeployGateError("Ops Projection signature is invalid") from exc
    expected_contract = "sha256:" + hashlib.sha256(
        _canonical_json({"tables": list(PROJECTED_CONTENT_TABLES)}).encode("utf-8")
    ).hexdigest()
    if envelope.get("contract_digest") != expected_contract:
        raise PredeployGateError("signed contract digest does not match projected tables")
    if envelope.get("projection_status") != "FRESH":
        raise PredeployGateError("signed empty/UNKNOWN projection must not switch MCP")
    source_cursor = envelope.get("source_cursor")
    export_cursor = envelope.get("export_cursor")
    applied_cursor = envelope.get("applied_cursor")
    if (
        source_cursor is None
        or export_cursor is None
        or applied_cursor is None
        or source_cursor != export_cursor
        or export_cursor != applied_cursor
    ):
        raise PredeployGateError("source/export/applied cursors must be non-null and equal")
    if envelope.get("coverage_policy_version") != "collection-coverage/v3":
        raise PredeployGateError("predeploy requires canonical Coverage V3")
    if envelope.get("b0_status") != "PASS" or envelope.get("b4_status") != "PASS":
        raise PredeployGateError("predeploy requires B0/B4 PASS")
    dataset_coverage = envelope.get("dataset_coverage")
    if not isinstance(dataset_coverage, dict) or not dataset_coverage:
        raise PredeployGateError("signed dataset coverage is empty")
    statuses = [
        row.get("status")
        for row in dataset_coverage.values()
        if isinstance(row, dict)
    ]
    if not statuses or set(statuses) <= {"UNKNOWN"}:
        raise PredeployGateError("signed empty/UNKNOWN projection must not switch MCP")
    row_counts = envelope.get("row_counts")
    manifest = envelope.get("content_manifest")
    if not isinstance(row_counts, dict) or not isinstance(manifest, dict):
        raise PredeployGateError("signed row_counts or content_manifest are missing")
    generation_id = str(row["generation_id"])
    pointer = _d1_json(
        environment,
        "SELECT generation_id,activated_at FROM ops_projection_active WHERE singleton=1",
    )
    if len(pointer) != 1 or pointer[0].get("generation_id") != generation_id:
        raise PredeployGateError("active pointer does not bind the sealed generation")
    observed_manifest: dict[str, dict[str, object]] = {}
    for table in PROJECTED_CONTENT_TABLES:
        rows = _d1_json(
            environment,
            f"SELECT * FROM {table} WHERE projection_generation_id="
            f"'{generation_id}'",
        )
        sorted_rows = sorted(
            [canonicalize(item) for item in rows],
            key=lambda item: _canonical_json(item).encode("utf-8"),
        )
        digest = "sha256:" + hashlib.sha256(
            _canonical_json({"rows": sorted_rows}).encode("utf-8")
        ).hexdigest()
        expected = manifest.get(table)
        if not isinstance(expected, dict):
            raise PredeployGateError(f"signed manifest is missing {table}")
        if expected.get("row_count") != len(sorted_rows) or expected.get("content_digest") != digest:
            raise PredeployGateError(f"active generation content digest drifted for {table}")
        if row_counts.get(table) != len(sorted_rows):
            raise PredeployGateError(f"active generation row count drifted for {table}")
        observed_manifest[table] = {"row_count": len(sorted_rows), "content_digest": digest}
    expected_content = "sha256:" + hashlib.sha256(
        _canonical_json({"tables": observed_manifest}).encode("utf-8")
    ).hexdigest()
    if envelope.get("content_digest") != expected_content or row.get("content_digest") != expected_content:
        raise PredeployGateError("signed content digest does not bind table manifests")
    for table in (
        "endpoint_inventory",
        "dataset_coverage",
        "ops_projection_metadata",
    ):
        if observed_manifest[table]["row_count"] == 0:
            raise PredeployGateError("signed empty/UNKNOWN projection must not switch MCP")
    final_pointer = _d1_json(
        environment,
        "SELECT generation_id,activated_at FROM ops_projection_active WHERE singleton=1",
    )
    if final_pointer != pointer:
        raise PredeployGateError("active pointer changed while projection content was verified")
    final_rows = _d1_json(
        environment,
        "SELECT g.generation_id, g.status, g.signature, g.content_digest, "
        "g.source_db_digest, g.contract_digest, g.registry_digest, "
        "g.issuer_key_id, g.signed_envelope_json, g.coverage_policy_version, "
        "g.producer_commit_sha "
        "FROM ops_projection_active a JOIN ops_projection_generation g "
        "ON g.generation_id=a.generation_id WHERE a.singleton=1",
    )
    if final_rows != sealed_rows or _d1_bookmark(environment) != opening_bookmark:
        raise PredeployGateError(
            "active projection changed while its signed content was verified"
        )
    finished_at = (
        evaluated_at
        if now is not None
        else datetime.now(timezone.utc).astimezone(timezone.utc)
    )
    if finished_at > key_not_after or finished_at - generated_at > MAX_GENERATION_AGE:
        raise PredeployGateError("signed generation expired during predeploy verification")
    return {
        "generation_id": generation_id,
        "status": "SEALED",
        "content_digest": row["content_digest"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--source-sha", default=None)
    args = parser.parse_args(argv)
    row = require_sealed_active_generation(
        args.environment, intended_source_sha=args.source_sha
    )
    print(f"ops projection predeploy: SEALED {row['generation_id']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PredeployGateError as exc:
        print(f"ops projection predeploy: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
