"""READY proof accepts only an opaque, fully bound receipt closure."""

from __future__ import annotations

import base64
from dataclasses import replace
import json
import sqlite3

import pytest

from data_contracts.coverage import coverage_policy_binding
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)
from paper_runtime.snapshot import SnapshotRejected
from paper_runtime.ready_policy import CoverageEvidence, collect_typed_evidence
from paper_runtime.snapshot_coverage_proof import (
    CoverageProofVerificationError,
    VerifiedCoverageProof,
    _coverage_proof,
    persist_coverage_proof,
    require_persisted_coverage_proof,
)
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    record_collection_receipt,
    record_required_segments,
)
from storage.receipt_crypto import (
    LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
    body_digest,
    canonical_receipt_body,
)
from storage.sqlite_store import SqliteStore
from storage.verified_receipt import (
    ReceiptVerificationError,
    audit_signed_receipt_claims,
    require_verified_collection_closure,
)


_DATASET = "markets_calendar"
_CHECKED_AT = "2026-08-25T00:00:00+00:00"
_POLICY_VERSION = coverage_policy_binding(_DATASET)["policy_version"]


def _seed_closed_segment(tmp_path, receipt_ed25519_keys):
    store = SqliteStore(tmp_path / "snapshot-closure.sqlite")
    conn = store._conn  # noqa: SLF001
    required = RequiredCoverageSegment(
        source="jquants",
        dataset=_DATASET,
        segment_id="2026-08",
        segment_start="2026-08-01",
        segment_end="2026-08-31",
        expected_scope={
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "expected_item_unit": "calendar_day",
        },
        expected_items=1,
    )
    raw_record = {"Date": "2026-08-25", "HolidayDivision": "1"}
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=41,
        raw_pages=[json.dumps({"data": [raw_record]}).encode("utf-8")],
        raw_records=[raw_record],
        structured_records=[raw_record],
        checked_at=_CHECKED_AT,
        source_request={"from": "2026-08-01", "to": "2026-08-31"},
    )
    receipt = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    ).issue(evidence)
    record_required_segments(conn, (required,), policy_version=_POLICY_VERSION)
    record_collection_receipt(conn, receipt)
    conn.execute(
        "UPDATE coverage_segments SET status='COMPLETE', receipt_run_id=? "
        "WHERE source=? AND dataset=? AND segment_id=? AND policy_version=?",
        (
            receipt.run_id,
            required.source,
            required.dataset,
            required.segment_id,
            _POLICY_VERSION,
        ),
    )
    conn.execute(
        """
        INSERT INTO dataset_coverage (
            dataset, status, policy_version, collection_scope,
            history_target_start, history_target_end_rule, coverage_mode,
            expected_frequency, universe_rule, raw_retention_required,
            structured_reconciliation_required, governance_tier,
            observed_start, observed_end, row_count, source_run_id,
            evaluated_at, detail_json
        ) VALUES (?, 'COMPLETE', ?, 'test-authoritative-scope',
                  '2026-08-01', 'fixed:2026-08-31', 'monthly', 'daily',
                  'all', 1, 1, 'governed', '2026-08-01', '2026-08-31',
                  1, 41, ?, '{}')
        """,
        (_DATASET, _POLICY_VERSION, _CHECKED_AT),
    )
    conn.execute(
        "CREATE TABLE ingestion_change_log (change_seq INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO ingestion_change_log VALUES (7)")
    conn.execute(
        "INSERT INTO sync_change_state "
        "(feed,last_applied_change_seq,updated_at) VALUES "
        "('jquants_records',7,?) "
        "ON CONFLICT(feed) DO UPDATE SET "
        "last_applied_change_seq=excluded.last_applied_change_seq, "
        "updated_at=excluded.updated_at",
        (_CHECKED_AT,),
    )
    conn.commit()
    coverage_rows = [{
        "dataset": _DATASET,
        "policy_version": _POLICY_VERSION,
        "status": "COMPLETE",
    }]
    return store, receipt, coverage_rows


def _coverage_item(evidence):
    return next(
        item.to_item() for item in evidence if isinstance(item, CoverageEvidence)
    )


def test_persisted_coverage_proof_is_canonical_immutable_and_policy_eligible(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001

    proof_id = persist_coverage_proof(conn, (_DATASET,))
    capability = require_persisted_coverage_proof(
        conn, (_DATASET,), proof_id
    )
    assert capability.proof_id == proof_id
    assert capability.required_datasets == (_DATASET,)
    assert capability.source_generation == capability.applied_generation == 7
    item = _coverage_item(
        collect_typed_evidence(
            conn,
            store.path,
            (_DATASET,),
            coverage_proof_id=proof_id,
        )
    )
    assert item.passed is True
    assert item.detail["proof_id"] == proof_id
    assert item.detail["required_datasets"] == [_DATASET]

    row = conn.execute(
        "SELECT required_datasets_json,coverage_proof_json,"
        "source_generation,applied_generation "
        "FROM local_coverage_proofs WHERE proof_id=?",
        (proof_id,),
    ).fetchone()
    assert json.loads(row[0]) == [_DATASET]
    assert json.loads(row[1]) == capability.proof
    assert tuple(row[2:]) == (7, 7)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE local_coverage_proofs SET persisted_at='tampered' "
            "WHERE proof_id=?",
            (proof_id,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM local_coverage_proofs WHERE proof_id=?", (proof_id,)
        )
    conn.rollback()
    store.close()


def test_caller_constructed_verified_value_is_not_policy_authority(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(conn, (_DATASET,))
    forged_id = "sha256:" + ("22" * 32)
    forged = VerifiedCoverageProof(
        proof_id=forged_id,
        _proof_json=json.dumps(
            {
                "status": "COMPLETE",
                "proof_digest": "sha256:" + ("33" * 32),
                "dataset_count": 999,
            }
        ),
        required_datasets=(_DATASET,),
        source_generation=7,
        applied_generation=7,
    )
    assert forged.proof["status"] == "COMPLETE"
    assert CoverageEvidence(conn, (_DATASET,), forged.proof_id).to_item().passed is False
    store.close()


def test_persisted_coverage_proof_rejects_tampered_unknown_and_stale_ids(
    tmp_path, receipt_ed25519_keys
):
    store, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(conn, (_DATASET,))
    tampered_id = proof_id[:-1] + ("0" if proof_id[-1] != "0" else "1")
    for invalid_id in (None, "UNKNOWN", tampered_id):
        with pytest.raises(CoverageProofVerificationError):
            require_persisted_coverage_proof(conn, (_DATASET,), invalid_id)
    with pytest.raises(CoverageProofVerificationError, match="exact, sorted"):
        require_persisted_coverage_proof(
            conn, (_DATASET, _DATASET), proof_id
        )

    conn.execute("INSERT INTO ingestion_change_log VALUES (8)")
    conn.execute(
        "UPDATE sync_change_state SET last_applied_change_seq=8 "
        "WHERE feed='jquants_records'"
    )
    conn.commit()
    with pytest.raises(CoverageProofVerificationError, match="stale"):
        require_persisted_coverage_proof(conn, (_DATASET,), proof_id)
    assert _coverage_item(
        collect_typed_evidence(
            conn,
            store.path,
            (_DATASET,),
            coverage_proof_id=proof_id,
        )
    ).passed is False
    store.close()


def test_persisted_coverage_proof_rejects_receipt_ledger_mutation(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(conn, (_DATASET,))
    conn.execute(
        "UPDATE collection_receipts SET observed_items=0 "
        "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
        (receipt.source, receipt.dataset, receipt.segment_id, receipt.run_id),
    )
    conn.commit()
    with pytest.raises(
        CoverageProofVerificationError, match="cannot be reproduced"
    ):
        require_persisted_coverage_proof(conn, (_DATASET,), proof_id)
    store.close()


def test_copied_coverage_record_without_receipt_cannot_mint_capability(
    tmp_path, receipt_ed25519_keys
):
    source, _receipt, _coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    source_conn = source._conn  # noqa: SLF001
    proof_id = persist_coverage_proof(source_conn, (_DATASET,))

    target = SqliteStore(tmp_path / "copied-record.sqlite")
    target_conn = target._conn  # noqa: SLF001
    for table in ("dataset_coverage", "local_coverage_proofs"):
        cursor = source_conn.execute(f"SELECT * FROM {table}")
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
        target_conn.executemany(
            f"INSERT INTO {table} ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            [tuple(row) for row in rows],
        )
    target_conn.execute(
        "CREATE TABLE ingestion_change_log (change_seq INTEGER NOT NULL)"
    )
    target_conn.execute("INSERT INTO ingestion_change_log VALUES (7)")
    target_conn.execute(
        "INSERT INTO sync_change_state "
        "(feed,last_applied_change_seq,updated_at) VALUES "
        "('jquants_records',7,?)",
        (_CHECKED_AT,),
    )
    target_conn.commit()

    with pytest.raises(
        CoverageProofVerificationError, match="cannot be reproduced"
    ):
        require_persisted_coverage_proof(target_conn, (_DATASET,), proof_id)
    target.close()
    source.close()


def test_snapshot_proof_hashes_verified_closure_and_rejects_outer_mutation(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    conn = store._conn  # noqa: SLF001
    proof = _coverage_proof(conn, (_DATASET,), coverage_rows)
    assert proof["status"] == "COMPLETE"
    assert proof["receipt_count"] == 1
    assert proof["proof_digest"].startswith("sha256:")

    # The receipt row is only a transport DTO. Even though the segment row is
    # still marked COMPLETE, changing a gating mirror invalidates its closure.
    conn.execute(
        "UPDATE collection_receipts SET observed_items=0 "
        "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
        (receipt.source, receipt.dataset, receipt.segment_id, receipt.run_id),
    )
    conn.commit()
    with pytest.raises(SnapshotRejected, match="receipt closure invalid"):
        _coverage_proof(conn, (_DATASET,), coverage_rows)
    store.close()


def test_snapshot_proof_rejects_validly_signed_legacy_v1(
    tmp_path, receipt_ed25519_keys
):
    store, receipt, coverage_rows = _seed_closed_segment(
        tmp_path, receipt_ed25519_keys
    )
    digests = dict(receipt.digests)
    claims = json.loads(base64.b64decode(digests["signed_body_b64"]))
    claims["version"] = LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION
    legacy_body = canonical_receipt_body(claims)
    digests["signed_body_b64"] = base64.b64encode(legacy_body).decode("ascii")
    digests["signature"] = receipt_ed25519_keys.signing_key.sign(legacy_body)
    digests["body_digest"] = body_digest(legacy_body)
    legacy_receipt = replace(receipt, digests=digests)
    assert (
        audit_signed_receipt_claims(legacy_receipt)["version"]
        == LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION
    )
    with pytest.raises(ReceiptVerificationError, match="audit-only"):
        require_verified_collection_closure(legacy_receipt)

    conn = store._conn  # noqa: SLF001
    conn.execute(
        "UPDATE collection_receipts SET digests_json=? "
        "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
        (
            json.dumps(digests, sort_keys=True, separators=(",", ":")),
            receipt.source,
            receipt.dataset,
            receipt.segment_id,
            receipt.run_id,
        ),
    )
    conn.commit()
    with pytest.raises(
        SnapshotRejected, match="v1 is audit-only and not COMPLETE-eligible"
    ):
        _coverage_proof(conn, (_DATASET,), coverage_rows)
    store.close()
