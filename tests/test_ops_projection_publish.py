"""Behavioral tests for immutable Ops Projection publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import gc
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from data_contracts.coverage import all_coverage_contracts, coverage_policy_binding
from ops import projection_signing
from ops.projection_meta import build_projection_metadata
from ops.projection_content import (
    PROJECTED_CONTENT_TABLES,
    build_projection_content_manifest,
)
from ops.projection_signing import (
    OpsProjectionSignatureError,
    PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_GENERATION,
    open_ops_projection_signing_service,
    sha256_digest,
    verified_pinned_ops_projection_dataset_evidence as _verified_pinned_ops_projection_dataset_evidence,
    verify_pinned_ops_projection as _verify_pinned_ops_projection,
)
from scripts import export_ops_projection as exporter
from scripts import publish_ops_projection as publisher
from scripts import sync_d1_to_sqlite as sync_script
from scripts.export_ops_projection import (
    _render_trusted_projection_bundle,
    render_projection_bundle,
)
from storage.sqlite_store import SqliteStore
from tests.ops_projection_signing_support import (
    TestOpsProjectionSigningKey,
    make_test_ops_projection_verifier,
    render_projection_bundle_for_test,
    sign_projection_bundle_for_test,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted(
    (ROOT / "platform/workers/quant-ops-mcp/migrations/projection").glob("*.sql")
)


def verify_pinned_ops_projection(document):
    return _verify_pinned_ops_projection(
        document, expected_environment="production"
    )


def verified_pinned_ops_projection_dataset_evidence(document, datasets):
    return _verified_pinned_ops_projection_dataset_evidence(
        document, datasets, expected_environment="production"
    )


def test_projection_content_digest_matches_worker_storage_representation() -> None:
    rows = {table: [] for table in PROJECTED_CONTENT_TABLES}
    rows["endpoint_inventory"] = [
        {
            "projection_generation_id": "g",
            "dataset_id": "日本株",
            "research_eligible": True,
            "enabled": False,
            "weight": 1.0,
            "note": "東京",
        }
    ]
    manifest, _digest = build_projection_content_manifest(rows)
    assert manifest["endpoint_inventory"]["content_digest"] == (
        "sha256:76195ac60aedf9a62db147dd1c8914282617553423c5d0fb918627447aac7d61"
    )
    rows["endpoint_inventory"][0]["weight"] = 1.25
    with pytest.raises(ValueError, match="non-integral REAL"):
        build_projection_content_manifest(rows)


def _source(path: Path) -> None:
    store = SqliteStore(path)
    coverage_rows = []
    for contract in all_coverage_contracts():
        observed = contract.dataset_id == "equities_bars_daily"
        coverage_rows.append(
            (
                contract.dataset_id,
                "PARTIAL",
                coverage_policy_binding(contract.dataset_id)["policy_version"],
                contract.collection_scope,
                contract.history_target_start,
                contract.history_target_end_rule,
                contract.coverage_mode,
                contract.expected_frequency,
                contract.universe_rule,
                int(contract.raw_retention_required),
                int(contract.structured_reconciliation_required),
                contract.governance_tier,
                "2008-05-07" if observed else None,
                "2026-08-24" if observed else None,
                10 if observed else 0,
                10,
                "2026-08-25T00:00:00Z",
                "{}",
            )
        )
    store._conn.executemany(  # noqa: SLF001
        """INSERT INTO dataset_coverage
           (dataset,status,policy_version,collection_scope,
            history_target_start,history_target_end_rule,coverage_mode,
            expected_frequency,universe_rule,raw_retention_required,
            structured_reconciliation_required,governance_tier,
            observed_start,observed_end,row_count,source_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        coverage_rows,
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
    for migration in MIGRATIONS:
        conn.executescript(migration.read_text(encoding="utf-8"))
    return conn


def _opaque_source(path: Path, marker: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE opaque_source_marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO opaque_source_marker VALUES (?)", (marker,))
        conn.commit()
        assert conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (
            0,
            0,
            0,
        )
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone() == (
            "delete",
        )
    finally:
        conn.close()


def _test_mirror_identity(
    *,
    source_cursor: object = 7,
    applied_cursor: object = 7,
    distinct_source_schema: bool = False,
):
    def identity(conn: sqlite3.Connection) -> dict[str, object]:
        marker = conn.execute(
            "SELECT value FROM opaque_source_marker"
        ).fetchone()[0]
        digest = sha256_digest({"opaque_source_marker": marker})
        source_schema_digest = (
            sha256_digest({"source_schema": "remote"})
            if distinct_source_schema
            else digest
        )
        return {
            "environment": "production",
            "resource_identity": {
                "provider": "cloudflare",
                "kind": "d1",
                "name": "quant-ingest",
                "database_id": "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
                "authority_id": "cloudflare-d1:be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
            },
            "audit_digest": digest,
            "issuer_key_id": "test-d1-sync-authority",
            "export_digest": digest,
            "source_change_seq": source_cursor,
            "applied_change_seq": applied_cursor,
            "source_content_digest": digest,
            "local_content_digest": digest,
            "source_schema_digest": source_schema_digest,
            "schema_digest": digest,
            "table_counts": {
                table: 0 for table in sync_script.DEFAULT_TABLES
            },
        }

    return identity


def _bundle(path: Path, generation: str):
    return render_projection_bundle(
        path,
        generation_id=generation,
        producer_commit_sha="d" * 40,
        refresh_status="success",
        last_success_at="2026-08-25T00:01:00Z",
    )


def _insert_ingestion_run(store: SqliteStore, run_id: int, source: str) -> None:
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log "
        "(id,ran_at,source,runtime,status,detail) VALUES (?,?,?,?,?,?)",
        (
            run_id,
            "2026-08-25T00:00:00Z",
            source,
            "governed-test",
            "pass",
            "{}",
        ),
    )


def _insert_collection_receipt(
    store: SqliteStore,
    *,
    source: str,
    dataset: str,
    run_id: int,
    segment_id: str,
    digests: Mapping[str, object] | None = None,
    status: str = "SUCCESS",
) -> None:
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO collection_receipts
          (source,dataset,segment_id,segment_start,segment_end,expected_scope,
           expected_items,observed_items,raw_page_count,raw_row_count,
           structured_row_count,pagination_exhausted,digests_json,run_id,
           status,error,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            source,
            dataset,
            segment_id,
            "2026-08-25",
            "2026-08-25",
            "{}",
            1,
            1,
            1,
            1,
            1,
            1,
            json.dumps(digests or {}, sort_keys=True, separators=(",", ":")),
            run_id,
            status,
            None if status == "SUCCESS" else "collection failed",
            "2026-08-25T00:00:00Z",
        ),
    )


def _insert_raw_manifest(
    store: SqliteStore,
    *,
    dataset: str,
    run_id: int,
    completeness: str = "ACQUIRED",
) -> None:
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO raw_retention_manifests
           (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,
            data_digest,completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            dataset,
            run_id,
            f"raw/{dataset}/{run_id}.json",
            1,
            1,
            10,
            f"sha256:{run_id:064x}",
            completeness,
            "2026-08-25T00:00:00Z",
        ),
    )


def _receipt_product_projection_source() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE collection_receipts (
          source TEXT, dataset TEXT, segment_id TEXT, segment_start TEXT,
          segment_end TEXT, expected_scope TEXT, expected_items INTEGER,
          observed_items INTEGER, raw_page_count INTEGER, raw_row_count INTEGER,
          structured_row_count INTEGER, pagination_exhausted INTEGER,
          digests_json TEXT, run_id INTEGER, status TEXT, error TEXT,
          checked_at TEXT
        );
        CREATE TABLE receipt_product_materializations (
          operation_id TEXT, run_id INTEGER, source TEXT, dataset TEXT,
          segment_id TEXT, artifact_key TEXT, artifact_digest TEXT,
          artifact_body TEXT, row_count INTEGER, byte_count INTEGER,
          manifest_key TEXT, manifest_digest TEXT, raw_manifest_key TEXT,
          raw_manifest_digest TEXT, raw_page_count INTEGER,
          raw_row_count INTEGER, raw_bytes INTEGER, committed_at TEXT
        );
        CREATE TABLE ingestion_run_log (
          id INTEGER, source TEXT, runtime TEXT, status TEXT,
          authority_operation_id TEXT
        );
        CREATE TABLE raw_retention_manifests (
          dataset TEXT, run_id INTEGER, manifest_key TEXT, page_count INTEGER,
          row_count INTEGER, raw_bytes INTEGER, data_digest TEXT
        );
        CREATE TABLE jquants_records (
          source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT,
          available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT
        );
        """
    )
    return conn


def _insert_product_receipt_candidate(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    segment_id: str = "2024-02",
) -> None:
    digests = {
        "eligibility": "TRUSTED_COLLECTION",
        "issuer_class": "SignedReceiptAuthority",
        "structured_digest": f"sha256:{run_id:064x}",
        "raw_manifest_digest": f"sha256:{run_id + 1000:064x}",
    }
    conn.execute(
        "INSERT INTO collection_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "indices_bars_daily_topix",
            segment_id,
            "2024-02-01",
            "2024-02-29",
            "{}",
            1,
            1,
            1,
            1,
            1,
            1,
            json.dumps(digests, sort_keys=True, separators=(",", ":")),
            run_id,
            "SUCCESS",
            None,
            f"2026-08-25T00:00:{run_id % 60:02d}Z",
        ),
    )


def _insert_current_product_materialization(
    conn: sqlite3.Connection,
    *,
    run_id: int,
) -> None:
    row = {
        "source": "jquants",
        "dataset": "indices_bars_daily_topix",
        "natural_key": '{"Date":"2024-02-01"}',
        "event_time": "2024-02-01T00:00:00Z",
        "available_at": "2024-02-01T00:00:00Z",
        "ingested_at": "2026-08-25T00:00:00Z",
        "payload": '{"Close":2,"Date":"2024-02-01","Open":1}',
        "raw_payload": '{"Date":"2024-02-01","Open":1,"Close":2}',
    }
    body = exporter.canonical_product_artifact_bytes([row]).decode("utf-8")
    digest = exporter.product_artifact_body_digest(body)
    raw_digest = f"sha256:{run_id + 1000:064x}"
    operation_id = f"sha256:{run_id:064x}"
    conn.execute(
        "UPDATE collection_receipts SET digests_json=? WHERE run_id=?",
        (
            json.dumps(
                {
                    "eligibility": "TRUSTED_COLLECTION",
                    "issuer_class": "SignedReceiptAuthority",
                    "structured_digest": digest,
                    "raw_manifest_digest": raw_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            run_id,
        ),
    )
    conn.execute(
        "INSERT INTO receipt_product_materializations VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            operation_id,
            run_id,
            row["source"],
            row["dataset"],
            "2024-02",
            f"structured/{run_id}.jsonl",
            digest,
            body,
            1,
            len(body.encode("utf-8")),
            f"structured/{run_id}.manifest.json",
            f"sha256:{run_id + 2000:064x}",
            f"raw/{run_id}.manifest.json",
            raw_digest,
            1,
            1,
            100,
            f"2026-08-25T00:00:{run_id % 60:02d}Z",
        ),
    )
    conn.execute(
        "INSERT INTO ingestion_run_log VALUES (?,?,?,?,?)",
        (run_id, "jquants", "receipt-evidence-authority", "SUCCESS", operation_id),
    )
    conn.execute(
        "INSERT INTO raw_retention_manifests VALUES (?,?,?,?,?,?,?)",
        (row["dataset"], run_id, f"raw/{run_id}.manifest.json", 1, 1, 100, raw_digest),
    )
    conn.execute(
        "INSERT INTO jquants_records VALUES (?,?,?,?,?,?,?,?)",
        tuple(row.values()),
    )


def test_product_projection_selects_only_latest_active_receipt_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _receipt_product_projection_source()
    _insert_product_receipt_candidate(conn, run_id=101)
    _insert_product_receipt_candidate(conn, run_id=102)
    _insert_current_product_materialization(conn, run_id=102)

    def verify(receipt: object) -> SimpleNamespace:
        run_id = object.__getattribute__(receipt, "run_id")
        return SimpleNamespace(run_id=run_id, structured_generation=run_id)

    monkeypatch.setattr(exporter, "verify_collection_closure", verify)
    rows = exporter._read_receipt_product_materializations(conn, "generation")
    assert [row["run_id"] for row in rows] == [102]
    conn.close()


def test_product_projection_keeps_revoked_receipt_audit_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _receipt_product_projection_source()
    _insert_product_receipt_candidate(conn, run_id=101)

    def inactive(_receipt: object) -> None:
        raise exporter.ReceiptVerificationError("key is not active")

    monkeypatch.setattr(exporter, "verify_collection_closure", inactive)
    monkeypatch.setattr(
        exporter, "receipt_verify_key_status", lambda _key_id: "revoked"
    )
    monkeypatch.setattr(
        exporter,
        "audit_signed_receipt_claims",
        lambda _receipt: MappingProxyType({"version": "signed-receipt-claims/v2"}),
    )
    assert exporter._read_receipt_product_materializations(conn, "generation") == []
    conn.close()


def test_product_projection_rejects_forged_trusted_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _receipt_product_projection_source()
    _insert_product_receipt_candidate(conn, run_id=101)

    def rejected(_receipt: object) -> None:
        raise exporter.ReceiptVerificationError("invalid signature")

    monkeypatch.setattr(exporter, "verify_collection_closure", rejected)
    monkeypatch.setattr(
        exporter, "receipt_verify_key_status", lambda _key_id: "active"
    )
    with pytest.raises(RuntimeError, match="non-revoked trusted receipt"):
        exporter._read_receipt_product_materializations(conn, "generation")
    conn.close()


def test_product_projection_rejects_corrupt_revoked_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _receipt_product_projection_source()
    _insert_product_receipt_candidate(conn, run_id=101)

    def rejected(_receipt: object) -> None:
        raise exporter.ReceiptVerificationError("invalid signature")

    monkeypatch.setattr(exporter, "verify_collection_closure", rejected)
    monkeypatch.setattr(exporter, "audit_signed_receipt_claims", rejected)
    monkeypatch.setattr(
        exporter, "receipt_verify_key_status", lambda _key_id: "revoked"
    )
    with pytest.raises(RuntimeError, match="neither active nor valid audit evidence"):
        exporter._read_receipt_product_materializations(conn, "generation")
    conn.close()


def _recreate_evidence_table_without_constraints(
    store: SqliteStore,
    table: str,
) -> None:
    if table not in {
        "collection_receipts",
        "ingestion_run_log",
        "raw_retention_manifests",
    }:
        raise ValueError(f"unsupported test evidence table: {table}")
    retained = table + "_with_constraints"
    store._conn.execute(f'ALTER TABLE "{table}" RENAME TO "{retained}"')  # noqa: S608,SLF001
    store._conn.execute(  # noqa: S608,SLF001
        f'CREATE TABLE "{table}" AS SELECT * FROM "{retained}" WHERE 0'
    )
    store._conn.execute(f'DROP TABLE "{retained}"')  # noqa: S608,SLF001


def test_two_generations_preserve_prior_rows_and_flip_pointer(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    first = _bundle(source, "projgen-first")
    second = _bundle(source, "projgen-second")
    target = _target()
    target.executescript(first.sql)
    target.executescript(second.sql)
    assert target.execute("SELECT COUNT(*) FROM dataset_coverage").fetchone() == (
        2 * len(all_coverage_contracts()),
    )
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-second",)
    assert target.execute(
        "SELECT COUNT(*) FROM dataset_coverage WHERE projection_generation_id=?",
        ("projgen-first",),
    ).fetchone() == (len(all_coverage_contracts()),)
    target.close()


def test_published_sql_storage_rows_rehash_to_the_signed_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    bundle = _bundle(source, "projgen-storage-parity")
    target = _target()
    target.executescript(bundle.sql)
    stored: dict[str, list[dict[str, object]]] = {}
    for table in PROJECTED_CONTENT_TABLES:
        cursor = target.execute(
            f"SELECT * FROM {table} WHERE projection_generation_id=?",  # noqa: S608
            (bundle.generation_id,),
        )
        columns = [str(item[0]) for item in cursor.description or ()]
        stored[table] = [dict(zip(columns, row, strict=True)) for row in cursor]
    manifest, digest = build_projection_content_manifest(stored)
    assert digest == bundle.content_digest
    assert {table: row["row_count"] for table, row in manifest.items()} == dict(
        bundle.row_counts
    )
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
    ).fetchone() == ("OPEN",)
    target.close()


def test_pointer_update_atomically_rejects_cursor_regression(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)

    def set_cursor(value: int) -> None:
        with sqlite3.connect(source) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sync_change_state "
                "(feed,last_applied_change_seq,updated_at) VALUES (?,?,?)",
                ("jquants_records", value, "2026-08-25T00:00:00Z"),
            )

    cursor = 12
    set_cursor(cursor)
    first = render_projection_bundle_for_test(
        source,
        source_cursor=cursor,
        export_cursor=cursor,
        generation_id="projgen-cursor-12",
        producer_commit_sha="a" * 40,
    )
    target = _target()
    target.executescript(first.sql)

    cursor = 11
    set_cursor(cursor)
    replay = render_projection_bundle_for_test(
        source,
        source_cursor=cursor,
        export_cursor=cursor,
        generation_id="projgen-cursor-11",
        producer_commit_sha="b" * 40,
    )
    target.executescript(replay.sql)
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-cursor-12",)
    assert target.execute(
        "SELECT status FROM ops_projection_generation WHERE generation_id=?",
        ("projgen-cursor-11",),
    ).fetchone() == ("SEALED",)
    target.close()


def test_newer_successful_run_supersedes_late_closing_old_failed_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    store._conn.executemany(  # noqa: SLF001
        "INSERT INTO ingestion_run_log "
        "(id,ran_at,source,runtime,status,detail) VALUES (?,?,?,?,?,?)",
        (
            (10, "2026-08-24T00:00:00Z", "jsda", "governed-test", "failed", "{}"),
            (11, "2026-08-25T00:00:00Z", "jsda", "governed-test", "pass", "{}"),
        ),
    )
    receipt = """INSERT INTO collection_receipts
      (source,dataset,segment_id,segment_start,segment_end,expected_scope,
       expected_items,observed_items,raw_page_count,raw_row_count,
       structured_row_count,pagination_exhausted,digests_json,run_id,status,
       error,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    store._conn.execute(  # noqa: SLF001
        receipt,
        (
            "jsda", "jsda_otc_bond_reference_prices", "2002-08-02",
            "2002-08-02", "2002-08-02", "{}", 1, 0, 0, 0, 0, 0, "{}",
            10, "FAILED",
            "timeout", "2026-08-26T00:00:00Z",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        receipt,
        (
            "jsda", "jsda_otc_bond_reference_prices", "2002-08-02",
            "2002-08-02", "2002-08-02", "{}", 1, 10, 1, 10, 10, 1, "{}",
            11, "SUCCESS",
            None, "2026-08-25T00:00:00Z",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO raw_retention_manifests
           (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,
            data_digest,completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "jsda_otc_bond_reference_prices", 11, "raw/success.json", 1, 10, 100,
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
        "jsda",
        11,
        "ACQUIRED",
        "latest operational raw acquisition receipt",
    )
    target.close()


def test_run_projection_globally_rejects_unreferenced_duplicate_ids(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _recreate_evidence_table_without_constraints(store, "ingestion_run_log")
    _insert_ingestion_run(store, 50, "jquants")
    _insert_ingestion_run(store, 50, "jsda")
    store._conn.commit()  # noqa: SLF001
    store.close()

    with pytest.raises(RuntimeError, match="duplicate authority id"):
        _bundle(source, "projgen-unreferenced-duplicate-run")


@pytest.mark.parametrize(
    ("run_id", "source_name"),
    ((0, "jsda"), ("not-an-integer", "jsda"), (52, " jsda"), (53, 1)),
)
def test_run_projection_globally_rejects_noncanonical_unreferenced_identity(
    tmp_path: Path,
    run_id: object,
    source_name: object,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _recreate_evidence_table_without_constraints(store, "ingestion_run_log")
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log "
        "(id,ran_at,source,runtime,status,detail) VALUES (?,?,?,?,?,?)",
        (
            run_id,
            "2026-08-25T00:00:00Z",
            source_name,
            "governed-test",
            "pass",
            "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    with pytest.raises(RuntimeError, match="non-canonical positive integer id"):
        _bundle(source, "projgen-unreferenced-noncanonical-run")


def test_run_projection_uses_positive_id_as_deterministic_authority_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _insert_ingestion_run(store, 51, "jquants")
    _insert_ingestion_run(store, 53, "jsda")
    _insert_ingestion_run(store, 52, "jquants")
    store._conn.commit()  # noqa: SLF001
    store.close()

    with sqlite3.connect(source) as conn:
        rows = exporter._read_latest_runs(
            conn,
            "projgen-run-order",
            exporter._capture_projection_contract_snapshot(),
        )
    assert [(row["id"], row["source"]) for row in rows] == [
        (53, "jsda"),
        (52, "jquants"),
        (51, "jquants"),
    ]


@pytest.mark.parametrize("table", ["collection_receipts", "raw_retention_manifests"])
def test_raw_projection_rejects_noncanonical_run_id(
    tmp_path: Path,
    table: str,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    if table == "collection_receipts":
        store._conn.execute(  # noqa: SLF001
            """INSERT INTO collection_receipts
              (source,dataset,segment_id,segment_start,segment_end,expected_scope,
               expected_items,observed_items,raw_page_count,raw_row_count,
               structured_row_count,pagination_exhausted,digests_json,run_id,
               status,error,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "jsda", "jsda_otc_bond_reference_prices", "bad-run",
                "2002-08-02", "2002-08-02", "{}", 1, 0, 0, 0, 0, 0, "{}",
                "not-an-integer", "FAILED", "invalid", "2026-08-25T00:00:00Z",
            ),
        )
    else:
        store._conn.execute(  # noqa: SLF001
            """INSERT INTO raw_retention_manifests
               (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,
                data_digest,completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "jsda_otc_bond_reference_prices", "not-an-integer", "raw/bad",
                0, 0, 0, "sha256:bad", "FAILED", "2026-08-25T00:00:00Z",
            ),
        )
    store._conn.commit()  # noqa: SLF001
    store.close()
    with pytest.raises(RuntimeError, match="non-canonical positive integer run_id"):
        _bundle(source, "projgen-bad-run-id")


def test_raw_projection_rejects_receipt_without_authority_run(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO collection_receipts
          (source,dataset,segment_id,segment_start,segment_end,expected_scope,
           expected_items,observed_items,raw_page_count,raw_row_count,
           structured_row_count,pagination_exhausted,digests_json,run_id,
           status,error,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jsda", "jsda_otc_bond_reference_prices", "orphan-run",
            "2002-08-02", "2002-08-02", "{}", 1, 0, 0, 0, 0, 0, "{}", 99,
            "FAILED", "orphan", "2026-08-25T00:00:00Z",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    with pytest.raises(RuntimeError, match="authority-bound to its source run"):
        _bundle(source, "projgen-orphan-run-id")


def test_raw_projection_rejects_cross_source_dataset_spoof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _insert_ingestion_run(store, 20, "jquants")
    _insert_collection_receipt(
        store,
        source="jquants",
        dataset="jsda_otc_bond_reference_prices",
        run_id=20,
        segment_id="spoofed-jsda-segment",
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    with pytest.raises(RuntimeError, match="mismatches frozen canonical inventory"):
        _bundle(source, "projgen-cross-source-spoof")


def test_raw_projection_rejects_manifest_without_exact_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _insert_ingestion_run(store, 21, "jquants")
    _insert_raw_manifest(store, dataset="equities_bars_daily", run_id=21)
    store._conn.commit()  # noqa: SLF001
    store.close()

    with pytest.raises(RuntimeError, match="no exact operational acquisition"):
        _bundle(source, "projgen-orphan-raw")


@pytest.mark.parametrize(
    ("duplicate_table", "message"),
    [
        ("collection_receipts", "duplicate authoritative identity"),
        ("raw_retention_manifests", "duplicate acquisition identity"),
        ("ingestion_run_log", "duplicate authority id"),
    ],
)
def test_raw_projection_rejects_duplicate_authority_identities(
    tmp_path: Path,
    duplicate_table: str,
    message: str,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _recreate_evidence_table_without_constraints(store, duplicate_table)
    _insert_ingestion_run(store, 23, "jquants")
    if duplicate_table == "ingestion_run_log":
        _insert_ingestion_run(store, 23, "jquants")
    _insert_collection_receipt(
        store,
        source="jquants",
        dataset="equities_bars_daily",
        run_id=23,
        segment_id="duplicate-identity",
    )
    if duplicate_table == "collection_receipts":
        _insert_collection_receipt(
            store,
            source="jquants",
            dataset="equities_bars_daily",
            run_id=23,
            segment_id="duplicate-identity",
            status="FAILED",
        )
    if duplicate_table == "raw_retention_manifests":
        _insert_raw_manifest(store, dataset="equities_bars_daily", run_id=23)
        store._conn.execute(  # noqa: SLF001
            "INSERT INTO raw_retention_manifests "
            "SELECT dataset,run_id,manifest_key || '-conflict',page_count,row_count,"
            "raw_bytes,data_digest,completeness,created_at "
            "FROM raw_retention_manifests WHERE dataset=? AND run_id=?",
            ("equities_bars_daily", 23),
        )
    store._conn.commit()  # noqa: SLF001
    store.close()

    with pytest.raises(RuntimeError, match=message):
        _bundle(source, f"projgen-duplicate-{duplicate_table}")


@pytest.mark.parametrize("evidence_table", ["receipt", "raw"])
def test_raw_projection_rejects_unknown_dataset(
    tmp_path: Path,
    evidence_table: str,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _insert_ingestion_run(store, 22, "jquants")
    if evidence_table == "receipt":
        _insert_collection_receipt(
            store,
            source="jquants",
            dataset="unknown_dataset",
            run_id=22,
            segment_id="unknown",
        )
    else:
        _insert_raw_manifest(store, dataset="unknown_dataset", run_id=22)
    store._conn.commit()  # noqa: SLF001
    store.close()

    with pytest.raises(RuntimeError, match="unknown canonical dataset"):
        _bundle(source, f"projgen-unknown-{evidence_table}")


def test_unsigned_operational_receipts_emit_raw_only_not_coverage_or_ready(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    for run_id, plane, dataset in (
        (30, "jquants", "equities_bars_daily"),
        (31, "jsda", "jsda_otc_bond_reference_prices"),
    ):
        _insert_ingestion_run(store, run_id, plane)
        _insert_collection_receipt(
            store,
            source=plane,
            dataset=dataset,
            run_id=run_id,
            segment_id=f"segment-{run_id}",
        )
        _insert_raw_manifest(store, dataset=dataset, run_id=run_id)
    store._conn.commit()  # noqa: SLF001
    store.close()

    with sqlite3.connect(source) as conn:
        operational_digests = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT digests_json FROM collection_receipts ORDER BY run_id"
            )
        ]
    assert operational_digests == [{}, {}]

    bundle = _bundle(source, "projgen-valid-source-bindings")
    target = _target()
    target.executescript(bundle.sql)
    assert target.execute(
        "SELECT source,dataset,run_id,completeness,reason "
        "FROM raw_retention_manifests ORDER BY run_id"
    ).fetchall() == [
        (
            "jquants",
            "equities_bars_daily",
            30,
            "ACQUIRED",
            "latest operational raw acquisition receipt",
        ),
        (
            "jsda",
            "jsda_otc_bond_reference_prices",
            31,
            "ACQUIRED",
            "latest operational raw acquisition receipt",
        ),
    ]
    assert target.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?",
        ("equities_bars_daily",),
    ).fetchone() == ("PARTIAL",)
    assert target.execute(
        "SELECT status,snapshot_id FROM ops_ready_state"
    ).fetchone() == ("NOT_READY", None)
    assert target.execute("SELECT COUNT(*) FROM ops_ready_snapshots").fetchone() == (
        0,
    )
    target.close()


@pytest.mark.parametrize(
    "digests",
    (
        {
            "eligibility": "RECOVERED_RAW_ONLY",
            "origin": "recovered-raw-only",
        },
        {"eligibility": []},
        {"eligibility": None},
        {"eligibility": "TRUSTED_COLLECTION "},
        {"origin": []},
        {"origin": {}},
        {"origin": None},
        {"synthetic": "true"},
        {"synthetic": None},
    ),
)
def test_recovered_raw_only_receipt_stays_unprojected_and_cannot_bind_raw(
    tmp_path: Path,
    digests: Mapping[str, object],
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    _insert_ingestion_run(store, 40, "jsda")
    _insert_collection_receipt(
        store,
        source="jsda",
        dataset="jsda_otc_bond_reference_prices",
        run_id=40,
        segment_id="recovered-only",
        digests=digests,
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    pending = _bundle(source, "projgen-recovered-pending")
    target = _target()
    target.executescript(pending.sql)
    assert target.execute("SELECT COUNT(*) FROM raw_retention_manifests").fetchone() == (
        0,
    )
    target.close()

    store = SqliteStore(source)
    _insert_raw_manifest(
        store,
        dataset="jsda_otc_bond_reference_prices",
        run_id=40,
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    with pytest.raises(RuntimeError, match="no exact operational acquisition"):
        _bundle(source, "projgen-recovered-cannot-upgrade")


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


def test_storage_aggregate_jsda_coverage_rejects_prefix_spoof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    with sqlite3.connect(source) as conn:
        snapshot = exporter._capture_projection_contract_snapshot()
        exact_jsda = exporter._canonical_jsda_datasets(snapshot)
        assert exact_jsda == frozenset(
            {
                "jsda_corporate_bond_transactions",
                "jsda_otc_bond_reference_prices",
                "jsda_tokyo_repo_rates",
            }
        )
        payload = exporter._storage_payload(
            conn,
            generation_id="projgen-storage-jsda-membership",
            generated_at="2026-08-25T00:00:00Z",
            source_db_digest="sha256:" + "0" * 64,
            coverage=(
                {
                    "dataset": "jsda_fake",
                    "status": "COMPLETE",
                    "row_count": 999,
                },
                {
                    "dataset": "jsda_otc_bond_reference_prices",
                    "status": "PARTIAL",
                    "row_count": 5_886,
                },
            ),
            jsda_datasets=exact_jsda,
            hot_cutoff=None,
        )
    assert set(payload["jsda_coverage"]) == {
        "jsda_otc_bond_reference_prices"
    }


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
    target = _target()
    target.executescript(output.read_text(encoding="utf-8"))
    assert target.execute(
        "SELECT status FROM ops_projection_generation WHERE generation_id=?",
        (document["generation_id"],),
    ).fetchone() == ("SEALED",)
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == (document["generation_id"],)
    target.close()


def test_signed_projection_envelope_binds_content_cursors_and_gate_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-test-v1", private)
    bundle = render_projection_bundle_for_test(
        source,
        generation_id="projgen-signed",
        producer_commit_sha="f" * 40,
        source_cursor=12,
        export_cursor=11,
    )
    signed_envelope = sign_projection_bundle_for_test(bundle, signer)
    registry = make_test_ops_projection_verifier(private)
    with pytest.raises(
        OpsProjectionSignatureError, match="environment mismatch"
    ):
        projection_signing._verify_document(
            signed_envelope,
            {signer.key_id: private.public_key()},
            expected_environment="staging",
        )
    assert bundle.signed_envelope is None
    schema = json.loads(
        (ROOT / "specs/ops_projection/signed_envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(signed_envelope)
    envelope = registry.verify(signed_envelope)
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
        "coverage", "product_materializations", "raw_retention", "ready",
        "storage", "sync", "validation"
    }
    derived = registry.verified_dataset_evidence(
        signed_envelope, ["equities_bars_daily"]
    )["equities_bars_daily"]
    assert derived["status"] == "PARTIAL"
    assert derived["coverage_mode"] == next(
        row.coverage_mode
        for row in all_coverage_contracts()
        if row.dataset_id == "equities_bars_daily"
    )
    assert derived["source_generation"] == 12
    assert derived["export_cursor"] == 11
    assert derived["applied_cursor"] is None

    with pytest.raises(OpsProjectionSignatureError, match="issuer is not trusted"):
        verify_pinned_ops_projection(signed_envelope)

    tampered = json.loads(json.dumps(signed_envelope))
    tampered["envelope"]["applied_cursor"] = 12
    with pytest.raises(OpsProjectionSignatureError, match="signature is invalid"):
        registry.verify(tampered)

    former = json.loads(json.dumps(signed_envelope))
    former["issuer_key_id"] = "ops-projection-20260825-v1"
    with pytest.raises(OpsProjectionSignatureError, match="issuer is not trusted"):
        verify_pinned_ops_projection(former)


def test_pinned_projection_verifier_freezes_one_exact_document_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-ephemeral", private)
    bundle = render_projection_bundle_for_test(
        source,
        generation_id="signed-A",
        producer_commit_sha="f" * 40,
        source_cursor=12,
        export_cursor=12,
    )
    signed_a = sign_projection_bundle_for_test(bundle, signer)
    monkeypatch.setattr(
        projection_signing,
        "_load_pinned_active_keys",
        lambda _environment="production": {signer.key_id: private.public_key()},
    )

    verified = verify_pinned_ops_projection(signed_a)
    assert verified["generation_id"] == "signed-A"
    dataset = "equities_bars_daily"
    original_status = verified["dataset_coverage"][dataset]["status"]
    signed_a["envelope"]["generation_id"] = "mutated-after-verify"
    signed_a["envelope"]["dataset_coverage"][dataset]["status"] = "COMPLETE"
    assert verified["generation_id"] == "signed-A"
    assert verified["dataset_coverage"][dataset]["status"] == original_status
    with pytest.raises(TypeError):
        verified["generation_id"] = "mutable"  # type: ignore[index]
    with pytest.raises(TypeError):
        verified["dataset_coverage"][dataset]["status"] = "COMPLETE"


def test_verified_dataset_evidence_retains_signed_document_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-ephemeral", private)
    signed = sign_projection_bundle_for_test(
        render_projection_bundle_for_test(
            source,
            generation_id="signed-A",
            producer_commit_sha="f" * 40,
            source_cursor=12,
            export_cursor=12,
        ),
        signer,
    )
    monkeypatch.setattr(
        projection_signing,
        "_load_pinned_active_keys",
        lambda _environment="production": {signer.key_id: private.public_key()},
    )
    expected_digest = sha256_digest(signed)

    envelope, evidence = verified_pinned_ops_projection_dataset_evidence(
        signed, ("equities_bars_daily",)
    )
    signed["issuer_key_id"] = "unsigned-B"
    signed["envelope"]["generation_id"] = "unsigned-B"  # type: ignore[index]
    row = evidence["equities_bars_daily"]

    assert envelope["generation_id"] == "signed-A"
    assert row["projection_generation"] == "signed-A"
    assert row["signed_projection_document_digest"] == expected_digest
    assert row["signed_projection_issuer_key_id"] == signer.key_id
    with pytest.raises(TypeError, match="exact dict"):
        sha256_digest(envelope)
    with pytest.raises(TypeError):
        row["signed_projection_issuer_key_id"] = "mutable"  # type: ignore[index]


def test_signed_projection_raw_json_is_strictly_decoded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-ephemeral", private)
    signed = sign_projection_bundle_for_test(
        render_projection_bundle_for_test(
            source,
            generation_id="raw-signed",
            producer_commit_sha="f" * 40,
            source_cursor=12,
            export_cursor=12,
        ),
        signer,
    )
    monkeypatch.setattr(
        projection_signing,
        "_load_pinned_active_keys",
        lambda _environment="production": {signer.key_id: private.public_key()},
    )

    raw = json.dumps(signed, separators=(",", ":")).encode("utf-8")
    envelope, evidence = verified_pinned_ops_projection_dataset_evidence(
        raw, ("equities_bars_daily",)
    )
    assert envelope["generation_id"] == "raw-signed"
    assert evidence["equities_bars_daily"]["projection_generation"] == (
        "raw-signed"
    )

    # A permissive pre-parse would keep the later, valid schema_version and
    # erase the attack before the signed boundary sees it.
    duplicate = raw.replace(
        b"{", b'{"schema_version":"attacker",', 1
    )
    with pytest.raises(OpsProjectionSignatureError, match="duplicate key"):
        verified_pinned_ops_projection_dataset_evidence(
            duplicate, ("equities_bars_daily",)
        )
    nonfinite = raw.replace(b'"schema_version"', b'"x":NaN,"schema_version"', 1)
    with pytest.raises(OpsProjectionSignatureError, match="non-finite"):
        verify_pinned_ops_projection(nonfinite)


def test_projection_a_signature_cannot_return_stateful_b_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-ephemeral", private)
    bundle = render_projection_bundle_for_test(
        source,
        generation_id="signed-A",
        producer_commit_sha="f" * 40,
        source_cursor=12,
        export_cursor=12,
    )
    signed = sign_projection_bundle_for_test(bundle, signer)
    envelope_a = json.loads(json.dumps(signed["envelope"]))
    envelope_b = json.loads(json.dumps(envelope_a))
    envelope_b["generation_id"] = "unsigned-B"
    envelope_b["dataset_coverage"]["equities_bars_daily"]["status"] = "COMPLETE"

    class SwitchingEnvelope(Mapping):
        def __init__(self) -> None:
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return iter(envelope_a if self.iterations <= 2 else envelope_b)

        def __len__(self):
            return len(envelope_a)

        def __getitem__(self, key):
            source_envelope = envelope_a if self.iterations <= 2 else envelope_b
            return source_envelope[key]

    attacked = {**signed, "envelope": SwitchingEnvelope()}
    monkeypatch.setattr(
        projection_signing,
        "_load_pinned_active_keys",
        lambda _environment="production": {signer.key_id: private.public_key()},
    )
    with pytest.raises(OpsProjectionSignatureError, match="exact finite JSON"):
        verify_pinned_ops_projection(attacked)
    with pytest.raises(OpsProjectionSignatureError, match="exact finite JSON"):
        verified_pinned_ops_projection_dataset_evidence(
            attacked, ("equities_bars_daily",)
        )


def test_projection_nested_subclasses_and_extra_fields_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-ephemeral", private)
    signed = sign_projection_bundle_for_test(
        render_projection_bundle_for_test(
            source,
            generation_id="signed",
            producer_commit_sha="f" * 40,
        ),
        signer,
    )
    monkeypatch.setattr(
        projection_signing,
        "_load_pinned_active_keys",
        lambda _environment="production": {signer.key_id: private.public_key()},
    )

    class StatefulString(str):
        pass

    scalar = json.loads(json.dumps(signed))
    scalar["envelope"]["generation_id"] = StatefulString("signed")
    with pytest.raises(OpsProjectionSignatureError, match="exact finite JSON"):
        verify_pinned_ops_projection(scalar)

    nested = json.loads(json.dumps(signed))

    class DatasetMap(dict):
        pass

    nested["envelope"]["dataset_coverage"] = DatasetMap(
        nested["envelope"]["dataset_coverage"]
    )
    with pytest.raises(OpsProjectionSignatureError, match="exact finite JSON"):
        verify_pinned_ops_projection(nested)

    extra = json.loads(json.dumps(signed))
    extra["envelope"]["caller_complete"] = True
    with pytest.raises(OpsProjectionSignatureError, match="not closed"):
        verify_pinned_ops_projection(extra)


def test_trusted_renderer_rejects_generic_sqlite_path_and_caller_claims(
    tmp_path: Path,
) -> None:
    source = tmp_path / "manual.sqlite"
    _source(source)
    with pytest.raises(RuntimeError, match="authenticated applied mirror handle"):
        _render_trusted_projection_bundle(
            source,
            generation_id="projgen-forged",
            producer_commit_sha="f" * 40,
        )
    with pytest.raises(ValueError, match="authenticated current D1 export"):
        sync_script.open_authenticated_applied_mirror(source)


def test_product_exporter_has_no_signer_or_test_authority_injection_surface(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    assert not hasattr(exporter, "_render_projection_bundle_for_test")
    forbidden_injections = (
        {
            "projection_signer": TestOpsProjectionSigningKey(
                "ops-projection-test-v1", Ed25519PrivateKey.generate()
            )
        },
        {"_test_authority": object()},
        {"_test_enforce_trusted_guards": False},
    )
    for forged in forbidden_injections:
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            exporter._render_projection_bundle(source, **forged)


def test_authenticated_mirror_pins_one_snapshot_and_is_single_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "original")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    handle = sync_script.open_authenticated_applied_mirror(source)

    writer = sqlite3.connect(source, timeout=0)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute(
                "UPDATE opaque_source_marker SET value='replacement'"
            )
        writer.rollback()
    finally:
        writer.close()

    observed = sync_script._consume_authenticated_applied_mirror(
        handle,
        lambda conn, identity: (
            conn.execute("SELECT value FROM opaque_source_marker").fetchone()[0],
            identity["source_content_digest"],
        ),
    )
    assert observed == (
        "original",
        sha256_digest({"opaque_source_marker": "original"}),
    )
    with sqlite3.connect(source, timeout=0) as writer:
        writer.execute("UPDATE opaque_source_marker SET value='after-consume'")
    with pytest.raises(RuntimeError, match="already consumed"):
        sync_script._consume_authenticated_applied_mirror(
            handle,
            lambda _conn, _identity: pytest.fail("replayed source was consumed"),
        )


def test_authenticated_mirror_releases_writer_lock_after_consumer_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    handle = sync_script.open_authenticated_applied_mirror(source)

    def fail_consumer(_conn, _identity):
        raise LookupError("consumer failed")

    with pytest.raises(LookupError, match="consumer failed"):
        sync_script._consume_authenticated_applied_mirror(
            handle, fail_consumer
        )
    with sqlite3.connect(source, timeout=0) as writer:
        writer.execute("UPDATE opaque_source_marker SET value='unlocked'")


def test_authenticated_mirror_gc_releases_descriptor_and_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    handle = sync_script.open_authenticated_applied_mirror(source)
    with sqlite3.connect(source, timeout=0) as writer:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute("UPDATE opaque_source_marker SET value='blocked'")
        writer.rollback()
    del handle
    gc.collect()
    with sqlite3.connect(source, timeout=0) as writer:
        writer.execute("UPDATE opaque_source_marker SET value='released'")


@pytest.mark.parametrize("attack", ["symlink", "stale_sidecar", "live_wal"])
def test_authenticated_mirror_rejects_nonfrozen_path_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    target = source
    writer = None
    if attack == "symlink":
        target = tmp_path / "alias.sqlite"
        target.symlink_to(source)
    elif attack == "stale_sidecar":
        Path(f"{source}-wal").touch()
    else:
        writer = sqlite3.connect(source)
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("UPDATE opaque_source_marker SET value='hot'")
        writer.commit()
    try:
        with pytest.raises(ValueError, match="not authoritative|not an authenticated"):
            sync_script.open_authenticated_applied_mirror(target)
    finally:
        if writer is not None:
            writer.close()


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_CLOEXEC"])
def test_authenticated_mirror_fails_closed_without_secure_descriptor_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.delattr(sync_script.os, flag)
    with pytest.raises(ValueError, match="not an authenticated current"):
        sync_script.open_authenticated_applied_mirror(source)


def test_authenticated_mirror_preserves_distinct_source_schema_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(distinct_source_schema=True),
    )
    handle = sync_script.open_authenticated_applied_mirror(source)
    observed = sync_script._consume_authenticated_applied_mirror(
        handle,
        lambda _conn, identity: (
            identity["source_schema_digest"],
            identity["schema_digest"],
        ),
    )
    assert observed[0] != observed[1]


def test_authenticated_mirror_rejects_path_replacement_before_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    replacement = tmp_path / "attacker.sqlite"
    _opaque_source(source, "trusted")
    _opaque_source(replacement, "attacker")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    handle = sync_script.open_authenticated_applied_mirror(source)
    replacement.replace(source)
    consumed: list[bool] = []

    with pytest.raises(RuntimeError, match="path was replaced"):
        sync_script._consume_authenticated_applied_mirror(
            handle,
            lambda _conn, _identity: consumed.append(True),
        )
    assert consumed == []
    with pytest.raises(RuntimeError, match="already consumed"):
        sync_script._consume_authenticated_applied_mirror(
            handle,
            lambda _conn, _identity: None,
        )


@pytest.mark.parametrize(
    ("source_cursor", "applied_cursor"),
    [
        (None, None),
        (7, None),
        (7, 6),
        (0, 0),
        (True, True),
    ],
)
def test_authenticated_mirror_rejects_null_or_mismatched_cursor_at_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_cursor: object,
    applied_cursor: object,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(
            source_cursor=source_cursor,
            applied_cursor=applied_cursor,
        ),
    )
    with pytest.raises(ValueError, match="authenticated current D1 export"):
        sync_script.open_authenticated_applied_mirror(source)


def test_trusted_renderer_consumes_handle_before_pending_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    monkeypatch.setattr(
        sync_script,
        "_authenticated_applied_mirror_identity_from_conn",
        _test_mirror_identity(),
    )
    handle = sync_script.open_authenticated_applied_mirror(source)
    with pytest.raises(RuntimeError, match="PENDING full-source authority"):
        _render_trusted_projection_bundle(handle)
    with pytest.raises(RuntimeError, match="already consumed"):
        _render_trusted_projection_bundle(handle)


@pytest.mark.parametrize("dry_run", [False, True])
def test_remote_publish_requires_dedicated_ops_projection_signer_before_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    output = tmp_path / "projection.sql"
    meta = tmp_path / "projection.json"
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    monkeypatch.setattr(
        publisher,
        "read_remote_active_cursor",
        lambda: pytest.fail("remote probe happened before authority gate"),
    )
    argv = [
        f"--db={source}",
        f"--output={output}",
        f"--meta-output={meta}",
        "--refresh-coverage",
        "--apply-remote",
    ]
    if dry_run:
        argv.append("--dry-run")
    assert publisher.main(argv) == 6
    assert not output.exists()
    assert not meta.exists()


def test_remote_publish_rejects_arbitrary_db_before_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "manual.sqlite"
    _source(source)
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (9, 9)
    )
    assert publisher.main([f"--db={source}", "--apply-remote"]) == 7


@pytest.mark.parametrize(
    "forbidden",
    [
        ["--source-cursor", "9"],
        ["--export-cursor", "9"],
        ["--projection-signing-key", "/tmp/fake.pem"],
        ["--projection-signing-key-id", "fake-key"],
        ["--force-apply-remote"],
    ],
)
def test_publisher_has_no_public_evidence_or_signer_override(
    forbidden: list[str],
) -> None:
    with pytest.raises(SystemExit):
        publisher.main(forbidden)


def test_remote_probe_uses_pinned_ops_wrangler_and_withholds_output(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    secret = "provider-secret-must-not-appear"
    calls = []

    def fail(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1, stdout=secret, stderr=secret)

    monkeypatch.setattr(publisher.subprocess, "run", fail)
    assert publisher.count_remote_complete() is None
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    argv, kwargs = calls[0]
    assert argv[0] == str(publisher.OPS_WRANGLER_BIN.resolve())
    assert "npx" not in argv
    assert argv[1:4] == ["d1", "execute", "quant-ops-projection"]
    assert argv[argv.index("--env") + 1] == "production"
    assert kwargs["cwd"] == str(publisher.OPS_WRANGLER_CWD)
    assert kwargs["capture_output"] is True


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"active_count": 0}, 0),
        (
            {
                "active_count": 1,
                "source_cursor": 8,
                "export_cursor": 8,
                "applied_cursor": 8,
            },
            8,
        ),
        (
            {
                "active_count": 1,
                "source_cursor": 8,
                "export_cursor": 7,
                "applied_cursor": 8,
            },
            None,
        ),
        (
            {
                "active_count": 1,
                "source_cursor": None,
                "export_cursor": None,
                "applied_cursor": None,
            },
            None,
        ),
    ],
)
def test_remote_active_cursor_requires_exact_chain(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, object], expected: int | None
) -> None:
    monkeypatch.setattr(
        publisher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"results": [row]}]),
            stderr="",
        ),
    )
    assert publisher.read_remote_active_cursor() == expected


@pytest.mark.parametrize("remote_cursor", [None, 5])
def test_remote_publish_rejects_unknown_or_regressing_active_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_cursor: int | None,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (4, 4)
    )
    monkeypatch.setattr(
        publisher,
        "open_ops_projection_signing_service",
        lambda: TestOpsProjectionSigningKey(
            "ops-projection-test-v1", Ed25519PrivateKey.generate()
        ),
    )
    monkeypatch.setattr(
        publisher, "read_remote_active_cursor", lambda: remote_cursor
    )
    assert publisher.main([f"--db={source}", "--apply-remote"]) == 7


@pytest.mark.parametrize(
    ("attack", "expected"),
    [("cursor_second_view", 7), ("complete_count_regression", 3)],
)
def test_remote_guards_use_exact_descriptor_render_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    expected: int,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    base = exporter.render_projection_bundle(source)
    cursor = 8 if attack == "cursor_second_view" else 7
    trusted = replace(
        base,
        complete_coverage_segments=2,
        envelope={
            **base.envelope,
            "source_cursor": cursor,
            "export_cursor": cursor,
            "applied_cursor": cursor,
        },
    )
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (7, 7)
    )
    monkeypatch.setattr(
        publisher,
        "open_ops_projection_signing_service",
        lambda: TestOpsProjectionSigningKey(
            "ops-projection-test-v1", Ed25519PrivateKey.generate()
        ),
    )
    monkeypatch.setattr(publisher, "read_remote_active_cursor", lambda: 7)
    monkeypatch.setattr(
        publisher, "open_authenticated_applied_mirror", lambda _path: object()
    )
    monkeypatch.setattr(
        publisher, "_render_trusted_projection_bundle", lambda *_a, **_k: trusted
    )
    remote_count_calls: list[bool] = []

    def remote_count(**_kwargs):
        remote_count_calls.append(True)
        return 3

    monkeypatch.setattr(publisher, "count_remote_complete", remote_count)
    assert publisher.main([f"--db={source}", "--apply-remote"]) == expected
    assert remote_count_calls == ([] if attack == "cursor_second_view" else [True])
    assert not hasattr(publisher, "count_local_complete")


def test_production_projection_package_is_verify_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUANT_OPS_PROJECTION_SIGNING_KEY_PEM", "ignored")
    monkeypatch.setenv("QUANT_RECEIPT_SIGNING_KEY_PEM", "ignored")
    monkeypatch.setenv("QUANT_READINESS_SIGNING_KEY_FILE", "/tmp/ignored")
    assert open_ops_projection_signing_service() is None
    assert not hasattr(projection_signing, "OpsProjectionSigningKey")
    assert not hasattr(projection_signing, "OpsProjectionPublicKeyRegistry")
    assert not hasattr(projection_signing, "load_ops_projection_signer")
    assert not hasattr(projection_signing, "DEFAULT_SIGNING_KEY_PATH")
    assert not hasattr(projection_signing, "DEFAULT_VERIFY_REGISTRY_PATH")
    assert not hasattr(projection_signing, "parse_projection_key_registry")
    assert not hasattr(projection_signing, "verify_projection_with_registry")


def test_pinned_registry_binds_full_document_body_generation_and_prior_audit() -> None:
    current_path = ROOT / "specs/ops_projection/verify_public_keys.json"
    audit_path = ROOT / "specs/ops_projection/verify_public_keys.generation-1.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert current["generation"] == PINNED_OPS_PROJECTION_REGISTRY_GENERATION
    assert current["prior_registry_digest"] == PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST
    assert PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST == sha256_digest(audit)
    assert current["registry_digest"] == PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST
    assert PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST == sha256_digest(
        {key: value for key, value in current.items() if key != "registry_digest"}
    )
    assert sha256_digest(current) == PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST
    assert audit["purpose"] == "ops_projection_registry_audit"
    assert audit["authority_status"] == "REVOKED"
    assert current["authority_status"] == "PENDING"
    assert [row["status"] for row in current["keys"]] == ["revoked", "pending"]


def test_generation_one_audit_and_attacker_registry_cannot_replace_pinned_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_path = ROOT / "specs/ops_projection/verify_public_keys.generation-1.json"
    monkeypatch.setattr(
        projection_signing, "_PINNED_VERIFY_REGISTRY_PATH", audit_path
    )
    with pytest.raises(OpsProjectionSignatureError, match="digest mismatch"):
        verify_pinned_ops_projection({})

    current = json.loads(
        (ROOT / "specs/ops_projection/verify_public_keys.json").read_text(
            encoding="utf-8"
        )
    )
    current["purpose"] = "attacker_selected_verification"
    current["registry_digest"] = sha256_digest(
        {key: value for key, value in current.items() if key != "registry_digest"}
    )
    attacker = tmp_path / "attacker-ops-registry.json"
    attacker.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(
        projection_signing, "_PINNED_VERIFY_REGISTRY_PATH", attacker
    )
    with pytest.raises(OpsProjectionSignatureError, match="digest mismatch"):
        verify_pinned_ops_projection({})


def test_pinned_ops_registry_rejects_duplicate_key_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = (
        ROOT / "specs/ops_projection/verify_public_keys.json"
    ).read_text(encoding="utf-8")
    duplicate = current.replace(
        '"schema_version": 2,',
        '"schema_version": 1, "schema_version": 2,',
        1,
    )
    path = tmp_path / "duplicate-ops-registry.json"
    path.write_text(duplicate, encoding="utf-8")
    monkeypatch.setattr(
        projection_signing, "_PINNED_VERIFY_REGISTRY_PATH", path
    )
    with pytest.raises(OpsProjectionSignatureError, match="cannot load"):
        verify_pinned_ops_projection({})


@pytest.mark.parametrize("field", ["schema_version", "generation"])
def test_pinned_ops_registry_rejects_float_integer_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    current = json.loads(
        (ROOT / "specs/ops_projection/verify_public_keys.json").read_text(
            encoding="utf-8"
        )
    )
    current[field] = 2.0
    current["registry_digest"] = sha256_digest(
        {key: value for key, value in current.items() if key != "registry_digest"}
    )
    path = tmp_path / f"float-{field}-ops-registry.json"
    path.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(projection_signing, "_PINNED_VERIFY_REGISTRY_PATH", path)
    monkeypatch.setattr(
        projection_signing,
        "PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST",
        current["registry_digest"],
    )
    monkeypatch.setattr(
        projection_signing,
        "PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST",
        sha256_digest(current),
    )

    with pytest.raises(OpsProjectionSignatureError, match="registry is invalid"):
        verify_pinned_ops_projection({})


@pytest.mark.parametrize(
    "extra",
    [
        ["--snapshot-dir", "/tmp/caller-snapshot"],
        ["--otc-index-html", "/tmp/caller-index.html"],
        ["--storage-hot-cutoff", "2026-01-01"],
    ],
)
def test_remote_publish_rejects_caller_selected_evidence_paths_and_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str],
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    assert publisher.main([f"--db={source}", "--apply-remote", *extra]) == 7


def test_failed_refresh_never_publishes_fresh_or_applies(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)

    def fail(*_args, **_kwargs):
        raise RuntimeError("ledger failure")

    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    monkeypatch.setattr("storage.coverage_ledger.refresh_coverage_ledger", fail)
    monkeypatch.setattr(publisher, "count_remote_complete", lambda **_kwargs: 0)
    monkeypatch.setattr(publisher, "read_remote_active_cursor", lambda: 1)
    monkeypatch.setattr(
        publisher,
        "open_ops_projection_signing_service",
        lambda **_kwargs: TestOpsProjectionSigningKey(
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
    assert not output.exists()
    assert not meta.exists()


def test_successful_refresh_must_reverify_and_freeze_same_owner_before_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    monkeypatch.setattr(
        "storage.coverage_ledger.refresh_coverage_ledger",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        publisher,
        "_freeze_authenticated_current_applied_mirror",
        lambda _store: (_ for _ in ()).throw(RuntimeError("audit drift")),
    )
    monkeypatch.setattr(publisher, "read_remote_active_cursor", lambda: 1)
    monkeypatch.setattr(
        publisher,
        "open_ops_projection_signing_service",
        lambda: TestOpsProjectionSigningKey(
            "ops-projection-test-v1", Ed25519PrivateKey.generate()
        ),
    )
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [
            f"--db={source}",
            f"--output={output}",
            f"--meta-output={meta}",
            "--refresh-coverage",
            "--apply-remote",
        ]
    ) == 4
    assert not output.exists()
    assert not meta.exists()


def test_projection_metadata_requires_successful_refresh_for_fresh(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    assert build_projection_metadata(source, refresh_status="skipped")["status"] == "STALE"
    assert build_projection_metadata(source, refresh_status="success")["status"] == "FRESH"
