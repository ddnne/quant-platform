"""Behavioral tests for immutable Ops Projection publication."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from ops.projection_meta import build_projection_metadata
from ops.projection_signing import (
    OpsProjectionPublicKeyRegistry,
    OpsProjectionSignatureError,
    OpsProjectionSigningKey,
    load_ops_projection_signer,
)
from scripts import publish_ops_projection as publisher
from scripts.export_ops_projection import render_projection_bundle
from storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "platform/workers/quant-ops-mcp/migrations/projection/0001_ops_projection.sql"


def _source(path: Path) -> None:
    store = SqliteStore(path)
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO dataset_coverage
           (dataset,status,policy_version,collection_scope,
            history_target_start,history_target_end_rule,coverage_mode,
            expected_frequency,universe_rule,raw_retention_required,
            structured_reconciliation_required,governance_tier,
            observed_start,observed_end,row_count,source_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "equities_bars_daily", "PARTIAL", "collection-coverage/v3", "jquants",
            "2008-05-07", "current", "official", "daily", "all", 1, 1,
            "governed", "2008-05-07", "2026-08-24", 10, 10,
            "2026-08-25T00:00:00Z", "{}",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jquants", "equities_bars_daily", "2008-05",
            "collection-coverage/v3", "2008-05-07", "2008-05-31", "{}", 1,
            "PARTIAL", 10, "2026-08-25T00:00:00Z", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()


def _target() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return conn


def _bundle(path: Path, generation: str):
    return render_projection_bundle(
        path,
        generation_id=generation,
        producer_commit_sha="d" * 40,
        refresh_status="success",
        last_success_at="2026-08-25T00:01:00Z",
    )


def test_render_is_append_only_and_pointer_is_last(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    sql = _bundle(source, "projgen-one").sql
    assert "DELETE FROM" not in sql
    assert "INSERT OR REPLACE" not in sql
    assert "UPDATE ops_projection_generation" not in sql
    statements = [line for line in sql.splitlines() if line and line != "COMMIT;"]
    assert statements[-1].startswith("INSERT INTO ops_projection_active")


def test_two_generations_preserve_prior_rows_and_flip_pointer(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    first = _bundle(source, "projgen-first")
    second = _bundle(source, "projgen-second")
    target = _target()
    target.executescript(first.sql)
    target.executescript(second.sql)
    assert target.execute("SELECT COUNT(*) FROM dataset_coverage").fetchone() == (2,)
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-second",)
    assert target.execute(
        "SELECT COUNT(*) FROM dataset_coverage WHERE projection_generation_id=?",
        ("projgen-first",),
    ).fetchone() == (1,)
    target.close()


def test_incomplete_generation_cannot_replace_active_pointer(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    first = _bundle(source, "projgen-active")
    incomplete = _bundle(source, "projgen-incomplete")
    lines = [
        line for line in incomplete.sql.splitlines()
        if not line.startswith("INSERT INTO dataset_coverage ")
    ]
    target = _target()
    target.executescript(first.sql)
    target.executescript("\n".join(lines) + "\n")
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-active",)
    assert target.execute(
        "SELECT status FROM ops_projection_generation WHERE generation_id=?",
        ("projgen-incomplete",),
    ).fetchone() is None
    target.close()


def test_latest_successful_receipt_supersedes_old_failed_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    receipt = """INSERT INTO collection_receipts
      (source,dataset,segment_id,segment_start,segment_end,expected_scope,
       expected_items,observed_items,raw_page_count,raw_row_count,
       structured_row_count,pagination_exhausted,digests_json,run_id,status,
       error,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    store._conn.execute(  # noqa: SLF001
        receipt,
        (
            "jquants", "equities_bars_daily", "2008-05", "2008-05-07",
            "2008-05-31", "{}", 1, 0, 0, 0, 0, 0, "{}", 10, "FAILED",
            "timeout", "2026-08-24T00:00:00Z",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        receipt,
        (
            "jquants", "equities_bars_daily", "2008-05", "2008-05-07",
            "2008-05-31", "{}", 1, 10, 1, 10, 10, 1, "{}", 11, "SUCCESS",
            None, "2026-08-25T00:00:00Z",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO raw_retention_manifests
           (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,
            data_digest,completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "equities_bars_daily", 11, "raw/success.json", 1, 10, 100,
            "sha256:success", "ACQUIRED", "2026-08-25T00:00:00Z",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    bundle = _bundle(source, "projgen-raw")
    target = _target()
    target.executescript(bundle.sql)
    assert target.execute(
        "SELECT source,run_id,completeness,reason FROM raw_retention_manifests "
        "WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == (
        "jquants", 11, "ACQUIRED", "latest authoritative segment receipt"
    )
    target.close()


def test_storage_aggregate_has_no_default_cutoff(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    target = _target()
    bundle = _bundle(source, "projgen-storage")
    target.executescript(bundle.sql)
    payload = json.loads(
        target.execute(
            "SELECT payload_json FROM ops_storage_plane_status "
            "WHERE projection_generation_id=?",
            (bundle.generation_id,),
        ).fetchone()[0]
    )
    assert payload["hot_window"] == {
        "cutoff": None,
        "reason": "publisher did not receive an explicit storage hot cutoff",
        "status": "NOT_PROJECTED",
    }
    target.close()


def test_explicit_hot_cutoff_is_materialized_at_publish_time(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO jquants_records
           (source,dataset,natural_key,event_time,available_at,ingested_at,
            payload,raw_payload) VALUES (?,?,?,?,?,?,?,?)""",
        (
            "jquants", "equities_bars_daily", '{"Code":"1"}', "2026-08-24",
            "2026-08-24T15:30:00Z", "2026-08-25T00:00:00Z", "{}", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    bundle = render_projection_bundle(
        source,
        generation_id="projgen-hot",
        producer_commit_sha="e" * 40,
        storage_hot_cutoff="2026-08-01",
    )
    target = _target()
    target.executescript(bundle.sql)
    payload = json.loads(
        target.execute("SELECT payload_json FROM ops_storage_plane_status").fetchone()[0]
    )
    assert payload["hot_window"]["status"] == "MATERIALIZED"
    assert payload["hot_window"]["cutoff"] == "2026-08-01"
    assert payload["hot_window"]["bars_hot"] == 1
    target.close()


def test_publish_dry_run_does_not_write_artifacts(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [f"--db={source}", f"--output={output}", f"--meta-output={meta}", "--dry-run"]
    ) == 0
    assert not output.exists()
    assert not meta.exists()
    rendered = capsys.readouterr().out
    assert '"generation_id"' in rendered
    assert '"source_db_digest"' in rendered


def test_publish_writes_content_addressed_generation_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [f"--db={source}", f"--output={output}", f"--meta-output={meta}"]
    ) == 0
    document = json.loads(meta.read_text(encoding="utf-8"))
    assert document["generation_id"].startswith("projgen-")
    assert document["source_db_digest"].startswith("sha256:")
    assert document["row_counts"]["ops_projection_metadata"] == 1
    assert "DELETE FROM" not in output.read_text(encoding="utf-8")


def test_signed_projection_envelope_binds_content_cursors_and_gate_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = OpsProjectionSigningKey("ops-projection-test-v1", private)
    bundle = render_projection_bundle(
        source,
        generation_id="projgen-signed",
        producer_commit_sha="f" * 40,
        source_cursor=12,
        export_cursor=11,
        projection_signer=signer,
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    import base64

    registry = OpsProjectionPublicKeyRegistry.from_document(
        {
            "schema_version": 1,
            "keys": [
                {
                    "key_id": "ops-projection-test-v1",
                    "algorithm": "Ed25519",
                    "public_key_base64": base64.b64encode(public_raw).decode("ascii"),
                }
            ],
        }
    )
    assert bundle.signed_envelope is not None
    schema = json.loads(
        (ROOT / "specs/ops_projection/signed_envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(bundle.signed_envelope)
    envelope = registry.verify(bundle.signed_envelope)
    assert envelope["generation_id"] == "projgen-signed"
    assert envelope["content_digest"] == bundle.content_digest
    assert envelope["source_cursor"] == 12
    assert envelope["export_cursor"] == 11
    assert envelope["applied_cursor"] is None
    assert envelope["coverage_status_digest"].startswith("sha256:")
    assert envelope["projection_status"] in {"FRESH", "STALE"}
    assert envelope["dataset_coverage"]["equities_bars_daily"]["status"] == "PARTIAL"
    assert envelope["b0_status"] == "UNKNOWN"
    assert envelope["b4_status"] == "UNKNOWN"
    assert set(envelope["evidence_digests"]) == {
        "coverage", "raw_retention", "ready", "storage", "sync", "validation"
    }
    derived = registry.verified_dataset_evidence(
        bundle.signed_envelope, ["equities_bars_daily"]
    )["equities_bars_daily"]
    assert derived["status"] == "PARTIAL"
    assert derived["coverage_mode"] == "official"
    assert derived["source_generation"] == 12
    assert derived["export_cursor"] == 11
    assert derived["applied_cursor"] is None

    tampered = json.loads(json.dumps(bundle.signed_envelope))
    tampered["envelope"]["applied_cursor"] = 12
    with pytest.raises(OpsProjectionSignatureError, match="signature is invalid"):
        registry.verify(tampered)


def test_remote_publish_requires_dedicated_ops_projection_signer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    monkeypatch.delenv("QUANT_OPS_PROJECTION_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("QUANT_OPS_PROJECTION_SIGNING_KEY_ID", raising=False)
    assert publisher.main([f"--db={source}", "--apply-remote"]) == 6


def test_receipt_and_ready_keys_never_mint_ops_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    ready_path = tmp_path / "readiness.pem"
    ready_path.write_bytes(pem)
    monkeypatch.setenv("QUANT_RECEIPT_SIGNING_KEY_PEM", pem.decode("ascii"))
    monkeypatch.setenv("QUANT_READINESS_SIGNING_KEY_FILE", str(ready_path))
    monkeypatch.delenv("QUANT_OPS_PROJECTION_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("QUANT_OPS_PROJECTION_SIGNING_KEY_ID", raising=False)
    assert load_ops_projection_signer() is None


def test_failed_refresh_never_publishes_fresh_or_applies(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)

    def fail(*_args, **_kwargs):
        raise RuntimeError("ledger failure")

    monkeypatch.setattr("storage.coverage_ledger.refresh_coverage_ledger", fail)
    monkeypatch.setattr(publisher, "count_local_complete", lambda _path: 0)
    monkeypatch.setattr(publisher, "count_remote_complete", lambda **_kwargs: 0)
    monkeypatch.setattr(
        publisher,
        "load_ops_projection_signer",
        lambda **_kwargs: OpsProjectionSigningKey(
            "ops-projection-test-v1", Ed25519PrivateKey.generate()
        ),
    )
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [
            f"--db={source}", f"--output={output}", f"--meta-output={meta}",
            "--refresh-coverage", "--apply-remote",
        ]
    ) == 4
    document = json.loads(meta.read_text(encoding="utf-8"))
    assert document["status"] == "FAILED"


def test_projection_metadata_requires_successful_refresh_for_fresh(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    assert build_projection_metadata(source, refresh_status="skipped")["status"] == "STALE"
    assert build_projection_metadata(source, refresh_status="success")["status"] == "FRESH"
