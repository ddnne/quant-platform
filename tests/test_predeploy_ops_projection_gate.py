"""Behavioral predeploy gate: ACTIVE registry membership and table content hashes."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import subprocess
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts import predeploy_ops_projection_gate as gate


SHA = "a" * 40
NOW = datetime(2026, 9, 2, 0, 10, tzinfo=timezone.utc)
BOOKMARK = "00000001-00000002-00000003-" + "d" * 32


def _local_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "_release_source_sha", lambda: SHA)
    monkeypatch.setattr(gate, "_d1_bookmark", lambda _environment: BOOKMARK)


def test_release_source_requires_official_remote_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[-1] == "HEAD" or argv[-1] == "origin/main":
            return subprocess.CompletedProcess(argv, 0, SHA + "\n", "")
        if argv[1:] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)

    observed: list[str] = []
    monkeypatch.setattr(gate, "_run", run)
    monkeypatch.setattr(
        gate, "_require_official_origin_main", lambda sha: observed.append(sha)
    )
    assert gate._release_source_sha() == SHA
    assert observed == [SHA]


def test_release_source_rejects_unverified_official_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[-1] == "HEAD" or argv[-1] == "origin/main":
            return subprocess.CompletedProcess(argv, 0, SHA + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(gate, "_run", run)
    monkeypatch.setattr(
        gate,
        "_require_official_origin_main",
        lambda _sha: (_ for _ in ()).throw(
            gate.ReceiptPendingLiveAcceptanceError("unverified")
        ),
    )
    with pytest.raises(gate.PredeployGateError, match="official remote main"):
        gate._release_source_sha()


def _install_valid_generation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    producer: str = SHA,
    generated_at: str = "2026-09-02T00:00:00Z",
    not_before: str = "2026-09-01T00:00:00Z",
    not_after: str = "2026-09-03T00:00:00Z",
    pointer_times: tuple[str, ...] = ("2026-09-02T00:01:00Z",),
) -> None:
    _local_release(monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    private = Ed25519PrivateKey.generate()
    der = private.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    monkeypatch.setattr(
        gate,
        "_load_spki",
        lambda environment: (
            "ops-projection-test-v1" if environment == "production" else "staging-key",
            der,
        ),
    )
    monkeypatch.setattr(
        gate,
        "_require_pinned_registry",
        lambda *_args, **_kwargs: {
            "not_before": not_before,
            "not_after": not_after,
        },
    )
    generation = "gen-valid"
    table_rows = {
        table: (
            [{"projection_generation_id": generation, "table": table}]
            if table
            in {"endpoint_inventory", "dataset_coverage", "ops_projection_metadata"}
            else []
        )
        for table in gate.PROJECTED_CONTENT_TABLES
    }
    manifest: dict[str, dict[str, object]] = {}
    for table, rows in table_rows.items():
        manifest[table] = {
            "row_count": len(rows),
            "content_digest": "sha256:"
            + hashlib.sha256(
                gate._canonical_json({"rows": rows}).encode("utf-8")
            ).hexdigest(),
        }
    content_digest = "sha256:" + hashlib.sha256(
        gate._canonical_json({"tables": manifest}).encode("utf-8")
    ).hexdigest()
    contract_digest = "sha256:" + hashlib.sha256(
        gate._canonical_json(
            {"tables": list(gate.PROJECTED_CONTENT_TABLES)}
        ).encode("utf-8")
    ).hexdigest()
    envelope = {
        "generation_id": generation,
        "content_digest": content_digest,
        "source_db_digest": "sha256:" + "2" * 64,
        "contract_digest": contract_digest,
        "environment": "production",
        "producer_commit_sha": producer,
        "generated_at": generated_at,
        "projection_status": "FRESH",
        "source_cursor": 12,
        "export_cursor": 12,
        "applied_cursor": 12,
        "coverage_policy_version": "collection-coverage/v3",
        "b0_status": "PASS",
        "b4_status": "PASS",
        "dataset_coverage": {
            "equities_bars_daily": {
                "status": "COMPLETE",
                "policy_version": "collection-coverage/v3",
            }
        },
        "row_counts": {table: len(rows) for table, rows in table_rows.items()},
        "content_manifest": manifest,
    }
    body = {
        "schema_version": "ops-projection-signed-envelope/v1",
        "algorithm": "Ed25519",
        "issuer_key_id": "ops-projection-test-v1",
        "envelope": envelope,
    }
    signature = private.sign(gate._canonical_json(body).encode("utf-8"))
    generation_row = {
        "generation_id": generation,
        "status": "SEALED",
        "signature": "ed25519:" + base64.b64encode(signature).decode(),
        "content_digest": content_digest,
        "source_db_digest": envelope["source_db_digest"],
        "contract_digest": contract_digest,
        "registry_digest": "sha256:" + "5" * 64,
        "issuer_key_id": "ops-projection-test-v1",
        "signed_envelope_json": json.dumps(body),
        "coverage_policy_version": "collection-coverage/v3",
        "producer_commit_sha": producer,
    }
    pointer_index = {"value": 0}

    def d1(_environment: str, command: str) -> list[dict[str, Any]]:
        if "JOIN ops_projection_generation" in command:
            return [generation_row]
        if "FROM ops_projection_active" in command:
            index = min(pointer_index["value"], len(pointer_times) - 1)
            pointer_index["value"] += 1
            return [{"generation_id": generation, "activated_at": pointer_times[index]}]
        for table, rows in table_rows.items():
            if f"FROM {table} " in command:
                return list(rows)
        raise AssertionError(command)

    monkeypatch.setattr(gate, "_d1_json", d1)


def test_committed_pending_registry_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_release(monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    key = Ed25519PrivateKey.generate().public_key()
    spki = base64.b64encode(key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode()
    monkeypatch.setenv("OPS_PROJECTION_VERIFY_SPKI_B64", spki)
    monkeypatch.setattr(
        gate,
        "_load_spki",
        lambda environment: (
            "ops-projection-cloud-production-v1"
            if environment == "production"
            else "ops-projection-cloud-staging-v1",
            base64.b64decode(spki),
        ),
    )
    with pytest.raises(gate.PredeployGateError, match="not ACTIVE"):
        gate.require_sealed_active_generation("production")


def test_content_digest_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_release(monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    der = public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    raw = der[12:]
    monkeypatch.setattr(
        gate,
        "_load_spki",
        lambda environment: (
            "ops-projection-test-v1"
            if environment == "production"
            else "ops-projection-cloud-staging-v1",
            der,
        ),
    )

    def fake_registry(environment: str, key_id: str, spki: bytes) -> dict[str, Any]:
        assert environment == "production"
        assert key_id == "ops-projection-test-v1"
        assert spki == der
        return {
            "authority_status": "ACTIVE",
            "not_before": "2026-09-01T00:00:00Z",
            "not_after": "2026-09-03T00:00:00Z",
        }

    monkeypatch.setattr(gate, "_require_pinned_registry", fake_registry)
    generation = "gen-1"
    empty_digest = "sha256:" + hashlib.sha256(
        gate._canonical_json({"rows": []}).encode("utf-8")
    ).hexdigest()
    manifest = {
        table: {"row_count": 0, "content_digest": empty_digest}
        for table in gate.PROJECTED_CONTENT_TABLES
    }
    contract_digest = "sha256:" + hashlib.sha256(
        gate._canonical_json({"tables": list(gate.PROJECTED_CONTENT_TABLES)}).encode("utf-8")
    ).hexdigest()
    envelope = {
        "generation_id": generation,
        "content_digest": "sha256:" + "1" * 64,
        "source_db_digest": "sha256:" + "2" * 64,
        "contract_digest": contract_digest,
        "environment": "production",
        "producer_commit_sha": SHA,
        "generated_at": "2026-09-02T00:00:00Z",
        "projection_status": "FRESH",
        "source_cursor": 12,
        "export_cursor": 12,
        "applied_cursor": 12,
        "coverage_policy_version": "collection-coverage/v3",
        "b0_status": "PASS",
        "b4_status": "PASS",
        "dataset_coverage": {
            "equities_bars_daily": {
                "status": "PARTIAL",
                "policy_version": "collection-coverage/v3",
            }
        },
        "row_counts": {table: 0 for table in gate.PROJECTED_CONTENT_TABLES},
        "content_manifest": manifest,
    }
    body = {
        "schema_version": "ops-projection-signed-envelope/v1",
        "algorithm": "Ed25519",
        "issuer_key_id": "ops-projection-test-v1",
        "envelope": envelope,
    }
    signature = private.sign(gate._canonical_json(body).encode("utf-8"))
    row = {
        "generation_id": generation,
        "status": "SEALED",
        "signature": "ed25519:" + base64.b64encode(signature).decode(),
        "content_digest": envelope["content_digest"],
        "source_db_digest": envelope["source_db_digest"],
        "contract_digest": envelope["contract_digest"],
        "registry_digest": "sha256:" + "5" * 64,
        "issuer_key_id": "ops-projection-test-v1",
        "signed_envelope_json": json.dumps(body),
        "coverage_policy_version": "collection-coverage/v3",
        "producer_commit_sha": SHA,
    }

    def d1(_environment: str, command: str) -> list[dict[str, Any]]:
        if "ops_projection_active a JOIN" in command or "JOIN ops_projection_generation" in command:
            return [row]
        if "FROM ops_projection_active" in command:
            return [{"generation_id": generation}]
        return []

    monkeypatch.setattr(gate, "_d1_json", d1)
    with pytest.raises(gate.PredeployGateError, match="content digest"):
        gate.require_sealed_active_generation("production", now=NOW)


def test_unknown_projection_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_release(monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    private = Ed25519PrivateKey.generate()
    der = private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(
        gate,
        "_load_spki",
        lambda environment: (
            "ops-projection-test-v1"
            if environment == "production"
            else "ops-projection-cloud-staging-v1",
            der,
        ),
    )
    monkeypatch.setattr(
        gate,
        "_require_pinned_registry",
        lambda *_args, **_kwargs: {
            "authority_status": "ACTIVE",
            "not_before": "2026-09-01T00:00:00Z",
            "not_after": "2026-09-03T00:00:00Z",
        },
    )
    envelope = {
        "generation_id": "gen-1",
        "content_digest": "sha256:" + "1" * 64,
        "source_db_digest": "sha256:" + "2" * 64,
        "contract_digest": "sha256:" + hashlib.sha256(
            gate._canonical_json({"tables": list(gate.PROJECTED_CONTENT_TABLES)}).encode()
        ).hexdigest(),
        "environment": "production",
        "producer_commit_sha": SHA,
        "generated_at": "2026-09-02T00:00:00Z",
        "projection_status": "UNKNOWN",
        "source_cursor": None,
        "export_cursor": None,
        "applied_cursor": None,
        "coverage_policy_version": "collection-coverage/v3",
        "dataset_coverage": {"equities_bars_daily": {"status": "UNKNOWN"}},
        "row_counts": {table: 0 for table in gate.PROJECTED_CONTENT_TABLES},
        "content_manifest": {},
    }
    body = {
        "schema_version": "ops-projection-signed-envelope/v1",
        "algorithm": "Ed25519",
        "issuer_key_id": "ops-projection-test-v1",
        "envelope": envelope,
    }
    signature = private.sign(gate._canonical_json(body).encode("utf-8"))
    row = {
        "generation_id": "gen-1",
        "status": "SEALED",
        "signature": "ed25519:" + base64.b64encode(signature).decode(),
        "content_digest": envelope["content_digest"],
        "source_db_digest": envelope["source_db_digest"],
        "contract_digest": envelope["contract_digest"],
        "registry_digest": "sha256:" + "5" * 64,
        "issuer_key_id": "ops-projection-test-v1",
        "signed_envelope_json": json.dumps(body),
        "coverage_policy_version": "collection-coverage/v3",
        "producer_commit_sha": SHA,
    }
    monkeypatch.setattr(gate, "_d1_json", lambda *_args: [row])
    with pytest.raises(gate.PredeployGateError, match="UNKNOWN"):
        gate.require_sealed_active_generation("production", now=NOW)


def test_environment_key_ids_must_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    key = Ed25519PrivateKey.generate().public_key()
    der = key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(
        gate,
        "_load_spki",
        lambda _environment: ("same-key-id", der),
    )
    with pytest.raises(gate.PredeployGateError, match="environment-scoped"):
        gate.require_sealed_active_generation("production")


def test_stale_generation_and_old_source_sha_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_generation(
        monkeypatch, generated_at="2026-09-01T00:00:00Z"
    )
    with pytest.raises(gate.PredeployGateError, match="stale"):
        gate.require_sealed_active_generation("production", now=NOW)
    _install_valid_generation(monkeypatch, producer="b" * 40)
    with pytest.raises(gate.PredeployGateError, match="producer SHA"):
        gate.require_sealed_active_generation("production", now=NOW)


@pytest.mark.parametrize(
    ("not_before", "not_after"),
    [
        ("2026-09-02T00:11:00Z", "2026-09-03T00:00:00Z"),
        ("2026-09-01T00:00:00Z", "2026-09-02T00:09:59Z"),
    ],
)
def test_key_must_be_currently_valid(
    monkeypatch: pytest.MonkeyPatch, not_before: str, not_after: str
) -> None:
    _install_valid_generation(
        monkeypatch, not_before=not_before, not_after=not_after
    )
    with pytest.raises(gate.PredeployGateError, match="validity window"):
        gate.require_sealed_active_generation("production", now=NOW)


def test_active_pointer_toctou_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_valid_generation(
        monkeypatch,
        pointer_times=("2026-09-02T00:01:00Z", "2026-09-02T00:02:00Z"),
    )
    with pytest.raises(gate.PredeployGateError, match="pointer changed"):
        gate.require_sealed_active_generation("production", now=NOW)
