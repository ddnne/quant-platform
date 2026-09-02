"""Independent 0020 schema-invariant replay. Expected names come from a
checked-in manifest, never from executing the same SQL under test.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "specs" / "receipts" / "receipt_authority_schema_invariants.json"
MIGRATION_DIR = ROOT / "platform" / "workers" / "ingestion-premium" / "migrations"


def _expected() -> dict:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert document["schema_version"] == "receipt-authority-schema-invariants/v1"
    assert "CREATE TRIGGER" not in MANIFEST.read_text(encoding="utf-8")
    return document


def _replay(through: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        if path.name > through:
            break
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _trigger_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _foreign_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, str]]:
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return {(str(row[3]), str(row[2]), str(row[4])) for row in rows}


def test_fresh_0019_has_the_ten_triggers_that_0020_used_to_drop() -> None:
    expected = _expected()
    conn = _replay("0019_receipt_authority_recovery_smoke.sql")
    try:
        names = _trigger_names(conn)
        missing = [
            name
            for name in expected["pre_0020_trigger_names_that_must_survive"]
            if name not in names
        ]
        assert missing == []
        assert "ix_receipt_authority_rows_dataset" in _index_names(conn)
        assert ("operation_id", "receipt_authority_operations", "operation_id") in _foreign_keys(
            conn, "receipt_authority_structured_rows"
        )
        assert ("operation_id", "receipt_authority_operations", "operation_id") in _foreign_keys(
            conn, "receipt_product_materializations"
        )
        assert ("run_id", "ingestion_run_log", "id") in _foreign_keys(
            conn, "receipt_product_materializations"
        )
    finally:
        conn.close()

def test_0020_preserves_independent_expected_invariants() -> None:
    expected = _expected()
    before = _replay("0019_receipt_authority_recovery_smoke.sql")
    after = _replay("0020_receipt_authority_governed_sources.sql")
    try:
        before_triggers = _trigger_names(before)
        after_triggers = _trigger_names(after)
        lost = [
            name
            for name in expected["pre_0020_trigger_names_that_must_survive"]
            if name not in after_triggers
        ]
        assert lost == []
        for row in expected["triggers"]:
            match = after.execute(
                "SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND name=?",
                (row["name"],),
            ).fetchone()
            assert match is not None, row["name"]
            assert match[0] == row["tbl_name"], row["name"]
        after_indexes = _index_names(after)
        for row in expected["indexes"]:
            assert row["name"] in after_indexes, row["name"]
        for row in expected["foreign_keys"]:
            observed = _foreign_keys(after, row["table"])
            assert (row["from"], row["ref_table"], row["to"]) in observed, row
        columns = {
            str(item[1])
            for item in after.execute("PRAGMA table_info(receipt_authority_operations)")
        }
        for name in expected["required_operation_columns"]:
            assert name in columns
        tables = {
            str(item[0])
            for item in after.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "quant_ingest_mutation_lease" not in tables
        lost_any = sorted(
            name
            for name in before_triggers
            if (
                name.startswith("receipt_authority_")
                or name.startswith("receipt_product_")
            )
            and name not in after_triggers
        )
        assert lost_any == []
    finally:
        before.close()
        after.close()


def _seed_collecting(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO ingestion_run_log(id,ran_at,source,runtime,status,detail,authority_operation_id) "
        "VALUES (9001,'2026-08-01T00:00:00Z','jquants','receipt-evidence-authority','RUNNING',NULL,'op-inv')"
    )
    conn.execute(
        """
        INSERT INTO receipt_authority_operations(
            operation_id,request_digest,run_id,environment,source,contract_id,dataset,
            segment_id,segment_start,segment_end,state,checked_at,updated_at
        ) VALUES (
            'op-inv','sha256:' || ?,9001,'production','jquants','jquants_premium_core',
            'equities_bars_daily','2026-08','2026-08-01','2026-08-31','COLLECTING',
            '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z'
        )
        """,
        ("ab" * 32,),
    )
    conn.execute(
        """
        INSERT INTO receipt_authority_requests(
            operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,
            state,created_at,updated_at
        ) VALUES (
            'op-inv',?,'production','jquants','jquants_premium_core','equities_bars_daily',
            '2026-08','PREPARED','2026-08-01T00:00:00Z','2026-08-01T00:00:00Z'
        )
        """,
        ("cd" * 32,),
    )
    conn.execute(
        """
        INSERT INTO receipt_authority_structured_rows(
            operation_id,natural_key,source,dataset,event_time,available_at,ingested_at,
            payload,raw_payload,row_digest
        ) VALUES (
            'op-inv','k1','jquants','equities_bars_daily','2026-08-01','2026-08-01',
            '2026-08-01T00:00:00Z','{}','{}','sha256:' || ?
        )
        """,
        ("11" * 32,),
    )
    conn.execute(
        """
        INSERT INTO receipt_product_materializations(
            operation_id,run_id,source,dataset,segment_id,artifact_key,artifact_digest,
            artifact_body,row_count,byte_count,manifest_key,manifest_digest,
            raw_manifest_key,raw_manifest_digest,raw_page_count,raw_row_count,raw_bytes,
            committed_at
        ) VALUES (
            'op-inv',9001,'jquants','equities_bars_daily','2026-08','artifact.jsonl',
            'sha256:' || ?,'{}',1,2,'manifest.json','sha256:' || ?,'raw.json',
            'sha256:' || ?,1,1,2,'2026-08-01T00:00:00Z'
        )
        """,
        ("aa" * 32, "bb" * 32, "cc" * 32),
    )
    conn.commit()


def test_0020_forbids_relabel_and_delete_of_authority_identity() -> None:
    conn = _replay("0020_receipt_authority_governed_sources.sql")
    try:
        _seed_collecting(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_authority_operations SET dataset='other' WHERE operation_id='op-inv'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_authority_operations SET source='jsda' WHERE operation_id='op-inv'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_authority_operations SET contract_id='other' WHERE operation_id='op-inv'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_authority_operations SET state='RECEIPT_COMMITTED', receipt_digest=? WHERE operation_id='op-inv'",
                ("sha256:" + "dd" * 32,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM receipt_authority_operations WHERE operation_id='op-inv'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_authority_structured_rows SET dataset='other' WHERE operation_id='op-inv'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM receipt_authority_structured_rows WHERE operation_id='op-inv'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_product_materializations SET dataset='other' WHERE operation_id='op-inv'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM receipt_product_materializations WHERE operation_id='op-inv'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM receipt_authority_requests WHERE operation_id='op-inv'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE receipt_authority_requests SET dataset='other' WHERE operation_id='op-inv'"
            )
    finally:
        conn.close()


def test_0022_persists_closed_jsda_locator_identity() -> None:
    conn = _replay("0022_receipt_authority_jsda_locator.sql")
    try:
        columns = {
            str(item[1])
            for item in conn.execute("PRAGMA table_info(receipt_authority_requests)")
        }
        assert {"work_key", "expected_contract_digest", "raw_object_key"} <= columns
        names = _trigger_names(conn)
        assert "receipt_authority_requests_locator_insert" in names
        assert "receipt_authority_requests_locator_update" in names
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO receipt_authority_requests(
                    operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,
                    state,created_at,updated_at
                ) VALUES (
                    'op-jsda',?,'production','jsda','jsda_governed_otc_reference_archive',
                    'jsda_otc_bond_reference_prices','file_2002-08-02_otc','PREPARED',
                    '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z'
                )
                """,
                ("ab" * 32,),
            )
        conn.execute(
            """
            INSERT INTO receipt_authority_requests(
                operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,
                state,created_at,updated_at,work_key,expected_contract_digest,raw_object_key
            ) VALUES (
                'op-jsda',?,'production','jsda','jsda_governed_otc_reference_archive',
                'jsda_otc_bond_reference_prices','file_2002-08-02_otc','PREPARED',
                '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z',
                'jsda:v2:file:jsda_otc_bond_reference_prices:abc',?,
                'raw/jsda/file.csv'
            )
            """,
            ("cd" * 32, "sha256:" + "ab" * 32),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO receipt_authority_requests(
                    operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,
                    state,created_at,updated_at,work_key,expected_contract_digest,raw_object_key
                ) VALUES (
                    'op-jq',?,'production','jquants','jquants_premium_core',
                    'equities_bars_daily','2026-08','PREPARED',
                    '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z',
                    'should-be-null',?, 'raw/not-allowed'
                )
                """,
                ("ef" * 32, "sha256:" + "11" * 32),
            )
    finally:
        conn.close()
